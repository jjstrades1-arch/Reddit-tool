"""Funnel roll-ups: tie Reddit engagement to Patreon outcomes.

These pure-query functions are the single source the dashboard renders from, so
the CLI and the web UI always agree.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.models import (
    Comment,
    Conversion,
    LinkClick,
    MemberStatus,
    OptimalWindow,
    PatreonMember,
    PatreonMetric,
    PatreonTier,
    Post,
    PostMetric,
    PostStatus,
    TitleVariant,
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


def conversions_by_campaign(session: Session) -> list[tuple[str, int]]:
    """Number of attributed conversions per UTM campaign."""
    stmt = (
        select(UTMLink.campaign, func.count(Conversion.id))
        .join(LinkClick, LinkClick.utm_link_id == UTMLink.id)
        .join(Conversion, Conversion.link_click_id == LinkClick.id)
        .group_by(UTMLink.campaign)
        .order_by(func.count(Conversion.id).desc())
    )
    return [(c or "(none)", n) for c, n in session.execute(stmt).all()]


# --------------------------------------------------------------------------- #
# Dashboard panel helpers
# --------------------------------------------------------------------------- #
def optimal_window_grid(session: Session, subreddit_id: int) -> dict:
    """7x24 (weekday x hour, UTC) engagement matrix for the heatmap.

    Reads the rows that ``growth.timing_analyzer.compute_windows`` materializes.
    """
    grid = [[0.0] * 24 for _ in range(7)]
    max_value = 0.0
    for w in session.scalars(
        select(OptimalWindow).where(OptimalWindow.subreddit_id == subreddit_id)
    ):
        grid[w.weekday][w.hour] = w.engagement_index
        max_value = max(max_value, w.engagement_index)
    return {"grid": grid, "max": max_value}


def ab_winners(session: Session) -> list[dict]:
    """Best-performing title variant per chapter (``content_key``)."""
    from ..growth.ab_titles import score_variants

    winners: list[dict] = []
    keys = session.scalars(select(TitleVariant.content_key).distinct()).all()
    for key in keys:
        scores = score_variants(session, key)
        if not scores:
            continue
        top = scores[0]
        winners.append(
            {
                "content_key": key,
                "text": top.variant.text,
                "engagement": round(top.avg_engagement, 1),
                "variants": len(scores),
            }
        )
    winners.sort(key=lambda w: w["engagement"], reverse=True)
    return winners


def attribution_confidence_breakdown(session: Session) -> dict:
    """Bucket conversions by attribution confidence."""
    buckets = {"high": 0, "medium": 0, "low": 0}
    for c in session.scalars(select(Conversion)):
        if c.confidence >= 0.7:
            buckets["high"] += 1
        elif c.confidence >= 0.4:
            buckets["medium"] += 1
        else:
            buckets["low"] += 1
    return buckets


def patreon_breakdown(session: Session) -> dict:
    """Churn + tier mix for the Patreon panel."""
    latest = session.scalar(
        select(PatreonMetric).order_by(PatreonMetric.captured_at.desc()).limit(1)
    )
    churn = latest.churn_count if latest else 0
    tier_stmt = (
        select(PatreonTier.title, func.count(PatreonMember.id))
        .join(PatreonMember, PatreonMember.tier_id == PatreonTier.id)
        .where(PatreonMember.status == MemberStatus.ACTIVE)
        .group_by(PatreonTier.title)
        .order_by(func.count(PatreonMember.id).desc())
    )
    tiers = [(title, n) for title, n in session.execute(tier_stmt).all()]
    tier_mix_by_cents: dict = {}
    if latest and latest.tier_mix_json:
        try:
            tier_mix_by_cents = json.loads(latest.tier_mix_json)
        except (ValueError, TypeError):
            tier_mix_by_cents = {}
    return {"churn": churn, "tiers": tiers, "tier_mix_by_cents": tier_mix_by_cents}


def sentiment_overview(session: Session, *, limit: int = 5) -> dict:
    """Rolling average comment sentiment + a few flagged high-value comments."""
    from ..growth.engagement_monitor import high_value_queue

    avg = session.scalar(
        select(func.avg(Comment.sentiment_score)).where(
            Comment.sentiment_score.is_not(None)
        )
    )
    flagged = [
        {
            "author": c.author,
            "body": c.body[:160],
            "sentiment": round(c.sentiment_score or 0.0, 2),
        }
        for c in high_value_queue(session, limit=limit)
    ]
    return {"avg": round(float(avg), 3) if avg is not None else 0.0, "flagged": flagged}
