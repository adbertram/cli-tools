"""Regression tests for `sessions list --filter` ordering and pruning.

`--filter` must run against the whole result set before `--limit` caps it
(agent-issues #584: `--filter id:eq:X --limit 1` returned [] whenever X was
not the newest session), and an exact `id:eq:` filter must open only the
named transcript files instead of parsing every session on disk.
"""
import json

import pytest
from typer.testing import CliRunner

from claude_code_sessions_cli import client as client_mod
from claude_code_sessions_cli.client import ClaudeCodeSessionsClient
from claude_code_sessions_cli.commands import sessions as sessions_cmd
from claude_code_sessions_cli.commands.sessions import exact_session_ids

runner = CliRunner()

NEWEST = "11111111-1111-4111-8111-111111111111"
OLDER = "22222222-2222-4222-8222-222222222222"
OTHER_PROJECT = "33333333-3333-4333-8333-333333333333"
# Encoded project paths; the project name is the segment after "GitRepos".
PROJECT_A = "-Users-adam-GitRepos-alpha"
PROJECT_B = "-Users-adam-GitRepos-beta"


def _write_session(project_dir, session_id, timestamp, message_count):
    project_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    parent = None
    for index in range(message_count):
        uuid = f"{session_id}-u{index}"
        entries.append({
            "type": "user",
            "uuid": uuid,
            "parentUuid": parent,
            "timestamp": timestamp,
            "message": {"content": f"prompt {index}"},
        })
        parent = uuid
    (project_dir / f"{session_id}.jsonl").write_text(
        "\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8"
    )


@pytest.fixture
def projects_dir(tmp_path, monkeypatch):
    """Three sessions across two projects, newest first: NEWEST, OLDER, OTHER_PROJECT."""
    claude_dir = tmp_path / ".claude"
    projects = claude_dir / "projects"
    _write_session(projects / PROJECT_A, NEWEST, "2026-09-15T12:00:00.000Z", 1)
    _write_session(projects / PROJECT_A, OLDER, "2026-09-14T12:00:00.000Z", 2)
    _write_session(projects / PROJECT_B, OTHER_PROJECT, "2026-09-13T12:00:00.000Z", 3)

    client = ClaudeCodeSessionsClient.__new__(ClaudeCodeSessionsClient)
    client.claude_dir = claude_dir
    client.projects_dir = projects
    client.todos_dir = claude_dir / "todos"
    monkeypatch.setattr(sessions_cmd, "get_client", lambda: client)
    return projects


def _list(*args):
    result = runner.invoke(sessions_cmd.app, ["list", "--properties", "id", *args])
    assert result.exit_code == 0, result.output
    return [row["id"] for row in json.loads(result.stdout)]


def test_id_filter_with_limit_one_returns_non_newest_session(projects_dir):
    assert _list("--filter", f"id:eq:{OLDER}", "--limit", "1") == [OLDER]


def test_non_id_filter_runs_before_limit(projects_dir):
    # message_count 2 belongs to OLDER only; the newest session must not
    # consume the limit before the filter runs.
    assert _list("--filter", "message_count:eq:2", "--limit", "1") == [OLDER]


def test_limit_still_caps_filtered_rows(projects_dir):
    assert _list("--filter", "message_count:gte:1", "--limit", "2") == [NEWEST, OLDER]


def test_unfiltered_limit_returns_newest(projects_dir):
    assert _list("--limit", "1") == [NEWEST]


def test_id_filter_parses_only_the_named_transcript(projects_dir, monkeypatch):
    parsed = []
    real_parse = client_mod.parse_session_summary

    def recording_parse(session_path, project_name):
        parsed.append(session_path)
        return real_parse(session_path, project_name)

    monkeypatch.setattr(client_mod, "parse_session_summary", recording_parse)

    assert _list("--filter", f"id:eq:{OLDER}") == [OLDER]
    assert parsed == [projects_dir / PROJECT_A / f"{OLDER}.jsonl"]


def test_id_filter_scoped_to_project_parses_only_the_named_transcript(projects_dir, monkeypatch):
    parsed = []
    real_parse = client_mod.parse_session_summary

    def recording_parse(session_path, project_name):
        parsed.append(session_path)
        return real_parse(session_path, project_name)

    monkeypatch.setattr(client_mod, "parse_session_summary", recording_parse)

    assert _list("--project", "alpha", "--filter", f"id:eq:{OLDER}", "--limit", "1") == [OLDER]
    assert parsed == [projects_dir / PROJECT_A / f"{OLDER}.jsonl"]


def test_exact_session_ids_accepts_shorthand_and_or_groups():
    assert exact_session_ids([f"id:eq:{OLDER}"]) == [OLDER]
    assert exact_session_ids([f"id:{OLDER}"]) == [OLDER]
    assert exact_session_ids([f"id:eq:{OLDER},message_count:gte:1", f"id:eq:{NEWEST}"]) == [OLDER, NEWEST]


def test_exact_session_ids_is_none_when_any_group_is_unbounded():
    assert exact_session_ids(["message_count:eq:2"]) is None
    assert exact_session_ids([f"id:eq:{OLDER}", "message_count:eq:2"]) is None
    assert exact_session_ids([f"id:contains:{OLDER[:8]}"]) is None
