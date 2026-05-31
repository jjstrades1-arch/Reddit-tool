"""Thin Patreon API v2 client.

The long-unmaintained ``patreon`` PyPI package targets the v1 API, so we use a
small ``requests``-based wrapper around the v2 endpoints we need: the creator's
campaign, its tiers, and its members (pledges). OAuth token refresh is handled
when a client id/secret and refresh token are configured.
"""

from __future__ import annotations

from typing import Any

import requests

from .config import Settings, get_settings
from .logging import get_logger

log = get_logger(__name__)

API_BASE = "https://www.patreon.com/api/oauth2/v2"
TOKEN_URL = "https://www.patreon.com/api/oauth2/token"


class PatreonError(RuntimeError):
    pass


class PatreonClient:
    """Minimal Patreon v2 client scoped to a single creator's campaign."""

    def __init__(self, settings: Settings | None = None, session: requests.Session | None = None):
        self.settings = settings or get_settings()
        self.settings.require_patreon()
        self._access_token = self.settings.patreon_access_token
        self._http = session or requests.Session()

    # -- low level ---------------------------------------------------------- #
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token}"}

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{API_BASE}{path}"
        resp = self._http.get(url, headers=self._headers(), params=params, timeout=30)
        if resp.status_code == 401 and self.settings.patreon_refresh_token:
            self._refresh()
            resp = self._http.get(url, headers=self._headers(), params=params, timeout=30)
        if resp.status_code >= 400:
            raise PatreonError(f"Patreon GET {path} failed: {resp.status_code} {resp.text}")
        return resp.json()

    def _refresh(self) -> None:
        if not (self.settings.patreon_client_id and self.settings.patreon_client_secret):
            raise PatreonError("Cannot refresh Patreon token without client id/secret.")
        resp = self._http.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.settings.patreon_refresh_token,
                "client_id": self.settings.patreon_client_id,
                "client_secret": self.settings.patreon_client_secret,
            },
            timeout=30,
        )
        if resp.status_code >= 400:
            raise PatreonError(f"Token refresh failed: {resp.status_code} {resp.text}")
        self._access_token = resp.json()["access_token"]

    # -- high level --------------------------------------------------------- #
    def get_campaign_id(self) -> str:
        data = self._get("/campaigns")
        campaigns = data.get("data", [])
        if not campaigns:
            raise PatreonError("No campaigns found for this Patreon account.")
        return campaigns[0]["id"]

    def iter_members(self, campaign_id: str | None = None) -> list[dict[str, Any]]:
        """Return raw member records (with pledge + tier relationships)."""
        campaign_id = campaign_id or self.get_campaign_id()
        members: list[dict[str, Any]] = []
        params = {
            "include": "currently_entitled_tiers,user",
            "fields[member]": (
                "full_name,patron_status,currently_entitled_amount_cents,"
                "pledge_relationship_start,last_charge_date"
            ),
            "page[count]": 200,
        }
        path = f"/campaigns/{campaign_id}/members"
        while True:
            data = self._get(path, params=params)
            members.extend(data.get("data", []))
            nxt = data.get("links", {}).get("next")
            if not nxt:
                break
            # Patreon returns absolute next-cursor links; pass cursor through.
            cursor = data.get("meta", {}).get("pagination", {}).get("cursors", {}).get("next")
            if not cursor:
                break
            params = {**params, "page[cursor]": cursor}
        return members
