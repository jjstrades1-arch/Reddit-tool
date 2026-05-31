"""Tests for conversion tools: CTA links, attribution, polls, teasers."""

from __future__ import annotations

from datetime import timedelta

import pytest

from redditsuite.conversion import attribution, cta_links, polls, teaser_gen
from redditsuite.core import repositories as repo
from redditsuite.core.models import PollKind, PollStatus, utcnow


def test_tracked_and_destination_urls(settings, session):
    link = cta_links.create_link(
        session,
        destination_url="https://patreon.com/join",
        campaign="chapter-12",
        content="footer",
    )
    assert cta_links.tracked_url(link) == f"http://test.local/r/{link.slug}"
    dest = cta_links.destination_with_utm(link)
    assert "utm_source=reddit" in dest
    assert "utm_campaign=chapter-12" in dest


def test_attribution_matches_recent_click(settings, session):
    link = repo.create_utm_link(session, destination_url="https://patreon.com/join")
    now = utcnow()
    click = repo.record_click(session, link)
    click.clicked_at = now - timedelta(hours=1)
    member, _ = repo.upsert_member(
        session, patreon_member_id="m1", pledge_cents=500, started_at=now
    )
    session.flush()

    conv = attribution.attribute_member(session, member)
    assert conv is not None
    assert conv.link_click_id == click.id
    assert 0 < conv.confidence <= 1


def test_attribution_ignores_old_clicks(settings, session):
    link = repo.create_utm_link(session, destination_url="https://patreon.com/join")
    now = utcnow()
    click = repo.record_click(session, link)
    click.clicked_at = now - timedelta(days=30)  # outside lookback
    member, _ = repo.upsert_member(
        session, patreon_member_id="m2", pledge_cents=500, started_at=now
    )
    session.flush()
    assert attribution.attribute_member(session, member) is None


def test_one_click_not_double_counted(settings, session):
    link = repo.create_utm_link(session, destination_url="https://patreon.com/join")
    now = utcnow()
    click = repo.record_click(session, link)
    click.clicked_at = now - timedelta(hours=1)
    m1, _ = repo.upsert_member(session, patreon_member_id="a", started_at=now)
    m2, _ = repo.upsert_member(
        session, patreon_member_id="b", started_at=now + timedelta(minutes=5)
    )
    session.flush()
    assert attribution.attribute_member(session, m1) is not None
    # The single click is now claimed; the second member can't reuse it.
    assert attribution.attribute_member(session, m2) is None


def test_poll_one_vote_per_member(settings, session):
    poll = polls.create_poll(
        session, question="Door A or B?", options=["A", "B"], kind=PollKind.PLOT
    )
    member, _ = repo.upsert_member(session, patreon_member_id="m1")
    session.flush()
    polls.cast_vote(session, poll=poll, member=member, option=poll.options[0])
    with pytest.raises(polls.VoteError):
        polls.cast_vote(session, poll=poll, member=member, option=poll.options[1])
    assert poll.options[0].vote_count == 1
    assert poll.options[1].vote_count == 0


def test_poll_close_picks_winner(settings, session):
    poll = polls.create_poll(session, question="?", options=["A", "B"])
    voters = [repo.upsert_member(session, patreon_member_id=f"m{i}")[0] for i in range(3)]
    session.flush()
    polls.cast_vote(session, poll=poll, member=voters[0], option=poll.options[0])
    polls.cast_vote(session, poll=poll, member=voters[1], option=poll.options[0])
    polls.cast_vote(session, poll=poll, member=voters[2], option=poll.options[1])
    winner = polls.close_poll(session, poll)
    assert winner.label == "A"
    assert poll.status == PollStatus.CLOSED


def test_tier_weighted_voting_optional(settings, session, monkeypatch):
    monkeypatch.setenv("ENABLE_TIER_WEIGHTED_VOTES", "true")
    from redditsuite.core import config

    config.get_settings.cache_clear()
    poll = polls.create_poll(session, question="?", options=["A", "B"])
    big = repo.upsert_member(session, patreon_member_id="whale", pledge_cents=1500)[0]
    session.flush()
    polls.cast_vote(session, poll=poll, member=big, option=poll.options[0])
    assert poll.options[0].vote_count == 3  # bounded weight
    config.get_settings.cache_clear()


def test_suggestion_promotion(settings, session):
    members = [repo.upsert_member(session, patreon_member_id=f"m{i}")[0] for i in range(2)]
    session.flush()
    s1 = polls.add_suggestion(session, member=members[0], text="Name her Mira")
    s2 = polls.add_suggestion(session, member=members[1], text="Name her Sol")
    polls.shortlist(session, s1)
    polls.shortlist(session, s2)
    poll = polls.promote_shortlist_to_poll(session, question="Pick a name", kind=PollKind.NAMING)
    assert {o.label for o in poll.options} == {"Name her Mira", "Name her Sol"}


def test_teaser_is_draft(settings, session):
    poll = polls.create_poll(session, question="Door A or B?", options=["A", "B"])
    member, _ = repo.upsert_member(session, patreon_member_id="m1")
    session.flush()
    polls.cast_vote(session, poll=poll, member=member, option=poll.options[0])
    polls.close_poll(session, poll)
    draft = teaser_gen.draft_teaser(session, poll)
    assert "DRAFT" in draft
    assert "Do not ask for upvotes" in draft
    assert "**A**" in draft
