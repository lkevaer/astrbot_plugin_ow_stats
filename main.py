"""Provide three AstrBot commands backed by the existing OW rating service."""

from __future__ import annotations

import asyncio
import base64
import re
import time
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image
from astrbot.api.star import Context, Star
from astrbot.core.star.filter.command import GreedyStr
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .core import Bindings, OWClient, parse_tags, team_tags
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
        self.default_mode = config.get("default_mode", "competitive")
        if self.default_mode not in {"competitive", "leisure"}:
            raise ValueError("默认模式必须是 competitive 或 leisure。")
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

    async def _image_tags(self, event):
        """Pass a single bounded image to the service's existing OCR pipeline.

        Args:
            event: A command containing one roster screenshot.

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
                "未识别到完整ID，请裁剪名单后重试，或发送 /查询 昵称#12345。"
            )
        if recognized.get("review_count"):
            raise ValueError("识别有疑项，请核对后重新输入 /查询 " + " ".join(tags))
        return tags

    async def _query(self, event, args, mode=None):
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
            mode = mode or self.default_mode
            args = args.strip()
            explicit_mode = re.match(r"^(竞技|休闲)(?:\s+|$)", args)
            if explicit_mode:
                mode = "competitive" if explicit_mode[1] == "竞技" else "leisure"
                args = args[explicit_mode.end() :].strip()
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
                    "请在2分钟内发送一张名单截图（群聊需@我），或发送 /查询 昵称#12345。\n"
                    "用 /绑定 昵称#12345 后，/查询 可直接查自己。"
                )
                return
            if pictures:
                if tags:
                    raise ValueError("请附一张名单截图，或直接输入ID，两者任选其一。")
                yield event.plain_result("正在识别名单截图…")
                tags = await self._image_tags(event)
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
            yield event.chain_result([Image.fromBytes(picture)])
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
                f"已绑定 {tags[0]}。发送 /查询 查自己，/解绑 解除绑定。"
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

    @filter.command("查询")
    async def query(self, event: AstrMessageEvent, args: GreedyStr):
        """Query a BattleTag, a roster screenshot, or the sender's saved account."""
        async for reply in self._query(event, args):
            yield reply

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
            yield event.plain_result("等待截图已超时，请重新发送 /查询 图片。")
            return
        async for reply in self._query(event, "", mode=pending[0]):
            yield reply

    async def terminate(self):
        """Release the API client and headless browser on plugin unload."""
        await self.api.close()
        await self.renderer.close()
