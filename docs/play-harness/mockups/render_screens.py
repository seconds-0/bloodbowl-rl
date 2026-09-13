"""Render the static play-harness mockups to PNG (desktop 1440x900, phone 400 wide).

Usage: .venv/bin/python docs/play-harness/mockups/render_screens.py [name ...]
"""
import os
import sys

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "png")


def main(names):
    pages = sorted(f for f in os.listdir(HERE) if f.endswith(".html"))
    if names:
        pages = [p for p in pages if any(p.startswith(n) for n in names)]
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for page_name in pages:
            stem = page_name[:-5]
            url = "file://" + os.path.join(HERE, page_name)
            for label, viewport, full in (("desktop", {"width": 1440, "height": 900}, False),
                                          ("phone", {"width": 400, "height": 860}, True)):
                ctx = browser.new_context(viewport=viewport, device_scale_factor=2 if label == "phone" else 1)
                page = ctx.new_page()
                page.goto(url)
                page.wait_for_load_state("networkidle")
                page.evaluate("document.fonts.ready")
                page.wait_for_timeout(300)
                overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
                path = os.path.join(OUT, f"{stem}-{label}.png")
                page.screenshot(path=path, full_page=full)
                print(path, "horizontal-overflow" if overflow else "")
                ctx.close()
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1:])
