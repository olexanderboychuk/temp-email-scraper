"""tempail.com browser session cookies that bind an inbox to an address."""

from __future__ import annotations

from playwright.sync_api import Page

#: Dropping these forces tempail.com to assign a fresh address on the next load.
#: Keep ``cf_clearance`` and consent cookies so Cloudflare / GDPR stay satisfied.
MAIL_SESSION_COOKIES = frozenset({"oturum", "PHPSESSID"})


def clear_mail_session_cookies(page: Page) -> None:
    """Remove inbox-binding cookies while preserving anti-bot / consent state."""
    context = page.context
    preserved = [
        cookie
        for cookie in context.cookies()
        if cookie["name"] not in MAIL_SESSION_COOKIES
    ]
    context.clear_cookies()
    if preserved:
        context.add_cookies(preserved)
