"""tempail.com interaction logic, built on top of :class:`BrowserSession`.

Read-only endpoints (:meth:`get_email`, :meth:`get_inbox`) return data from an
in-memory snapshot that a background poller keeps fresh. They never block on
browser I/O, so API latency stays in the low milliseconds even while Chromium
is still booting or tempail.com is slow to respond.
"""

from __future__ import annotations

import logging
import threading

from playwright.sync_api import ElementHandle, Page
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from tempail_api.config import ScraperConfig
from tempail_api.exceptions import (
    AntiBotChallengeError,
    EmailNotFoundError,
    ScraperError,
    ScraperTimeoutError,
)
from tempail_api.scraper import selectors
from tempail_api.scraper.antibot import ensure_inbox_page, is_challenge_page
from tempail_api.scraper.body import IFRAME_BODY_JS, clean_mail_html, html_to_text
from tempail_api.scraper.meta import (
    MAIL_VIEW_META_JS,
    normalize_sender,
    normalize_subject,
    pick_meta,
)
from tempail_api.scraper.browser import BrowserSession
from tempail_api.scraper.navigation import goto_with_retry, is_transient_network_error
from tempail_api.scraper.overlays import dismiss_blocking_overlays
from tempail_api.scraper.session import clear_mail_session_cookies
from tempail_api.scraper.state import MailboxState

logger = logging.getLogger(__name__)


class TempailScraper:
    """High-level API over a shared tempail.com browser session."""

    def __init__(self, config: ScraperConfig | None = None) -> None:
        self.config = config or ScraperConfig.from_env()
        self._state = MailboxState()
        self._session = BrowserSession(self.config, self._prepare_page)
        self._poll_stop = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._bootstrap_failed = False
        self._bootstrap_error: ScraperError | None = None
        self._starting = False
        self._started = False
        self._lifecycle_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def ensure_started_async(self) -> None:
        """Kick off browser bootstrap on a background thread (non-blocking)."""
        with self._lifecycle_lock:
            if self._started or self._starting or self._bootstrap_failed:
                return
            self._starting = True
            threading.Thread(
                target=self._bootstrap,
                name="scraper-bootstrap",
                daemon=True,
            ).start()

    def shutdown(self) -> None:
        """Stop the poller and close the browser."""
        with self._lifecycle_lock:
            self._poll_stop.set()
            if self._poll_thread is not None:
                self._poll_thread.join(timeout=self.config.op_timeout_s)
                self._poll_thread = None
            self._session.shutdown()
            self._ready.clear()
            self._started = False
            self._starting = False
            self._bootstrap_failed = False
            self._bootstrap_error = None

    def _bootstrap(self) -> None:
        cfg = self.config
        last_exc: ScraperError | None = None

        for attempt in range(1, cfg.bootstrap_retries + 1):
            try:
                self._session.start()
                self._session.run(self._refresh_snapshot)
                self._start_poller()
                with self._lifecycle_lock:
                    self._started = True
                    self._starting = False
                    self._bootstrap_failed = False
                    self._bootstrap_error = None
                self._ready.set()
                logger.info("Browser bootstrap complete")
                return
            except ScraperError as exc:
                last_exc = exc
                logger.exception(
                    "Browser bootstrap failed (attempt %s/%s)",
                    attempt,
                    cfg.bootstrap_retries,
                )
                self._session.shutdown()
                retriable = (
                    attempt < cfg.bootstrap_retries
                    and not isinstance(exc, AntiBotChallengeError)
                    and is_transient_network_error(exc)
                )
                if not retriable:
                    break
                logger.warning(
                    "Retrying browser bootstrap in %.1fs", cfg.bootstrap_retry_delay_s
                )
                self._session = BrowserSession(self.config, self._prepare_page)
                self._poll_stop.wait(cfg.bootstrap_retry_delay_s)

        with self._lifecycle_lock:
            self._starting = False
            self._bootstrap_failed = True
            self._bootstrap_error = last_exc
        self._ready.set()

    def _ensure_ready_blocking(self) -> None:
        """Wait until bootstrap finishes (used by write operations only)."""
        self.ensure_started_async()
        if not self._ready.wait(timeout=self.config.op_timeout_s):
            raise ScraperTimeoutError(
                f"Browser bootstrap exceeded {self.config.op_timeout_s}s"
            )
        if self._bootstrap_failed or not self._started:
            if self._bootstrap_error is not None:
                raise self._bootstrap_error
            raise ScraperError("Browser failed to start")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_email(self) -> str:
        """Return the currently active temporary email address."""
        self.ensure_started_async()
        email = self._state.read().email
        if email:
            return email
        if self._bootstrap_failed and self._bootstrap_error is not None:
            raise self._bootstrap_error
        if self._bootstrap_failed:
            raise ScraperError("Browser failed to start")
        raise ScraperTimeoutError("Mailbox is still starting")

    def get_inbox(self) -> list[dict[str, str]]:
        """Return metadata for every message currently in the inbox."""
        self.ensure_started_async()
        return self._state.read().inbox

    def get_message(self, mail_id: str) -> dict[str, str]:
        """Return the full content of one message by its id."""
        if not selectors.SAFE_MAIL_ID_RE.match(mail_id):
            raise EmailNotFoundError(f"Invalid mail id: {mail_id!r}")
        mail_id = selectors.normalize_mail_id(mail_id)
        cached = self._state.get_cached_message(mail_id)
        if cached is not None:
            return cached
        self._ensure_ready_blocking()
        message = self._session.run(lambda page: self._read_message(page, mail_id))
        self._state.cache_message(message)
        self._session.run(self._refresh_snapshot)
        return message

    def refresh_email(self) -> str:
        """Discard the current address and return the newly generated one."""
        self._ensure_ready_blocking()
        new_email = self._session.run(self._rotate_address)
        self._state.update(email=new_email)
        self._state.clear_inbox()
        return new_email

    # ------------------------------------------------------------------
    # Background polling
    # ------------------------------------------------------------------

    def _start_poller(self) -> None:
        if self._poll_thread is not None and self._poll_thread.is_alive():
            return
        self._poll_stop.clear()
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            name="inbox-poller",
            daemon=True,
        )
        self._poll_thread.start()

    def _poll_loop(self) -> None:
        while not self._poll_stop.is_set():
            if self._poll_stop.wait(self.config.inbox_poll_interval_s):
                break
            try:
                self._session.run(self._refresh_snapshot)
            except ScraperError:
                logger.warning("Background inbox poll failed", exc_info=True)

    def _refresh_snapshot(self, page: Page) -> None:
        """Read the live page and push the result into the in-memory cache."""
        self._ensure_on_inbox(page)
        dismiss_blocking_overlays(page)
        self._state.update(email=self._read_email_value(page))
        self._state.merge_inbox(self._scrape_inbox(page))

    # ------------------------------------------------------------------
    # Page operations (run on the browser worker thread)
    # ------------------------------------------------------------------

    def _goto(self, page: Page, url: str) -> None:
        """Navigate with retries on transient network errors."""
        goto_with_retry(
            page,
            url,
            wait_until="domcontentloaded",
            timeout=self.config.nav_timeout_ms,
            retries=self.config.nav_retries,
            retry_delay_s=self.config.nav_retry_delay_s,
        )

    def _prepare_page(self, page: Page) -> None:
        """Initial setup for every (re)created page."""
        page.on("dialog", lambda dialog: dialog.accept())
        self._goto(page, self.config.base_url)
        ensure_inbox_page(page)
        dismiss_blocking_overlays(page)
        address = self._wait_for_email_value(page)
        self._persist_storage_state(page)
        logger.info("Inbox ready, current address: %s", address)

    def _is_mail_page(self, url: str) -> bool:
        return "/mail_" in url or "/mail/" in url

    def _ensure_on_inbox(self, page: Page) -> None:
        """Return to the inbox page if a previous call navigated away."""
        if self._is_mail_page(page.url):
            self._goto(page, self.config.base_url)
            dismiss_blocking_overlays(page)
            self._wait_for_email_value(page)
        else:
            dismiss_blocking_overlays(page)

    def _read_email_value(self, page: Page, different_from: str | None = None) -> str:
        """Read the address from the DOM, waiting only when it is not ready yet."""
        ensure_inbox_page(page)
        existing = self._read_email_from_dom(page)
        if existing and existing != different_from:
            return existing
        return self._wait_for_email_value(page, different_from=different_from)

    def _wait_for_email_value(
        self, page: Page, different_from: str | None = None
    ) -> str:
        """Block until the email input holds a (new) address."""
        ensure_inbox_page(page)
        try:
            page.wait_for_selector(selectors.EMAIL_INPUT, state="attached")
            page.wait_for_function(
                """([sel, old]) => {
                    const el = document.querySelector(sel);
                    if (!el) return false;
                    const value = (
                        el.value ||
                        el.getAttribute('data-clipboard-text') ||
                        el.textContent ||
                        ''
                    ).trim();
                    return value.includes('@') && value !== old;
                }""",
                arg=[selectors.EMAIL_INPUT, different_from],
            )
        except PlaywrightTimeoutError as exc:
            ensure_inbox_page(page)
            raise ScraperTimeoutError(
                "Timed out waiting for the tempail.com email field. "
                "The page markup may have changed or the session is blocked."
            ) from exc
        value = self._read_email_from_dom(page)
        if value is None or value == different_from:
            raise ScraperError("Email input disappeared after waiting")
        return value

    @staticmethod
    def _read_email_from_dom(page: Page) -> str | None:
        """Try every known selector (and plain text) without blocking waits."""
        for part in selectors.EMAIL_INPUT.split(","):
            element = page.query_selector(part.strip())
            if element is None:
                continue
            tag = element.evaluate("el => el.tagName.toLowerCase()")
            if tag == "input":
                value = element.input_value().strip()
            else:
                value = (
                    element.get_attribute("data-clipboard-text") or element.inner_text()
                ).strip()
            if "@" in value:
                return value
        match = selectors.EMAIL_TEXT_RE.search(page.inner_text("body"))
        if match:
            return match.group(1)
        return None

    def _persist_storage_state(self, page: Page) -> None:
        """Refresh the on-disk session file after a successful page load."""
        path = self.config.storage_state_path
        if not path:
            return
        if is_challenge_page(page):
            logger.warning(
                "Skipping storage_state save — page is still a CAPTCHA screen"
            )
            return
        try:
            page.context.storage_state(path=path)
            logger.info("Updated Playwright storage state at %s", path)
        except PlaywrightError as exc:
            logger.warning("Could not persist storage state to %s: %s", path, exc)

    def _cached_inbox_item(self, mail_id: str) -> dict[str, str]:
        """Return inbox metadata for ``mail_id`` from the poller cache."""
        for item in self._state.read().inbox:
            if item["id"] == mail_id:
                return item
        return {"sender": "", "subject": "", "time": ""}

    def _scrape_inbox(self, page: Page) -> list[dict[str, str]]:
        """Parse inbox rows from ``ul.mailler > li.mail`` without blocking waits."""
        root = page.query_selector(selectors.INBOX_ROOT)
        scope: Page | ElementHandle = root if root is not None else page
        messages: list[dict[str, str]] = []
        seen: set[str] = set()
        for row in scope.query_selector_all(selectors.MAIL_ROW):
            link = row.query_selector(selectors.MAIL_ROW_LINK)
            if link is None:
                continue
            href = link.get_attribute("href") or ""
            row_id = row.get_attribute("id")
            mail_id = selectors.extract_mail_id(href, row_id)
            if mail_id is None or mail_id in seen:
                continue
            seen.add(mail_id)
            messages.append(
                {
                    "id": mail_id,
                    "sender": normalize_sender(
                        self._text_of(row, selectors.MAIL_SENDER)
                    ),
                    "subject": normalize_subject(
                        self._text_of(row, selectors.MAIL_SUBJECT)
                    ),
                }
            )
        return messages

    def _read_message(self, page: Page, mail_id: str) -> dict[str, str]:
        mail_url = selectors.mail_page_url(self.config.base_url, mail_id)
        response = goto_with_retry(
            page,
            mail_url,
            wait_until="domcontentloaded",
            timeout=self.config.nav_timeout_ms,
            retries=self.config.nav_retries,
            retry_delay_s=self.config.nav_retry_delay_s,
        )
        if response is not None and response.status == 404:
            raise EmailNotFoundError(f"Mail {mail_id!r} was not found")
        dismiss_blocking_overlays(page)

        try:
            page.wait_for_selector(selectors.MAIL_BODY, state="attached")
        except PlaywrightTimeoutError as exc:
            if not self._is_mail_page(page.url):
                raise EmailNotFoundError(f"Mail {mail_id!r} was not found") from exc
            raise

        body_html, body_text = self._extract_body(page)
        page_meta = page.evaluate(MAIL_VIEW_META_JS)
        meta = pick_meta(page_meta, self._cached_inbox_item(mail_id))
        message = {
            "id": mail_id,
            "sender": meta["sender"],
            "subject": meta["subject"],
            "time": meta["time"],
            "body_text": body_text,
            "body_html": body_html,
        }
        self._goto(page, self.config.base_url)
        return message

    def _rotate_address(self, page: Page) -> str:
        """Delete the current inbox and load a genuinely new address.

        tempail.com stores the active address in the ``oturum`` session cookie.
        Clicking delete alone often restores the same address; clearing session
        cookies after delete forces a new assignment on reload.
        """
        self._ensure_on_inbox(page)
        dismiss_blocking_overlays(page)
        old_email = self._read_email_value(page)

        link = page.query_selector(selectors.DELETE_LINK)
        if link is None:
            raise ScraperError(
                "Delete control not found - selectors may be outdated"
            )

        link.click()
        page.wait_for_load_state("domcontentloaded")
        clear_mail_session_cookies(page)
        self._goto(page, self.config.base_url)
        dismiss_blocking_overlays(page)
        ensure_inbox_page(page)
        new_email = self._wait_for_email_value(page, different_from=old_email)
        self._persist_storage_state(page)
        logger.info("Address rotated: %s -> %s", old_email, new_email)
        return new_email

    # ------------------------------------------------------------------
    # Extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_body(page: Page) -> tuple[str, str]:
        """Return ``(body_html, body_text)`` without site/iframe boilerplate."""
        container = page.query_selector(selectors.MAIL_BODY)
        if container is None:
            return "", ""
        iframe_el = container.query_selector("iframe")
        frame = iframe_el.content_frame() if iframe_el is not None else None
        if frame is not None:
            frame.wait_for_load_state("domcontentloaded")
            payload = frame.evaluate(IFRAME_BODY_JS)
            return payload["html"], payload["text"]
        raw_html = container.inner_html()
        body_html = clean_mail_html(raw_html)
        body_text = html_to_text(body_html) or container.inner_text().strip()
        if body_html == body_text or "<" not in body_html:
            body_html = ""
        return body_html, body_text

    @staticmethod
    def _text_of(root: ElementHandle, selector: str) -> str:
        element = root.query_selector(selector)
        if element is None:
            return ""
        return element.inner_text().strip()

    @staticmethod
    def _page_text(page: Page, selector: str) -> str:
        element = page.query_selector(selector)
        if element is None:
            return ""
        return element.inner_text().strip()
