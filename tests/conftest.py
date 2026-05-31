"""Shared test fixtures: an isolated file-backed SQLite DB and test settings.

No test touches the live Reddit or Patreon APIs -- the only seams are the client
factories, which tests replace with simple fakes.
"""

from __future__ import annotations

import pytest

from redditsuite.core import config, db


@pytest.fixture
def settings(tmp_path, monkeypatch):
    """Point the suite at a throwaway database and deterministic config."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("HOME_SUBREDDIT", "TestStory")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://test.local")
    monkeypatch.setenv("CLICK_HASH_SALT", "test-salt")
    monkeypatch.setenv("MIN_POST_SPACING_MINUTES", "180")
    monkeypatch.setenv("MAX_POSTS_PER_DAY", "3")
    config.get_settings.cache_clear()
    yield config.get_settings()
    config.get_settings.cache_clear()


@pytest.fixture
def session(settings):
    """A committed-on-success session against a freshly created schema."""
    db.configure_engine(settings.database_url)
    db.reset_db()
    factory = db.get_sessionmaker()
    s = factory()
    try:
        yield s
        s.commit()
    finally:
        s.close()


class FakeSubmission:
    def __init__(self, id="abc123", score=0, num_comments=0, upvote_ratio=0.95):
        self.id = id
        self.permalink = f"/r/TestStory/comments/{id}/"
        self.score = score
        self.num_comments = num_comments
        self.upvote_ratio = upvote_ratio


class FakeSubreddit:
    def __init__(self, recorder):
        self._recorder = recorder

    def submit(self, title, selftext=""):
        self._recorder.append((title, selftext))
        return FakeSubmission(id=f"id{len(self._recorder)}")


class FakeReddit:
    """Stand-in for praw.Reddit covering submit + submission lookup."""

    def __init__(self, submissions=None):
        self.submitted = []
        self._submissions = submissions or {}

    def subreddit(self, name):
        return FakeSubreddit(self.submitted)

    def submission(self, id):
        return self._submissions.get(id, FakeSubmission(id=id, score=10, num_comments=2))


@pytest.fixture
def fake_reddit():
    return FakeReddit()
