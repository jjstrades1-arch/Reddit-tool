"""Tests for analytics: collectors, funnel roll-ups, dashboard, redirect."""

from __future__ import annotations

from fastapi.testclient import TestClient

from redditsuite.analytics import collectors, funnel, sentiment
from redditsuite.core import repositories as repo
from redditsuite.core.models import PostStatus, utcnow


class FakePatreonClient:
    def __init__(self, members):
        self._members = members

    def iter_members(self, campaign_id=None):
        return self._members


def _member_record(mid, status, cents, started):
    return {
        "id": mid,
        "attributes": {
            "full_name": f"Name {mid}",
            "patron_status": status,
            "currently_entitled_amount_cents": cents,
            "pledge_relationship_start": started,
            "last_charge_date": None,
        },
    }


def test_sentiment_scores_direction():
    assert sentiment.score_text("I love this, it's wonderful!") > 0.3
    assert sentiment.score_text("This is terrible and I hate it.") < -0.3
    assert sentiment.score_text("") == 0.0


def test_collect_post_metrics(settings, session, fake_reddit):
    p = repo.add_post(session, title="t")
    p.status = PostStatus.POSTED
    p.reddit_id = "xyz"
    session.flush()
    n = collectors.collect_post_metrics(session, reddit=fake_reddit)
    assert n == 1
    assert p.metrics[0].score == 10


def test_sync_patreon_snapshot(settings, session):
    client = FakePatreonClient(
        [
            _member_record("m1", "active_patron", 500, "2026-05-01T00:00:00Z"),
            _member_record("m2", "active_patron", 1000, "2026-05-10T00:00:00Z"),
            _member_record("m3", "former_patron", 0, "2026-01-01T00:00:00Z"),
        ]
    )
    metric = collectors.sync_patreon(session, client=client)
    assert metric.patron_count == 2
    assert metric.mrr_cents == 1500
    assert metric.churn_count == 1


def test_funnel_summary(settings, session):
    # One posted submission with a click and a conversion.
    p = repo.add_post(session, title="t")
    p.status = PostStatus.POSTED
    p.reddit_id = "r1"
    session.flush()
    repo.record_post_metric(session, p, score=42, num_comments=3)
    link = repo.create_utm_link(session, destination_url="https://patreon.com/x", campaign="c12")
    click = repo.record_click(session, link)
    member, _ = repo.upsert_member(
        session, patreon_member_id="m1", pledge_cents=500, started_at=utcnow()
    )
    repo.record_conversion(
        session, member=member, link_click=click, confidence=0.9, method="last_click"
    )
    session.flush()

    s = funnel.summary(session)
    assert s.posts == 1
    assert s.total_upvotes == 42
    assert s.clicks == 1
    assert s.conversions == 1
    assert s.click_to_conversion == 1.0
    assert ("c12", 1) in funnel.clicks_by_campaign(session)


def test_dashboard_and_redirect(settings, session):
    link = repo.create_utm_link(
        session, destination_url="https://patreon.com/join", campaign="c1"
    )
    slug = link.slug
    session.commit()

    from redditsuite.analytics.dashboard.app import create_app

    client = TestClient(create_app(), follow_redirects=False)

    # Dashboard renders.
    home = client.get("/")
    assert home.status_code == 200
    assert "Funnel" in home.text

    # Redirect logs a click and 302s to the Patreon destination with UTM params.
    resp = client.get(f"/r/{slug}")
    assert resp.status_code == 302
    assert "utm_source=reddit" in resp.headers["location"]

    api = client.get("/api/funnel")
    assert api.json()["clicks"] == 1


def test_redirect_unknown_slug(settings, session):
    session.commit()
    from redditsuite.analytics.dashboard.app import create_app

    client = TestClient(create_app(), follow_redirects=False)
    resp = client.get("/r/nope")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/"
