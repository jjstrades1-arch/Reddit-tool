"""Conversion attribution: map Reddit-sourced clicks to Patreon signups.

A new patron is attributed to the most recent click that happened within a
lookback window before they pledged. This is a heuristic -- we record a
``confidence`` and ``method`` so the dashboard can show how firm each match is.
"""

from __future__ import annotations

from datetime import timedelta

import typer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core import repositories as repo
from ..core.db import session_scope
from ..core.logging import get_logger
from ..core.models import Conversion, LinkClick, PatreonMember

log = get_logger(__name__)

#: Clicks older than this before a pledge are not considered the cause.
DEFAULT_LOOKBACK = timedelta(days=7)


def _already_attributed(session: Session, member: PatreonMember) -> bool:
    return bool(
        session.scalar(
            select(Conversion).where(Conversion.patreon_member_id == member.id)
        )
    )


def _unclaimed_click_before(
    session: Session, before, lookback: timedelta
) -> LinkClick | None:
    """Most recent click in the window that is not yet tied to a conversion."""
    window_start = before - lookback
    stmt = (
        select(LinkClick)
        .outerjoin(Conversion, Conversion.link_click_id == LinkClick.id)
        .where(Conversion.id.is_(None))
        .where(LinkClick.clicked_at <= before)
        .where(LinkClick.clicked_at >= window_start)
        .order_by(LinkClick.clicked_at.desc())
        .limit(1)
    )
    return session.scalar(stmt)


def attribute_member(
    session: Session, member: PatreonMember, *, lookback: timedelta = DEFAULT_LOOKBACK
) -> Conversion | None:
    """Attribute a single member to a click, if a plausible one exists."""
    if member.started_at is None or _already_attributed(session, member):
        return None
    click = _unclaimed_click_before(session, member.started_at, lookback)
    if click is None:
        return None
    # Confidence decays with the gap between click and pledge.
    gap = member.started_at - click.clicked_at
    confidence = max(0.1, 1.0 - gap / lookback)
    conversion = repo.record_conversion(
        session,
        member=member,
        link_click=click,
        confidence=round(confidence, 3),
        method="last_click",
    )
    log.info(
        "Attributed member %s to click %s (confidence %.2f)",
        member.patreon_member_id,
        click.id,
        confidence,
    )
    return conversion


def run_attribution(*, lookback: timedelta = DEFAULT_LOOKBACK) -> int:
    """Attribute all not-yet-attributed members. Returns count newly matched."""
    matched = 0
    with session_scope() as session:
        members = session.scalars(
            select(PatreonMember).where(PatreonMember.started_at.is_not(None))
        ).all()
        for member in members:
            if attribute_member(session, member, lookback=lookback):
                matched += 1
    return matched


def register_jobs(scheduler) -> None:
    """Re-run attribution hourly as new members and clicks arrive."""
    scheduler.add_job(
        run_attribution,
        "interval",
        hours=1,
        id="attribution.run_attribution",
        replace_existing=True,
    )


def register_cli(group: typer.Typer) -> None:
    @group.command("attribute")
    def attribute_cmd() -> None:
        """Match unattributed Patreon members to Reddit clicks."""
        count = run_attribution()
        typer.echo(f"Attributed {count} member(s) to Reddit clicks.")
