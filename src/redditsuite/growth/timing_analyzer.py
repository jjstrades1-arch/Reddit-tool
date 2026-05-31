"""Derive the best posting windows from historical post performance.

For every (weekday, hour) bucket we average an engagement signal (score plus
comments) across past posts, writing the result to ``optimal_windows`` so the
scheduler and dashboard can recommend slots. Read-only over your own data.
"""

from __future__ import annotations

from collections import defaultdict

import typer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import session_scope
from ..core.logging import get_logger
from ..core.models import OptimalWindow, Post, PostMetric, PostStatus, utcnow

log = get_logger(__name__)


def _latest_metric_for_post(session: Session, post_id: int) -> PostMetric | None:
    return session.scalar(
        select(PostMetric)
        .where(PostMetric.post_id == post_id)
        .order_by(PostMetric.captured_at.desc())
        .limit(1)
    )


def compute_windows(session: Session, subreddit_id: int) -> list[OptimalWindow]:
    """Recompute optimal windows for one subreddit from posted history."""
    posts = session.scalars(
        select(Post)
        .where(Post.subreddit_id == subreddit_id)
        .where(Post.status == PostStatus.POSTED)
        .where(Post.submitted_at.is_not(None))
    ).all()

    buckets: dict[tuple[int, int], list[float]] = defaultdict(list)
    for post in posts:
        metric = _latest_metric_for_post(session, post.id)
        if metric is None:
            continue
        engagement = float(metric.score) + 2.0 * float(metric.num_comments)
        key = (post.submitted_at.weekday(), post.submitted_at.hour)
        buckets[key].append(engagement)

    # Clear previous windows for this sub, then rewrite.
    for existing in session.scalars(
        select(OptimalWindow).where(OptimalWindow.subreddit_id == subreddit_id)
    ):
        session.delete(existing)
    session.flush()

    windows: list[OptimalWindow] = []
    now = utcnow()
    for (weekday, hour), values in buckets.items():
        window = OptimalWindow(
            subreddit_id=subreddit_id,
            weekday=weekday,
            hour=hour,
            engagement_index=sum(values) / len(values),
            sample_size=len(values),
            computed_at=now,
        )
        session.add(window)
        windows.append(window)
    session.flush()
    log.info("Computed %d optimal windows for subreddit_id=%s", len(windows), subreddit_id)
    return windows


def top_windows(session: Session, subreddit_id: int, limit: int = 5) -> list[OptimalWindow]:
    return session.scalars(
        select(OptimalWindow)
        .where(OptimalWindow.subreddit_id == subreddit_id)
        .order_by(OptimalWindow.engagement_index.desc())
        .limit(limit)
    ).all()


_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def register_cli(group: typer.Typer) -> None:
    @group.command("analyze-timing")
    def analyze_timing_cmd() -> None:
        """Recompute optimal posting windows and show the top slots."""
        from ..core import repositories as repo

        with session_scope() as session:
            sub = repo.get_home_subreddit(session)
            compute_windows(session, sub.id)
            typer.echo("Top posting windows (UTC):")
            for w in top_windows(session, sub.id):
                typer.echo(
                    f"  {_DAYS[w.weekday]} {w.hour:02d}:00  "
                    f"engagement={w.engagement_index:.1f}  (n={w.sample_size})"
                )
