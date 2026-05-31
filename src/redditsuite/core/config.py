"""Typed configuration loaded from the environment / ``.env``.

A single :class:`Settings` object is the source of truth for every credential
and tunable in the suite. Validation happens at load time so the app fails fast
with a clear message when a required secret is missing, rather than deep inside
an API call.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration for the suite, sourced from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Core ---
    database_url: str = "sqlite:///data/redditsuite.db"
    home_subreddit: str = "YourStorySub"
    public_base_url: str = "http://localhost:8000"

    # --- Reddit API ---
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_username: str = ""
    reddit_password: str = ""
    reddit_user_agent: str = "redditsuite/0.1"

    # --- Patreon API ---
    patreon_client_id: str = ""
    patreon_client_secret: str = ""
    patreon_access_token: str = ""
    patreon_refresh_token: str = ""

    # --- Compliance guardrails ---
    min_post_spacing_minutes: int = 180
    max_posts_per_day: int = 3
    default_early_access_hours: int = 48

    # --- Dashboard ---
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8000

    # --- Privacy ---
    click_hash_salt: str = "change-me"

    # Optional tier-weighted voting (off by default -- one member, one vote).
    enable_tier_weighted_votes: bool = Field(default=False)

    def require_reddit(self) -> None:
        """Raise if Reddit credentials are incomplete."""
        missing = [
            name
            for name in (
                "reddit_client_id",
                "reddit_client_secret",
                "reddit_username",
                "reddit_password",
            )
            if not getattr(self, name)
        ]
        if missing:
            raise RuntimeError(
                "Missing Reddit credentials: "
                + ", ".join(m.upper() for m in missing)
                + ". Set them in your .env (see .env.example)."
            )

    def require_patreon(self) -> None:
        """Raise if Patreon credentials are incomplete."""
        if not self.patreon_access_token:
            raise RuntimeError(
                "Missing PATREON_ACCESS_TOKEN. Set it in your .env "
                "(see .env.example)."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""
    return Settings()
