"""Churn / anomaly alerts.

Compares the two most recent Patreon snapshots and inspects campaign
performance to surface things worth a human's attention: a drop in MRR, a spike
in churn, or a campaign that draws clicks but converts no one. Alerts are
computed on demand (no extra tables) and shown on the dashboard + CLI.
"""

from __future__ import annotations

from dataclasses import dataclass

import typer
from sqlalchemy.orm import Session

from ..core.db import session_scope
from ..core.logging import get_logger
from . import funnel

log = get_logger(__name__)

# Defaults for what counts as "anomalous".
MRR_DROP_PCT = 0.10        # >=10% MRR decline between snapshots
CHURN_SPIKE = 3            # >=3 more former patrons since last snapshot
DEAD_CAMPAIGN_MIN_CLICKS = 5  # clicks needed before "0 conversions" is notable


@dataclass(frozen=True)
class Alert:
    severity: str  # "info" | "warning" | "critical"
    message: str


def detect_anomalies(
    session: Session,
    *,
    mrr_drop_pct: float = MRR_DROP_PCT,
    churn_spike: int = CHURN_SPIKE,
    dead_campaign_min_clicks: int = DEAD_CAMPAIGN_MIN_CLICKS,
) -> list[Alert]:
    """Return the list of currently-firing alerts (empty if all is well)."""
    alerts: list[Alert] = []

    trend = funnel.patreon_trend(session, limit=2)
    if len(trend) >= 2:
        prev, curr = trend[-2], trend[-1]
        if prev.mrr_cents > 0:
            change = (curr.mrr_cents - prev.mrr_cents) / prev.mrr_cents
            if change <= -mrr_drop_pct:
                alerts.append(
                    Alert(
                        "critical",
                        f"MRR dropped {abs(change) * 100:.0f}% "
                        f"(${prev.mrr_cents / 100:.2f} → ${curr.mrr_cents / 100:.2f}).",
                    )
                )
        churn_delta = curr.churn_count - prev.churn_count
        if churn_delta >= churn_spike:
            alerts.append(
                Alert(
                    "warning",
                    f"Churn spike: {churn_delta} patron(s) left since the last snapshot.",
                )
            )

    converted = dict(funnel.conversions_by_campaign(session))
    for name, clicks in funnel.clicks_by_campaign(session):
        if clicks >= dead_campaign_min_clicks and converted.get(name, 0) == 0:
            alerts.append(
                Alert(
                    "warning",
                    f"Campaign '{name}' has {clicks} click(s) but 0 conversions — "
                    f"review the CTA or landing page.",
                )
            )
    return alerts


def _log_alerts() -> None:
    with session_scope() as session:
        for alert in detect_anomalies(session):
            log.warning("[%s] %s", alert.severity.upper(), alert.message)


def register_jobs(scheduler) -> None:
    """Check for anomalies every 6 hours and log any that fire."""
    scheduler.add_job(
        _log_alerts, "interval", hours=6, id="alerts.detect", replace_existing=True
    )


def register_cli(group: typer.Typer) -> None:
    @group.command("alerts")
    def alerts_cmd() -> None:
        """Show churn/anomaly alerts detected from the latest data."""
        with session_scope() as session:
            alerts = detect_anomalies(session)
        if not alerts:
            typer.echo("No anomalies detected. All clear.")
            return
        for a in alerts:
            typer.echo(f"[{a.severity.upper():8s}] {a.message}")
