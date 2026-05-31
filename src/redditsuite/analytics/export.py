"""CSV / JSON exports of the funnel and its underlying metrics.

Dumps the funnel summary plus post, Patreon, and conversion data to flat files
for use in spreadsheets or BI tools. Pure stdlib (``csv`` / ``json``); reuses
the same queries the dashboard renders from.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

import typer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import session_scope
from ..core.logging import get_logger
from ..core.models import Conversion, PatreonMetric, Post, PostMetric
from . import funnel

log = get_logger(__name__)

VALID_FORMATS = ("csv", "json")


def _iso(value) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else value


def _collect(session: Session) -> dict[str, list[dict]]:
    """Build the export datasets as lists of flat dicts."""
    summary = [funnel.summary(session).as_dict()]

    post_metrics: list[dict] = []
    rows = session.execute(
        select(PostMetric, Post).join(Post, PostMetric.post_id == Post.id)
    ).all()
    for metric, post in rows:
        post_metrics.append(
            {
                "post_id": post.id,
                "reddit_id": post.reddit_id,
                "title": post.title,
                "captured_at": _iso(metric.captured_at),
                "score": metric.score,
                "num_comments": metric.num_comments,
                "upvote_ratio": metric.upvote_ratio,
            }
        )

    patreon_metrics = [
        {
            "captured_at": _iso(m.captured_at),
            "patron_count": m.patron_count,
            "mrr_cents": m.mrr_cents,
            "new_patrons": m.new_patrons,
            "churn_count": m.churn_count,
            "tier_mix_json": m.tier_mix_json,
        }
        for m in session.scalars(select(PatreonMetric))
    ]

    conversions = [
        {
            "id": c.id,
            "patreon_member_id": c.patreon_member_id,
            "link_click_id": c.link_click_id,
            "confidence": c.confidence,
            "method": c.method,
            "matched_at": _iso(c.matched_at),
        }
        for c in session.scalars(select(Conversion))
    ]

    return {
        "funnel_summary": summary,
        "post_metrics": post_metrics,
        "patreon_metrics": patreon_metrics,
        "conversions": conversions,
    }


def export_all(session: Session, out_dir: Path, fmt: str = "csv") -> list[Path]:
    """Write all datasets to ``out_dir`` as ``.csv`` or ``.json``. Returns paths."""
    if fmt not in VALID_FORMATS:
        raise ValueError(f"Unsupported format '{fmt}'. Use one of {VALID_FORMATS}.")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for name, rows in _collect(session).items():
        path = out_dir / f"{name}.{fmt}"
        if fmt == "json":
            path.write_text(json.dumps(rows, indent=2, default=str))
        else:
            _write_csv(path, rows)
        written.append(path)
        log.info("Exported %d row(s) to %s", len(rows), path)
    return written


def _write_csv(path: Path, rows: list[dict]) -> None:
    # Union of keys keeps columns stable even if some rows omit a field.
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def register_cli(group: typer.Typer) -> None:
    @group.command("export")
    def export_cmd(
        out: str = typer.Option("./exports", help="Output directory."),
        fmt: str = typer.Option("csv", "--format", help="csv | json"),
    ) -> None:
        """Export funnel + metrics data to CSV or JSON files."""
        with session_scope() as session:
            paths = export_all(session, Path(out), fmt=fmt)
        typer.echo(f"Wrote {len(paths)} file(s) to {out}:")
        for p in paths:
            typer.echo(f"  {p}")
