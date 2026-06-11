"""playwright-stealth integration shared by the API and capture script."""

from __future__ import annotations

from playwright.sync_api import BrowserContext
from playwright_stealth import Stealth

#: Match production browser locale (see BrowserSession context options).
_STEALTH = Stealth(navigator_languages_override=("uk-UA", "uk", "en"))


def apply_stealth(context: BrowserContext) -> None:
    """Inject playwright-stealth evasions into every page in ``context``."""
    _STEALTH.apply_stealth_sync(context)
