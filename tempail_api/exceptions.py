"""Domain exceptions shared between the scraper and the API layer."""

from __future__ import annotations


class ScraperError(RuntimeError):
    """Base error for any browser/scraping failure."""


class ScraperTimeoutError(ScraperError):
    """The page did not reach the expected state in time
    (slow network, anti-bot interstitial, changed markup)."""


class AntiBotChallengeError(ScraperError):
    """tempail.com served a CAPTCHA / bot-check page instead of the inbox."""


class EmailNotFoundError(ScraperError):
    """The requested mail id does not exist in the current inbox."""
