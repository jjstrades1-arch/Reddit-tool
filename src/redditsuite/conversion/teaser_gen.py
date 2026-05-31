"""Teaser / FOMO post generator -- DRAFTS ONLY for a human to review and post.

After a member poll closes, a tasteful "here's what members decided" post on the
public sub creates genuine FOMO and advertises the Patreon's value. This module
only drafts that text; a human edits and submits it. It never solicits Reddit
votes or awards (that would violate Reddit's rules) -- it presents an outcome.
"""

from __future__ import annotations

import typer
from sqlalchemy.orm import Session

from ..core.compliance import requires_human_approval
from ..core.config import get_settings
from ..core.db import session_scope
from ..core.logging import get_logger
from ..core.models import Poll, PollKind
from .polls import tally

log = get_logger(__name__)


def draft_teaser(session: Session, poll: Poll) -> str:
    """Return draft post text announcing what members influenced. Not auto-posted."""
    assert requires_human_approval("post_teaser")  # documents the contract
    results = tally(session, poll)
    winner = results[0][0].label if results and results[0][1] > 0 else "(undecided)"
    total_votes = sum(c for _, c in results)
    settings = get_settings()

    verb = {
        PollKind.PLOT: "steered the story",
        PollKind.NAMING: "named a character",
        PollKind.SUGGESTION: "shaped what comes next",
    }.get(poll.kind, "shaped the story")

    lines = [
        f"**Patrons just {verb}.**",
        "",
        f"On this week's member poll — *{poll.question}* — "
        f"{total_votes} patron vote(s) came in, and the winner is:",
        "",
        f"> **{winner}**",
        "",
        "Members get early chapters and a direct say in moments like this. "
        f"If you'd like a vote on what happens next, join us: {settings.public_base_url}",
        "",
        "_[DRAFT — review, edit and post manually. Do not ask for upvotes.]_",
    ]
    return "\n".join(lines)


def register_cli(group: typer.Typer) -> None:
    @group.command("teaser")
    def teaser_cmd(
        poll_id: int = typer.Option(..., help="Closed poll to announce."),
    ) -> None:
        """Draft a FOMO teaser post for a poll result (you post it manually)."""
        with session_scope() as session:
            poll = session.get(Poll, poll_id)
            if not poll:
                typer.echo("No such poll.")
                return
            typer.echo(draft_teaser(session, poll))
