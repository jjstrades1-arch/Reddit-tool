"""Compliant cross-promotion helper -- an ASSISTANT, never an auto-poster.

Larger writing subs (r/WritingPrompts, r/HFY, r/nosleep, ...) each have their own
self-promotion rules and cadence. This tool stores those rules and *warns* you
when a promo would break them. It never submits to another subreddit on your
behalf; doing so automatically is how accounts get banned for spam.
"""

from __future__ import annotations

import typer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core import repositories as repo
from ..core.compliance import check_cross_promo_cadence
from ..core.db import session_scope
from ..core.logging import get_logger
from ..core.models import Subreddit, utcnow

log = get_logger(__name__)


def add_target(
    session: Session,
    *,
    name: str,
    rules_notes: str | None = None,
    self_promo_ratio: int | None = None,
    min_days_between_promos: int | None = None,
) -> Subreddit:
    """Register or update a cross-promo target subreddit's rules."""
    sub = repo.get_or_create_subreddit(session, name)
    if rules_notes is not None:
        sub.rules_notes = rules_notes
    if self_promo_ratio is not None:
        sub.self_promo_ratio = self_promo_ratio
    if min_days_between_promos is not None:
        sub.min_days_between_promos = min_days_between_promos
    session.flush()
    return sub


def check_target(session: Session, name: str):
    """Return a GuardDecision for promoting to ``name`` right now."""
    sub = session.scalar(select(Subreddit).where(Subreddit.name == name))
    if sub is None:
        raise ValueError(f"Unknown target subreddit '{name}'. Add it first.")
    return check_cross_promo_cadence(sub)


def record_manual_promo(session: Session, name: str) -> None:
    """Record that *you* (a human) posted a promo to ``name``, updating cadence."""
    sub = session.scalar(select(Subreddit).where(Subreddit.name == name))
    if sub is None:
        raise ValueError(f"Unknown target subreddit '{name}'.")
    sub.last_promo_at = utcnow()
    session.flush()


def register_cli(group: typer.Typer) -> None:
    @group.command("add-target")
    def add_target_cmd(
        name: str = typer.Option(..., help="Target subreddit (no r/ prefix)."),
        rules: str = typer.Option("", help="Free-text notes on the sub's promo rules."),
        ratio: int = typer.Option(None, help="Allowed self-promo ratio, e.g. 10 means 1-in-10."),
        min_days: int = typer.Option(None, help="Minimum days between self-promos."),
    ) -> None:
        """Register a cross-promo target and its rules."""
        with session_scope() as session:
            add_target(
                session,
                name=name,
                rules_notes=rules or None,
                self_promo_ratio=ratio,
                min_days_between_promos=min_days,
            )
            typer.echo(f"Saved target r/{name}.")

    @group.command("check-target")
    def check_target_cmd(
        name: str = typer.Option(..., help="Target subreddit to check."),
    ) -> None:
        """Check whether a promo to this sub would respect its cadence (assist only)."""
        with session_scope() as session:
            decision = check_target(session, name)
            if decision.allowed:
                typer.echo(
                    f"OK to consider a (manual) promo to r/{name}. Follow their rules."
                )
            else:
                typer.echo(f"HOLD: {decision.reason}")

    @group.command("log-promo")
    def log_promo_cmd(
        name: str = typer.Option(..., help="Sub you manually promoted to."),
    ) -> None:
        """Record a promo you posted manually, to keep cadence tracking honest."""
        with session_scope() as session:
            record_manual_promo(session, name)
            typer.echo(f"Recorded manual promo to r/{name}.")
