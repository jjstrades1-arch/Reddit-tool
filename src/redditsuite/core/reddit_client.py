"""PRAW client factory.

Centralizes authentication, the required descriptive user-agent and a single
place tests can patch. PRAW itself handles Reddit's API rate limits; we simply
make sure every call goes through one configured instance.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from .config import Settings, get_settings
from .logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    import praw

log = get_logger(__name__)


def build_reddit(settings: Settings | None = None) -> praw.Reddit:
    """Construct a configured PRAW ``Reddit`` instance.

    Imported lazily so the rest of the suite (and the test-suite) does not
    require ``praw`` unless Reddit access is actually used.
    """
    import praw

    settings = settings or get_settings()
    settings.require_reddit()
    reddit = praw.Reddit(
        client_id=settings.reddit_client_id,
        client_secret=settings.reddit_client_secret,
        username=settings.reddit_username,
        password=settings.reddit_password,
        user_agent=settings.reddit_user_agent,
    )
    # Fail loudly if credentials are read-only when we expect to post.
    reddit.validate_on_submit = True
    return reddit


@lru_cache(maxsize=1)
def get_reddit() -> praw.Reddit:
    """Return a cached PRAW instance."""
    return build_reddit()
