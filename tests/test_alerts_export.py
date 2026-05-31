"""Tests for churn/anomaly alerts and CSV/JSON exports."""

from __future__ import annotations

import csv
import json
from datetime import timedelta

from redditsuite.analytics import alerts, export, funnel
from redditsuite.core import repositories as repo
from redditsuite.core.models import PatreonMetric, PostStatus, utcnow


def _snapshot(session, *, when, mrr, churn, patrons=10):
    m = PatreonMetric(
        captured_at=when, patron_count=patrons, mrr_cents=mrr, churn_count=churn
    )
    session.add(m)
    session.flush()
    return m


def test_alert_on_mrr_drop_and_churn_spike(settings, session):
    now = utcnow()
    _snapshot(session, when=now - timedelta(days=1), mrr=10000, churn=0)
    _snapshot(session, when=now, mrr=5000, churn=5)
    found = alerts.detect_anomalies(session)
    severities = {a.severity for a in found}
    messages = " ".join(a.message for a in found)
    assert "critical" in severities  # MRR halved
    assert "warning" in severities   # churn spike
    assert "MRR dropped" in messages
    assert "Churn spike" in messages


def test_no_alerts_when_healthy(settings, session):
    now = utcnow()
    _snapshot(session, when=now - timedelta(days=1), mrr=10000, churn=0)
    _snapshot(session, when=now, mrr=10500, churn=0)  # MRR up, no churn
    assert alerts.detect_anomalies(session) == []


def test_dead_campaign_alert(settings, session):
    link = repo.create_utm_link(
        session, destination_url="https://patreon.com/x", campaign="dead"
    )
    for _ in range(5):  # >= DEAD_CAMPAIGN_MIN_CLICKS, zero conversions
        repo.record_click(session, link)
    session.flush()
    found = alerts.detect_anomalies(session)
    assert any("dead" in a.message for a in found)


def test_converting_campaign_not_flagged(settings, session):
    link = repo.create_utm_link(
        session, destination_url="https://patreon.com/x", campaign="good"
    )
    clicks = [repo.record_click(session, link) for _ in range(5)]
    member, _ = repo.upsert_member(session, patreon_member_id="m1", started_at=utcnow())
    repo.record_conversion(
        session, member=member, link_click=clicks[0], confidence=0.9, method="last_click"
    )
    session.flush()
    assert not any("good" in a.message for a in alerts.detect_anomalies(session))


def test_export_csv(settings, session, tmp_path):
    p = repo.add_post(session, title="t")
    p.status = PostStatus.POSTED
    p.reddit_id = "r1"
    session.flush()
    repo.record_post_metric(session, p, score=42, num_comments=3)
    _snapshot(session, when=utcnow(), mrr=2000, churn=1)
    session.flush()

    paths = export.export_all(session, tmp_path, fmt="csv")
    names = {p.name for p in paths}
    assert names == {
        "funnel_summary.csv",
        "post_metrics.csv",
        "patreon_metrics.csv",
        "conversions.csv",
    }
    rows = list(csv.DictReader((tmp_path / "post_metrics.csv").open()))
    assert rows[0]["score"] == "42"
    assert rows[0]["title"] == "t"


def test_export_json(settings, session, tmp_path):
    _snapshot(session, when=utcnow(), mrr=2000, churn=1)
    session.flush()
    export.export_all(session, tmp_path, fmt="json")
    data = json.loads((tmp_path / "patreon_metrics.json").read_text())
    assert data[0]["mrr_cents"] == 2000


def test_export_rejects_bad_format(settings, session, tmp_path):
    try:
        export.export_all(session, tmp_path, fmt="xml")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_conversions_by_campaign(settings, session):
    link = repo.create_utm_link(
        session, destination_url="https://patreon.com/x", campaign="c1"
    )
    click = repo.record_click(session, link)
    member, _ = repo.upsert_member(session, patreon_member_id="m1", started_at=utcnow())
    repo.record_conversion(
        session, member=member, link_click=click, confidence=0.9, method="last_click"
    )
    session.flush()
    assert ("c1", 1) in funnel.conversions_by_campaign(session)
