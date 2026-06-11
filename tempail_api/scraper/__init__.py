"""Browser automation subpackage for tempail.com."""

from tempail_api.scraper.browser import BrowserSession
from tempail_api.scraper.tempail import TempailScraper

__all__ = ["BrowserSession", "TempailScraper"]
