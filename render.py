"""Render the website's original UI as a complete, expanded, lossless report."""

from __future__ import annotations

import asyncio
import io
import json
import math
import os
import re
import struct
import zlib
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image
from playwright.async_api import async_playwright

REPORT_ORIGIN = "https://ow-report.invalid"
UI_PATH = Path(__file__).with_name("report_ui")
REPORT_PREPARE = """report => {
    render(report);
    document.querySelector('.inputs').closest('section').remove();
    document.querySelector('#selfBinding')?.remove();
    document.querySelectorAll('.site-nav, .web-callout, .match-query-column').forEach(node => node.remove());
    document.querySelectorAll('main button').forEach(node => node.remove());
    document.querySelector('.sub').textContent = '近12场休闲或竞技表现 · 玩家逐场详情已展开';
    document.querySelectorAll('#details details').forEach(node => node.open = true);
    document.querySelector('#scoringReference').open = false;
    document.querySelectorAll('#results .key span').forEach(node => {
        if (node.textContent === '展开玩家查看逐场详情') node.textContent = '玩家逐场详情（已展开）';
    });
    const summary = document.querySelector('#horseSummary');
    const output = document.createElement('div');
    output.id = 'horseSummary';
    output.className = 'bot-summary';
    output.textContent = summary.value;
    summary.replaceWith(output);
    const summaryLabel = document.querySelector('label[for=horseSummary]');
    if (summaryLabel) {
        const note = document.createElement('p');
        note.className = 'note'; note.textContent = summaryLabel.textContent;
        summaryLabel.replaceWith(note);
    }
    const footer = document.createElement('footer');
    footer.id = 'botRulesFooter';
    footer.innerHTML = '<strong>访问 lkevaer.xyz</strong><span>进入网页版查询当局所有人评分评级</span><small>查询完整评分规则 · 展开每场详情，点击“查询当局”</small>';
    document.querySelector('main').append(footer);
    document.querySelectorAll('img[loading=lazy]').forEach(node => node.loading = 'eager');
}"""

REPORT_CSS = """
main { max-width: none; width: 1600px; margin: 0; padding-bottom: 28px; }
.scroll { overflow: visible !important; }
#scoringReference:not([open]) > :not(summary) { display: none !important; }
.bot-summary { white-space: pre-wrap; overflow-wrap: anywhere; padding: 12px;
    border: 1px solid #536b89; border-radius: 9px; background: #101a2a;
    font-size: 15px; line-height: 1.9; }
#botRulesFooter { margin-top: 26px; padding: 24px; color: #f3d4a2;
    border: 1px solid #9e7b42; border-radius: 12px; background: #242d3d; text-align: center; }
#botRulesFooter strong { display: block; color: #ffd18b; font-size: 24px; }
#botRulesFooter span { display: block; font-size: 18px; margin-top: 7px; }
#botRulesFooter small { display: block; color: #aebbd0; margin-top: 7px; font-size: 13px; }
*, *::before, *::after { animation: none !important; transition: none !important; }
"""

HERO_PREPARE = """report => {
    renderHeroRates(report);
    document.querySelector('.hero-nav')?.remove();
    document.querySelector('#heroAccess')?.remove();
    document.querySelectorAll('#heroFilters select').forEach(select => {
        const value = document.createElement('span'); value.className = 'static-filter';
        value.textContent = report.filter_labels[select.id]; select.replaceWith(value);
    });
    document.querySelectorAll('main button').forEach(button => {
        const label = document.createElement('span'); label.innerHTML = button.innerHTML;
        button.replaceWith(label);
    });
    document.querySelectorAll('img').forEach(image => image.loading = 'eager');
}"""

HERO_CSS = """
main { width: 1400px; margin: 0; }
.hero-board { padding: 0 32px 32px; margin: 35px 0 0; }
.hero-filters { grid-template-columns: repeat(6, minmax(0,1fr)); }
.hero-rate-table th > span { display: flex; gap: 10px; align-items: center; font-size: 17px; }
*, *::before, *::after { animation: none !important; transition: none !important; }
"""


class WebRenderer:
    """Use a pinned copy of the website UI without dashboard cookies or API keys."""

    def __init__(self):
        self.driver = None
        self.browser = None
        self.lock = asyncio.Lock()

    async def render(self, report: dict) -> bytes:
        """Expand all player tables and capture the entire report at double density.

        Args:
            report: An unmodified result returned by the existing rating API.

        Returns:
            Original PNG bytes with no resizing or lossy compression.

        Raises:
            ValueError: The browser is unavailable or any report content is clipped.
        """
        async with self.lock:
            hero_report = report.get("report_type") == "hero_rates"
            minimum_width = 1400 if hero_report else 1600
            if self.browser is None or not self.browser.is_connected():
                if self.driver is None:
                    self.driver = await async_playwright().start()
                options = {"headless": True}
                if os.name == "nt":
                    edge = (
                        Path(
                            os.environ.get(
                                "PROGRAMFILES(X86)", "C:/Program Files (x86)"
                            )
                        )
                        / "Microsoft/Edge/Application/msedge.exe"
                    )
                    if edge.exists():
                        options["channel"] = "msedge"
                try:
                    self.browser = await self.driver.chromium.launch(**options)
                except Exception as exc:
                    raise ValueError(
                        "长图组件未就绪，请管理员安装 Chromium 和中文字体。"
                    ) from exc
            context = await self.browser.new_context(
                viewport={"width": minimum_width, "height": 1000},
                device_scale_factor=2,
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                service_workers="block",
            )
            try:
                await context.add_init_script("window.__OW_STATIC_REPORT__ = true;")
                assets = {
                    "/": (
                        "text/html",
                        re.sub(
                            r'<script\b[^>]*src="/static/(?:ocr_crop|batch_rating_ocr)\.js"[^>]*></script>',
                            "",
                            (
                                UI_PATH
                                / (
                                    "hero_rates.html"
                                    if hero_report
                                    else "batch_rating.html"
                                )
                            ).read_text(encoding="utf-8"),
                        ),
                    ),
                    "/health": (
                        "application/json",
                        json.dumps({"api_key_required": False}),
                    ),
                }
                names = (
                    ("hero_rates.css", "hero_rates.js", "hero_rates_banner.png")
                    if hero_report
                    else ("batch_rating.css", "rating_account.js", "batch_rating.js")
                )
                for name in names:
                    assets["/static/" + name] = (
                        "image/png"
                        if name.endswith(".png")
                        else "text/css"
                        if name.endswith(".css")
                        else "application/javascript",
                        (UI_PATH / name).read_bytes()
                        if name.endswith(".png")
                        else (UI_PATH / name).read_text(encoding="utf-8"),
                    )

                async def serve(route):
                    request = route.request
                    url = urlsplit(request.url)
                    if (
                        url.scheme + "://" + url.netloc == REPORT_ORIGIN
                        and url.path in assets
                    ):
                        content_type, body = assets[url.path]
                        await route.fulfill(
                            status=200, content_type=content_type, body=body
                        )
                    elif request.resource_type == "image" and url.scheme in {
                        "https",
                        "http",
                    }:
                        await route.continue_()
                    else:
                        await route.abort()

                await context.route("**/*", serve)
                page = await context.new_page()
                await page.goto(REPORT_ORIGIN + "/", wait_until="load", timeout=30000)
                await page.wait_for_function(
                    "typeof renderHeroRates === 'function'"
                    if hero_report
                    else "typeof render === 'function'",
                    timeout=15000,
                )
                await page.add_style_tag(
                    content=HERO_CSS if hero_report else REPORT_CSS
                )
                await page.evaluate(
                    HERO_PREPARE if hero_report else REPORT_PREPARE, report
                )
                # Measure every expanded table, including nested detail padding.
                width = await page.evaluate(
                    """minimumWidth => {
                    const main = document.querySelector('main');
                    const left = main.getBoundingClientRect().left;
                    const padding = parseFloat(getComputedStyle(main).paddingRight);
                    return Math.ceil(Math.max(minimumWidth, ...[...main.querySelectorAll('table')].map(
                        table => table.getBoundingClientRect().right - left + padding + 32
                    )));
                }""",
                    minimum_width,
                )
                await page.set_viewport_size({"width": width, "height": 1000})
                await page.add_style_tag(content=f"main {{ width: {width}px; }}")
                await page.evaluate("""async () => {
                    await document.fonts.ready;
                    await Promise.all([...document.images].map(img => img.complete ? Promise.resolve() : new Promise(resolve => {
                        img.addEventListener('load', resolve, {once:true});
                        img.addEventListener('error', resolve, {once:true});
                        setTimeout(resolve, 5000);
                    })));
                }""")
                if hero_report:
                    complete = await page.evaluate(
                        """report => {
                        const rows = [...document.querySelectorAll('#heroRateRows > tr')];
                        const main = document.querySelector('main').getBoundingClientRect();
                        return rows.length === report.heroes.length
                            && rows.every(row => report.heroes.some(hero => hero.heroId === row.dataset.hero))
                            && [...document.querySelectorAll('table')].every(table => table.getBoundingClientRect().right <= main.right - 10)
                            && document.querySelectorAll('.static-filter').length === 6
                            && !document.querySelector('main button, main select, main input');
                    }""",
                        report,
                    )
                else:
                    complete = await page.evaluate(
                        """report => {
                    const main = document.querySelector('main');
                    const bounds = main.getBoundingClientRect();
                    const details = [...document.querySelectorAll('#details > details')];
                    return document.querySelectorAll('#rankings > tr').length === report.players.length
                        && details.length === report.players.length && details.every(node => node.open)
                        && document.querySelectorAll('#details tbody > tr').length === report.players.reduce((n,p) => n + p.matches.length, 0)
                        && [...main.querySelectorAll('table')].every(table => table.getBoundingClientRect().right <= bounds.right - 10)
                        && !document.querySelector('#scoringReference').open
                        && !main.querySelector('input, textarea, button, #selfBinding, .inputs');
                }""",
                        report,
                    )
                if not complete:
                    raise ValueError(
                        "网页结果未完整展开或仍有表格被裁切，本次未输出不完整图片。"
                    )
                bounds = await page.locator("main").bounding_box()
                height = math.ceil(bounds["height"])
                await page.add_style_tag(
                    content=f"body {{ min-height: {height + 2}px; }}"
                )
                tiles = []
                # Large GPU textures can wrap at 16384 physical pixels on Windows.
                # Capture short viewports and join their original pixels instead.
                for offset in range(0, height, 2000):
                    tile_height = min(2000, height - offset)
                    await page.set_viewport_size(
                        {"width": width, "height": tile_height}
                    )
                    await page.evaluate("y => window.scrollTo(0, y)", offset)
                    position = await page.evaluate("window.scrollY")
                    if abs(position - offset) > 0.1:
                        raise ValueError("长图分段位置异常，本次未输出不完整图片。")
                    tiles.append(
                        await page.screenshot(
                            type="png",
                            animations="disabled",
                            timeout=60000,
                        )
                    )
            finally:
                await context.close()
            return await asyncio.to_thread(
                self._join_tiles, tiles, width * 2, height * 2
            )

    @staticmethod
    def _join_tiles(tiles: list[bytes], width: int, height: int) -> bytes:
        """Join bounded screenshots without resizing or changing their pixels.

        Args:
            tiles: Consecutive double-density viewport PNGs.
            width: Expected physical pixel width.
            height: Expected final physical pixel height.

        Returns:
            A single losslessly compressed RGB PNG.

        Raises:
            ValueError: A screenshot has unexpected dimensions or is incomplete.
        """
        output = io.BytesIO()
        output.write(b"\x89PNG\r\n\x1a\n")

        def write_chunk(kind: bytes, payload: bytes):
            """Write a PNG chunk and its checksum to the output stream."""
            output.write(struct.pack(">I", len(payload)))
            output.write(kind + payload)
            output.write(struct.pack(">I", zlib.crc32(kind + payload)))

        write_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        compressor = zlib.compressobj(9)
        stride = width * 3
        offset = 0
        # Encode one tile at a time instead of allocating a full-height canvas.
        for tile in tiles:
            with Image.open(io.BytesIO(tile)) as source:
                if source.width != width or offset + source.height > height:
                    raise ValueError("长图分段尺寸异常，本次未输出不完整图片。")
                with source.convert("RGB") as image:
                    pixels = image.tobytes()
                offset += source.height
            for row in range(0, len(pixels), stride):
                # Filter 0 keeps each row independent across tile boundaries.
                compressed = compressor.compress(b"\0" + pixels[row : row + stride])
                if compressed:
                    write_chunk(b"IDAT", compressed)
            del pixels
        if offset != height:
            raise ValueError("长图分段不完整，本次未输出不完整图片。")
        write_chunk(b"IDAT", compressor.flush())
        write_chunk(b"IEND", b"")
        return output.getvalue()

    async def close(self):
        """Release the renderer when AstrBot unloads the plugin."""
        async with self.lock:
            if self.browser is not None:
                await self.browser.close()
            if self.driver is not None:
                await self.driver.stop()
            self.browser = self.driver = None
