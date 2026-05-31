"""The dashboard + control-panel FastAPI app.

Beyond the read-only funnel view, this serves click-through forms for the
everyday workflow -- scheduling chapters, making Patreon links, running member
polls, handling comments, and one-click tools -- so the whole suite is usable
without the command line. It also hosts the UTM redirect endpoint in the same
process, so click logging and reporting are one unified service.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ...core import repositories as repo
from ...core.config import get_settings
from ...core.db import session_scope
from ...core.models import CTASnippet, Poll, PollKind, PollStatus, Post
from ...services.utm_redirect import router as redirect_router
from .. import alerts, funnel
from ..collectors import collect_post_metrics, sync_patreon
from ..export import export_all

TEMPLATES_DIR = Path(__file__).parent / "templates"
_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def create_app() -> FastAPI:
    app = FastAPI(title="Reddit-Tool Suite")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.include_router(redirect_router)

    def render(request: Request, name: str, active: str, **ctx) -> HTMLResponse:
        """Render a template, injecting nav state and flash messages."""
        ctx.update(
            {
                "active": active,
                "msg": request.query_params.get("msg"),
                "error": request.query_params.get("error"),
                "home_sub": get_settings().home_subreddit,
            }
        )
        return templates.TemplateResponse(request, name, ctx)

    def back(path: str, *, msg: str | None = None, error: str | None = None):
        from urllib.parse import urlencode

        params = {k: v for k, v in {"msg": msg, "error": error}.items() if v}
        url = f"{path}?{urlencode(params)}" if params else path
        return RedirectResponse(url=url, status_code=303)

    # ----------------------------------------------------------------- #
    # Dashboard
    # ----------------------------------------------------------------- #
    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        with session_scope() as session:
            sub = repo.get_home_subreddit(session)
            trend = funnel.patreon_trend(session)
            ctx = {
                "s": funnel.summary(session),
                "campaigns": funnel.clicks_by_campaign(session),
                "heatmap": funnel.optimal_window_grid(session, sub.id),
                "ab": funnel.ab_winners(session),
                "confidence": funnel.attribution_confidence_breakdown(session),
                "patreon": funnel.patreon_breakdown(session),
                "sentiment": funnel.sentiment_overview(session),
                "alerts": alerts.detect_anomalies(session),
                "days": _DAYS,
                "trend_json": json.dumps(
                    {
                        "labels": [m.captured_at.strftime("%m-%d") for m in trend],
                        "mrr": [round(m.mrr_cents / 100, 2) for m in trend],
                        "patrons": [m.patron_count for m in trend],
                    }
                ),
            }
        return render(request, "index.html", "dashboard", **ctx)

    @app.get("/api/funnel")
    def api_funnel():
        with session_scope() as session:
            return JSONResponse(funnel.summary(session).as_dict())

    # ----------------------------------------------------------------- #
    # Chapters
    # ----------------------------------------------------------------- #
    @app.get("/chapters", response_class=HTMLResponse)
    def chapters(request: Request):
        from sqlalchemy import select

        with session_scope() as session:
            posts = session.scalars(
                select(Post).order_by(Post.scheduled_at.desc().nullslast(), Post.id.desc())
            ).all()
            return render(request, "chapters.html", "chapters", posts=posts)

    @app.post("/chapters/schedule")
    def chapters_schedule(
        title: str = Form(...),
        when: str = Form(...),
        body: str = Form(""),
        chapter: str = Form(""),
        early_access_hours: str = Form("48"),
    ):
        from ...growth.post_scheduler import schedule_chapter

        try:
            when_dt = datetime.fromisoformat(when)
        except ValueError:
            return back("/chapters", error="Couldn't read that date/time.")
        with session_scope() as session:
            schedule_chapter(
                session,
                title=title,
                body=body or None,
                chapter_no=int(chapter) if chapter.strip() else None,
                when=when_dt,
                early_access_hours=int(early_access_hours) if early_access_hours.strip() else None,
            )
        return back("/chapters", msg=f"Scheduled “{title}” for {when_dt} UTC.")

    @app.post("/chapters/run-due")
    def chapters_run_due():
        from ...growth.post_scheduler import run_due_posts

        try:
            count = run_due_posts()
        except Exception as exc:  # noqa: BLE001 - surface a friendly message
            return back("/chapters", error=f"Couldn't post: {exc}")
        return back("/chapters", msg=f"Posted {count} due chapter(s).")

    # ----------------------------------------------------------------- #
    # Patreon links
    # ----------------------------------------------------------------- #
    @app.get("/links", response_class=HTMLResponse)
    def links(request: Request):
        from sqlalchemy import select

        from ...conversion.cta_links import tracked_url
        from ...core.models import UTMLink

        with session_scope() as session:
            rows = []
            for link in session.scalars(select(UTMLink).order_by(UTMLink.id.desc())):
                rows.append(
                    {
                        "campaign": link.campaign,
                        "tracked": tracked_url(link),
                        "destination": link.destination_url,
                        "clicks": len(link.clicks),
                    }
                )
            snippets = session.scalars(
                select(CTASnippet).where(CTASnippet.active.is_(True))
            ).all()
        return render(
            request,
            "links.html",
            "links",
            links=rows,
            snippets=snippets,
            default_patreon="",
        )

    @app.post("/links/create")
    def links_create(
        destination: str = Form(...),
        campaign: str = Form(""),
        content: str = Form(""),
    ):
        from ...conversion.cta_links import create_link, tracked_url

        with session_scope() as session:
            link = create_link(
                session,
                destination_url=destination,
                campaign=campaign or None,
                content=content or None,
            )
            url = tracked_url(link)
        return back("/links", msg=f"Link ready — paste this into Reddit: {url}")

    @app.post("/links/snippet")
    def links_snippet(text: str = Form(...)):
        from ...conversion.cta_links import add_cta

        with session_scope() as session:
            add_cta(session, text=text)
        return back("/links", msg="Snippet saved.")

    # ----------------------------------------------------------------- #
    # Polls
    # ----------------------------------------------------------------- #
    @app.get("/polls", response_class=HTMLResponse)
    def polls_list(request: Request):
        from sqlalchemy import select

        with session_scope() as session:
            rows = []
            for poll in session.scalars(select(Poll).order_by(Poll.id.desc())):
                rows.append(
                    {"poll": poll, "votes": sum(o.vote_count for o in poll.options)}
                )
            return render(request, "polls.html", "polls", polls=rows)

    @app.post("/polls/create")
    def polls_create(
        question: str = Form(...),
        options: str = Form(...),
        kind: str = Form("plot"),
    ):
        from ...conversion.polls import create_poll

        opts = [line.strip() for line in options.splitlines() if line.strip()]
        if len(opts) < 2:
            return back("/polls", error="Please enter at least two options (one per line).")
        with session_scope() as session:
            poll = create_poll(session, question=question, options=opts, kind=PollKind(kind))
            pid = poll.id
        return back(f"/polls/{pid}", msg="Poll created. Record votes below.")

    @app.get("/polls/{poll_id}", response_class=HTMLResponse)
    def poll_detail(request: Request, poll_id: int):
        from ...conversion.polls import tally
        from ...conversion.teaser_gen import draft_teaser

        with session_scope() as session:
            poll = session.get(Poll, poll_id)
            if not poll:
                return back("/polls", error="That poll no longer exists.")
            results = tally(session, poll)
            teaser = None
            winner_label = "No clear winner"
            if poll.status == PollStatus.CLOSED:
                teaser = draft_teaser(session, poll)
                if results and results[0][1] > 0:
                    winner_label = results[0][0].label
            return render(
                request,
                "poll_detail.html",
                "polls",
                poll=poll,
                results=results,
                teaser=teaser,
                winner_label=winner_label,
            )

    @app.post("/polls/{poll_id}/vote")
    def poll_vote(poll_id: int, option_id: int = Form(...), member: str = Form("")):
        from ...conversion.polls import VoteError, cast_vote
        from ...core.models import PollOption

        with session_scope() as session:
            poll = session.get(Poll, poll_id)
            option = session.get(PollOption, option_id)
            if not poll or not option:
                return back("/polls", error="Poll or option not found.")
            member_key = member.strip() or f"web-{uuid4().hex[:12]}"
            m, _ = repo.upsert_member(
                session, patreon_member_id=member_key, full_name=member.strip() or None
            )
            try:
                cast_vote(session, poll=poll, member=m, option=option)
            except VoteError as exc:
                return back(f"/polls/{poll_id}", error=str(exc))
        return back(f"/polls/{poll_id}", msg="Vote recorded.")

    @app.post("/polls/{poll_id}/close")
    def poll_close(poll_id: int):
        from ...conversion.polls import close_poll

        with session_scope() as session:
            poll = session.get(Poll, poll_id)
            if not poll:
                return back("/polls", error="That poll no longer exists.")
            winner = close_poll(session, poll)
        if winner:
            return back(f"/polls/{poll_id}", msg=f"Poll closed. Members chose: {winner.label}")
        return back(f"/polls/{poll_id}", msg="Poll closed (tie or no votes).")

    # ----------------------------------------------------------------- #
    # Comments
    # ----------------------------------------------------------------- #
    @app.get("/comments", response_class=HTMLResponse)
    def comments(request: Request):
        from ...growth.engagement_monitor import draft_reply, high_value_queue

        with session_scope() as session:
            queue = []
            for c in high_value_queue(session):
                queue.append(
                    {
                        "id": c.id,
                        "author": c.author,
                        "score": c.score,
                        "sentiment": c.sentiment_score,
                        "body": c.body,
                        "draft": draft_reply(c),
                    }
                )
            return render(request, "comments.html", "comments", queue=queue)

    @app.post("/comments/{comment_id}/handled")
    def comment_handled(comment_id: int):
        from ...core.models import Comment

        with session_scope() as session:
            c = session.get(Comment, comment_id)
            if c:
                c.handled = True
        return back("/comments", msg="Marked handled.")

    # ----------------------------------------------------------------- #
    # Tools
    # ----------------------------------------------------------------- #
    @app.get("/tools", response_class=HTMLResponse)
    def tools(request: Request):
        from sqlalchemy import select

        from ...core.compliance import check_cross_promo_cadence
        from ...core.models import Subreddit

        with session_scope() as session:
            active_alerts = alerts.detect_anomalies(session)
            targets = []
            for sub in session.scalars(
                select(Subreddit).where(Subreddit.is_home.is_(False))
            ):
                decision = check_cross_promo_cadence(sub)
                targets.append(
                    {
                        "name": sub.name,
                        "min_days_between_promos": sub.min_days_between_promos,
                        "ok": decision.allowed,
                        "reason": decision.reason,
                    }
                )
            return render(request, "tools.html", "tools", alerts=active_alerts, targets=targets)

    @app.post("/tools/collect")
    def tools_collect():
        try:
            with session_scope() as session:
                n = collect_post_metrics(session)
                m = sync_patreon(session)
            return back("/tools", msg=f"Refreshed {n} post(s); {m.patron_count} patrons synced.")
        except Exception as exc:  # noqa: BLE001
            return back("/tools", error=f"Couldn't refresh (check your keys): {exc}")

    @app.post("/tools/analyze-timing")
    def tools_analyze_timing():
        from ...growth.timing_analyzer import compute_windows

        with session_scope() as session:
            sub = repo.get_home_subreddit(session)
            windows = compute_windows(session, sub.id)
        return back("/tools", msg=f"Analyzed timing across {len(windows)} window(s).")

    @app.post("/tools/export")
    def tools_export(fmt: str = Form("csv")):
        try:
            with session_scope() as session:
                paths = export_all(session, Path("exports"), fmt=fmt)
            return back("/tools", msg=f"Exported {len(paths)} file(s) to the 'exports' folder.")
        except ValueError as exc:
            return back("/tools", error=str(exc))

    @app.post("/tools/add-target")
    def tools_add_target(
        name: str = Form(...),
        rules: str = Form(""),
        min_days: str = Form(""),
    ):
        from ...growth.cross_promo import add_target

        with session_scope() as session:
            add_target(
                session,
                name=name,
                rules_notes=rules or None,
                min_days_between_promos=int(min_days) if min_days.strip() else None,
            )
        return back("/tools", msg=f"Saved r/{name}.")

    # ----------------------------------------------------------------- #
    # Settings (edit .env from the browser)
    # ----------------------------------------------------------------- #
    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request):
        cfg = get_settings()
        cur = {
            "home_subreddit": cfg.home_subreddit,
            "public_base_url": cfg.public_base_url,
            "reddit_client_id": cfg.reddit_client_id,
            "reddit_username": cfg.reddit_username,
            "reddit_user_agent": cfg.reddit_user_agent,
        }
        which = {
            "reddit": bool(cfg.reddit_client_id and cfg.reddit_client_secret),
            "reddit_secret": bool(cfg.reddit_client_secret),
            "reddit_password": bool(cfg.reddit_password),
            "patreon": bool(cfg.patreon_access_token),
        }
        return render(request, "settings.html", "settings", cur=cur, set=which)

    @app.post("/settings/save")
    def settings_save(
        home_subreddit: str = Form(""),
        public_base_url: str = Form(""),
        reddit_client_id: str = Form(""),
        reddit_client_secret: str = Form(""),
        reddit_username: str = Form(""),
        reddit_password: str = Form(""),
        reddit_user_agent: str = Form(""),
        patreon_access_token: str = Form(""),
    ):
        from ...core.config import get_settings as _gs
        from ...core.envfile import update_env

        # Plain fields: update when provided. Secret fields: only when non-blank
        # (blank means "keep the saved one").
        candidates = {
            "HOME_SUBREDDIT": home_subreddit,
            "PUBLIC_BASE_URL": public_base_url,
            "REDDIT_CLIENT_ID": reddit_client_id,
            "REDDIT_USERNAME": reddit_username,
            "REDDIT_USER_AGENT": reddit_user_agent,
            "REDDIT_CLIENT_SECRET": reddit_client_secret,
            "REDDIT_PASSWORD": reddit_password,
            "PATREON_ACCESS_TOKEN": patreon_access_token,
        }
        updates = {k: v.strip() for k, v in candidates.items() if v.strip()}
        if updates:
            update_env(updates)
            _gs.cache_clear()  # pick up the new values on the next request
        return back("/settings", msg="Settings saved.")

    return app


app = create_app()
