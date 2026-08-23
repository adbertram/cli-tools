import json

import pytest

from claude_code_sessions_cli.client import ClaudeCodeSessionsClient, ClientError


def _make_client(tmp_path):
    """Build a client rooted at a temp ~/.claude/projects tree."""
    claude_dir = tmp_path / ".claude"
    projects_dir = claude_dir / "projects"
    projects_dir.mkdir(parents=True)
    client = ClaudeCodeSessionsClient.__new__(ClaudeCodeSessionsClient)
    client.claude_dir = claude_dir
    client.projects_dir = projects_dir
    client.todos_dir = claude_dir / "todos"
    return client, projects_dir


def _write_session(project_dir, session_id, *, title=None, message="hi"):
    project_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    if title is not None:
        lines.append(json.dumps({
            "type": "custom-title",
            "customTitle": title,
            "sessionId": session_id,
        }))
    lines.append(json.dumps({
        "type": "user",
        "uuid": f"{session_id}-u1",
        "timestamp": "2026-06-25T12:00:00.000Z",
        "message": {"content": message},
    }))
    (project_dir / f"{session_id}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


UUID_A = "bc0146bc-5608-492a-8c34-fb50ed5d95f7"
UUID_B = "3f2a1111-0000-0000-0000-000000000000"
UUID_C = "9b1c2222-0000-0000-0000-000000000000"


def test_uuid_passthrough_without_filesystem(tmp_path):
    client, _ = _make_client(tmp_path)
    # A UUID is returned unchanged even if no such session exists.
    assert client.resolve_session_id(UUID_A) == UUID_A


def test_uuid_passthrough_is_case_insensitive(tmp_path):
    client, _ = _make_client(tmp_path)
    upper = UUID_A.upper()
    assert client.resolve_session_id(upper) == upper


def test_exact_name_resolves_to_id(tmp_path):
    client, projects_dir = _make_client(tmp_path)
    _write_session(
        projects_dir / "-Users-adam-Dropbox-GitRepos-CourseCraft",
        UUID_A,
        title="Course: OpenAI Codex Advanced Features Module 2",
    )
    resolved = client.resolve_session_id(
        "Course: OpenAI Codex Advanced Features Module 2"
    )
    assert resolved == UUID_A


def test_name_match_is_case_insensitive(tmp_path):
    client, projects_dir = _make_client(tmp_path)
    _write_session(projects_dir / "-Users-adam-Dropbox-GitRepos-CourseCraft", UUID_A, title="My Session")
    assert client.resolve_session_id("MY SESSION") == UUID_A


def test_name_match_is_exact_not_substring(tmp_path):
    client, projects_dir = _make_client(tmp_path)
    _write_session(projects_dir / "-Users-adam-Dropbox-GitRepos-CourseCraft", UUID_A, title="Customer inquiries weekly")
    with pytest.raises(ClientError) as exc:
        client.resolve_session_id("Customer inquiries")
    assert 'No session named "Customer inquiries"' in str(exc.value)


def test_no_match_raises(tmp_path):
    client, projects_dir = _make_client(tmp_path)
    _write_session(projects_dir / "-Users-adam-Dropbox-GitRepos-CourseCraft", UUID_A, title="Something Else")
    with pytest.raises(ClientError) as exc:
        client.resolve_session_id("Nonexistent")
    msg = str(exc.value)
    assert 'No session named "Nonexistent"' in msg
    assert "sessions list" in msg


def test_multi_match_raises_with_count_and_listing(tmp_path):
    client, projects_dir = _make_client(tmp_path)
    _write_session(projects_dir / "-Users-adam-Dropbox-GitRepos-CourseCraft", UUID_B, title="Customer inquiries")
    _write_session(projects_dir / "-Users-adam-Dropbox-GitRepos-Agents", UUID_C, title="Customer inquiries")
    with pytest.raises(ClientError) as exc:
        client.resolve_session_id("Customer inquiries")
    msg = str(exc.value)
    assert '2 sessions match "Customer inquiries":' in msg
    assert UUID_B[:4] in msg
    assert UUID_C[:4] in msg
    assert "CourseCraft" in msg
    assert "Agents" in msg
    assert msg.strip().endswith("Re-run with a session ID.")


def test_project_scope_narrows_collision(tmp_path):
    client, projects_dir = _make_client(tmp_path)
    # Same name in two projects collides globally, but scoping to one resolves.
    _write_session(projects_dir / "-Users-adam-Dropbox-GitRepos-CourseCraft", UUID_B, title="Customer inquiries")
    _write_session(projects_dir / "-Users-adam-Dropbox-GitRepos-Agents", UUID_C, title="Customer inquiries")
    resolved = client.resolve_session_id("Customer inquiries", project="CourseCraft")
    assert resolved == UUID_B
