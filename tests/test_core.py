"""Tests for the shared core: config, repositories, compliance."""

from __future__ import annotations

from datetime import timedelta

import pytest

from redditsuite.core import repositories as repo
from redditsuite.core.compliance import (
    ComplianceError,
    PostingGuard,
    assert_not_vote_manipulation,
    check_cross_promo_cadence,
    requires_human_approval,
)
from redditsuite.core.models import PostStatus, utcnow


def test_home_subreddit_created_once(session):
    a = repo.get_home_subreddit(session)
    b = repo.get_home_subreddit(session)
    assert a.id == b.id
    assert a.is_home is True
    assert a.name == "TestStory"


def test_hash_ip_is_salted_and_stable(session):
    h1 = repo.hash_ip("1.2.3.4")
    h2 = repo.hash_ip("1.2.3.4")
    assert h1 == h2
    assert h1 != "1.2.3.4"
    assert repo.hash_ip(None) is None


def test_utm_link_slug_is_unique(session):
    a = repo.create_utm_link(session, destination_url="https://patreon.com/x")
    b = repo.create_utm_link(session, destination_url="https://patreon.com/x")
    assert a.slug != b.slug


def test_posting_guard_daily_cap(session):
    sub = repo.get_home_subreddit(session)
    now = utcnow()
    # Three posts already today (cap is 3).
    for i in range(3):
        p = repo.add_post(session, title=f"t{i}")
        p.status = PostStatus.POSTED
        p.submitted_at = now - timedelta(minutes=10 * i)
    session.flush()
    decision = PostingGuard().check_home_post(session, sub, now=now)
    assert decision.allowed is False
    assert "Daily cap" in decision.reason


def test_posting_guard_spacing(session):
    sub = repo.get_home_subreddit(session)
    now = utcnow()
    p = repo.add_post(session, title="recent")
    p.status = PostStatus.POSTED
    p.submitted_at = now - timedelta(minutes=30)  # < 180 min spacing
    session.flush()
    decision = PostingGuard().check_home_post(session, sub, now=now)
    assert decision.allowed is False
    assert "Too soon" in decision.reason


def test_posting_guard_allows_when_clear(session):
    sub = repo.get_home_subreddit(session)
    assert PostingGuard().check_home_post(session, sub).allowed is True


def test_vote_manipulation_is_blocked():
    for action in ("upvote", "downvote", "vote", "award"):
        with pytest.raises(ComplianceError):
            assert_not_vote_manipulation(action)
    assert_not_vote_manipulation("post_chapter")  # fine


def test_human_in_the_loop_actions():
    assert requires_human_approval("reply_to_comment")
    assert requires_human_approval("cross_post")
    assert requires_human_approval("post_teaser")
    assert not requires_human_approval("schedule_post")


def test_cross_promo_cadence_warns(session):
    sub = repo.get_or_create_subreddit(session, "WritingPrompts")
    sub.min_days_between_promos = 7
    sub.last_promo_at = utcnow() - timedelta(days=2)
    session.flush()
    decision = check_cross_promo_cadence(sub)
    assert decision.allowed is False
    assert "WILL NOT auto-post".lower() in decision.reason.lower()
