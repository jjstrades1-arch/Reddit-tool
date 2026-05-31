"""Member story-influence: polls and free-form suggestions.

This is the product the Patreon sells. It supports the three influence modes the
creator uses:

* **Fixed-option polls** for plot-direction branches and character naming/fates.
* **Free-form suggestions** members submit, which the author shortlists and can
  promote into a fixed-option poll.
* **Early-access** is handled by the post scheduler; this module focuses on voting.

Compliance: voting happens ONLY inside our own poll system, among Patreon
members, one vote per member (tier-weighting optional via config). It never
touches Reddit's up/down votes. Teaser results posted to Reddit are *content*
("members chose X"), never a request to upvote anything.
"""

from __future__ import annotations

from datetime import datetime

import typer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.db import session_scope
from ..core.logging import get_logger
from ..core.models import (
    PatreonMember,
    Poll,
    PollKind,
    PollOption,
    PollStatus,
    PollVote,
    Suggestion,
    SuggestionStatus,
    utcnow,
)

log = get_logger(__name__)


class VoteError(RuntimeError):
    pass


def create_poll(
    session: Session,
    *,
    question: str,
    options: list[str],
    kind: PollKind = PollKind.PLOT,
    closes_at: datetime | None = None,
) -> Poll:
    if len(options) < 2:
        raise ValueError("A poll needs at least two options.")
    poll = Poll(question=question, kind=kind, closes_at=closes_at)
    poll.options = [PollOption(label=label) for label in options]
    session.add(poll)
    session.flush()
    log.info("Created %s poll id=%s with %d options", kind.value, poll.id, len(options))
    return poll


def _member_vote_weight(member: PatreonMember) -> int:
    """Voting weight for a member.

    One member, one vote by default. If tier-weighted voting is enabled, the
    weight scales gently with pledge size (still bounded to avoid pay-to-dominate).
    """
    if not get_settings().enable_tier_weighted_votes:
        return 1
    # $0-4.99 -> 1, $5-9.99 -> 2, $10+ -> 3 (bounded).
    return min(3, 1 + member.pledge_cents // 500)


def cast_vote(
    session: Session, *, poll: Poll, member: PatreonMember, option: PollOption
) -> PollVote:
    """Record one member's vote. Enforces poll-open + one-vote-per-member."""
    if poll.status != PollStatus.OPEN:
        raise VoteError("This poll is closed.")
    if poll.closes_at and utcnow() > poll.closes_at:
        raise VoteError("This poll's voting window has ended.")
    if option.poll_id != poll.id:
        raise VoteError("Option does not belong to this poll.")
    existing = session.scalar(
        select(PollVote)
        .where(PollVote.poll_id == poll.id)
        .where(PollVote.patreon_member_id == member.id)
    )
    if existing:
        raise VoteError("This member has already voted in this poll.")
    weight = _member_vote_weight(member)
    vote = PollVote(poll=poll, option_id=option.id, patreon_member_id=member.id, weight=weight)
    session.add(vote)
    option.vote_count += weight
    session.flush()
    return vote


def tally(session: Session, poll: Poll) -> list[tuple[PollOption, int]]:
    """Return options sorted by vote count, descending."""
    opts = sorted(poll.options, key=lambda o: o.vote_count, reverse=True)
    return [(o, o.vote_count) for o in opts]


def close_poll(session: Session, poll: Poll) -> PollOption | None:
    """Close a poll and return the winning option (None if tie/no votes)."""
    poll.status = PollStatus.CLOSED
    poll.closes_at = poll.closes_at or utcnow()
    results = tally(session, poll)
    session.flush()
    if not results or results[0][1] == 0:
        return None
    if len(results) > 1 and results[0][1] == results[1][1]:
        return None  # tie -- author decides
    return results[0][0]


# -- Suggestions ------------------------------------------------------------ #
def add_suggestion(
    session: Session, *, member: PatreonMember, text: str
) -> Suggestion:
    s = Suggestion(patreon_member_id=member.id, text=text)
    session.add(s)
    session.flush()
    return s


def shortlist(session: Session, suggestion: Suggestion) -> None:
    suggestion.status = SuggestionStatus.SHORTLISTED
    session.flush()


def promote_shortlist_to_poll(
    session: Session, *, question: str, kind: PollKind = PollKind.SUGGESTION
) -> Poll:
    """Turn all currently shortlisted suggestions into a fixed-option poll."""
    shortlisted = session.scalars(
        select(Suggestion).where(Suggestion.status == SuggestionStatus.SHORTLISTED)
    ).all()
    if len(shortlisted) < 2:
        raise ValueError("Need at least two shortlisted suggestions to make a poll.")
    poll = create_poll(
        session, question=question, options=[s.text for s in shortlisted], kind=kind
    )
    for s in shortlisted:
        s.status = SuggestionStatus.PROMOTED
        s.poll_id = poll.id
    session.flush()
    return poll


def register_cli(group: typer.Typer) -> None:
    @group.command("poll-create")
    def poll_create_cmd(
        question: str = typer.Option(..., help="The poll question."),
        option: list[str] = typer.Option(..., "--option", "-o", help="Option (repeat for each)."),
        kind: str = typer.Option("plot", help="plot | naming | suggestion"),
    ) -> None:
        """Create a member poll (plot direction, naming, etc.)."""
        with session_scope() as session:
            poll = create_poll(
                session, question=question, options=list(option), kind=PollKind(kind)
            )
            typer.echo(f"Created poll id={poll.id} with {len(poll.options)} options.")

    @group.command("poll-results")
    def poll_results_cmd(
        poll_id: int = typer.Option(..., help="Poll id."),
    ) -> None:
        """Show current tally for a poll."""
        with session_scope() as session:
            poll = session.get(Poll, poll_id)
            if not poll:
                typer.echo("No such poll.")
                return
            typer.echo(f"{poll.question} [{poll.status.value}]")
            for opt, count in tally(session, poll):
                typer.echo(f"  {count:4d}  {opt.label}")

    @group.command("poll-close")
    def poll_close_cmd(
        poll_id: int = typer.Option(..., help="Poll id."),
    ) -> None:
        """Close a poll and announce the winning option."""
        with session_scope() as session:
            poll = session.get(Poll, poll_id)
            if not poll:
                typer.echo("No such poll.")
                return
            winner = close_poll(session, poll)
            if winner is None:
                typer.echo("Poll closed with no clear winner (tie or no votes).")
            else:
                typer.echo(f"Poll closed. Members chose: {winner.label}")
