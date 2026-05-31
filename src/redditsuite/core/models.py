"""All ORM models for the suite, kept in one module so relationships resolve.

The attribution join is the spine of the funnel::

    posts -> utm_links -> link_clicks -> conversions
          -> patreon_members -> patreon_metrics
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    """Timezone-aware UTC now (stored naive-UTC for SQLite friendliness)."""
    return datetime.now(UTC).replace(tzinfo=None)


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class PostStatus(str, enum.Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    POSTED = "posted"
    FAILED = "failed"


class PollKind(str, enum.Enum):
    PLOT = "plot"            # plot-direction branch
    NAMING = "naming"        # character name / fate
    SUGGESTION = "suggestion"  # free-form suggestion bucket promoted to a poll


class PollStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"


class SuggestionStatus(str, enum.Enum):
    NEW = "new"
    SHORTLISTED = "shortlisted"
    PROMOTED = "promoted"
    REJECTED = "rejected"


class MemberStatus(str, enum.Enum):
    ACTIVE = "active"
    FORMER = "former"
    DECLINED = "declined"


# --------------------------------------------------------------------------- #
# Growth / content
# --------------------------------------------------------------------------- #
class Subreddit(Base):
    __tablename__ = "subreddits"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    is_home: Mapped[bool] = mapped_column(Boolean, default=False)
    # Cross-promo metadata (assist-only; see growth/cross_promo.py).
    rules_notes: Mapped[str | None] = mapped_column(Text, default=None)
    self_promo_ratio: Mapped[int | None] = mapped_column(Integer, default=None)
    min_days_between_promos: Mapped[int | None] = mapped_column(Integer, default=None)
    last_promo_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    posts: Mapped[list[Post]] = relationship(back_populates="subreddit")


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    reddit_id: Mapped[str | None] = mapped_column(String(32), unique=True, default=None)
    subreddit_id: Mapped[int] = mapped_column(ForeignKey("subreddits.id"))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str | None] = mapped_column(Text, default=None)
    chapter_no: Mapped[int | None] = mapped_column(Integer, default=None)
    status: Mapped[PostStatus] = mapped_column(
        Enum(PostStatus), default=PostStatus.DRAFT, index=True
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    permalink: Mapped[str | None] = mapped_column(String(400), default=None)
    title_variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("title_variants.id"), default=None
    )
    # Members get the chapter this many hours before the public post is allowed.
    early_access_until: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    subreddit: Mapped[Subreddit] = relationship(back_populates="posts")
    metrics: Mapped[list[PostMetric]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )
    comments: Mapped[list[Comment]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )
    utm_links: Mapped[list[UTMLink]] = relationship(back_populates="post")
    title_variant: Mapped[TitleVariant | None] = relationship()


class TitleVariant(Base):
    __tablename__ = "title_variants"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Groups variants of the same chapter so they can be compared.
    content_key: Mapped[str] = mapped_column(String(120), index=True)
    text: Mapped[str] = mapped_column(String(300))
    hypothesis: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PostMetric(Base):
    __tablename__ = "post_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    num_comments: Mapped[int] = mapped_column(Integer, default=0)
    upvote_ratio: Mapped[float | None] = mapped_column(Float, default=None)
    views: Mapped[int | None] = mapped_column(Integer, default=None)

    post: Mapped[Post] = relationship(back_populates="metrics")


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    reddit_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), index=True)
    author: Mapped[str | None] = mapped_column(String(64), default=None)
    body: Mapped[str] = mapped_column(Text)
    score: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    sentiment_score: Mapped[float | None] = mapped_column(Float, default=None)
    is_flagged_high_value: Mapped[bool] = mapped_column(Boolean, default=False)
    handled: Mapped[bool] = mapped_column(Boolean, default=False)

    post: Mapped[Post] = relationship(back_populates="comments")


class OptimalWindow(Base):
    __tablename__ = "optimal_windows"
    __table_args__ = (UniqueConstraint("subreddit_id", "weekday", "hour"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    subreddit_id: Mapped[int] = mapped_column(ForeignKey("subreddits.id"), index=True)
    weekday: Mapped[int] = mapped_column(Integer)  # 0 = Monday
    hour: Mapped[int] = mapped_column(Integer)      # 0-23, UTC
    engagement_index: Mapped[float] = mapped_column(Float, default=0.0)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# --------------------------------------------------------------------------- #
# Conversion
# --------------------------------------------------------------------------- #
class CTASnippet(Base):
    __tablename__ = "cta_snippets"

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    tone: Mapped[str | None] = mapped_column(String(40), default=None)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UTMLink(Base):
    __tablename__ = "utm_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    destination_url: Mapped[str] = mapped_column(String(600))
    campaign: Mapped[str | None] = mapped_column(String(120), default=None)
    source: Mapped[str | None] = mapped_column(String(60), default="reddit")
    medium: Mapped[str | None] = mapped_column(String(60), default="social")
    content: Mapped[str | None] = mapped_column(String(120), default=None)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    post: Mapped[Post | None] = relationship(back_populates="utm_links")
    clicks: Mapped[list[LinkClick]] = relationship(
        back_populates="link", cascade="all, delete-orphan"
    )


class LinkClick(Base):
    __tablename__ = "link_clicks"

    id: Mapped[int] = mapped_column(primary_key=True)
    utm_link_id: Mapped[int] = mapped_column(ForeignKey("utm_links.id"), index=True)
    clicked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    user_agent: Mapped[str | None] = mapped_column(String(400), default=None)
    referer: Mapped[str | None] = mapped_column(String(400), default=None)

    link: Mapped[UTMLink] = relationship(back_populates="clicks")
    conversion: Mapped[Conversion | None] = relationship(back_populates="link_click")


class Poll(Base):
    __tablename__ = "polls"

    id: Mapped[int] = mapped_column(primary_key=True)
    question: Mapped[str] = mapped_column(Text)
    kind: Mapped[PollKind] = mapped_column(Enum(PollKind), default=PollKind.PLOT)
    status: Mapped[PollStatus] = mapped_column(
        Enum(PollStatus), default=PollStatus.OPEN, index=True
    )
    opens_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    closes_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    teaser_post_id: Mapped[int | None] = mapped_column(
        ForeignKey("posts.id"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    options: Mapped[list[PollOption]] = relationship(
        back_populates="poll", cascade="all, delete-orphan"
    )
    votes: Mapped[list[PollVote]] = relationship(
        back_populates="poll", cascade="all, delete-orphan"
    )


class PollOption(Base):
    __tablename__ = "poll_options"

    id: Mapped[int] = mapped_column(primary_key=True)
    poll_id: Mapped[int] = mapped_column(ForeignKey("polls.id"), index=True)
    label: Mapped[str] = mapped_column(String(300))
    vote_count: Mapped[int] = mapped_column(Integer, default=0)

    poll: Mapped[Poll] = relationship(back_populates="options")


class PollVote(Base):
    __tablename__ = "poll_votes"
    # One vote per member per poll -- enforced. No Reddit vote brigading.
    __table_args__ = (UniqueConstraint("poll_id", "patreon_member_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    poll_id: Mapped[int] = mapped_column(ForeignKey("polls.id"), index=True)
    option_id: Mapped[int] = mapped_column(ForeignKey("poll_options.id"))
    patreon_member_id: Mapped[int] = mapped_column(
        ForeignKey("patreon_members.id"), index=True
    )
    weight: Mapped[int] = mapped_column(Integer, default=1)
    voted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    poll: Mapped[Poll] = relationship(back_populates="votes")


class Suggestion(Base):
    __tablename__ = "suggestions"

    id: Mapped[int] = mapped_column(primary_key=True)
    patreon_member_id: Mapped[int] = mapped_column(
        ForeignKey("patreon_members.id"), index=True
    )
    poll_id: Mapped[int | None] = mapped_column(ForeignKey("polls.id"), default=None)
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[SuggestionStatus] = mapped_column(
        Enum(SuggestionStatus), default=SuggestionStatus.NEW, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# --------------------------------------------------------------------------- #
# Patreon / funnel
# --------------------------------------------------------------------------- #
class PatreonTier(Base):
    __tablename__ = "patreon_tiers"

    id: Mapped[int] = mapped_column(primary_key=True)
    patreon_tier_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    amount_cents: Mapped[int] = mapped_column(Integer, default=0)

    members: Mapped[list[PatreonMember]] = relationship(back_populates="tier")


class PatreonMember(Base):
    __tablename__ = "patreon_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    patreon_member_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True
    )
    full_name: Mapped[str | None] = mapped_column(String(200), default=None)
    email_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    status: Mapped[MemberStatus] = mapped_column(
        Enum(MemberStatus), default=MemberStatus.ACTIVE, index=True
    )
    tier_id: Mapped[int | None] = mapped_column(
        ForeignKey("patreon_tiers.id"), default=None
    )
    pledge_cents: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    last_charge_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    tier: Mapped[PatreonTier | None] = relationship(back_populates="members")


class PatreonMetric(Base):
    __tablename__ = "patreon_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    patron_count: Mapped[int] = mapped_column(Integer, default=0)
    mrr_cents: Mapped[int] = mapped_column(Integer, default=0)
    new_patrons: Mapped[int] = mapped_column(Integer, default=0)
    churn_count: Mapped[int] = mapped_column(Integer, default=0)
    tier_mix_json: Mapped[str | None] = mapped_column(Text, default=None)


class Conversion(Base):
    __tablename__ = "conversions"
    # The attribution table: joins a Reddit-sourced click to a Patreon signup.

    id: Mapped[int] = mapped_column(primary_key=True)
    link_click_id: Mapped[int | None] = mapped_column(
        ForeignKey("link_clicks.id"), default=None, index=True
    )
    patreon_member_id: Mapped[int] = mapped_column(
        ForeignKey("patreon_members.id"), index=True
    )
    matched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    method: Mapped[str | None] = mapped_column(String(40), default=None)

    link_click: Mapped[LinkClick | None] = relationship(back_populates="conversion")
    member: Mapped[PatreonMember] = relationship()
