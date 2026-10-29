"""Command input, durable sender bindings, and asynchronous OW API access."""

from __future__ import annotations

import asyncio
import re
import sqlite3
import time
import unicodedata
import hashlib
import math
from contextlib import closing
from pathlib import Path

import httpx

TAG = re.compile(r"[^\s#,，、;；]{1,32}#[0-9]{3,12}")
CONTRIBUTION_NOTICE = "数据不能反映出全部贡献，单局评分高低只是基于队友区分，与敌方无关。"
EMPTY_QUERY_NOTICE = "暂未获得可用战绩，可能是网易大神搜索接口维护中或服务器异常，建议部署到本地查询。"
NOTICE = "仅比较本名单各自匹配池近12场；段位跨度过大时上下等马评级无意义。\n" + CONTRIBUTION_NOTICE
HELP = (
    """守望评分机器人（群聊先@机器人）
/help 或 /帮助：查看全部指令和作用。
/绑定 昵称#12345：绑定或换绑自己的默认战网ID，重启后仍保留。
/解绑：解除自己的绑定，不影响其他群友。
/查询 [战网ID]：查询近12场竞技模式；省略ID时查询自己绑定的账号。
/查询休闲 [战网ID]：查询近12场休闲模式；省略ID时查询自己绑定的账号。
/韩服数据 坦克（或输出、辅助）：发送韩服大师、竞技职责预选、所有地图、PC的完整英雄胜率图，按胜率从高到低排序，缓存每6小时更新。

多人查询：在查询指令后输入多个完整ID，用空格或逗号分隔。
图片查询：发送 /查询 或 /查询休闲，并在同一条消息附一张名单截图。
也可先发 /查询 图片 或 /查询休闲 图片，再在2分钟内发送截图（群聊需@我）。
多人或截图查询会自动加入已绑定的本人、去重，最多10人；单个ID临时查询不会修改绑定。
返回展开全部逐场详情的高清长图。完整评分规则：
https://lkevaer.xyz
进入网页版后，可点击每场最左侧“查询当局”，查询当局所有人的评分评级。
"""
    + NOTICE
)


def has_rated_players(report: dict) -> bool:
    players = report.get("players")
    return isinstance(players, list) and any(
        isinstance(row, dict) and isinstance(row.get("score"), (int, float))
        and not isinstance(row["score"], bool) and math.isfinite(row["score"])
        for row in players
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
        self, base_url: str, api_key: str = "", timeout: int = 300, transport=None, *, service_key: str = ""
    ):
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("战绩服务地址必须以 http:// 或 https:// 开头。")
        self.timeout = max(30, min(int(timeout), 900))
        self.service_key = service_key
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"X-API-Key": api_key} if api_key else {},
            timeout=httpx.Timeout(self.timeout, connect=10),
            trust_env=False,
            transport=transport,
        )

    def actor_headers(self, actor):
        if not self.service_key:
            return {}
        if actor is None or len(actor) != 3 or not all(actor):
            raise ValueError("无法确认查询用户，请重新发送指令。")
        platform, sender, group = map(str, actor)
        def digest(parts):
            return hashlib.sha256("\0".join(parts).encode()).hexdigest()
        return {"X-Bot-Key": self.service_key,
                "X-Bot-User": digest([platform, sender]),
                "X-Bot-Group": digest([platform, group])}

    async def request(self, method: str, path: str, *, actor=None, **kwargs) -> dict:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.update(self.actor_headers(actor))
        try:
            response = await self.client.request(method, path, headers=headers, **kwargs)
        except httpx.TimeoutException as exc:
            raise ValueError("战绩查询等待超时，请稍后重试。") from exc
        except httpx.HTTPError as exc:
            raise ValueError("战绩服务连接失败，请管理员检查插件的服务地址。") from exc
        if response.status_code in (401, 403):
            raise ValueError("战绩服务访问码不正确，请在插件设置中更新。")
        if response.is_error:
            try:
                payload = response.json()
                message = payload.get("error") or payload.get("detail") or "查询失败"
                if not isinstance(message, str):
                    message = "请求参数有误，请检查指令和截图"
            except (ValueError, AttributeError):
                message = "查询失败"
            retry = response.headers.get("Retry-After", "")
            if response.status_code in {429, 503} and retry.isdigit() and "秒" not in message:
                message += f"，请在{min(int(retry), 900)}秒后重试"
            raise ValueError(f"战绩服务：{str(message)[:180]}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError(EMPTY_QUERY_NOTICE) from exc
        if not isinstance(payload, dict) or not payload:
            raise ValueError(EMPTY_QUERY_NOTICE)
        if payload.get("success") is False:
            raise ValueError("战绩服务未返回成功结果，请稍后重试。")
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            raise ValueError(EMPTY_QUERY_NOTICE)
        return data

    async def rating(
        self, mode: str, tags: list[str], poll_interval: float = 2, *, actor=None
    ) -> dict:
        if mode not in {"competitive", "leisure"}:
            raise ValueError("查询模式必须是竞技或休闲。")
        tags = team_tags(tags, None)
        # Include admission + HTTP time + polling in a single client budget.
        try:
            async with asyncio.timeout(self.timeout):
                return await self._rating(mode, tags, poll_interval, actor)
        except TimeoutError as exc:
            raise ValueError("战绩查询等待超时，请稍后重试；未用空数据生成评分。") from exc

    async def _rating(self, mode, tags, poll_interval, actor):
        job = await self.request(
            "POST",
            f"/api/batch-rating/{mode}",
            json={"battletags": tags, "wait": False},
            actor=actor,
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
            job = await self.request("GET", f"/api/batch-rating/tasks/{task_id}", actor=actor)
        if job.get("status") == "error":
            raise ValueError(str(job.get("error") or "战绩查询失败")[:180])
        if job.get("status") == "done" and not isinstance(job.get("result"), dict):
            raise ValueError(EMPTY_QUERY_NOTICE)
        if not job:
            raise ValueError(EMPTY_QUERY_NOTICE)
        if job.get("status") != "done":
            raise ValueError("战绩查询未完成，没有生成评分。")
        return {**job["result"], "task_id": task_id}

    async def close(self):
        await self.client.aclose()


class QueryGate:
    """Bound in-flight work before downloading screenshots or fetching reports."""

    def __init__(self, capacity=4, per_group=2):
        self.capacity, self.per_group = capacity, per_group
        self.active = {}

    def enter(self, identity, group):
        if identity in self.active:
            raise ValueError("你上一条查询仍在运行，请等它完成。")
        if len(self.active) >= self.capacity:
            raise ValueError("机器人查询繁忙，请稍后重试。")
        if sum(value == group for value in self.active.values()) >= self.per_group:
            raise ValueError("本群已有多条查询正在处理，请稍后重试。")
        self.active[identity] = group

    def leave(self, identity):
        self.active.pop(identity, None)
