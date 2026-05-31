"""Tests for token-free Patreon: public read, manual snapshot, and routes."""

from __future__ import annotations

import pytest
import responses

from redditsuite.analytics import patreon_snapshot
from redditsuite.core import patreon_public


def test_normalize_url_forms():
    assert patreon_public.normalize_url("mycreator") == "https://www.patreon.com/mycreator"
    assert patreon_public.normalize_url("patreon.com/x") == "https://patreon.com/x"
    assert patreon_public.normalize_url("https://www.patreon.com/x") == "https://www.patreon.com/x"
    with pytest.raises(patreon_public.PatreonPublicError):
        patreon_public.normalize_url("")


def test_parse_counts():
    html = '...stuff "patron_count": 137, more "pledge_sum": 45600 ...'
    data = patreon_public.parse_counts(html)
    assert data["patron_count"] == 137
    assert data["pledge_sum_cents"] == 45600


def test_parse_counts_missing():
    with pytest.raises(patreon_public.PatreonPublicError):
        patreon_public.parse_counts("no numbers here")


@responses.activate
def test_fetch_public_campaign(settings):
    responses.add(
        responses.GET,
        "https://www.patreon.com/mycreator",
        body='x "patron_count": 88, "pledge_sum": 22000 y',
        status=200,
    )
    data = patreon_public.fetch_public_campaign("mycreator")
    assert data["patron_count"] == 88
    assert data["pledge_sum_cents"] == 22000


@responses.activate
def test_fetch_public_blocked(settings):
    responses.add(responses.GET, "https://www.patreon.com/blocked", status=403)
    with pytest.raises(patreon_public.PatreonPublicError):
        patreon_public.fetch_public_campaign("blocked")


def test_record_manual_snapshot(settings, session):
    m = patreon_snapshot.record_manual_snapshot(
        session, patron_count=120, mrr_cents=48000
    )
    assert m.patron_count == 120
    assert m.mrr_cents == 48000


def test_snapshot_from_public_injected(settings, session):
    def fake_fetch(_url):
        return {"patron_count": 75, "pledge_sum_cents": 30000}

    m = patreon_snapshot.snapshot_from_public(session, "anything", fetch=fake_fetch)
    assert m.patron_count == 75
    assert m.mrr_cents == 30000
