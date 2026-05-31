"""Credential-free reading of public Reddit data.

Reddit serves public, read-only JSON when you append ``.json`` to a page URL.
That lets the suite recover upvote/comment stats and comments for your own posts
**without an API app or login** -- you just paste a post's link after you
publish it. This is read-only and low-volume by design, and sends a descriptive
User-Agent as Reddit asks. It cannot post or vote (those need authentication).
"""

from __future__ import annotations

import re

import requests

from .config import get_settings
from .logging import get_logger

log = get_logger(__name__)

_TIMEOUT = 20
_POST_ID_RE = re.compile(r"comments/([a-z0-9]+)", re.IGNORECASE)
_BARE_ID_RE = re.compile(r"^[a-z0-9]+$", re.IGNORECASE)


class RedditPublicError(RuntimeError):
    """Raised when public Reddit data can't be read."""


def _user_agent() -> str:
    return get_settings().reddit_user_agent or "redditsuite/0.1 (public reader)"


def _get_json(url: str) -> object:
    sep = "&" if "?" in url else "?"
    resp = requests.get(
        f"{url}{sep}raw_json=1", headers={"User-Agent": _user_agent()}, timeout=_TIMEOUT
    )
    if resp.status_code == 429:
        raise RedditPublicError("Reddit is rate-limiting right now; try again in a minute.")
    if resp.status_code >= 400:
        raise RedditPublicError(f"Reddit returned status {resp.status_code}.")
    try:
        return resp.json()
    except ValueError as exc:  # pragma: no cover - defensive
        raise RedditPublicError("Reddit did not return readable data.") from exc


def extract_post_id(url_or_id: str) -> str:
    """Pull the post id out of a full Reddit URL, a ``t3_`` name, or a bare id."""
    text = (url_or_id or "").strip()
    match = _POST_ID_RE.search(text)
    if match:
        return match.group(1)
    tail = text.rsplit("/", 1)[-1]
    if tail.startswith("t3_"):
        tail = tail[3:]
    if _BARE_ID_RE.match(tail):
        return tail
    raise RedditPublicError(f"Couldn't find a Reddit post id in '{url_or_id}'.")


def fetch_post(url_or_id: str) -> dict:
    """Return public stats for one post (score, comments, ratio, title, ...)."""
    post_id = extract_post_id(url_or_id)
    data = _get_json(f"https://www.reddit.com/comments/{post_id}.json")
    try:
        post = data[0]["data"]["children"][0]["data"]
    except (IndexError, KeyError, TypeError) as exc:
        raise RedditPublicError("Unexpected response shape from Reddit.") from exc
    return {
        "id": post.get("id"),
        "title": post.get("title"),
        "score": int(post.get("score") or 0),
        "num_comments": int(post.get("num_comments") or 0),
        "upvote_ratio": post.get("upvote_ratio"),
        "permalink": post.get("permalink"),
        "subreddit": post.get("subreddit"),
    }


def fetch_comments(url_or_id: str, limit: int = 50) -> list[dict]:
    """Return top-level public comments for a post (author, body, score)."""
    post_id = extract_post_id(url_or_id)
    data = _get_json(f"https://www.reddit.com/comments/{post_id}.json?limit={limit}")
    out: list[dict] = []
    try:
        children = data[1]["data"]["children"]
    except (IndexError, KeyError, TypeError):
        return out
    for child in children:
        if child.get("kind") != "t1":
            continue
        c = child.get("data", {})
        if not c.get("id"):
            continue
        out.append(
            {
                "id": c["id"],
                "author": c.get("author"),
                "body": c.get("body") or "",
                "score": int(c.get("score") or 0),
            }
        )
    return out


def fetch_subreddit_new(subreddit: str, limit: int = 25) -> list[dict]:
    """Return the subreddit's most recent posts (to match your chapters by title)."""
    data = _get_json(f"https://www.reddit.com/r/{subreddit}/new.json?limit={limit}")
    out: list[dict] = []
    try:
        children = data["data"]["children"]
    except (KeyError, TypeError):
        return out
    for child in children:
        p = child.get("data", {})
        out.append(
            {
                "id": p.get("id"),
                "title": p.get("title"),
                "score": int(p.get("score") or 0),
                "num_comments": int(p.get("num_comments") or 0),
                "permalink": p.get("permalink"),
                "upvote_ratio": p.get("upvote_ratio"),
            }
        )
    return out
