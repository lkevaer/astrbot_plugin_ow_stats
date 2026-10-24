"""Verify rendered PNGs and inspect the real DOM immediately before capture."""

import io
import struct
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops
from playwright.async_api import Page

from ..render import WebRenderer
from .fixtures import make_report


class RenderTests(unittest.IsolatedAsyncioTestCase):
    async def test_expanded_reports_keep_all_rows_without_horizontal_clipping(self):
        renderer = WebRenderer()
        original = Page.screenshot
        observations = []
        captures = []

        async def inspect(page, *args, **kwargs):
            observations.append(
                await page.evaluate("""() => {
                const main = document.querySelector('main').getBoundingClientRect();
                const last = document.querySelector('#details > details:last-child');
                return {
                    players: document.querySelectorAll('#details > details[open]').length,
                    rows: document.querySelectorAll('#details tbody > tr').length,
                    clipped: [...document.querySelectorAll('.scroll')].some(node => node.scrollWidth > node.clientWidth + 1),
                    controls: document.querySelectorAll('main input, main textarea, main button, #selfBinding, .inputs').length,
                    rulesOpen: document.querySelector('#scoringReference').open,
                    rulesVisibleHeight: document.querySelector('.rule-reference').getBoundingClientRect().height,
                    footer: document.querySelector('#botRulesFooter').textContent,
                    lastBottom: last.getBoundingClientRect().bottom,
                    mainBottom: main.bottom, width: main.width, height: main.height,
                    scrollY: window.scrollY, viewportHeight: window.innerHeight,
                    footerBottom: document.querySelector('#botRulesFooter').getBoundingClientRect().bottom,
                    hasMvp: !!document.querySelector('.highlight-mvp .award.mvp'),
                    hasSmurf: !!document.querySelector('.smurf'),
                    hasRank: !!document.querySelector('#details .rank-badge'),
                    body: document.querySelector('main').innerText,
                };
            }""")
            )
            picture = await original(page, *args, **kwargs)
            captures.append(picture)
            return picture

        try:
            with patch.object(Page, "screenshot", inspect):
                for count, mode in [
                    (1, "leisure"),
                    (5, "competitive"),
                    (10, "competitive"),
                ]:
                    with self.subTest(count=count, mode=mode):
                        observations.clear()
                        captures.clear()
                        png = await renderer.render(make_report(count, mode))
                        observed = observations[-1]
                        width, height = struct.unpack(">II", png[16:24])
                        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
                        self.assertAlmostEqual(width, observed["width"] * 2, delta=2)
                        self.assertAlmostEqual(height, observed["height"] * 2, delta=2)
                        self.assertEqual(observed["players"], count)
                        self.assertEqual(observed["rows"], count * 12)
                        self.assertFalse(observed["clipped"])
                        self.assertEqual(observed["controls"], 0)
                        self.assertFalse(observed["rulesOpen"])
                        self.assertEqual(observed["rulesVisibleHeight"], 0)
                        self.assertLess(observed["lastBottom"], observed["mainBottom"])
                        self.assertIn(
                            "访问 lkevaer.xyz 查询完整评分规则", observed["footer"]
                        )
                        self.assertIn(f"示例玩家{count}#12345", observed["body"])
                        self.assertIn("第12场", observed["body"])
                        self.assertTrue(observed["hasMvp"])
                        self.assertTrue(observed["hasSmurf"])
                        self.assertEqual(observed["hasRank"], mode == "competitive")
                        self.assertGreater(len(captures), 1)
                        self.assertEqual(
                            [entry["scrollY"] for entry in observations],
                            list(range(0, int(observed["height"] + 0.999), 2000)),
                        )
                        self.assertLessEqual(
                            observed["footerBottom"], observed["viewportHeight"]
                        )
                        if count == 5:
                            with (
                                Image.open(io.BytesIO(png)) as joined,
                                Image.open(io.BytesIO(captures[-1])) as tail,
                            ):
                                crop = joined.crop(
                                    (
                                        0,
                                        joined.height - tail.height,
                                        joined.width,
                                        joined.height,
                                    )
                                )
                                self.assertIsNone(
                                    ImageChops.difference(
                                        crop.convert("RGB"), tail.convert("RGB")
                                    ).getbbox()
                                )
        finally:
            await renderer.close()
