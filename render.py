"""Render the website's original UI as a complete, expanded, lossless report."""

from __future__ import annotations

import asyncio
import io
import json
import math
import os
import re
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
    footer.textContent = '访问 lkevaer.xyz 查询完整评分规则';
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
#botRulesFooter { margin-top: 24px; color: var(--muted); opacity: .8;
    font-size: 13px; text-align: center; }
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
                viewport={"width": 1600, "height": 1000},
                device_scale_factor=2,
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                service_workers="block",
            )
            try:
                assets = {
                    "/": (
                        "text/html",
                        re.sub(
                            r'<script\b[^>]*src="/static/(?:ocr_crop|batch_rating_ocr)\.js"[^>]*></script>',
                            "",
                            (UI_PATH / "batch_rating.html").read_text(encoding="utf-8"),
                        ),
                    ),
                    "/health": (
                        "application/json",
                        json.dumps({"api_key_required": False}),
                    ),
                }
                for name in (
                    "batch_rating.css",
                    "rating_account.js",
                    "batch_rating.js",
                ):
                    assets["/static/" + name] = (
                        "text/css"
                        if name.endswith(".css")
                        else "application/javascript",
                        (UI_PATH / name).read_text(encoding="utf-8"),
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
                    "typeof render === 'function'", timeout=15000
                )
                await page.add_style_tag(content=REPORT_CSS)
                await page.evaluate(REPORT_PREPARE, report)
                # Measure every expanded table, including nested detail padding.
                width = await page.evaluate("""() => {
                    const main = document.querySelector('main');
                    const left = main.getBoundingClientRect().left;
                    const padding = parseFloat(getComputedStyle(main).paddingRight);
                    return Math.ceil(Math.max(1600, ...[...main.querySelectorAll('table')].map(
                        table => table.getBoundingClientRect().right - left + padding + 32
                    )));
                }""")
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
                return await asyncio.to_thread(
                    self._join_tiles, tiles, width * 2, height * 2
                )
            finally:
                await context.close()

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
        with Image.new("RGB", (width, height)) as canvas:
            offset = 0
            for tile in tiles:
                with Image.open(io.BytesIO(tile)) as image:
                    if image.width != width or offset + image.height > height:
                        raise ValueError("长图分段尺寸异常，本次未输出不完整图片。")
                    canvas.paste(image, (0, offset))
                    offset += image.height
            if offset != height:
                raise ValueError("长图分段不完整，本次未输出不完整图片。")
            output = io.BytesIO()
            canvas.save(output, format="PNG", compress_level=9)
            return output.getvalue()

    async def close(self):
        """Release the renderer when AstrBot unloads the plugin."""
        async with self.lock:
            if self.browser is not None:
                await self.browser.close()
            if self.driver is not None:
                await self.driver.stop()
            self.browser = self.driver = None
