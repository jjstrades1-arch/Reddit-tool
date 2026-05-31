"""Best-effort, token-free reading of a public Patreon page.

Patreon shows a public patron count on every creator page, embedded in the
page's JSON. This tries to read it without an API token. Patreon aggressively
blocks automated requests though, so this can fail (HTTP 403) -- in that case
the UI falls back to quick manual entry. Read-only and low-volume.
"""

from __future__ import annotations

import re

import requests

from .logging import get_logger

log = get_logger(__name__)

_TIMEOUT = 20
# A browser-like UA reduces (does not guarantee) the chance of being blocked.
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_PATRON_RE = re.compile(r'"patron_count"\s*:\s*(\d+)')
_PLEDGE_RE = re.compile(r'"(?:pledge_sum|campaign_pledge_sum)"\s*:\s*(\d+)')


class PatreonPublicError(RuntimeError):
    """Raised when the public patron count can't be read."""


def normalize_url(url_or_vanity: str) -> str:
    """Turn 'name', 'patreon.com/name', or a full URL into a full https URL."""
    text = (url_or_vanity or "").strip()
    if not text:
        raise PatreonPublicError("Please enter your Patreon page address.")
    if text.startswith("http://") or text.startswith("https://"):
        return text
    if text.startswith("patreon.com") or text.startswith("www.patreon.com"):
        return "https://" + text
    return "https://www.patreon.com/" + text.lstrip("/")


def parse_counts(html: str) -> dict:
    """Extract patron_count (and pledge_sum if present) from page HTML."""
    patron = _PATRON_RE.search(html)
    if not patron:
        raise PatreonPublicError(
            "Couldn't find the patron count on that page. Use manual entry instead."
        )
    pledge = _PLEDGE_RE.search(html)
    return {
        "patron_count": int(patron.group(1)),
        "pledge_sum_cents": int(pledge.group(1)) if pledge else None,
    }


def fetch_public_campaign(url_or_vanity: str) -> dict:
    """Fetch a creator page and return its public patron count (best effort)."""
    url = normalize_url(url_or_vanity)
    resp = requests.get(
        url, headers={"User-Agent": _UA, "Accept": "text/html"}, timeout=_TIMEOUT
    )
    if resp.status_code == 403:
        raise PatreonPublicError(
            "Patreon blocked the automated request (this is common). "
            "Use the manual entry box below instead."
        )
    if resp.status_code >= 400:
        raise PatreonPublicError(f"Patreon returned status {resp.status_code}.")
    return parse_counts(resp.text)
