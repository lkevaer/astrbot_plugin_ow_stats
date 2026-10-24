"""Command input, durable sender bindings, and asynchronous OW API access."""

from __future__ import annotations

import asyncio
import re
import sqlite3
import time
import unicodedata
from contextlib import closing
from pathlib import Path

import httpx

TAG = re.compile(r"[^\s#,，、;；]{1,32}#[0-9]{3,12}")
NOTICE = "仅比较本名单各自匹配池近12场；段位跨度过大时上下等马评级无意义。"
HELP = (
    """守望评分查询（群聊先@机器人）
/绑定 昵称#12345
/解绑
/查询 昵称#12345（多人用空格分隔）
/查询 + 同一条消息附一张名单截图
/查询 图片（随后2分钟内发送截图）
绑定后 /查询 查自己；多人或截图查询自动补入本人、去重，最多10人。
默认查询竞技；/查询 休闲 [ID或截图] 可查休闲。
返回展开逐场详情的高清长图。完整评分规则：lkevaer.xyz
"""
    + NOTICE
)


def parse_tags(text: str) -> list[str]:
    """Validate complete BattleTags without silently ignoring malformed input.

    Args:
        text: BattleTags separated by spaces, commas, or newlines.

    Returns:
        Unique normalized tags in input order.

    Raises:
        ValueError: Some input is not a complete BattleTag.
    """
    text = unicodedata.normalize("NFKC", str(text)).strip()
    if not text:
        return []
    parts = re.split(r"[\s,，、;；]+", text)
    if any(not TAG.fullmatch(part) for part in parts):
        raise ValueError("请填写完整ID，例如 昵称#12345；多人用空格或逗号分隔。")
    result, seen = [], set()
    for tag in parts:
        key = tag.casefold()
        if key not in seen:
            result.append(tag)
            seen.add(key)
    return result


def team_tags(tags: list[str], own: str | None) -> list[str]:
    """Add the authenticated sender's own tag once and enforce the ten-player query limit.

    Args:
        tags: Validated teammate BattleTags.
        own: Sender's saved binding, if present.

    Returns:
        The actual team roster, including the sender when bound.

    Raises:
        ValueError: The roster exceeds ten players or contains no target.
    """
    result = parse_tags(" ".join(tags + ([own] if own else [])))
    if len(result) > 10:
        raise ValueError("合并本人并去重后超过10人，请减少名单；不会自动截掉账号。")
    if not result:
        raise ValueError("请先 /绑定 昵称#12345，或在指令后填写完整ID。")
    return result


class Bindings:
    """Keep independent bindings for each platform instance and sender."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with closing(sqlite3.connect(path, timeout=10, isolation_level=None)) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS bindings (platform TEXT, sender TEXT, tag TEXT NOT NULL, PRIMARY KEY(platform,sender))"
            )

    def get(self, platform: str, sender: str) -> str | None:
        with closing(
            sqlite3.connect(self.path, timeout=10, isolation_level=None)
        ) as db:
            row = db.execute(
                "SELECT tag FROM bindings WHERE platform=? AND sender=?",
                (platform, sender),
            ).fetchone()
        return row[0] if row else None

    def set(self, platform: str, sender: str, tag: str) -> None:
        if not platform or not sender:
            raise ValueError("无法确认消息发送者，未保存绑定。")
        with closing(
            sqlite3.connect(self.path, timeout=10, isolation_level=None)
        ) as db:
            db.execute(
                "INSERT INTO bindings VALUES (?,?,?) ON CONFLICT(platform,sender) DO UPDATE SET tag=excluded.tag",
                (platform, sender, tag),
            )

    def remove(self, platform: str, sender: str) -> None:
        with closing(
            sqlite3.connect(self.path, timeout=10, isolation_level=None)
        ) as db:
            db.execute(
                "DELETE FROM bindings WHERE platform=? AND sender=?", (platform, sender)
            )


class OWClient:
    """Call the existing service without duplicating its scoring algorithm."""

    def __init__(
        self, base_url: str, api_key: str = "", timeout: int = 300, transport=None
    ):
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("战绩服务地址必须以 http:// 或 https:// 开头。")
        self.timeout = max(30, min(int(timeout), 900))
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"X-API-Key": api_key} if api_key else {},
            timeout=httpx.Timeout(self.timeout, connect=10),
            trust_env=False,
            transport=transport,
        )

    async def request(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = await self.client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise ValueError("战绩查询等待超时，请稍后重试。") from exc
        except httpx.HTTPError as exc:
            raise ValueError("战绩服务连接失败，请管理员检查插件的服务地址。") from exc
        if response.status_code in (401, 403):
            raise ValueError("战绩服务访问码不正确，请在插件设置中更新。")
        if response.is_error:
            try:
                message = response.json().get("detail") or "查询失败"
            except (ValueError, AttributeError):
                message = "查询失败"
            raise ValueError(f"战绩服务：{str(message)[:180]}")
        payload = response.json()
        if payload.get("success") is False:
            raise ValueError("战绩服务未返回成功结果，请稍后重试。")
        return payload.get("data", payload)

    async def rating(
        self, mode: str, tags: list[str], poll_interval: float = 2
    ) -> dict:
        if mode not in {"competitive", "leisure"}:
            raise ValueError("查询模式必须是竞技或休闲。")
        tags = team_tags(tags, None)
        job = await self.request(
            "POST",
            f"/api/batch-rating/{mode}",
            json={"battletags": tags, "wait": False},
        )
        task_id = job.get("task_id")
        if job.get("status") in {"queued", "running"} and not re.fullmatch(
            r"[0-9a-f]{32}", str(task_id or "")
        ):
            raise ValueError("战绩服务返回了无效的查询任务，请稍后重试。")
        deadline = time.monotonic() + self.timeout
        while job.get("status") in {"queued", "running"}:
            if time.monotonic() >= deadline:
                raise ValueError("战绩查询等待超时，请稍后重试；未用空数据生成评分。")
            await asyncio.sleep(poll_interval)
            job = await self.request("GET", f"/api/batch-rating/tasks/{task_id}")
        if job.get("status") == "error":
            raise ValueError(str(job.get("error") or "战绩查询失败")[:180])
        if job.get("status") != "done" or not isinstance(job.get("result"), dict):
            raise ValueError("战绩查询未完成，没有生成评分。")
        return {**job["result"], "task_id": task_id}

    async def close(self):
        await self.client.aclose()
