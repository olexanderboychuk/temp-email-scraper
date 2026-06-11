"""Normalise and extract mail metadata from tempail.com pages."""

from __future__ import annotations

import re

from tempail_api.scraper import selectors

#: Read sender / subject / time from the opened mail view (not the inbox list).
MAIL_VIEW_META_JS = """
() => {
  const panel = document.querySelector(
    '.mail-oku-panel, .mail-oku, .mail-alani'
  );
  if (!panel) {
    return { sender: '', subject: '', time: '' };
  }
  const pick = (sel) => {
    const el = panel.querySelector(sel);
    return el ? el.innerText.trim() : '';
  };
  return {
    sender: pick('.mail-oku-gonderen'),
    subject: pick('.mail-oku-baslik'),
    time: pick('.mail-oku-zaman'),
  };
}
"""

_ANGLE_EMAIL_RE = re.compile(r"<([^<>]+@[^<>]+)>")


def first_line(value: str) -> str:
    """Keep only the first line — tempail sometimes merges fields in one block."""
    lines = value.strip().splitlines()
    return lines[0].strip() if lines else ""


def normalize_sender(value: str) -> str:
    """Return a clean sender address or name."""
    line = first_line(value)
    angle = _ANGLE_EMAIL_RE.search(line)
    if angle:
        return angle.group(1).strip()
    email = selectors.EMAIL_TEXT_RE.search(line)
    if email:
        return email.group(1)
    return line


def normalize_subject(value: str) -> str:
    return first_line(value)


def pick_meta(
    page_meta: dict[str, str],
    cached_meta: dict[str, str],
) -> dict[str, str]:
    """Prefer dedicated view selectors, fall back to inbox cache."""
    sender_raw = page_meta.get("sender") or cached_meta.get("sender", "")
    subject_raw = page_meta.get("subject") or cached_meta.get("subject", "")
    return {
        "sender": normalize_sender(sender_raw),
        "subject": normalize_subject(subject_raw),
        "time": cached_meta.get("time", ""),
    }
