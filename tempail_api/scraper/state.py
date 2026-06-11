"""In-memory mailbox snapshot shared between the poller and API handlers."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class MailboxSnapshot:
    """Point-in-time view of the active address and inbox metadata."""

    email: str = ""
    inbox: list[dict[str, str]] = field(default_factory=list)


class MailboxState:
    """Thread-safe cache updated by the background browser poller."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot = MailboxSnapshot()
        self._first_seen: dict[str, datetime] = {}
        self._messages: dict[str, dict[str, str]] = {}

    def read(self) -> MailboxSnapshot:
        with self._lock:
            return MailboxSnapshot(
                email=self._snapshot.email,
                inbox=list(self._snapshot.inbox),
            )

    def update(
        self,
        *,
        email: str | None = None,
        inbox: list[dict[str, str]] | None = None,
    ) -> None:
        with self._lock:
            if email is not None:
                self._snapshot.email = email
            if inbox is not None:
                self._snapshot.inbox = list(inbox)

    def merge_inbox(self, rows: list[dict[str, str]]) -> None:
        """Merge scraped inbox rows, stamping ``time`` at first discovery."""
        now = datetime.now(UTC)
        with self._lock:
            current_ids: set[str] = set()
            merged: list[dict[str, str]] = []
            for row in rows:
                mail_id = row["id"]
                current_ids.add(mail_id)
                if mail_id not in self._first_seen:
                    self._first_seen[mail_id] = now
                merged.append(
                    {
                        "id": mail_id,
                        "sender": row["sender"],
                        "subject": row["subject"],
                        "time": self._first_seen[mail_id].isoformat(),
                    }
                )
            for mail_id in list(self._first_seen):
                if mail_id not in current_ids:
                    del self._first_seen[mail_id]
            for mail_id in list(self._messages):
                if mail_id not in current_ids:
                    del self._messages[mail_id]
            self._snapshot.inbox = merged

    def get_cached_message(self, mail_id: str) -> dict[str, str] | None:
        with self._lock:
            cached = self._messages.get(mail_id)
            return dict(cached) if cached is not None else None

    def cache_message(self, message: dict[str, str]) -> None:
        with self._lock:
            self._messages[message["id"]] = dict(message)

    def clear_inbox(self) -> None:
        with self._lock:
            self._snapshot.inbox = []
            self._first_seen.clear()
            self._messages.clear()
