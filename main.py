"""Provide help, account binding, and OW rating queries through AstrBot."""

from __future__ import annotations

import asyncio
import base64
import re
import time
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image, Plain
from astrbot.api.star import Context, Star
from astrbot.core.star.filter.command import GreedyStr
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .core import HELP, Bindings, OWClient, parse_tags, team_tags
from .render import WebRenderer


class ScreenshotOnly(filter.CustomFilter):
    """Recognize a follow-up image without matching normal text commands."""

    def filter(self, event, cfg):
        return event.get_message_str().strip() in {"", "[图片]"} and any(
            isinstance(message, Image) for message in event.get_messages()
        )


class OWStatsPlugin(Star):
    """Keep sender bindings outside the plugin's replaceable source directory."""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.bindings = Bindings(
            Path(get_astrbot_data_path())
            / "plugin_data/astrbot_plugin_ow_stats/bindings.sqlite3"
        )
        self.api = OWClient(
            config.get("api_url", "https://lkevaer.xyz"),
            config.get("api_key", ""),
            config.get("timeout_seconds", 300),
        )
        self.renderer = WebRenderer()
        self.busy: set[tuple[str, str]] = set()
        self.pending_images: dict[tuple[str, str, str], tuple[str, float]] = {}

    def _identity(self, event):
        platform = str(event.get_platform_id() or "")
        sender = str(event.get_sender_id() or "")
        if not platform or not sender:
            raise ValueError("无法确认消息发送者，请重新发送指令。")
        return platform, sender

    def _conversation(self, event):
        return (*self._identity(event), str(event.get_session_id()))

    async def _image_tags(self, event, command):
        """Pass a single bounded image to the service's existing OCR pipeline.

        Args:
            event: A command containing one roster screenshot.
            command: Query command to preserve when asking for OCR corrections.

        Returns:
            Complete, validated BattleTags in the recognized order.

        Raises:
            ValueError: The image is missing, oversized, or requires correction.
        """
        pictures = [item for item in event.get_messages() if isinstance(item, Image)]
        if len(pictures) != 1:
            raise ValueError("请每次仅发送一张名单截图。")
        image_path = Path(await pictures[0].convert_to_file_path())
        if image_path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("截图不能超过8MB，请先框选账号列表。")
        image_data = await asyncio.to_thread(image_path.read_bytes)
        recognized = await self.api.request(
            "POST",
            "/api/batch-rating/recognize",
            json={"image_base64": base64.b64encode(image_data).decode()},
        )
        tags = parse_tags(" ".join(recognized.get("battletags", [])))
        if not tags:
            raise ValueError(
                f"未识别到完整ID，请裁剪名单后重试，或发送 {command} 昵称#12345。"
            )
        if recognized.get("review_count"):
            raise ValueError(
                f"识别有疑项，请核对后重新输入 {command} " + " ".join(tags)
            )
        return tags

    async def _query(self, event, args, mode="competitive"):
        event.should_call_llm(False)
        identity = None
        acquired = False
        try:
            identity = self._identity(event)
            if identity in self.busy:
                yield event.plain_result("你上一条查询仍在运行，请等它完成。")
                return
            self.busy.add(identity)
            acquired = True
            command = "/查询休闲" if mode == "leisure" else "/查询"
            args = args.strip()
            pictures = [
                item for item in event.get_messages() if isinstance(item, Image)
            ]
            wants_image = args in {"图片", "截图"}
            if wants_image:
                args = ""
            tags = parse_tags(args)
            own = self.bindings.get(*identity)
            if not pictures and (wants_image or (not tags and not own)):
                now = time.monotonic()
                self.pending_images = {
                    key: value
                    for key, value in self.pending_images.items()
                    if value[1] > now
                }
                self.pending_images[self._conversation(event)] = (mode, now + 120)
                yield event.plain_result(
                    f"请在2分钟内发送一张名单截图（群聊需@我），或发送 {command} 昵称#12345。\n"
                    f"用 /绑定 昵称#12345 后，{command} 可直接查自己。"
                )
                return
            if pictures:
                if tags:
                    raise ValueError("请附一张名单截图，或直接输入ID，两者任选其一。")
                yield event.plain_result("正在识别名单截图…")
                tags = await self._image_tags(event, command)
            self.pending_images.pop(self._conversation(event), None)
            # A single explicit ID is a temporary target. Rosters include the sender.
            tags = team_tags(tags, own if pictures or len(tags) != 1 else None)
            yield event.plain_result(
                f"正在查询{'竞技' if mode == 'competitive' else '休闲'}近12场，共{len(tags)}人；将返回展开详情的高清长图…"
            )
            report = await self.api.rating(mode, tags)
            if not report.get("players"):
                yield event.plain_result(
                    "本次没有可展示的公开对局，请确认ID和战绩隐私设置。"
                )
                return
            picture = await self.renderer.render(report)
            chain = [Image.fromBytes(picture)]
            if re.fullmatch(r"[0-9a-f]{32}", str(report.get("task_id") or "")):
                chain.append(
                    Plain(
                        text="进入网页版查询当局所有人评分评级：https://lkevaer.xyz/?task="
                        + report["task_id"]
                    )
                )
            yield event.chain_result(chain)
        except ValueError as exc:
            yield event.plain_result(str(exc))
        except Exception as exc:
            logger.error("OW rating query failed: %s", type(exc).__name__)
            yield event.plain_result(
                "查询或长图生成暂时失败，请稍后重试；不会返回缺少详情的图片。"
            )
        finally:
            if acquired:
                self.busy.discard(identity)

    @filter.command("绑定")
    async def bind(self, event: AstrMessageEvent, args: GreedyStr):
        """Bind or replace the current sender's default BattleTag."""
        event.should_call_llm(False)
        try:
            tags = parse_tags(args)
            if len(tags) != 1:
                raise ValueError("用法：/绑定 昵称#12345；每人绑定一个账号。")
            self.bindings.set(*self._identity(event), tags[0])
            yield event.plain_result(
                f"已绑定 {tags[0]}。/查询 查近12场竞技，/查询休闲 查近12场休闲；/解绑 解除绑定，/帮助 查看全部用法。"
            )
        except ValueError as exc:
            yield event.plain_result(str(exc))

    @filter.command("解绑")
    async def unbind(self, event: AstrMessageEvent):
        """Remove only this sender's saved default and pending image requests."""
        event.should_call_llm(False)
        try:
            identity = self._identity(event)
            self.bindings.remove(*identity)
            self.pending_images = {
                key: value
                for key, value in self.pending_images.items()
                if key[:2] != identity
            }
            yield event.plain_result("已解除你的账号绑定。")
        except ValueError as exc:
            yield event.plain_result(str(exc))

    @filter.command("help", alias={"帮助"}, priority=100)
    async def help_command(self, event: AstrMessageEvent):
        """Return this bot's command guide before AstrBot's generic help handler."""
        event.should_call_llm(False)
        yield event.plain_result(HELP)
        # Stop propagation after delivering the reply to avoid duplicate help.
        event.stop_event()

    @filter.command("查询")
    async def query(self, event: AstrMessageEvent, args: GreedyStr):
        """Query recent competitive matches, accepting the old explicit mode prefix."""
        mode = "competitive"
        args = args.strip()
        explicit_mode = re.match(r"^(竞技|休闲)(?:\s+|$)", args)
        if explicit_mode:
            mode = "competitive" if explicit_mode[1] == "竞技" else "leisure"
            args = args[explicit_mode.end() :].strip()
        async for reply in self._query(event, args, mode):
            yield reply

    @filter.command("查询休闲")
    async def query_leisure(self, event: AstrMessageEvent, args: GreedyStr):
        """Query recent leisure matches using a saved tag, explicit tags, or an image."""
        async for reply in self._query(event, args, mode="leisure"):
            yield reply

    @filter.command("韩服数据")
    async def hero_rates(self, event: AstrMessageEvent, args: GreedyStr):
        """Return a complete Chinese hero statistics image for a fixed Korea preset."""
        event.should_call_llm(False)
        role = {"坦克": "tank", "输出": "damage", "辅助": "support"}.get(args.strip())
        if role is None:
            yield event.plain_result(
                "用法：/韩服数据 坦克，或 /韩服数据 输出、/韩服数据 辅助。\n固定：韩服 · 大师 · 竞技职责预选 · 所有地图 · PC，按胜率排序，每24小时更新缓存。"
            )
            return
        identity, acquired = None, False
        try:
            identity = self._identity(event)
            if identity in self.busy:
                yield event.plain_result("你上一条查询仍在运行，请等它完成。")
                return
            self.busy.add(identity)
            acquired = True
            selected = {
                "role": role,
                "rq": "2",
                "rank": "master",
                "map": "all",
                "input": "pc",
                "region": "korea",
            }
            yield event.plain_result(
                f"正在读取韩服大师{args.strip()}数据缓存，将返回按胜率排序的完整中文数据图…"
            )
            report = await self.api.request("GET", "/api/hero-rates", params=selected)
            if (
                report.get("filters") != selected
                or report.get("report_type") != "hero_rates"
            ):
                raise ValueError("统计筛选条件不匹配，未生成其他段位或地区的图片。")
            if not report.get("heroes"):
                yield event.plain_result("原站在这些筛选条件下暂无英雄数据。")
                return
            picture = await self.renderer.render(report)
            yield event.chain_result([Image.fromBytes(picture)])
        except ValueError as error:
            yield event.plain_result(str(error))
        except Exception as error:
            logger.error("Hero statistics image failed: %s", type(error).__name__)
            yield event.plain_result("韩服数据或图片生成暂时不可用，请稍后重试。")
        finally:
            if acquired:
                self.busy.discard(identity)

    @filter.custom_filter(ScreenshotOnly)
    async def screenshot(self, event: AstrMessageEvent):
        """Accept an image only after a query request in this same conversation."""
        try:
            key = self._conversation(event)
        except ValueError:
            return
        pending = self.pending_images.pop(key, None)
        if pending is None:
            return
        if pending[1] <= time.monotonic():
            event.should_call_llm(False)
            command = "/查询休闲" if pending[0] == "leisure" else "/查询"
            yield event.plain_result(f"等待截图已超时，请重新发送 {command} 图片。")
            return
        async for reply in self._query(event, "", mode=pending[0]):
            yield reply

    async def terminate(self):
        """Release the API client and headless browser on plugin unload."""
        await self.api.close()
        await self.renderer.close()
