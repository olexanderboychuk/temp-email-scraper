"""Application configuration resolved from environment variables."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BASE_URL = "https://tempail.com/ua/"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

LOG_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"


def configure_logging() -> None:
    """Set up root logging once, honouring the LOG_LEVEL variable."""
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format=LOG_FORMAT,
    )


def _resolve_storage_state_path() -> str | None:
    """Resolve session file from env, /app/storage_state.json, or project root."""
    env = os.getenv("PLAYWRIGHT_STORAGE_STATE")
    if env:
        return env
    project_root = Path(__file__).resolve().parents[1]
    for candidate in (
        Path("/app/storage_state.json"),
        project_root / "storage_state.json",
        Path.cwd() / "storage_state.json",
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def _env_bool(name: str, default: bool) -> bool:
    """Read a boolean environment variable (true/1/yes/on)."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ScraperConfig:
    """Browser/scraper runtime settings."""

    base_url: str = DEFAULT_BASE_URL
    headless: bool = True
    user_agent: str = DEFAULT_USER_AGENT
    viewport_width: int = 1366
    viewport_height: int = 768
    nav_timeout_ms: int = 30_000
    action_timeout_ms: int = 15_000
    #: Hard ceiling for one API-facing browser operation, in seconds.
    op_timeout_s: float = 60.0
    #: How often the background poller refreshes the in-memory snapshot.
    inbox_poll_interval_s: float = 2.0
    #: Playwright storage_state JSON (cookies/localStorage) from a real session.
    storage_state_path: str | None = None
    #: Use ``launch_persistent_context`` instead of ephemeral ``new_context``.
    use_persistent_context: bool = True
    #: Chromium profile directory when persistent context is enabled.
    browser_user_data_dir: str = "/tmp/chromium-profile"
    #: Retries for page.goto on transient network errors (ERR_NETWORK_CHANGED…).
    nav_retries: int = 3
    nav_retry_delay_s: float = 2.0
    #: Full bootstrap retries when the browser fails to open tempail.com.
    bootstrap_retries: int = 3
    bootstrap_retry_delay_s: float = 3.0

    @classmethod
    def from_env(cls) -> ScraperConfig:
        """Build the config from environment variables."""
        return cls(
            base_url=os.getenv("TEMPAIL_BASE_URL", DEFAULT_BASE_URL),
            headless=_env_bool("HEADLESS", True),
            user_agent=os.getenv("USER_AGENT", DEFAULT_USER_AGENT),
            viewport_width=int(os.getenv("VIEWPORT_WIDTH", "1366")),
            viewport_height=int(os.getenv("VIEWPORT_HEIGHT", "768")),
            nav_timeout_ms=int(os.getenv("NAV_TIMEOUT_MS", "30000")),
            action_timeout_ms=int(os.getenv("ACTION_TIMEOUT_MS", "15000")),
            op_timeout_s=float(os.getenv("OP_TIMEOUT_S", "60")),
            inbox_poll_interval_s=float(os.getenv("INBOX_POLL_INTERVAL_S", "2")),
            storage_state_path=_resolve_storage_state_path(),
            use_persistent_context=_env_bool("USE_PERSISTENT_CONTEXT", True),
            browser_user_data_dir=os.getenv(
                "BROWSER_USER_DATA_DIR", "/tmp/chromium-profile"
            ),
            nav_retries=int(os.getenv("NAV_RETRIES", "3")),
            nav_retry_delay_s=float(os.getenv("NAV_RETRY_DELAY_S", "2")),
            bootstrap_retries=int(os.getenv("BOOTSTRAP_RETRIES", "3")),
            bootstrap_retry_delay_s=float(os.getenv("BOOTSTRAP_RETRY_DELAY_S", "3")),
        )
