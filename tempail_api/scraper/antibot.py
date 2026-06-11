"""Detection of tempail.com bot-check / CAPTCHA interstitials."""

from __future__ import annotations

from playwright.sync_api import Page

from tempail_api.exceptions import AntiBotChallengeError

_CHALLENGE_MARKERS = (
    "verifying your request",
    "please verify that you are not a robot",
    "g-recaptcha",
    "bot-kontrol.php",
    "captcha-form",
)


def is_challenge_page(page: Page) -> bool:
    """Return True when the current document is a bot-check screen."""
    title = page.title().casefold()
    if "verifying your request" in title:
        return True
    if page.locator(".g-recaptcha, #captcha-form").count() > 0:
        return True
    html = page.content().casefold()
    return any(marker in html for marker in _CHALLENGE_MARKERS)


def ensure_inbox_page(page: Page) -> None:
    """Fail fast when tempail blocks automation with a CAPTCHA page."""
    if is_challenge_page(page):
        raise AntiBotChallengeError(
            "tempail.com returned a reCAPTCHA / bot-check page instead of "
            "the inbox. Headless automation cannot solve it automatically. "
            "Run `python scripts/capture_session.py` in a normal browser, "
            "solve the challenge once, then mount the generated "
            "storage_state.json via PLAYWRIGHT_STORAGE_STATE."
        )


