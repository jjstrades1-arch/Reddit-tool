"""Root Typer CLI.

Exposes one command group per funnel stage. Each tool module registers its own
subcommands via ``register_cli`` so this file never becomes a monolith.

    redditsuite db init
    redditsuite growth schedule --title "Ch. 12" --when 2026-06-01T17:00
    redditsuite conversion cta-create --destination https://patreon.com/...
    redditsuite analytics dashboard
"""

from __future__ import annotations

import importlib

import typer

from .core.logging import get_logger

log = get_logger(__name__)

app = typer.Typer(
    help="Reddit-Tool Suite: grow a story sub, convert readers to Patreon.",
    no_args_is_help=True,
)

growth_app = typer.Typer(help="Growth: reach more Reddit readers.", no_args_is_help=True)
conversion_app = typer.Typer(
    help="Conversion: turn readers into Patreon members.", no_args_is_help=True
)
analytics_app = typer.Typer(help="Analytics: measure the whole funnel.", no_args_is_help=True)
db_app = typer.Typer(help="Database management.", no_args_is_help=True)

app.add_typer(growth_app, name="growth")
app.add_typer(conversion_app, name="conversion")
app.add_typer(analytics_app, name="analytics")
app.add_typer(db_app, name="db")


#: (module, target typer group) -- each module exposes ``register_cli(group)``.
_CLI_MODULES = {
    growth_app: (
        "redditsuite.growth.post_scheduler",
        "redditsuite.growth.timing_analyzer",
        "redditsuite.growth.ab_titles",
        "redditsuite.growth.cross_promo",
        "redditsuite.growth.engagement_monitor",
    ),
    conversion_app: (
        "redditsuite.conversion.cta_links",
        "redditsuite.conversion.attribution",
        "redditsuite.conversion.polls",
        "redditsuite.conversion.teaser_gen",
    ),
    analytics_app: (
        "redditsuite.analytics.collectors",
        "redditsuite.analytics.alerts",
        "redditsuite.analytics.export",
    ),
}


def _wire_tool_commands() -> None:
    for group, modules in _CLI_MODULES.items():
        for mod_name in modules:
            module = importlib.import_module(mod_name)
            register = getattr(module, "register_cli", None)
            if callable(register):
                register(group)


# --------------------------------------------------------------------------- #
# db group
# --------------------------------------------------------------------------- #
@db_app.command("init")
def db_init() -> None:
    """Create the SQLite database and all tables, and seed the home subreddit."""
    from .core import repositories as repo
    from .core.db import init_db, session_scope

    init_db()
    with session_scope() as session:
        sub = repo.get_home_subreddit(session)
        typer.echo(f"Database ready. Home subreddit: r/{sub.name}")


@db_app.command("status")
def db_status() -> None:
    """Show row counts for the main tables."""
    from sqlalchemy import func, select

    from .core.db import session_scope
    from .core.models import Conversion, LinkClick, PatreonMember, Post, UTMLink

    with session_scope() as session:
        for model in (Post, UTMLink, LinkClick, PatreonMember, Conversion):
            n = session.scalar(select(func.count()).select_from(model)) or 0
            typer.echo(f"  {model.__tablename__:18s} {n}")


# --------------------------------------------------------------------------- #
# analytics: dashboard + run
# --------------------------------------------------------------------------- #
@analytics_app.command("dashboard")
def dashboard() -> None:
    """Run the funnel dashboard + click-redirect service."""
    import uvicorn

    from .core.config import get_settings

    settings = get_settings()
    uvicorn.run(
        "redditsuite.analytics.dashboard.app:app",
        host=settings.dashboard_host,
        port=settings.dashboard_port,
    )


@analytics_app.command("funnel")
def funnel_cmd() -> None:
    """Print the funnel summary to the terminal."""
    from .analytics import funnel as funnel_mod
    from .core.db import session_scope

    with session_scope() as session:
        s = funnel_mod.summary(session)
    typer.echo(
        f"posts={s.posts} upvotes={s.total_upvotes} clicks={s.clicks} "
        f"conversions={s.conversions} patrons={s.active_patrons} "
        f"MRR=${s.mrr_cents / 100:.2f}"
    )


@app.command("run")
def run() -> None:
    """Start the background scheduler (posting, collection, attribution)."""
    import time

    from .core.scheduler import build_scheduler

    scheduler = build_scheduler()
    scheduler.start()
    typer.echo("Scheduler started. Ctrl-C to stop.")
    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):  # pragma: no cover
        scheduler.shutdown()


# Wire tool subcommands at import time so `redditsuite --help` shows them all.
_wire_tool_commands()


if __name__ == "__main__":  # pragma: no cover
    app()
