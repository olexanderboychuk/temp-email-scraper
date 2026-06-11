"""Resilient page navigation helpers."""

from __future__ import annotations

import logging
import time

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, Response

logger = logging.getLogger(__name__)

_TRANSIENT_NET_MARKERS = (
    "ERR_NETWORK_CHANGED",
    "ERR_CONNECTION_RESET",
    "ERR_INTERNET_DISCONNECTED",
    "ERR_CONNECTION_CLOSED",
    "ERR_SOCKET_NOT_CONNECTED",
    "ERR_NETWORK_IO_SUSPENDED",
    "ERR_ADDRESS_UNREACHABLE",
)


def is_transient_network_error(exc: BaseException) -> bool:
    """Return True for Chromium network errors that are safe to retry."""
    message = str(exc)
    return any(marker in message for marker in _TRANSIENT_NET_MARKERS)


def goto_with_retry(
    page: Page,
    url: str,
    *,
    wait_until: str = "domcontentloaded",
    timeout: int | None = None,
    retries: int = 3,
    retry_delay_s: float = 2.0,
) -> Response | None:
    """Navigate to ``url``, retrying transient network failures."""
    last_exc: PlaywrightError | None = None
    for attempt in range(1, retries + 1):
        try:
            kwargs: dict[str, object] = {"url": url, "wait_until": wait_until}
            if timeout is not None:
                kwargs["timeout"] = timeout
            return page.goto(**kwargs)
        except PlaywrightError as exc:
            last_exc = exc
            if attempt >= retries or not is_transient_network_error(exc):
                raise
            logger.warning(
                "Transient network error navigating to %s (attempt %s/%s): %s",
                url,
                attempt,
                retries,
                exc,
            )
            time.sleep(retry_delay_s)
    if last_exc is not None:
        raise last_exc
    return None
