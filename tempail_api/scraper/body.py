"""Extract and sanitise email body content from tempail.com mail views."""

from __future__ import annotations

import re

#: Strip tags to derive plain text from a HTML fragment.
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def html_to_text(fragment: str) -> str:
    """Best-effort plain text from a HTML fragment."""
    text = _TAG_RE.sub(" ", fragment)
    return _WS_RE.sub(" ", text).strip()


def clean_mail_html(raw_html: str) -> str:
    """Remove tempail/iframe boilerplate (translate widget, analytics, scripts)."""
    html = raw_html
    html = re.sub(
        r"<script[^>]*>.*?</script>",
        "",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    html = re.sub(
        r"<style[^>]*>.*?</style>",
        "",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    html = re.sub(r"<link[^>]*/?>", "", html, flags=re.IGNORECASE)
    html = re.sub(
        r'<div id="google_translate_element"[^>]*>\s*</div>',
        "",
        html,
        flags=re.IGNORECASE,
    )
    body_match = re.search(
        r"<body[^>]*>(.*)</body>", html, flags=re.DOTALL | re.IGNORECASE
    )
    if body_match:
        html = body_match.group(1)
    return html.strip()


#: Run inside an iframe to return only the message payload.
IFRAME_BODY_JS = """
() => {
  const root = document.body.cloneNode(true);
  root
    .querySelectorAll(
      'script, style, link, noscript, #google_translate_element, iframe'
    )
    .forEach((node) => node.remove());
  const main =
    root.querySelector('div[dir]') ||
    root.querySelector('.mail-icerik, .mail-body, article') ||
    root;
  const html = main.innerHTML.trim();
  const text = main.innerText.trim();
  const hasMarkup = /<[a-z][\\s\\S]*>/i.test(html);
  return {
    html: hasMarkup ? html : '',
    text,
  };
}
"""
