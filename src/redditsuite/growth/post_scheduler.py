"""Schedule and submit story chapters to the home subreddit.

Compliance: this only ever posts *your own* content to *your own* sub, and every
submission passes :class:`~redditsuite.core.compliance.PostingGuard` (min spacing
+ per-day cap). Chapters with a future ``early_access_until`` stay members-only
until that window passes.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import typer
from sqlalchemy.orm import Session

from ..core import repositories as repo
from ..core.compliance import ComplianceError, PostingGuard
from ..core.config import get_settings
from ..core.db import session_scope
from ..core.logging import get_logger
from ..core.models import Post, PostStatus, utcnow

log = get_logger(__name__)


def schedule_chapter(
    session: Session,
    *,
    title: str,
    body: str | None,
    chapter_no: int | None,
    when: datetime,
    early_access_hours: int | None = None,
) -> Post:
    """Queue a chapter for *public* submission at ``when`` (UTC).

    ``when`` is the public release time. Members receive the chapter
    ``early_access_hours`` earlier (delivered via Patreon, outside Reddit); we
    record that head-start so the dashboard and teaser tools can reference it.
    ``early_access_until`` on the post equals ``when`` -- the moment the public
    submission is permitted -- so the scheduler never posts ahead of time.
    """
    settings = get_settings()
    hours = (
        settings.default_early_access_hours
        if early_access_hours is None
        else early_access_hours
    )
    post = repo.add_post(
        session,
        title=title,
        body=body,
        chapter_no=chapter_no,
        scheduled_at=when,
        early_access_until=when,
    )
    log.info("Scheduled chapter %s for public release %s (post id=%s)", chapter_no, when, post.id)
    if hours:
        log.info("Members' early access began ~%s", when - timedelta(hours=hours))
    return post


def submit_post(session: Session, post: Post, *, reddit=None, now: datetime | None = None) -> Post:
    """Submit a single queued post to Reddit, after compliance checks."""
    now = now or utcnow()
    guard = PostingGuard()
    guard.enforce_home_post(session, post.subreddit, now=now)

    if reddit is None:  # pragma: no cover - exercised via integration, not unit tests
        from ..core.reddit_client import get_reddit

        reddit = get_reddit()

    subreddit = reddit.subreddit(post.subreddit.name)
    submission = subreddit.submit(title=post.title, selftext=post.body or "")
    post.reddit_id = getattr(submission, "id", None)
    post.permalink = getattr(submission, "permalink", None)
    post.status = PostStatus.POSTED
    post.submitted_at = now
    session.flush()
    log.info("Submitted post id=%s to r/%s", post.id, post.subreddit.name)
    return post


def run_due_posts(*, reddit=None, now: datetime | None = None) -> int:
    """Submit every scheduled post that is now due. Returns count submitted."""
    submitted = 0
    with session_scope() as session:
        for post in repo.get_due_scheduled_posts(session, now=now):
            try:
                submit_post(session, post, reddit=reddit, now=now)
                submitted += 1
            except ComplianceError as exc:
                log.warning("Skipping post id=%s: %s", post.id, exc)
    return submitted


def register_jobs(scheduler) -> None:
    """Check for due posts every 5 minutes."""
    scheduler.add_job(
        run_due_posts,
        "interval",
        minutes=5,
        id="post_scheduler.run_due_posts",
        replace_existing=True,
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def register_cli(group: typer.Typer) -> None:
    @group.command("schedule")
    def schedule_cmd(
        title: str = typer.Option(..., help="Reddit post title."),
        when: str = typer.Option(..., help="Post time, ISO 8601 UTC, e.g. 2026-06-01T17:00"),
        body: str = typer.Option("", help="Post body (selftext)."),
        chapter: int = typer.Option(None, help="Chapter number."),
        early_access_hours: int = typer.Option(
            None, help="Members' head-start in hours (defaults to config)."
        ),
    ) -> None:
        """Queue a chapter for automated submission to the home sub."""
        when_dt = datetime.fromisoformat(when)
        with session_scope() as session:
            post = schedule_chapter(
                session,
                title=title,
                body=body or None,
                chapter_no=chapter,
                when=when_dt,
                early_access_hours=early_access_hours,
            )
            typer.echo(f"Scheduled post id={post.id} for {when_dt} UTC")

    @group.command("run-due")
    def run_due_cmd() -> None:
        """Submit any posts whose scheduled time has arrived."""
        count = run_due_posts()
        typer.echo(f"Submitted {count} due post(s).")
