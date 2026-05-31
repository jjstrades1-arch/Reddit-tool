"""Central compliance guardrails.

Reddit and Patreon both prohibit spam, vote manipulation and fake engagement.
Rather than scatter these rules through the tools, every risky action routes
through here. The two pillars are:

* :class:`PostingGuard` -- enforces minimum spacing and per-day caps on
  automated submissions to the home subreddit.
* :func:`requires_human_approval` -- marks an action as human-in-the-loop. Such
  actions only ever *draft*; a human must explicitly approve before anything is
  sent to Reddit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from . import repositories as repo
from .config import Settings, get_settings
from .models import Subreddit, utcnow


class ComplianceError(RuntimeError):
    """Raised when an action would violate a guardrail."""


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    reason: str = ""


class PostingGuard:
    """Spacing and rate limits for automated submissions."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def check_home_post(
        self, session: Session, subreddit: Subreddit, *, now: datetime | None = None
    ) -> GuardDecision:
        now = now or utcnow()
        posted_today = repo.count_posts_today(session, subreddit.id, now=now)
        if posted_today >= self.settings.max_posts_per_day:
            return GuardDecision(
                False,
                f"Daily cap reached ({posted_today}/"
                f"{self.settings.max_posts_per_day}) for r/{subreddit.name}.",
            )
        last = repo.last_post_time(session, subreddit.id)
        if last is not None:
            spacing = timedelta(minutes=self.settings.min_post_spacing_minutes)
            if now - last < spacing:
                wait = spacing - (now - last)
                mins = int(wait.total_seconds() // 60)
                return GuardDecision(
                    False,
                    f"Too soon since last post; wait ~{mins} min "
                    f"(min spacing {self.settings.min_post_spacing_minutes} min).",
                )
        return GuardDecision(True)

    def enforce_home_post(
        self, session: Session, subreddit: Subreddit, *, now: datetime | None = None
    ) -> None:
        decision = self.check_home_post(session, subreddit, now=now)
        if not decision.allowed:
            raise ComplianceError(decision.reason)


def check_cross_promo_cadence(
    subreddit: Subreddit, *, now: datetime | None = None
) -> GuardDecision:
    """Warn (never auto-post) if a cross-promo would break a sub's cadence."""
    now = now or utcnow()
    if subreddit.is_home:
        return GuardDecision(True)
    if subreddit.min_days_between_promos and subreddit.last_promo_at:
        gap = timedelta(days=subreddit.min_days_between_promos)
        if now - subreddit.last_promo_at < gap:
            next_ok = subreddit.last_promo_at + gap
            return GuardDecision(
                False,
                f"r/{subreddit.name} allows self-promo every "
                f"{subreddit.min_days_between_promos} day(s); next OK on "
                f"{next_ok:%Y-%m-%d}. This tool will NOT auto-post -- review manually.",
            )
    return GuardDecision(True)


#: Actions that must never be fully automated -- they only ever produce drafts.
HUMAN_IN_THE_LOOP_ACTIONS: frozenset[str] = frozenset(
    {
        "reply_to_comment",      # engagement_monitor: drafts only
        "cross_post",            # cross_promo: assist only, never auto-post
        "post_teaser",           # teaser_gen: drafts only
    }
)


def requires_human_approval(action: str) -> bool:
    """True if ``action`` may only be performed after explicit human approval."""
    return action in HUMAN_IN_THE_LOOP_ACTIONS


def assert_not_vote_manipulation(action: str) -> None:
    """Hard stop on anything resembling Reddit vote manipulation."""
    banned = {"upvote", "downvote", "vote", "award", "brigade"}
    if action.lower() in banned:
        raise ComplianceError(
            "Reddit vote/award manipulation is prohibited and not supported. "
            "Member voting happens only inside our own poll system."
        )
