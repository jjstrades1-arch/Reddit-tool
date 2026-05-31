"""Refresh post stats and comments from PUBLIC Reddit -- no login required.

For every posted chapter that has a Reddit link attached, this pulls the current
score/comment count (a new ``PostMetric`` snapshot) and ingests its comments
(with sentiment + high-value flags). This recovers the upvote heatmap, A/B title
winners, the funnel's upvote stage, and the comments queue without an API app.
"""

from __future__ import annotations

import typer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core import repositories as repo
from ..core.db import session_scope
from ..core.logging import get_logger
from ..core.models import Post, PostStatus
from ..growth.engagement_monitor import ingest_comments

log = get_logger(__name__)


def refresh_from_public(
    session: Session,
    *,
    fetch_post=None,
    fetch_comments=None,
    with_comments: bool = True,
) -> dict:
    """Update metrics (and optionally comments) for linked posts. Returns counts.

    The fetchers are injected so tests never touch the network; in production they
    default to :mod:`redditsuite.core.reddit_public`.
    """
    if fetch_post is None or fetch_comments is None:
        from ..core import reddit_public

        fetch_post = fetch_post or reddit_public.fetch_post
        fetch_comments = fetch_comments or reddit_public.fetch_comments

    posts = session.scalars(
        select(Post)
        .where(Post.status == PostStatus.POSTED)
        .where(Post.reddit_id.is_not(None))
    ).all()

    updated = 0
    new_comments = 0
    for post in posts:
        info = fetch_post(post.reddit_id)
        repo.record_post_metric(
            session,
            post,
            score=info["score"],
            num_comments=info["num_comments"],
            upvote_ratio=info.get("upvote_ratio"),
        )
        if not post.permalink and info.get("permalink"):
            post.permalink = info["permalink"]
        updated += 1
        if with_comments:
            new_comments += ingest_comments(session, post, fetch_comments(post.reddit_id))

    session.flush()
    log.info("Public refresh: %d post(s), %d new comment(s)", updated, new_comments)
    return {"updated": updated, "new_comments": new_comments}


def register_cli(group: typer.Typer) -> None:
    @group.command("refresh-public")
    def refresh_public_cmd(
        comments: bool = typer.Option(True, help="Also pull comments."),
    ) -> None:
        """Pull upvotes/comments from public Reddit for your linked posts (no login)."""
        with session_scope() as session:
            res = refresh_from_public(session, with_comments=comments)
        typer.echo(
            f"Updated {res['updated']} post(s); found {res['new_comments']} new comment(s)."
        )
