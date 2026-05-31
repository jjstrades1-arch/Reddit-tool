"""Record Patreon snapshots without an API token.

Two paths, both writing a ``PatreonMetric`` row so the dashboard, funnel and
alerts show real numbers:

* :func:`snapshot_from_public` -- read the public patron count from a creator
  page (best effort; may be blocked).
* :func:`record_manual_snapshot` -- the user types the patron count and monthly
  income they see on their own Patreon dashboard (always works).
"""

from __future__ import annotations

import typer
from sqlalchemy.orm import Session

from ..core.db import session_scope
from ..core.logging import get_logger
from ..core.models import PatreonMetric

log = get_logger(__name__)


def record_manual_snapshot(
    session: Session, *, patron_count: int, mrr_cents: int, churn_count: int = 0
) -> PatreonMetric:
    metric = PatreonMetric(
        patron_count=max(0, patron_count),
        mrr_cents=max(0, mrr_cents),
        churn_count=max(0, churn_count),
    )
    session.add(metric)
    session.flush()
    log.info("Recorded manual Patreon snapshot: %d patrons", metric.patron_count)
    return metric


def snapshot_from_public(session: Session, url: str, *, fetch=None) -> PatreonMetric:
    """Fetch the public patron count and store it as a snapshot."""
    if fetch is None:
        from ..core.patreon_public import fetch_public_campaign

        fetch = fetch_public_campaign
    data = fetch(url)
    return record_manual_snapshot(
        session,
        patron_count=data["patron_count"],
        mrr_cents=data.get("pledge_sum_cents") or 0,
    )


def register_cli(group: typer.Typer) -> None:
    @group.command("patreon-snapshot")
    def patreon_snapshot_cmd(
        patrons: int = typer.Option(..., help="Current patron count."),
        monthly: float = typer.Option(0.0, help="Monthly income in dollars."),
    ) -> None:
        """Record a Patreon snapshot by hand (no token needed)."""
        with session_scope() as session:
            m = record_manual_snapshot(
                session, patron_count=patrons, mrr_cents=int(round(monthly * 100))
            )
        typer.echo(f"Saved: {m.patron_count} patrons, ${m.mrr_cents / 100:.2f} MRR.")
