"""The dashboard FastAPI app.

It serves the funnel view and, in the same process, the UTM redirect endpoint --
so click logging and reporting are one unified service.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from ...core.db import session_scope
from ...services.utm_redirect import router as redirect_router
from .. import funnel

TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app() -> FastAPI:
    app = FastAPI(title="Reddit-Tool Suite Dashboard")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.include_router(redirect_router)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        with session_scope() as session:
            summary = funnel.summary(session)
            campaigns = funnel.clicks_by_campaign(session)
            trend = funnel.patreon_trend(session)
            trend_data = {
                "labels": [m.captured_at.strftime("%m-%d") for m in trend],
                "mrr": [round(m.mrr_cents / 100, 2) for m in trend],
                "patrons": [m.patron_count for m in trend],
            }
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "s": summary,
                "campaigns": campaigns,
                "trend_json": json.dumps(trend_data),
            },
        )

    @app.get("/api/funnel")
    def api_funnel():
        with session_scope() as session:
            return JSONResponse(funnel.summary(session).as_dict())

    return app


app = create_app()
