"""Title / hook A/B helper.

Store multiple title variants for the same chapter (grouped by ``content_key``)
and, once posts have metrics, score which variant performed best. This does not
manipulate anything -- it just helps you learn which hooks resonate.
"""

from __future__ import annotations

from dataclasses import dataclass

import typer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import session_scope
from ..core.logging import get_logger
from ..core.models import Post, PostMetric, TitleVariant

log = get_logger(__name__)


def add_variant(
    session: Session, *, content_key: str, text: str, hypothesis: str | None = None
) -> TitleVariant:
    variant = TitleVariant(content_key=content_key, text=text, hypothesis=hypothesis)
    session.add(variant)
    session.flush()
    return variant


def list_variants(session: Session, content_key: str) -> list[TitleVariant]:
    return session.scalars(
        select(TitleVariant).where(TitleVariant.content_key == content_key)
    ).all()


@dataclass
class VariantScore:
    variant: TitleVariant
    posts: int
    avg_engagement: float


def score_variants(session: Session, content_key: str) -> list[VariantScore]:
    """Rank variants of one chapter by mean engagement of posts that used them."""
    results: list[VariantScore] = []
    for variant in list_variants(session, content_key):
        posts = session.scalars(
            select(Post).where(Post.title_variant_id == variant.id)
        ).all()
        engagements: list[float] = []
        for post in posts:
            metric = session.scalar(
                select(PostMetric)
                .where(PostMetric.post_id == post.id)
                .order_by(PostMetric.captured_at.desc())
                .limit(1)
            )
            if metric:
                engagements.append(float(metric.score) + 2.0 * float(metric.num_comments))
        avg = sum(engagements) / len(engagements) if engagements else 0.0
        results.append(VariantScore(variant=variant, posts=len(posts), avg_engagement=avg))
    results.sort(key=lambda r: r.avg_engagement, reverse=True)
    return results


def register_cli(group: typer.Typer) -> None:
    @group.command("add-title")
    def add_title_cmd(
        content_key: str = typer.Option(..., help="Identifier grouping variants of one chapter."),
        text: str = typer.Option(..., help="The candidate title."),
        hypothesis: str = typer.Option("", help="Why you think this hook works."),
    ) -> None:
        """Register a candidate title variant for a chapter."""
        with session_scope() as session:
            v = add_variant(
                session, content_key=content_key, text=text, hypothesis=hypothesis or None
            )
            typer.echo(f"Added variant id={v.id} under '{content_key}'.")

    @group.command("score-titles")
    def score_titles_cmd(
        content_key: str = typer.Option(..., help="Chapter identifier to score."),
    ) -> None:
        """Show which title variant performed best."""
        with session_scope() as session:
            scores = score_variants(session, content_key)
            if not scores:
                typer.echo("No variants found.")
                return
            for s in scores:
                typer.echo(
                    f"  [{s.avg_engagement:7.1f}] ({s.posts} post(s)) {s.variant.text!r}"
                )
