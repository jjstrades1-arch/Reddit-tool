"""Typed data-access helpers. Tools call these, not raw SQL.

Every function takes an explicit :class:`~sqlalchemy.orm.Session` so callers
control the transaction boundary (usually via ``core.db.session_scope``).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import (
    Conversion,
    LinkClick,
    PatreonMember,
    Post,
    PostMetric,
    PostStatus,
    Subreddit,
    UTMLink,
    utcnow,
)


# --------------------------------------------------------------------------- #
# Subreddits
# --------------------------------------------------------------------------- #
def get_or_create_subreddit(
    session: Session, name: str, *, is_home: bool = False
) -> Subreddit:
    sub = session.scalar(select(Subreddit).where(Subreddit.name == name))
    if sub is None:
        sub = Subreddit(name=name, is_home=is_home)
        session.add(sub)
        session.flush()
    elif is_home and not sub.is_home:
        sub.is_home = True
    return sub


def get_home_subreddit(session: Session) -> Subreddit:
    """Return (creating if needed) the configured home subreddit."""
    return get_or_create_subreddit(
        session, get_settings().home_subreddit, is_home=True
    )


# --------------------------------------------------------------------------- #
# Posts
# --------------------------------------------------------------------------- #
def add_post(
    session: Session,
    *,
    title: str,
    body: str | None = None,
    chapter_no: int | None = None,
    subreddit: Subreddit | None = None,
    scheduled_at: datetime | None = None,
    early_access_until: datetime | None = None,
) -> Post:
    sub = subreddit or get_home_subreddit(session)
    status = PostStatus.SCHEDULED if scheduled_at else PostStatus.DRAFT
    post = Post(
        title=title,
        body=body,
        chapter_no=chapter_no,
        subreddit=sub,
        scheduled_at=scheduled_at,
        early_access_until=early_access_until,
        status=status,
    )
    session.add(post)
    session.flush()
    return post


def get_due_scheduled_posts(session: Session, *, now: datetime | None = None) -> list[Post]:
    """Scheduled posts whose time has arrived and whose early-access window passed."""
    now = now or utcnow()
    stmt = (
        select(Post)
        .where(Post.status == PostStatus.SCHEDULED)
        .where(Post.scheduled_at <= now)
        .order_by(Post.scheduled_at)
    )
    due = []
    for post in session.scalars(stmt):
        if post.early_access_until and post.early_access_until > now:
            continue
        due.append(post)
    return due


def count_posts_today(
    session: Session, subreddit_id: int, *, now: datetime | None = None
) -> int:
    now = now or utcnow()
    start = now - timedelta(hours=24)
    stmt = (
        select(func.count())
        .select_from(Post)
        .where(Post.subreddit_id == subreddit_id)
        .where(Post.status == PostStatus.POSTED)
        .where(Post.submitted_at >= start)
    )
    return session.scalar(stmt) or 0


def last_post_time(
    session: Session, subreddit_id: int
) -> datetime | None:
    stmt = (
        select(func.max(Post.submitted_at))
        .where(Post.subreddit_id == subreddit_id)
        .where(Post.status == PostStatus.POSTED)
    )
    return session.scalar(stmt)


def record_post_metric(
    session: Session,
    post: Post,
    *,
    score: int,
    num_comments: int,
    upvote_ratio: float | None = None,
    views: int | None = None,
) -> PostMetric:
    metric = PostMetric(
        post=post,
        score=score,
        num_comments=num_comments,
        upvote_ratio=upvote_ratio,
        views=views,
    )
    session.add(metric)
    session.flush()
    return metric


# --------------------------------------------------------------------------- #
# UTM links / clicks
# --------------------------------------------------------------------------- #
def _unique_slug(session: Session) -> str:
    while True:
        slug = secrets.token_urlsafe(6)[:8]
        if not session.scalar(select(UTMLink).where(UTMLink.slug == slug)):
            return slug


def create_utm_link(
    session: Session,
    *,
    destination_url: str,
    campaign: str | None = None,
    source: str = "reddit",
    medium: str = "social",
    content: str | None = None,
    post: Post | None = None,
) -> UTMLink:
    link = UTMLink(
        slug=_unique_slug(session),
        destination_url=destination_url,
        campaign=campaign,
        source=source,
        medium=medium,
        content=content,
        post=post,
    )
    session.add(link)
    session.flush()
    return link


def get_link_by_slug(session: Session, slug: str) -> UTMLink | None:
    return session.scalar(select(UTMLink).where(UTMLink.slug == slug))


def hash_ip(ip: str | None) -> str | None:
    """Salted hash of a client IP -- we store no raw IPs (privacy)."""
    if not ip:
        return None
    salt = get_settings().click_hash_salt
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()


def record_click(
    session: Session,
    link: UTMLink,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
    referer: str | None = None,
) -> LinkClick:
    click = LinkClick(
        link=link,
        ip_hash=hash_ip(ip),
        user_agent=user_agent,
        referer=referer,
    )
    session.add(click)
    session.flush()
    return click


# --------------------------------------------------------------------------- #
# Patreon members / conversions
# --------------------------------------------------------------------------- #
def upsert_member(
    session: Session,
    *,
    patreon_member_id: str,
    full_name: str | None = None,
    pledge_cents: int = 0,
    started_at: datetime | None = None,
) -> tuple[PatreonMember, bool]:
    """Insert or update a member. Returns ``(member, created)``."""
    member = session.scalar(
        select(PatreonMember).where(
            PatreonMember.patreon_member_id == patreon_member_id
        )
    )
    created = member is None
    if member is None:
        member = PatreonMember(patreon_member_id=patreon_member_id)
        session.add(member)
    if full_name is not None:
        member.full_name = full_name
    member.pledge_cents = pledge_cents
    if started_at is not None:
        member.started_at = started_at
    session.flush()
    return member, created


def record_conversion(
    session: Session,
    *,
    member: PatreonMember,
    link_click: LinkClick | None,
    confidence: float,
    method: str,
) -> Conversion:
    conversion = Conversion(
        member=member,
        link_click=link_click,
        confidence=confidence,
        method=method,
    )
    session.add(conversion)
    session.flush()
    return conversion
