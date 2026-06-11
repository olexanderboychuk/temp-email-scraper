"""Generic long-lived Playwright session bound to a dedicated worker thread.

Playwright's sync API is not thread-safe, while Flask serves requests from
many threads. ``BrowserSession`` therefore owns every Playwright object on a
single worker thread (a one-worker ``ThreadPoolExecutor``) and exposes
:meth:`run`, which marshals an arbitrary page operation onto that thread and
blocks until it completes or times out.

This module knows nothing about tempail.com - site-specific behaviour is
injected through the ``on_page_ready`` hook.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import TypeVar

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
)
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from tempail_api.config import ScraperConfig
from tempail_api.exceptions import (
    AntiBotChallengeError,
    ScraperError,
    ScraperTimeoutError,
)
from tempail_api.scraper.overlays import AD_GUARD_INIT_SCRIPT
from tempail_api.scraper.profile import profile_is_fresh, seed_context_from_storage
from tempail_api.scraper.stealth import apply_stealth

logger = logging.getLogger(__name__)

T = TypeVar("T")


class BrowserSession:
    """One Chromium instance, owned by one worker thread, shared by the app.

    :param config: browser runtime settings.
    :param on_page_ready: hook invoked (on the worker thread) for every new
        page - both the initial one and any page recreated during recovery.
        Use it to install dialog handlers and open the landing page.
    """

    def __init__(
        self,
        config: ScraperConfig,
        on_page_ready: Callable[[Page], None],
    ) -> None:
        self._config = config
        self._on_page_ready = on_page_ready
        self._executor: ThreadPoolExecutor | None = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="browser"
        )
        self._started = False
        self._lifecycle_lock = threading.Lock()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Boot the browser and prepare the initial page (idempotent)."""
        with self._lifecycle_lock:
            if self._started:
                return
            self._submit(self._launch)
            self._started = True

    def shutdown(self) -> None:
        """Close the browser and release the worker thread (idempotent)."""
        with self._lifecycle_lock:
            if self._executor is None:
                return
            try:
                self._submit(self._close_all)
            except ScraperError:
                logger.warning("Browser did not shut down cleanly", exc_info=True)
            self._executor.shutdown(wait=False)
            self._executor = None
            self._started = False

    # ------------------------------------------------------------------
    # Public execution API (thread-safe)
    # ------------------------------------------------------------------

    def run(self, operation: Callable[[Page], T]) -> T:
        """Execute ``operation(page)`` on the browser thread.

        Translates Playwright failures into domain exceptions and retries
        once with a fresh page if the current one crashed or was closed.
        """
        self.start()
        return self._submit(lambda: self._guarded(operation))

    # ------------------------------------------------------------------
    # Worker-thread plumbing
    # ------------------------------------------------------------------

    def _submit(self, func: Callable[[], T]) -> T:
        if self._executor is None:
            raise ScraperError("Browser session has been shut down")
        future = self._executor.submit(func)
        try:
            return future.result(timeout=self._config.op_timeout_s)
        except FutureTimeoutError as exc:
            raise ScraperTimeoutError(
                f"Browser operation exceeded {self._config.op_timeout_s}s"
            ) from exc

    def _guarded(self, operation: Callable[[Page], T]) -> T:
        """Run an operation in the worker, recovering from a dead page once."""
        try:
            return operation(self.page)
        except PlaywrightTimeoutError as exc:
            raise ScraperTimeoutError(str(exc)) from exc
        except (AntiBotChallengeError, ScraperError):
            raise
        except PlaywrightError as exc:
            logger.warning("Playwright error, attempting page recovery: %s", exc)
            self._recover_page()
            try:
                return operation(self.page)
            except PlaywrightTimeoutError as retry_exc:
                raise ScraperTimeoutError(str(retry_exc)) from retry_exc
            except PlaywrightError as retry_exc:
                raise ScraperError(str(retry_exc)) from retry_exc

    # ------------------------------------------------------------------
    # Worker-thread internals (must only run on the browser thread)
    # ------------------------------------------------------------------

    @property
    def page(self) -> Page:
        if self._page is None:
            raise ScraperError("Browser session is not started")
        return self._page

    def _launch(self) -> None:
        try:
            self._launch_impl()
        except PlaywrightTimeoutError as exc:
            self._close_all()
            raise ScraperTimeoutError(str(exc)) from exc
        except PlaywrightError as exc:
            # Don't leak a half-initialized Playwright on startup failure.
            self._close_all()
            raise ScraperError(str(exc)) from exc

    def _launch_impl(self) -> None:
        cfg = self._config
        self._playwright = sync_playwright().start()
        if cfg.use_persistent_context:
            self._launch_persistent(cfg)
        else:
            self._launch_ephemeral(cfg)
        self._on_page_ready(self._page)

    def _chromium_launch_kwargs(self, cfg: ScraperConfig) -> dict[str, object]:
        return {
            "headless": cfg.headless,
            "ignore_default_args": ["--enable-automation"],
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        }

    def _context_kwargs(self, cfg: ScraperConfig) -> dict[str, object]:
        return {
            "user_agent": cfg.user_agent,
            "viewport": {"width": cfg.viewport_width, "height": cfg.viewport_height},
            "locale": "uk-UA",
            "timezone_id": "Europe/Kyiv",
            "color_scheme": "light",
        }

    def _configure_context(self, context: BrowserContext, cfg: ScraperConfig) -> None:
        apply_stealth(context)
        context.add_init_script(AD_GUARD_INIT_SCRIPT)
        context.set_default_timeout(cfg.action_timeout_ms)
        context.set_default_navigation_timeout(cfg.nav_timeout_ms)

    def _open_initial_page(self, context: BrowserContext) -> Page:
        if context.pages:
            return context.pages[0]
        return context.new_page()

    def _launch_persistent(self, cfg: ScraperConfig) -> None:
        user_data_dir = Path(cfg.browser_user_data_dir)
        user_data_dir.mkdir(parents=True, exist_ok=True)
        fresh = profile_is_fresh(user_data_dir)
        logger.info(
            "Launching Chromium persistent profile (headless=%s, dir=%s, fresh=%s)",
            cfg.headless,
            user_data_dir,
            fresh,
        )
        self._browser = None
        self._context = self._playwright.chromium.launch_persistent_context(
            str(user_data_dir),
            **self._chromium_launch_kwargs(cfg),
            **self._context_kwargs(cfg),
        )
        self._configure_context(self._context, cfg)
        if fresh and cfg.storage_state_path:
            seed_context_from_storage(
                self._context,
                Path(cfg.storage_state_path),
                nav_timeout_ms=cfg.nav_timeout_ms,
            )
        self._page = self._open_initial_page(self._context)

    def _launch_ephemeral(self, cfg: ScraperConfig) -> None:
        logger.info("Launching Chromium ephemeral context (headless=%s)", cfg.headless)
        self._browser = self._playwright.chromium.launch(
            **self._chromium_launch_kwargs(cfg),
        )
        context_options = self._context_kwargs(cfg)
        if cfg.storage_state_path:
            state_file = Path(cfg.storage_state_path)
            try:
                state_readable = state_file.is_file()
            except PermissionError as exc:
                logger.error(
                    "Cannot read storage state %s (%s). "
                    "On Fedora/Podman add ':z' to the docker-compose volume.",
                    state_file,
                    exc,
                )
                state_readable = False
            if state_readable:
                try:
                    cookies = json.loads(state_file.read_text(encoding="utf-8")).get(
                        "cookies", []
                    )
                    names = {cookie.get("name") for cookie in cookies}
                    logger.info(
                        "Loading storage state from %s (%s cookies, cf_clearance=%s)",
                        state_file,
                        len(cookies),
                        "cf_clearance" in names,
                    )
                except (OSError, json.JSONDecodeError, TypeError) as exc:
                    logger.warning("Could not inspect storage state file: %s", exc)
                context_options["storage_state"] = str(state_file)
            else:
                logger.error(
                    "Storage state file is missing or unreadable: %s",
                    state_file,
                )
        self._context = self._browser.new_context(**context_options)
        self._configure_context(self._context, cfg)
        self._page = self._context.new_page()

    def _recover_page(self) -> None:
        """Replace a crashed/closed page with a fresh one on the same context."""
        if self._context is None:
            raise ScraperError("Browser context is not available")
        if self._page is not None and not self._page.is_closed():
            self._page.close()
        self._page = self._context.new_page()
        self._on_page_ready(self._page)

    def _close_all(self) -> None:
        logger.info("Shutting down browser session")
        if self._context is not None:
            try:
                self._context.close()
            except PlaywrightError as exc:
                logger.warning("Error while closing browser context: %s", exc)
        elif self._browser is not None:
            try:
                self._browser.close()
            except PlaywrightError as exc:
                logger.warning("Error while closing browser: %s", exc)
        if self._playwright is not None:
            self._playwright.stop()
        self._page = self._context = self._browser = self._playwright = None
