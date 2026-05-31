"""Engagement monitor -- surfaces high-value comments for a HUMAN to answer.

Replying to readers boosts a thread's visibility and builds community, but
automated/templated replies look like bot engagement and violate Reddit's
rules. So this tool is strictly human-in-the-loop: it pulls new comments, scores
them, flags the ones worth a personal reply, and can draft a reply -- but a human
always reviews and sends.
"""

from __future__ import annotations

import typer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analytics.sentiment import score_text
from ..core.compliance import requires_human_approval
from ..core.db import session_scope
from ..core.logging import get_logger
from ..core.models import Comment, Post

log = get_logger(__name__)

#: A comment is "high value" if it is substantive and either very positive
#: (a fan to nurture) or strongly negative (a concern to address).
_MIN_LENGTH = 80


def ingest_comments(session: Session, post: Post, raw_comments) -> int:
    """Persist new comments for ``post`` with sentiment + high-value flags.

    ``raw_comments`` is any iterable of objects/dicts exposing ``id``, ``body``,
    ``author`` and ``score`` -- in production these are PRAW comments; in tests
    they are simple stand-ins.
    """
    added = 0
    for rc in raw_comments:
        cid = _attr(rc, "id")
        if cid is None:
            continue
        exists = session.scalar(select(Comment).where(Comment.reddit_id == cid))
        if exists:
            continue
        body = _attr(rc, "body") or ""
        sentiment = score_text(body)
        comment = Comment(
            reddit_id=cid,
            post=post,
            author=_attr(rc, "author"),
            body=body,
            score=int(_attr(rc, "score") or 0),
            sentiment_score=sentiment,
            is_flagged_high_value=_is_high_value(body, sentiment),
        )
        session.add(comment)
        added += 1
    session.flush()
    return added


def _is_high_value(body: str, sentiment: float) -> bool:
    if len(body.strip()) < _MIN_LENGTH:
        return False
    return abs(sentiment) >= 0.5


def high_value_queue(session: Session, *, limit: int = 20) -> list[Comment]:
    return session.scalars(
        select(Comment)
        .where(Comment.is_flagged_high_value.is_(True))
        .where(Comment.handled.is_(False))
        .order_by(Comment.score.desc())
        .limit(limit)
    ).all()


def draft_reply(comment: Comment) -> str:
    """Produce a *draft* reply for a human to edit and send. Never auto-sent."""
    assert requires_human_approval("reply_to_comment")  # documents the contract
    tone = "Thanks so much for reading and for this" if (comment.sentiment_score or 0) >= 0 else (
        "I really appreciate you taking the time to share this"
    )
    return (
        f"{tone} -- [DRAFT, review before sending]. "
        f"Re: \"{comment.body[:120].strip()}\"..."
    )


def _attr(obj, name):
    if isinstance(obj, dict):
        return obj.get(name)
    val = getattr(obj, name, None)
    # PRAW author is a Redditor object; stringify for storage.
    if name == "author" and val is not None:
        return str(val)
    return val


def register_cli(group: typer.Typer) -> None:
    @group.command("queue")
    def queue_cmd(
        limit: int = typer.Option(20, help="Max comments to show."),
    ) -> None:
        """Show high-value comments awaiting a personal (human) reply."""
        with session_scope() as session:
            rows = high_value_queue(session, limit=limit)
            if not rows:
                typer.echo("No high-value comments pending. Nice and tidy.")
                return
            for c in rows:
                s = c.sentiment_score or 0.0
                typer.echo(f"[{s:+.2f}] u/{c.author} (score {c.score}): {c.body[:140]}")
                typer.echo(f"    draft -> {draft_reply(c)}")

    @group.command("mark-handled")
    def mark_handled_cmd(
        comment_id: int = typer.Option(..., help="Local comment id to mark handled."),
    ) -> None:
        """Mark a comment as handled once you've replied yourself."""
        with session_scope() as session:
            c = session.get(Comment, comment_id)
            if not c:
                typer.echo("No such comment.")
                return
            c.handled = True
            typer.echo(f"Marked comment {comment_id} handled.")
