"""CTA + UTM link manager.

Generates trackable short links (served by ``services/utm_redirect``) that carry
UTM parameters to your Patreon, plus a small library of tasteful call-to-action
snippets you can append to posts. Standard marketing analytics -- no PII beyond a
salted IP hash on click.
"""

from __future__ import annotations

from urllib.parse import urlencode

import typer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core import repositories as repo
from ..core.config import get_settings
from ..core.db import session_scope
from ..core.logging import get_logger
from ..core.models import CTASnippet, UTMLink

log = get_logger(__name__)


def tracked_url(link: UTMLink) -> str:
    """The short, trackable URL a reader clicks (hits our redirect service)."""
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/r/{link.slug}"


def destination_with_utm(link: UTMLink) -> str:
    """The final Patreon URL with UTM params appended (used by the redirector)."""
    params = {
        k: v
        for k, v in {
            "utm_source": link.source,
            "utm_medium": link.medium,
            "utm_campaign": link.campaign,
            "utm_content": link.content,
        }.items()
        if v
    }
    if not params:
        return link.destination_url
    sep = "&" if "?" in link.destination_url else "?"
    return f"{link.destination_url}{sep}{urlencode(params)}"


def create_link(
    session: Session,
    *,
    destination_url: str,
    campaign: str | None = None,
    content: str | None = None,
    post_id: int | None = None,
) -> UTMLink:
    post = repo_post(session, post_id)
    link = repo.create_utm_link(
        session,
        destination_url=destination_url,
        campaign=campaign,
        content=content,
        post=post,
    )
    return link


def repo_post(session: Session, post_id: int | None):
    if post_id is None:
        return None
    from ..core.models import Post

    return session.get(Post, post_id)


def add_cta(session: Session, *, text: str, tone: str | None = None) -> CTASnippet:
    snippet = CTASnippet(text=text, tone=tone)
    session.add(snippet)
    session.flush()
    return snippet


def active_ctas(session: Session) -> list[CTASnippet]:
    return session.scalars(select(CTASnippet).where(CTASnippet.active.is_(True))).all()


def register_cli(group: typer.Typer) -> None:
    @group.command("cta-create")
    def cta_create_cmd(
        destination: str = typer.Option(..., help="Patreon URL to send readers to."),
        campaign: str = typer.Option("", help="Campaign label, e.g. chapter-12."),
        content: str = typer.Option("", help="Content label, e.g. footer-cta."),
        post_id: int = typer.Option(None, help="Local post id to attribute clicks to."),
    ) -> None:
        """Create a trackable CTA link to your Patreon."""
        with session_scope() as session:
            link = create_link(
                session,
                destination_url=destination,
                campaign=campaign or None,
                content=content or None,
                post_id=post_id,
            )
            typer.echo(f"Tracked link: {tracked_url(link)}")
            typer.echo(f"  -> {destination_with_utm(link)}")

    @group.command("cta-snippet")
    def cta_snippet_cmd(
        text: str = typer.Option(..., help="CTA snippet text."),
        tone: str = typer.Option("", help="Optional tone label."),
    ) -> None:
        """Save a reusable call-to-action snippet."""
        with session_scope() as session:
            s = add_cta(session, text=text, tone=tone or None)
            typer.echo(f"Saved CTA snippet id={s.id}.")
