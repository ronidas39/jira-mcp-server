"""Capture screenshots of every dashboard page against a running stack.

Hits the local dev or compose-deployed UI, walks every documented route,
and writes full-page PNGs into docs/screenshots/. Use as a substitute for
a screen recording when one is not available.

Prerequisites:
    pip install playwright
    playwright install chromium
    docker-compose --profile ui up -d   # or `npm run dev` in web/

Usage:
    python scripts/capture_screenshots.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import Browser, sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT = REPO_ROOT / "docs" / "screenshots"
BASE = "http://localhost:3000"

PAGES: list[tuple[str, str]] = [
    ("dashboard", "/"),
    ("issues-list", "/issues"),
    ("issues-new", "/issues/new"),
    ("issue-detail", "/issues/SCRUM-1"),
    ("projects-list", "/projects"),
    ("project-detail", "/projects/SCRUM"),
    ("sprints", "/sprints"),
    ("analytics", "/analytics"),
    ("chat", "/chat"),
    ("settings", "/settings"),
]


def capture(browser: Browser) -> int:
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    failures = 0
    for label, path in PAGES:
        url = BASE + path
        try:
            resp = page.goto(url, wait_until="networkidle", timeout=30_000)
            if resp is None or resp.status >= 400:
                print(f"  {label} {url} -> {resp.status if resp else 'no response'}")
                failures += 1
                continue
        except Exception as exc:
            print(f"  {label} {url} -> ERROR: {exc}")
            failures += 1
            continue
        page.wait_for_timeout(800)  # let TanStack Query settle
        out = OUT / f"{label}.png"
        page.screenshot(path=str(out), full_page=True)
        print(f"  {label}: {out.relative_to(REPO_ROOT)}")
    page.close()
    return failures


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"capturing into {OUT.relative_to(REPO_ROOT)}/")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            failures = capture(browser)
        finally:
            browser.close()
    if failures:
        print(f"\n{failures} page(s) failed")
        return 1
    print("\nall pages captured")
    return 0


if __name__ == "__main__":
    sys.exit(main())
