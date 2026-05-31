"""Tests for the interactive control-panel routes (forms + actions)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from redditsuite.analytics.dashboard.app import create_app
from redditsuite.core import repositories as repo
from redditsuite.core.models import Comment, Poll, PollOption, PollStatus
from redditsuite.growth import engagement_monitor


def _client():
    return TestClient(create_app())


def test_all_pages_load(settings, session):
    client = _client()
    for path in ("/", "/chapters", "/links", "/polls", "/comments", "/tools", "/settings"):
        assert client.get(path).status_code == 200


def test_schedule_chapter_via_form(settings, session):
    client = _client()
    r = client.post(
        "/chapters/schedule",
        data={
            "title": "Chapter 7: The Bridge",
            "when": "2026-06-02T17:00",
            "body": "It began...",
            "chapter": "7",
            "early_access_hours": "48",
        },
    )
    assert r.status_code == 200
    assert "Chapter 7: The Bridge" in r.text  # listed after redirect


def test_create_link_via_form(settings, session):
    client = _client()
    r = client.post(
        "/links/create",
        data={"destination": "https://patreon.com/16106807", "campaign": "ch7"},
    )
    assert r.status_code == 200
    assert "/r/" in r.text  # tracked link surfaced in the flash + table


def test_poll_full_workflow(settings, session):
    client = _client()
    # Create
    r = client.post(
        "/polls/create",
        data={"question": "Which door?", "options": "Left door\nRight door", "kind": "plot"},
    )
    assert r.status_code == 200
    assert "Left door" in r.text

    poll = session.scalars(select(Poll)).first()
    options = session.scalars(
        select(PollOption).where(PollOption.poll_id == poll.id)
    ).all()
    left = next(o for o in options if o.label == "Left door")

    # Vote
    r = client.post(f"/polls/{poll.id}/vote", data={"option_id": left.id, "member": "alice"})
    assert "Vote recorded" in r.text

    # Close -> winner announced
    r = client.post(f"/polls/{poll.id}/close")
    assert "Left door" in r.text
    session.expire_all()
    assert session.get(Poll, poll.id).status == PollStatus.CLOSED


def test_poll_options_validation(settings, session):
    client = _client()
    r = client.post(
        "/polls/create", data={"question": "Bad", "options": "only one", "kind": "plot"}
    )
    assert "at least two options" in r.text


def test_comment_handled_via_form(settings, session):
    post = repo.add_post(session, title="t")
    session.flush()
    engagement_monitor.ingest_comments(
        session,
        post,
        [
            {
                "id": "c1",
                "body": (
                    "This is one of the most beautiful and moving chapters I have "
                    "ever read, I am completely in love with this story!"
                ),
                "author": "superfan",
                "score": 25,
            }
        ],
    )
    session.commit()

    client = _client()
    page = client.get("/comments")
    assert "superfan" in page.text

    comment = session.scalars(select(Comment)).first()
    r = client.post(f"/comments/{comment.id}/handled")
    assert r.status_code == 200
    session.expire_all()
    assert session.get(Comment, comment.id).handled is True


def test_tools_analyze_timing(settings, session):
    client = _client()
    r = client.post("/tools/analyze-timing")
    assert r.status_code == 200
    assert "Analyzed timing" in r.text


def test_tools_export(settings, session, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = _client()
    r = client.post("/tools/export", data={"fmt": "csv"})
    assert r.status_code == 200
    assert "Exported" in r.text
    assert (tmp_path / "exports" / "funnel_summary.csv").exists()


def test_add_cross_promo_target(settings, session):
    client = _client()
    r = client.post(
        "/tools/add-target",
        data={"name": "WritingPrompts", "rules": "1-in-10", "min_days": "7"},
    )
    assert r.status_code == 200
    assert "WritingPrompts" in r.text


def test_settings_save_writes_env(settings, session, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = _client()
    r = client.post(
        "/settings/save",
        data={
            "home_subreddit": "MyEpic",
            "reddit_client_id": "abc123",
            "patreon_access_token": "tok-xyz",
        },
    )
    assert r.status_code == 200
    assert "Settings saved" in r.text

    from redditsuite.core.envfile import read_env

    env = read_env(tmp_path / ".env")
    assert env["HOME_SUBREDDIT"] == "MyEpic"
    assert env["REDDIT_CLIENT_ID"] == "abc123"
    assert env["PATREON_ACCESS_TOKEN"] == "tok-xyz"


def test_settings_blank_secret_is_not_written(settings, session, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = _client()
    client.post("/settings/save", data={"home_subreddit": "OnlyThis"})
    from redditsuite.core.envfile import read_env

    env = read_env(tmp_path / ".env")
    assert env["HOME_SUBREDDIT"] == "OnlyThis"
    assert "REDDIT_CLIENT_SECRET" not in env  # blank secrets are skipped


def test_envfile_preserves_comments_and_keys(tmp_path):
    from redditsuite.core import envfile

    p = tmp_path / ".env"
    p.write_text("# my settings\nHOME_SUBREDDIT=old\nKEEP=yes\n")
    envfile.update_env({"HOME_SUBREDDIT": "new", "NEWKEY": "1"}, path=p)
    data = envfile.read_env(p)
    assert data["HOME_SUBREDDIT"] == "new"
    assert data["KEEP"] == "yes"
    assert data["NEWKEY"] == "1"
    assert "# my settings" in p.read_text()
