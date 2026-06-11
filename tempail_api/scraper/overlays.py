"""Dismiss cookie banners and full-screen ad overlays on tempail.com."""

from __future__ import annotations

import logging

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from tempail_api.scraper import selectors

logger = logging.getLogger(__name__)

#: Injected before page scripts run — strips the ad container as soon as it
#: is inserted into the DOM (covers the “sit on the page for a while” case).
AD_GUARD_INIT_SCRIPT = """
(() => {
  const removeAds = () => {
    document.querySelector('#ad_position_box')?.remove();
    document.querySelector('#ad_iframe')?.remove();
  };
  removeAds();
  new MutationObserver(removeAds).observe(document.documentElement, {
    childList: true,
    subtree: true,
  });
})();
"""

_DISMISS_LABELS = (
    "Закрити",
    "Close",
    "Schließen",
    "Fermer",
    "Cerrar",
)


def dismiss_cookie_banner(page: Page) -> None:
    """Click the GDPR cookie consent if it blocks interaction."""
    banner = page.locator(selectors.COOKIE_BANNER).first
    if banner.count() == 0 or not banner.is_visible():
        return
    for label in ("OK", "D'accord", "Добре", "Accept"):
        try:
            banner.get_by_text(label, exact=True).first.click(timeout=2_000)
            return
        except PlaywrightTimeoutError:
            continue
    for label in ("OK", "D'accord", "Добре", "Accept"):
        button = page.get_by_role("button", name=label, exact=True)
        if button.count() > 0:
            try:
                button.first.click(timeout=2_000)
                return
            except PlaywrightTimeoutError:
                continue


def dismiss_ad_overlay(page: Page) -> bool:
    """Close or remove a full-screen ad overlay if it is blocking the page."""
    if page.locator(selectors.AD_OVERLAY).count() == 0:
        return False

    for part in selectors.AD_DISMISS.split(","):
        button = page.locator(part.strip()).first
        if button.count() == 0 or not button.is_visible():
            continue
        try:
            button.click(timeout=3_000)
            page.locator(selectors.AD_OVERLAY).first.wait_for(
                state="hidden", timeout=5_000
            )
            logger.info("Closed ad overlay via %s", part.strip())
            return True
        except PlaywrightTimeoutError:
            continue

    for label in _DISMISS_LABELS:
        try:
            page.get_by_text(label, exact=True).first.click(timeout=2_000)
            page.locator(selectors.AD_OVERLAY).first.wait_for(
                state="hidden", timeout=5_000
            )
            logger.info("Closed ad overlay via label %r", label)
            return True
        except PlaywrightTimeoutError:
            continue

    removed = page.evaluate(
        """() => {
            const box = document.querySelector('#ad_position_box');
            if (!box) return false;
            box.remove();
            return true;
        }"""
    )
    if removed:
        logger.info("Removed ad overlay from DOM")
        return True
    return False


def dismiss_blocking_overlays(page: Page) -> None:
    """Best-effort cleanup of anything covering the inbox UI."""
    dismiss_cookie_banner(page)
    dismiss_ad_overlay(page)
