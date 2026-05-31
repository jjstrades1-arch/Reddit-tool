"""Periodic metric snapshots from Reddit and Patreon.

Read-only over data you own (your posts, your campaign). Each run appends a
time-series row so trends and the funnel can be charted. External clients are
injected for testability.
"""

from __future__ import annotations

import json
from collections import Counter

import typer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core import repositories as repo
from ..core.db import session_scope
from ..core.logging import get_logger
from ..core.models import (
    MemberStatus,
    PatreonMember,
    PatreonMetric,
    Post,
    PostStatus,
)

log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Reddit post metrics
# --------------------------------------------------------------------------- #
def collect_post_metrics(session: Session, *, reddit=None) -> int:
    """Snapshot score/comments for every posted submission. Returns rows written."""
    if reddit is None:  # pragma: no cover - integration path
        from ..core.reddit_client import get_reddit

        reddit = get_reddit()

    posts = session.scalars(
        select(Post)
        .where(Post.status == PostStatus.POSTED)
        .where(Post.reddit_id.is_not(None))
    ).all()
    written = 0
    for post in posts:
        submission = reddit.submission(id=post.reddit_id)
        repo.record_post_metric(
            session,
            post,
            score=int(getattr(submission, "score", 0) or 0),
            num_comments=int(getattr(submission, "num_comments", 0) or 0),
            upvote_ratio=getattr(submission, "upvote_ratio", None),
        )
        written += 1
    log.info("Captured %d post-metric snapshot(s)", written)
    return written


# --------------------------------------------------------------------------- #
# Patreon members + metrics
# --------------------------------------------------------------------------- #
def _parse_member(record: dict) -> dict:
    attrs = record.get("attributes", {})
    return {
        "patreon_member_id": record.get("id"),
        "full_name": attrs.get("full_name"),
        "patron_status": attrs.get("patron_status"),
        "pledge_cents": int(attrs.get("currently_entitled_amount_cents") or 0),
        "started_at": attrs.get("pledge_relationship_start"),
        "last_charge_at": attrs.get("last_charge_date"),
    }


def sync_patreon(session: Session, *, client=None) -> PatreonMetric:
    """Sync members from Patreon and append a metrics snapshot."""
    if client is None:  # pragma: no cover - integration path
        from ..core.patreon_client import PatreonClient

        client = PatreonClient()

    from datetime import datetime

    raw_members = client.iter_members()
    active = 0
    mrr = 0
    tier_amounts: Counter[int] = Counter()
    for record in raw_members:
        parsed = _parse_member(record)
        started = None
        if parsed["started_at"]:
            try:
                started = datetime.fromisoformat(
                    parsed["started_at"].replace("Z", "+00:00")
                ).replace(tzinfo=None)
            except ValueError:
                started = None
        member, _ = repo.upsert_member(
            session,
            patreon_member_id=parsed["patreon_member_id"],
            full_name=parsed["full_name"],
            pledge_cents=parsed["pledge_cents"],
            started_at=started,
        )
        if parsed["patron_status"] == "active_patron":
            member.status = MemberStatus.ACTIVE
            active += 1
            mrr += parsed["pledge_cents"]
            tier_amounts[parsed["pledge_cents"]] += 1
        elif parsed["patron_status"] == "former_patron":
            member.status = MemberStatus.FORMER
        else:
            member.status = MemberStatus.DECLINED

    churn_count = (
        session.scalar(
            select(func.count())
            .select_from(PatreonMember)
            .where(PatreonMember.status == MemberStatus.FORMER)
        )
        or 0
    )

    metric = PatreonMetric(
        patron_count=active,
        mrr_cents=mrr,
        new_patrons=0,
        churn_count=churn_count,
        tier_mix_json=json.dumps({str(k): v for k, v in tier_amounts.items()}),
    )
    session.add(metric)
    session.flush()
    log.info("Patreon snapshot: %d active patrons, $%.2f MRR", active, mrr / 100)
    return metric


def register_jobs(scheduler) -> None:
    """Collect Reddit + Patreon snapshots a few times a day."""

    def _collect_reddit():
        with session_scope() as session:
            collect_post_metrics(session)

    def _collect_patreon():
        with session_scope() as session:
            sync_patreon(session)

    scheduler.add_job(
        _collect_reddit, "interval", hours=6, id="collectors.reddit", replace_existing=True
    )
    scheduler.add_job(
        _collect_patreon, "interval", hours=6, id="collectors.patreon", replace_existing=True
    )


def register_cli(group: typer.Typer) -> None:
    @group.command("collect")
    def collect_cmd(
        reddit: bool = typer.Option(True, help="Collect Reddit post metrics."),
        patreon: bool = typer.Option(True, help="Collect Patreon member metrics."),
    ) -> None:
        """Run metric collection once now."""
        with session_scope() as session:
            if reddit:
                n = collect_post_metrics(session)
                typer.echo(f"Captured {n} Reddit post snapshot(s).")
            if patreon:
                m = sync_patreon(session)
                typer.echo(f"Patreon: {m.patron_count} patrons, ${m.mrr_cents / 100:.2f} MRR.")
