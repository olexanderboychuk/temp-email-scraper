"""All tempail.com CSS selectors in one place.

Each constant is a CSS *fallback chain* (comma-separated): Playwright
matches the first selector that exists, so minor site redesigns only
require editing this module.

Current inbox markup (2025+):
  #epostalar > ul.mailler > li.mail#mail_<id> > a[href*="/mail_<id>/"]
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

#: Element that exposes the active temporary address.
EMAIL_INPUT = (
    "#eposta_adres, input.eposta-adres, input[onclick*='select'], "
    "input[readonly][value*='@'], [data-clipboard-text*='@']"
)

#: Wrapper around the inbox list.
INBOX_ROOT = "#epostalar, .mail-alani .epostalar, .mail-alani"

#: <ul> with one <li class="mail"> per received message.
INBOX_LIST = "ul.mailler, ul#eposta_listesi, ul.mail-listesi, ul#mail-listesi"

#: One inbox row (excludes the header row li.baslik).
MAIL_ROW = "ul.mailler li.mail, #epostalar li.mail, li.mail.active"

#: Link inside a row — opens /ua/mail_<id>/.
MAIL_ROW_LINK = "a[href*='mail_']"

#: Metadata inside an inbox row.
MAIL_SENDER = ".gonderen, .mail-gonderen, .sender"
MAIL_SUBJECT = ".baslik, .mail-baslik, .subject"
MAIL_TIME = ".zaman, .mail-zaman, .time"

#: Metadata on the opened mail view (not the inbox list).
MAIL_VIEW_SENDER = ".mail-oku-gonderen, .mail-gonderen"
MAIL_VIEW_SUBJECT = ".mail-oku-baslik"
MAIL_VIEW_TIME = ".mail-oku-zaman, .mail-zaman"

#: Container of an opened message body.
MAIL_BODY = (
    ".mail-oku-panel, #mail-oku, .mail-icerik, .mail-body, "
    "#epostalar .mail-oku, article"
)

#: "Delete address" control — tempail 2025+ uses ``.yoket-link`` (no href).
DELETE_LINK = (
    "a.yoket-link, a[href*='/sil'], a#sil, a.sil, a[href*='/delete'], "
    "a[title*='Delete'], a[title*='Effacer'], a[title*='Видалити']"
)

#: href like https://tempail.com/ua/mail_3912965142/
MAIL_ID_RE = re.compile(r"/(mail_\d+)/?")

#: API clients may pass mail_3912965142 or just 3912965142.
SAFE_MAIL_ID_RE = re.compile(r"^(?:mail_)?\d+$")

#: Fallback when the address is rendered as plain text rather than an input.
EMAIL_TEXT_RE = re.compile(
    r"\b([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b"
)

#: Full-screen Google ad overlay (appears after some time on the page).
AD_OVERLAY = "#ad_position_box, #ad_iframe, #creative"

#: Dismiss / close controls on the ad card.
AD_DISMISS = (
    "#dismiss-button, #dismiss-button-element, "
    ".close-button-outer, .close-button, "
    "[aria-label*='Закрити'], [aria-label*='Close']"
)

#: GDPR cookie bar (class ``goster`` = visible).
COOKIE_BANNER = ".we-use-cookies.goster, .we-use-cookies"


def normalize_mail_id(mail_id: str) -> str:
    """Return the canonical slug used in tempail URLs (``mail_<digits>``)."""
    if mail_id.startswith("mail_"):
        return mail_id
    return f"mail_{mail_id}"


def mail_page_url(base_url: str, mail_id: str) -> str:
    """Build https://tempail.com/ua/mail_<id>/ from an API id."""
    return urljoin(base_url, f"{normalize_mail_id(mail_id)}/")


def extract_mail_id(href: str, row_id: str | None = None) -> str | None:
    """Parse the mail slug from a row link or ``li#mail_<id>`` attribute."""
    if row_id and row_id.startswith("mail_"):
        return row_id
    match = MAIL_ID_RE.search(href)
    if match:
        return match.group(1)
    return None
