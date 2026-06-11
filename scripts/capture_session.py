#!/usr/bin/env python3
"""Capture a Playwright storage_state file after solving tempail.com CAPTCHA.

The saved session must use the **same browser profile** as the API (UA,
viewport, playwright-stealth). Otherwise Cloudflare ``cf_clearance`` is
invalidated on the next headless Docker start.

Usage:

    source .venv/bin/activate
    playwright install chromium
    python scripts/capture_session.py

For Docker, re-capture after any change to USER_AGENT / HEADLESS in
docker-compose, then ``docker compose up --build -d``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tempail_api.config import ScraperConfig  # noqa: E402
from tempail_api.scraper import selectors  # noqa: E402
from tempail_api.scraper.antibot import is_challenge_page  # noqa: E402
from tempail_api.scraper.overlays import AD_GUARD_INIT_SCRIPT  # noqa: E402
from tempail_api.scraper.stealth import apply_stealth  # noqa: E402


def _build_context(playwright, cfg: ScraperConfig):
    """Mirror the production BrowserSession context as closely as possible."""
    browser = playwright.chromium.launch(
        headless=cfg.headless,
        ignore_default_args=["--enable-automation"],
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )
    context = browser.new_context(
        user_agent=cfg.user_agent,
        viewport={"width": cfg.viewport_width, "height": cfg.viewport_height},
        locale="uk-UA",
        timezone_id="Europe/Kyiv",
        color_scheme="light",
    )
    apply_stealth(context)
    context.add_init_script(AD_GUARD_INIT_SCRIPT)
    return browser, context


def main() -> None:
    cfg = ScraperConfig.from_env()
    output = Path(cfg.storage_state_path or ROOT / "storage_state.json")

    mode = "headless" if cfg.headless else "visible"
    print(f"Opening {cfg.base_url} ({mode} Chromium, UA matches production).")
    if cfg.headless:
        print(
            "WARNING: HEADLESS=true — you cannot solve CAPTCHA manually.\n"
            "         Run with HEADLESS=false; keep USER_AGENT identical to Docker.",
            file=sys.stderr,
        )

    with sync_playwright() as playwright:
        browser, context = _build_context(playwright, cfg)
        page = context.new_page()
        page.goto(cfg.base_url, wait_until="domcontentloaded")

        if not cfg.headless:
            input("Press Enter after the temp email address is visible… ")

        if is_challenge_page(page):
            print("ERROR: CAPTCHA page is still active.", file=sys.stderr)
            sys.exit(1)
        if page.locator(selectors.EMAIL_INPUT).count() == 0:
            print(
                "ERROR: email field not found — session will not work.",
                file=sys.stderr,
            )
            sys.exit(1)

        email = page.locator(selectors.EMAIL_INPUT).first.input_value()
        print(f"Captured inbox for: {email}")

        context.storage_state(path=str(output))
        browser.close()

    payload = json.loads(output.read_text(encoding="utf-8"))
    cookie_names = [c["name"] for c in payload.get("cookies", [])]
    print(f"Saved {len(cookie_names)} cookies to {output}")
    for required in ("cf_clearance", "PHPSESSID", "oturum"):
        status = "OK" if required in cookie_names else "MISSING"
        print(f"  {required}: {status}")


if __name__ == "__main__":
    main()
