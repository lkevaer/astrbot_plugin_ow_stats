"""Exercise AstrBot's real command filters without connecting or sending to QQ."""

import base64
import importlib.util
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

if importlib.util.find_spec("astrbot") is None:
    raise unittest.SkipTest("Install AstrBot or add its checkout to PYTHONPATH.")

from astrbot.api.message_components import Image
from astrbot.core.star.filter.command import CommandFilter
from astrbot.core.star.star_handler import star_handlers_registry

from ..main import OWStatsPlugin

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jZZkAAAAASUVORK5CYII="
)


class Event:
    def __init__(
        self, text, sender="sender-a", platform="qq-a", session="group-a", messages=None
    ):
        self.text, self.sender, self.platform, self.session = (
            text,
            sender,
            platform,
            session,
        )
        self.messages = messages or []
        self.is_at_or_wake_command = True
        self.extras = {}
        self.call_llm = True

    def get_platform_id(self):
        return self.platform

    def get_sender_id(self):
        return self.sender

    def get_session_id(self):
        return self.session

    def get_message_str(self):
        return self.text

    def get_messages(self):
        return self.messages

    def set_extra(self, key, value):
        self.extras[key] = value

    def get_extra(self, key, default=None):
        return self.extras.get(key, default)

    def should_call_llm(self, value):
        self.call_llm = value

    def plain_result(self, text):
        return "text", text

    def chain_result(self, chain):
        return "chain", chain


class API:
    def __init__(self):
        self.calls = []
        self.ocr = {"battletags": ["甲#1234", "乙#1234"], "review_count": 0}

    async def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self.ocr

    async def rating(self, mode, tags):
        self.calls.append(("rating", mode, tags))
        return {"players": [{"battletag": tag} for tag in tags]}

    async def close(self):
        pass


class Renderer:
    async def render(self, report):
        return PNG

    async def close(self):
        pass


class CommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        with patch(
            "astrbot_plugin_ow_stats.main.get_astrbot_data_path",
            return_value=self.folder.name,
        ):
            self.plugin = OWStatsPlugin(None, {"api_url": "https://ow.test"})
        await self.plugin.api.close()
        self.plugin.api = API()
        self.plugin.renderer = Renderer()
        self.image_path = Path(self.folder.name) / "roster.png"
        self.image_path.write_bytes(PNG)

    async def asyncTearDown(self):
        await self.plugin.terminate()
        self.folder.cleanup()

    async def command(self, event):
        for handler in star_handlers_registry:
            if handler.handler_module_path == OWStatsPlugin.__module__ and all(
                f.filter(event, {}) for f in handler.event_filters
            ):
                return [
                    reply
                    async for reply in handler.handler(
                        self.plugin, event, **event.get_extra("parsed_params", {})
                    )
                ]
        self.fail("AstrBot did not recognize the requested command.")

    async def test_only_three_commands_are_registered(self):
        commands = {
            f.command_name
            for handler in star_handlers_registry
            if handler.handler_module_path == OWStatsPlugin.__module__
            for f in handler.event_filters
            if isinstance(f, CommandFilter)
        }
        self.assertEqual(commands, {"绑定", "解绑", "查询"})

    async def test_bound_query_returns_original_png_and_unbind_is_sender_scoped(self):
        await self.command(Event("绑定 本人＃1234"))
        await self.command(Event("绑定 队友#5678", sender="sender-b"))
        event = Event("查询")
        replies = await self.command(event)
        self.assertEqual(
            self.plugin.api.calls[-1], ("rating", "competitive", ["本人#1234"])
        )
        self.assertFalse(event.call_llm)
        self.assertEqual(
            replies[-1][1][0].file, "base64://" + base64.b64encode(PNG).decode()
        )
        await self.command(Event("解绑"))
        self.assertIsNone(self.plugin.bindings.get("qq-a", "sender-a"))
        self.assertEqual(self.plugin.bindings.get("qq-a", "sender-b"), "队友#5678")

    async def test_temporary_target_and_mode_do_not_replace_binding(self):
        await self.command(Event("绑定 本人#1234"))
        await self.command(Event("查询 休闲 临时#5678"))
        self.assertEqual(
            self.plugin.api.calls[-1], ("rating", "leisure", ["临时#5678"])
        )
        self.assertEqual(self.plugin.bindings.get("qq-a", "sender-a"), "本人#1234")

    async def test_four_teammates_include_self_once_and_deduplicate(self):
        await self.command(Event("绑定 本人#1234"))
        await self.command(Event("查询 甲#1234 乙#1234 丙#1234 丁#1234 甲#1234"))
        self.assertEqual(
            self.plugin.api.calls[-1][2],
            ["甲#1234", "乙#1234", "丙#1234", "丁#1234", "本人#1234"],
        )

    async def test_same_message_image_uses_ocr_then_rating(self):
        event = Event("查询", messages=[Image.fromFileSystem(str(self.image_path))])
        await self.command(event)
        self.assertEqual(
            self.plugin.api.calls[0][:2], ("POST", "/api/batch-rating/recognize")
        )
        self.assertEqual(
            self.plugin.api.calls[-1], ("rating", "competitive", ["甲#1234", "乙#1234"])
        )

    async def test_uncertain_ocr_and_mixed_text_image_stop_before_query(self):
        self.plugin.api.ocr["review_count"] = 1
        replies = await self.command(
            Event("查询", messages=[Image.fromFileSystem(str(self.image_path))])
        )
        self.assertIn("重新输入 /查询", replies[-1][1])
        self.assertFalse(any(call[0] == "rating" for call in self.plugin.api.calls))
        replies = await self.command(
            Event(
                "查询 本人#1234", messages=[Image.fromFileSystem(str(self.image_path))]
            )
        )
        self.assertIn("任选其一", replies[-1][1])

    async def test_pending_image_is_scoped_to_both_sender_and_conversation(self):
        await self.command(Event("查询 休闲 图片"))
        wrong = Event(
            "", session="group-b", messages=[Image.fromFileSystem(str(self.image_path))]
        )
        self.assertEqual(await self.command(wrong), [])
        self.assertTrue(wrong.call_llm)
        self.assertEqual(self.plugin.api.calls, [])
        await self.command(
            Event("", messages=[Image.fromFileSystem(str(self.image_path))])
        )
        self.assertEqual(self.plugin.api.calls[-1][1], "leisure")

    async def test_unsolicited_and_expired_images_never_run_queries(self):
        image = [Image.fromFileSystem(str(self.image_path))]
        self.assertEqual(await self.command(Event("", messages=image)), [])
        self.plugin.pending_images[("qq-a", "sender-a", "group-a")] = (
            "competitive",
            time.monotonic() - 1,
        )
        replies = await self.command(Event("", messages=image))
        self.assertIn("已超时", replies[-1][1])
        self.assertEqual(self.plugin.api.calls, [])

    async def test_busy_rejection_preserves_active_request_lock(self):
        self.plugin.busy.add(("qq-a", "sender-a"))
        replies = await self.command(Event("查询 本人#1234"))
        self.assertIn("仍在运行", replies[-1][1])
        self.assertIn(("qq-a", "sender-a"), self.plugin.busy)
        self.assertEqual(self.plugin.api.calls, [])

    async def test_missing_sender_is_reported_without_crashing(self):
        replies = await self.command(Event("查询 本人#1234", sender=""))
        self.assertIn("无法确认", replies[-1][1])
