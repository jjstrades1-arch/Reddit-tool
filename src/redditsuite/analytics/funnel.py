"""Funnel roll-ups: tie Reddit engagement to Patreon outcomes.

These pure-query functions are the single source the dashboard renders from, so
the CLI and the web UI always agree.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.models import (
    Conversion,
    LinkClick,
    MemberStatus,
    PatreonMember,
    PatreonMetric,
    Post,
    PostMetric,
    PostStatus,
    UTMLink,
)


@dataclass
class FunnelSummary:
    posts: int
    total_upvotes: int
    clicks: int
    conversions: int
    active_patrons: int
    mrr_cents: int
    # Stage-to-stage conversion rates (0-1).
    upvote_to_click: float
    click_to_conversion: float

    def as_dict(self) -> dict:
        return asdict(self)


def _latest_upvotes(session: Session) -> int:
    """Sum the most recent score snapshot of each posted submission."""
    total = 0
    posts = session.scalars(
        select(Post).where(Post.status == PostStatus.POSTED)
    ).all()
    for post in posts:
        metric = session.scalar(
            select(PostMetric)
            .where(PostMetric.post_id == post.id)
            .order_by(PostMetric.captured_at.desc())
            .limit(1)
        )
        if metric:
            total += metric.score
    return total


def summary(session: Session) -> FunnelSummary:
    posts = session.scalar(
        select(func.count()).select_from(Post).where(Post.status == PostStatus.POSTED)
    ) or 0
    clicks = session.scalar(select(func.count()).select_from(LinkClick)) or 0
    conversions = session.scalar(select(func.count()).select_from(Conversion)) or 0
    upvotes = _latest_upvotes(session)

    latest_patreon = session.scalar(
        select(PatreonMetric).order_by(PatreonMetric.captured_at.desc()).limit(1)
    )
    if latest_patreon:
        active = latest_patreon.patron_count
        mrr = latest_patreon.mrr_cents
    else:
        active = session.scalar(
            select(func.count())
            .select_from(PatreonMember)
            .where(PatreonMember.status == MemberStatus.ACTIVE)
        ) or 0
        mrr = session.scalar(
            select(func.coalesce(func.sum(PatreonMember.pledge_cents), 0)).where(
                PatreonMember.status == MemberStatus.ACTIVE
            )
        ) or 0

    return FunnelSummary(
        posts=posts,
        total_upvotes=upvotes,
        clicks=clicks,
        conversions=conversions,
        active_patrons=active,
        mrr_cents=mrr,
        upvote_to_click=(clicks / upvotes) if upvotes else 0.0,
        click_to_conversion=(conversions / clicks) if clicks else 0.0,
    )


def clicks_by_campaign(session: Session) -> list[tuple[str, int]]:
    stmt = (
        select(UTMLink.campaign, func.count(LinkClick.id))
        .join(LinkClick, LinkClick.utm_link_id == UTMLink.id)
        .group_by(UTMLink.campaign)
        .order_by(func.count(LinkClick.id).desc())
    )
    return [(c or "(none)", n) for c, n in session.execute(stmt).all()]


def patreon_trend(session: Session, limit: int = 30) -> list[PatreonMetric]:
    rows = session.scalars(
        select(PatreonMetric).order_by(PatreonMetric.captured_at.desc()).limit(limit)
    ).all()
    return list(reversed(rows))
