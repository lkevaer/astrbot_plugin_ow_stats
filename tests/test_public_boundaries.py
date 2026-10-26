"""Offline service-identity, admission, asset and rendering regressions."""
import asyncio
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

import httpx

from ..core import OWClient, QueryGate
from ..render import WebRenderer, UI_PATH


class AdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_bot_gate_limits_user_group_and_total_before_work(self):
        gate = QueryGate()
        gate.enter("one", "group-a")
        with self.assertRaisesRegex(ValueError, "上一条"):
            gate.enter("one", "group-b")
        gate.enter("two", "group-a")
        with self.assertRaisesRegex(ValueError, "本群"):
            gate.enter("three", "group-a")
        gate.enter("three", "group-b")
        gate.enter("four", "group-b")
        with self.assertRaisesRegex(ValueError, "繁忙"):
            gate.enter("five", "group-c")
        gate.leave("one")
        gate.enter("five", "group-c")
        self.assertEqual(len(gate.active), 4)

    async def test_service_identity_is_isolated_per_request_not_shared_cookie(self):
        calls = []
        async def handler(request):
            calls.append(request)
            return httpx.Response(200, json={"success": True, "data": {}}, headers={"Set-Cookie": "ow_browser_id=shared"})
        client = OWClient("https://test.invalid", service_key="test-only-service-key", transport=httpx.MockTransport(handler))
        try:
            await asyncio.gather(*(client.request("GET", "/api/batch-rating/rules", actor=("qq", name, "group")) for name in ["alice", "bob"]))
            self.assertNotEqual(calls[0].headers["x-bot-user"], calls[1].headers["x-bot-user"])
            self.assertEqual(calls[0].headers["x-bot-group"], calls[1].headers["x-bot-group"])
            self.assertEqual(calls[0].headers["x-bot-key"], "test-only-service-key")
            self.assertNotIn("alice", calls[0].headers["x-bot-user"])
            with self.assertRaises(ValueError):
                await client.request("GET", "/api/batch-rating/rules")
        finally:
            await client.close()

    async def test_rate_and_busy_errors_preserve_public_message_and_retry(self):
        client = OWClient("https://test.invalid", transport=httpx.MockTransport(
            lambda _: httpx.Response(429, json={"success": False, "error": "服务繁忙"}, headers={"Retry-After": "7"})))
        try:
            with self.assertRaisesRegex(ValueError, "服务繁忙.*7秒"):
                await client.request("POST", "/api/batch-rating/competitive")
        finally:
            await client.close()

    async def test_hero_png_cache_coalesces_and_expires_on_data_change(self):
        renderer = WebRenderer()
        async def image(report):
            await asyncio.sleep(0)
            return b"PNG-test"
        renderer._render_once = AsyncMock(side_effect=image)
        report = {"report_type": "hero_rates", "heroes": [], "fetched_at": 1}
        try:
            first, second = await asyncio.gather(renderer.render(report), renderer.render(report))
            self.assertEqual(first, second)
            self.assertEqual(renderer._render_once.await_count, 1)
            await renderer.render({**report, "fetched_at": 2})
            self.assertEqual(renderer._render_once.await_count, 2)
        finally:
            await renderer.close()

    async def test_renderer_has_a_bounded_waiting_room(self):
        renderer = WebRenderer()
        release = asyncio.Event()
        async def blocked(report):
            await release.wait()
            return b"PNG-test"
        renderer._render_once = blocked
        tasks = [asyncio.create_task(renderer.render({"players": []})) for _ in range(2)]
        try:
            await asyncio.sleep(0)
            with self.assertRaisesRegex(ValueError, "繁忙"):
                await renderer.render({"players": []})
            self.assertEqual(renderer.pending, 2)
        finally:
            release.set()
            await asyncio.gather(*tasks)
            await renderer.close()
        self.assertEqual(renderer.pending, 0)

    async def test_pinned_ui_manifest_covers_all_assets_and_fallbacks(self):
        manifest = json.loads((UI_PATH / "MANIFEST.json").read_text(encoding="utf-8"))
        actual = {str(path.relative_to(UI_PATH)).replace("\\", "/") for path in UI_PATH.rglob("*")
                  if path.is_file() and path.name not in {"SOURCE.md", "MANIFEST.json"}}
        self.assertEqual(actual, set(manifest["sha256"]))
        for name, digest in manifest["sha256"].items():
            self.assertEqual(hashlib.sha256((UI_PATH / name).read_bytes()).hexdigest(), digest, name)
        for kind in ["hero", "map", "rank"]:
            self.assertIn("game-icons/" + kind + "-default.svg", actual)
        self.assertIn("game_assets.js", actual)


if __name__ == "__main__":
    unittest.main()
