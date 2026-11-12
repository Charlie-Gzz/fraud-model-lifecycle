"""Render SVG diagrams to PNG with headless Chromium (Playwright)."""

from __future__ import annotations

from pathlib import Path

from fml import REPO_ROOT

DIAGRAMS = REPO_ROOT / "assets" / "diagrams"


def svg_to_png(svg: Path, png: Path, scale: float = 2.0) -> Path:
    from playwright.sync_api import sync_playwright

    text = svg.read_text(encoding="utf-8")
    import re

    m = re.search(r'viewBox="0 0 (\d+) (\d+)"', text)
    w, h = (int(m.group(1)), int(m.group(2))) if m else (1400, 800)
    html = f"<html><body style='margin:0;background:#0B0F17'>{text}</body></html>"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=scale)
        page.set_content(html, wait_until="networkidle")
        page.locator("svg").first.screenshot(path=str(png))
        browser.close()
    return png


def diagrams() -> list[Path]:
    return [
        svg_to_png(s, s.with_suffix(".png"), scale=1600 / 1400)
        for s in sorted(DIAGRAMS.glob("*.svg"))
    ]


if __name__ == "__main__":
    for p in diagrams():
        print(p)
