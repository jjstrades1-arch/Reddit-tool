"""The click-logging redirect endpoint.

A reader clicks ``{PUBLIC_BASE_URL}/r/<slug>``; we log the click (with a salted
IP hash, no raw PII) and 302 them to the Patreon destination with UTM params
appended. This is the bridge that makes Reddit-to-Patreon attribution possible.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from ..conversion.cta_links import destination_with_utm
from ..core import repositories as repo
from ..core.db import session_scope
from ..core.logging import get_logger

log = get_logger(__name__)

router = APIRouter()


@router.get("/r/{slug}")
def redirect(slug: str, request: Request) -> RedirectResponse:
    client_ip = request.client.host if request.client else None
    with session_scope() as session:
        link = repo.get_link_by_slug(session, slug)
        if link is None:
            # Unknown slug -> send home rather than error, but log nothing.
            return RedirectResponse(url="/", status_code=302)
        repo.record_click(
            session,
            link,
            ip=client_ip,
            user_agent=request.headers.get("user-agent"),
            referer=request.headers.get("referer"),
        )
        destination = destination_with_utm(link)
    return RedirectResponse(url=destination, status_code=302)
