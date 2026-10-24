"""Verify rendered PNGs and inspect the real DOM immediately before capture."""

import io
import struct
import unittest
from unittest.mock import patch

from PIL import Image
from playwright.async_api import Page

from ..render import WebRenderer
from .fixtures import make_report


class RenderTests(unittest.IsolatedAsyncioTestCase):
    async def test_hero_rate_images_include_every_hero_and_all_filter_labels(self):
        renderer = WebRenderer()
        original = Page.screenshot
        observed = []

        async def inspect(page, *args, **kwargs):
            observed.append(
                await page.evaluate("""() => ({
                count: document.querySelectorAll('#heroRateRows > tr').length,
                animatedRows: document.querySelectorAll('#heroRateRows .reveal-row').length,
                rowsVisible: [...document.querySelectorAll('#heroRateRows > tr')].every(row => getComputedStyle(row).opacity === '1'),
                filters: [...document.querySelectorAll('.static-filter')].map(node => node.textContent),
                body: document.querySelector('main').innerText,
                controls: document.querySelectorAll('main input, main button, main select').length,
                sort: document.querySelector('th[data-sort=winRate]').getAttribute('aria-sort'),
                width: document.querySelector('main').getBoundingClientRect().width,
                height: document.querySelector('main').getBoundingClientRect().height,
            })""")
            )
            return await original(page, *args, **kwargs)

        try:
            with patch.object(Page, "screenshot", inspect):
                for role, label, count in [
                    ("tank", "坦克", 15),
                    ("damage", "输出", 22),
                    ("support", "辅助", 17),
                ]:
                    observed.clear()
                    heroes = [
                        {
                            "heroId": f"example-{index}",
                            "name": f"示例{label}{index}",
                            "role": role,
                            "winRate": 60 - index,
                            "pickRate": index,
                            "banRate": index / 2,
                            "thumbnailUrl": None,
                            "colorCode": "#739baa",
                        }
                        for index in range(count)
                    ]
                    png = await renderer.render(
                        {
                            "report_type": "hero_rates",
                            "heroes": heroes,
                            "filters": {
                                "role": role,
                                "rq": "2",
                                "rank": "master",
                                "map": "all",
                                "input": "pc",
                                "region": "korea",
                            },
                            "filter_labels": {
                                "role": label,
                                "rq": "竞技比赛 · 职责预选",
                                "rank": "大师",
                                "map": "所有地图",
                                "input": "PC",
                                "region": "韩服",
                            },
                            "fetched_at": 1792800000,
                            "stale": False,
                            "source_url": "https://overwatch.nexon.com/hero/rate",
                        }
                    )
                    actual = observed[-1]
                    width, height = struct.unpack(">II", png[16:24])
                    self.assertEqual(actual["count"], count)
                    self.assertEqual(actual["animatedRows"], 0)
                    self.assertTrue(actual["rowsVisible"])
                    self.assertEqual(actual["controls"], 0)
                    self.assertEqual(actual["sort"], "descending")
                    for item in [label, "大师", "所有地图", "PC", "韩服"]:
                        self.assertIn(item, actual["filters"])
                    self.assertIn(f"示例{label}{count - 1}", actual["body"])
                    self.assertAlmostEqual(width, actual["width"] * 2, delta=2)
                    self.assertAlmostEqual(height, actual["height"] * 2, delta=2)
        finally:
            await renderer.close()

    def test_join_tiles_preserves_every_pixel_across_boundaries(self):
        tiles = []
        with Image.new("RGB", (7, 5)) as expected:
            offset = 0
            for tile_height in [2, 3]:
                with Image.new("RGBA", (7, tile_height)) as tile:
                    tile.putdata(
                        [
                            (x * 37, (y + offset) * 51, (x + y) * 23, x * 41)
                            for y in range(tile_height)
                            for x in range(7)
                        ]
                    )
                    expected.paste(tile, (0, offset))
                    output = io.BytesIO()
                    tile.save(output, format="PNG")
                    tiles.append(output.getvalue())
                offset += tile_height
            png = WebRenderer._join_tiles(tiles, 7, 5)
            with Image.open(io.BytesIO(png)) as actual:
                self.assertEqual(actual.mode, "RGB")
                self.assertEqual(actual.size, expected.size)
                self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_join_tiles_rejects_incomplete_or_mismatched_tiles(self):
        with Image.new("RGB", (7, 2)) as tile:
            output = io.BytesIO()
            tile.save(output, format="PNG")
        tiles = [output.getvalue()]
        with self.assertRaisesRegex(ValueError, "尺寸异常"):
            WebRenderer._join_tiles(tiles, 8, 2)
        with self.assertRaisesRegex(ValueError, "尺寸异常"):
            WebRenderer._join_tiles(tiles, 7, 1)
        with self.assertRaisesRegex(ValueError, "不完整"):
            WebRenderer._join_tiles(tiles, 7, 3)

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
                    webDetails: document.querySelectorAll('.match-details-row, .toggle-match-details, #metricHint, .metric-button').length,
                    values: [...document.querySelectorAll('.static-metric')].map(node => node.textContent),
                    headings: [...document.querySelectorAll('#details > details:first-child > .scroll > table > thead th')].map(node => node.textContent.trim()),
                    alignedValues: [...document.querySelectorAll('#details .metrics > tbody > tr')].every(row => {
                        const tops = [...row.querySelectorAll('.metric-main')].map(node => node.getBoundingClientRect().top);
                        return !tops.length || Math.max(...tops) - Math.min(...tops) < .6;
                    }),
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
                        report = make_report(count, mode)
                        report["players"][0]["matches"][0]["match_details"] = {
                            "other_players": [{"battletag": "网页专属#9876"}],
                            "total_players": 10,
                            "rated_players": 10,
                        }
                        png = await renderer.render(report)
                        observed = observations[-1]
                        width, height = struct.unpack(">II", png[16:24])
                        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
                        self.assertAlmostEqual(width, observed["width"] * 2, delta=2)
                        self.assertAlmostEqual(height, observed["height"] * 2, delta=2)
                        self.assertEqual(observed["players"], count)
                        self.assertEqual(observed["rows"], count * 12)
                        self.assertFalse(observed["clipped"])
                        self.assertEqual(observed["controls"], 0)
                        self.assertEqual(observed["webDetails"], 0)
                        self.assertTrue(observed["alignedValues"])
                        for heading in [
                            "本场评分",
                            "最后一击占比",
                            "FLETA指数",
                            "击杀",
                            "助攻",
                            "阵亡",
                            "KD",
                            "伤害/10分",
                            "治疗/10分",
                        ]:
                            self.assertIn(heading, observed["headings"])
                        self.assertNotIn("胜负", observed["headings"])
                        self.assertNotIn("网页专属#9876", observed["body"])
                        for value in ["28", "9", "3", "86.0%"]:
                            self.assertIn(value, observed["values"])
                        self.assertFalse(observed["rulesOpen"])
                        self.assertEqual(observed["rulesVisibleHeight"], 0)
                        self.assertLess(observed["lastBottom"], observed["mainBottom"])
                        self.assertIn("https://lkevaer.xyz", observed["footer"])
                        self.assertIn(
                            "进入网页版查询当局所有人评分评级", observed["footer"]
                        )
                        self.assertIn("查询完整评分规则", observed["footer"])
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
        finally:
            await renderer.close()
