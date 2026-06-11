"""Lifecycle of the shared scraper instance.

The whole application owns exactly one browser session. Bootstrap runs on a
background thread so read-only endpoints can answer immediately from cache.
"""

from __future__ import annotations

import atexit
import logging
import threading

from tempail_api.scraper import TempailScraper

logger = logging.getLogger(__name__)

_scraper: TempailScraper | None = None
_scraper_lock = threading.Lock()


def _get_or_create_scraper() -> TempailScraper:
    global _scraper
    with _scraper_lock:
        if _scraper is None:
            logger.info("Creating shared browser session")
            _scraper = TempailScraper()
        return _scraper


def warmup_scraper() -> None:
    """Boot Chromium in the background when the Flask app starts."""
    logger.info("Warming up browser session")
    _get_or_create_scraper().ensure_started_async()


def get_scraper() -> TempailScraper:
    """Return the shared scraper instance, kicking off bootstrap if needed."""
    scraper = _get_or_create_scraper()
    scraper.ensure_started_async()
    return scraper


def shutdown_scraper() -> None:
    """Close the browser; registered to run at interpreter exit."""
    global _scraper
    with _scraper_lock:
        if _scraper is not None:
            _scraper.shutdown()
            _scraper = None


atexit.register(shutdown_scraper)
