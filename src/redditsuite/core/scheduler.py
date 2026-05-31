"""APScheduler setup and a tiny job-registry the tools plug into.

Each tool module may expose ``register_jobs(scheduler)``; ``build_scheduler``
discovers and calls them so adding a recurring job never means editing this file.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from .logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from apscheduler.schedulers.background import BackgroundScheduler

log = get_logger(__name__)

#: Modules that may register recurring jobs.
_JOB_MODULES = (
    "redditsuite.growth.post_scheduler",
    "redditsuite.analytics.collectors",
    "redditsuite.conversion.attribution",
)


def build_scheduler() -> BackgroundScheduler:
    """Construct a scheduler and let each tool register its jobs."""
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(timezone="UTC")
    for mod_name in _JOB_MODULES:
        try:
            module = importlib.import_module(mod_name)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("Could not import %s for jobs: %s", mod_name, exc)
            continue
        register = getattr(module, "register_jobs", None)
        if callable(register):
            register(scheduler)
            log.info("Registered jobs from %s", mod_name)
    return scheduler
