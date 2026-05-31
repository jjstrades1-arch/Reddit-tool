"""Tests for credential-free public Reddit reading and refresh."""

from __future__ import annotations

import json

import pytest
import responses

from redditsuite.analytics import public_collect
from redditsuite.core import reddit_public
from redditsuite.core import repositories as repo
from redditsuite.core.models import PostStatus


def _post_json(post_id="abc12", score=42, num_comments=2, ratio=0.97):
    listing = {
        "data": {
            "children": [
                {
                    "kind": "t3",
                    "data": {
                        "id": post_id,
                        "title": "Chapter 1",
                        "score": score,
                        "num_comments": num_comments,
                        "upvote_ratio": ratio,
                        "permalink": f"/r/MyStory/comments/{post_id}/chapter_1/",
                        "subreddit": "MyStory",
                    },
                }
            ]
        }
    }
    comments = {
        "data": {
            "children": [
                {
                    "kind": "t1",
                    "data": {"id": "c1", "author": "fan", "body": "Loved it!", "score": 5},
                },
                {"kind": "more", "data": {"id": "x"}},
            ]
        }
    }
    return json.dumps([listing, comments])


def test_extract_post_id_forms():
    url = "https://www.reddit.com/r/X/comments/abc12/title/"
    assert reddit_public.extract_post_id(url) == "abc12"
    assert reddit_public.extract_post_id("t3_abc12") == "abc12"
    assert reddit_public.extract_post_id("abc12") == "abc12"
    with pytest.raises(reddit_public.RedditPublicError):
        reddit_public.extract_post_id("not a link!!")


@responses.activate
def test_fetch_post_and_comments(settings):
    body = _post_json()
    responses.add(
        responses.GET,
        "https://www.reddit.com/comments/abc12.json",
        body=body,
        status=200,
    )
    info = reddit_public.fetch_post("https://www.reddit.com/r/MyStory/comments/abc12/x/")
    assert info["score"] == 42
    assert info["num_comments"] == 2
    assert info["upvote_ratio"] == 0.97

    comments = reddit_public.fetch_comments("abc12")
    assert len(comments) == 1  # the "more" node is skipped
    assert comments[0]["author"] == "fan"


@responses.activate
def test_fetch_post_rate_limited(settings):
    responses.add(
        responses.GET, "https://www.reddit.com/comments/zzz.json", status=429
    )
    with pytest.raises(reddit_public.RedditPublicError):
        reddit_public.fetch_post("zzz")


def test_refresh_from_public_with_injected_fetchers(settings, session):
    post = repo.add_post(session, title="Chapter 1")
    post.status = PostStatus.POSTED
    post.reddit_id = "abc12"
    session.flush()

    def fake_post(_):
        return {"score": 88, "num_comments": 3, "upvote_ratio": 0.95, "permalink": "/r/MyStory/x/"}

    def fake_comments(_):
        return [
            {
                "id": "c1",
                "author": "superfan",
                "body": "This was an absolutely incredible and moving chapter, I loved every word!",
                "score": 12,
            }
        ]

    res = public_collect.refresh_from_public(
        session, fetch_post=fake_post, fetch_comments=fake_comments
    )
    assert res["updated"] == 1
    assert res["new_comments"] == 1
    session.refresh(post)
    assert post.metrics[0].score == 88
    assert post.permalink == "/r/MyStory/x/"
