"""Smoke tests for the CLI wiring."""

from __future__ import annotations

from typer.testing import CliRunner

from redditsuite.cli import app

runner = CliRunner()


def test_help_lists_funnel_groups():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for group in ("growth", "conversion", "analytics", "db"):
        assert group in result.output


def test_db_init_and_status(settings):
    init = runner.invoke(app, ["db", "init"])
    assert init.exit_code == 0
    assert "TestStory" in init.output

    status = runner.invoke(app, ["db", "status"])
    assert status.exit_code == 0
    assert "posts" in status.output


def test_growth_subcommands_registered():
    result = runner.invoke(app, ["growth", "--help"])
    assert result.exit_code == 0
    assert "schedule" in result.output
    assert "analyze-timing" in result.output


def test_conversion_subcommands_registered():
    result = runner.invoke(app, ["conversion", "--help"])
    assert result.exit_code == 0
    assert "poll-create" in result.output
    assert "cta-create" in result.output
