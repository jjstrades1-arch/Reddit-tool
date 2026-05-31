"""Tests for growth tools: scheduler, timing analyzer, A/B titles, engagement."""

from __future__ import annotations

from datetime import timedelta

from redditsuite.core import repositories as repo
from redditsuite.core.db import session_scope
from redditsuite.core.models import PostStatus, utcnow
from redditsuite.growth import ab_titles, engagement_monitor, post_scheduler, timing_analyzer


def test_schedule_and_submit_due_post(settings, session, fake_reddit):
    when = utcnow() - timedelta(minutes=1)  # already due
    post_scheduler.schedule_chapter(
        session, title="Chapter 1", body="hi", chapter_no=1, when=when, early_access_hours=0
    )
    session.commit()

    submitted = post_scheduler.run_due_posts(reddit=fake_reddit, now=utcnow())
    assert submitted == 1
    assert fake_reddit.submitted == [("Chapter 1", "hi")]

    with session_scope() as s:
        post = repo.get_due_scheduled_posts(s)
        assert post == []  # nothing left scheduled


def test_compliance_blocks_second_quick_post(settings, session, fake_reddit):
    now = utcnow()
    # An existing recent post trips the spacing rule.
    p = repo.add_post(session, title="earlier")
    p.status = PostStatus.POSTED
    p.submitted_at = now - timedelta(minutes=5)
    post_scheduler.schedule_chapter(
        session, title="Chapter 2", body="", chapter_no=2, when=now - timedelta(minutes=1),
        early_access_hours=0,
    )
    session.commit()

    submitted = post_scheduler.run_due_posts(reddit=fake_reddit, now=now)
    assert submitted == 0  # blocked by spacing guard
    assert fake_reddit.submitted == []


def test_timing_analyzer_ranks_windows(settings, session):
    sub = repo.get_home_subreddit(session)
    base = utcnow().replace(hour=17, minute=0, second=0, microsecond=0)
    # Two posts at hour 17 with high engagement, one at hour 3 with low.
    for score, when in [(100, base), (80, base + timedelta(days=7)), (2, base.replace(hour=3))]:
        p = repo.add_post(session, title="t", subreddit=sub)
        p.status = PostStatus.POSTED
        p.submitted_at = when
        session.flush()
        repo.record_post_metric(session, p, score=score, num_comments=0)
    session.flush()

    windows = timing_analyzer.compute_windows(session, sub.id)
    assert windows
    top = timing_analyzer.top_windows(session, sub.id, limit=1)[0]
    assert top.hour == 17


def test_ab_title_scoring(settings, session):
    a = ab_titles.add_variant(session, content_key="ch12", text="Hook A")
    b = ab_titles.add_variant(session, content_key="ch12", text="Hook B")
    for variant, score in [(a, 50), (b, 5)]:
        p = repo.add_post(session, title=variant.text)
        p.title_variant_id = variant.id
        p.status = PostStatus.POSTED
        session.flush()
        repo.record_post_metric(session, p, score=score, num_comments=0)
    session.flush()

    ranked = ab_titles.score_variants(session, "ch12")
    assert ranked[0].variant.text == "Hook A"
    assert ranked[0].avg_engagement > ranked[1].avg_engagement


def test_engagement_monitor_flags_high_value(settings, session):
    post = repo.add_post(session, title="t")
    session.flush()
    raw = [
        {"id": "c1", "body": "x", "author": "u1", "score": 1},  # too short
        {
            "id": "c2",
            "body": (
                "This absolutely blew me away, one of the best chapters "
                "I have ever read, truly wonderful!"
            ),
            "author": "u2",
            "score": 20,
        },
    ]
    added = engagement_monitor.ingest_comments(session, post, raw)
    assert added == 2
    queue = engagement_monitor.high_value_queue(session)
    assert len(queue) == 1
    assert queue[0].reddit_id == "c2"
    draft = engagement_monitor.draft_reply(queue[0])
    assert "DRAFT" in draft
