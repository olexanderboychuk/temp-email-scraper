"""Chromium user-data directory helpers for ``launch_persistent_context``."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from playwright.sync_api import BrowserContext, Page

logger = logging.getLogger(__name__)


def profile_is_fresh(user_data_dir: Path) -> bool:
    """Return whether ``user_data_dir`` has never been used by Chromium."""
    if not user_data_dir.exists():
        return True
    return not any(user_data_dir.iterdir())


def seed_context_from_storage(
    context: BrowserContext,
    state_path: Path,
    *,
    nav_timeout_ms: int,
) -> None:
    """Import cookies / localStorage from a ``storage_state.json`` export."""
    if not state_path.is_file():
        logger.warning("Storage state file is missing: %s", state_path)
        return
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        logger.warning("Could not read storage state %s: %s", state_path, exc)
        return

    cookies = payload.get("cookies", [])
    names = {cookie.get("name") for cookie in cookies}
    logger.info(
        "Seeding fresh profile from %s (%s cookies, cf_clearance=%s)",
        state_path,
        len(cookies),
        "cf_clearance" in names,
    )
    if cookies:
        context.add_cookies(cookies)

    origins = payload.get("origins", [])
    if not origins:
        return

    page = context.new_page()
    try:
        _seed_local_storage(page, origins, nav_timeout_ms=nav_timeout_ms)
    finally:
        page.close()


def _seed_local_storage(
    page: Page,
    origins: list[dict[str, object]],
    *,
    nav_timeout_ms: int,
) -> None:
    for origin_payload in origins:
        origin = origin_payload.get("origin")
        items = origin_payload.get("localStorage")
        if not isinstance(origin, str) or not isinstance(items, list) or not items:
            continue
        page.goto(origin, wait_until="domcontentloaded", timeout=nav_timeout_ms)
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            value = item.get("value")
            if not isinstance(name, str) or not isinstance(value, str):
                continue
            page.evaluate(
                "([key, val]) => localStorage.setItem(key, val)",
                [name, value],
            )
