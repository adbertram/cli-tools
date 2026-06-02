"""Tests for the `--exclude-tag` flag on `things todos list` and `things projects list`.

The CLI must drop items whose `tags` list contains ANY of the excluded tag names
(case-sensitive, union exclusion). Filtering happens client-side, after the
SQLite query, because the Things AppleScript bridge does not support
tag-exclusion server-side.
"""
import json
from typing import List, Optional

from typer.testing import CliRunner

from things_cli.commands import projects as projects_cmd
from things_cli.commands import todos as todos_cmd
from things_cli.models import Project, Task


runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures: in-memory clients that capture filter args and return canned data.
# ---------------------------------------------------------------------------


def _make_todos(specs):
    """Build Task models from (uuid, title, tags) tuples."""
    return [Task(uuid=u, title=t, tags=list(tags)) for u, t, tags in specs]


def _make_projects(specs):
    """Build Project models from (uuid, title, tags) tuples."""
    return [Project(uuid=u, title=t, tags=list(tags)) for u, t, tags in specs]


class _FakeTodosClient:
    def __init__(self, todos):
        self._todos = todos
        self.last_kwargs: Optional[dict] = None

    def list_todos(self, **kwargs):
        self.last_kwargs = kwargs
        return list(self._todos)

    def list_next_actions(self, limit=100):
        return list(self._todos)


class _FakeProjectsClient:
    def __init__(self, projects):
        self._projects = projects
        self.last_kwargs: Optional[dict] = None

    def list_projects(self, **kwargs):
        self.last_kwargs = kwargs
        return list(self._projects)


# ---------------------------------------------------------------------------
# todos list --exclude-tag
# ---------------------------------------------------------------------------


def _invoke_todos(monkeypatch, todos, args):
    fake = _FakeTodosClient(todos)
    monkeypatch.setattr(todos_cmd, "get_client", lambda: fake)
    result = runner.invoke(todos_cmd.app, ["list", *args])
    return result, fake


def test_todos_list_no_exclude_tag_is_noop(monkeypatch):
    """Default behavior: every todo returned, no filtering."""
    todos = _make_todos([
        ("u1", "alpha", ["WF"]),
        ("u2", "beta", []),
        ("u3", "gamma", ["work"]),
    ])
    result, _ = _invoke_todos(monkeypatch, todos, [])

    assert result.exit_code == 0, result.stdout
    titles = sorted(t["title"] for t in json.loads(result.stdout))
    assert titles == ["alpha", "beta", "gamma"]


def test_todos_list_excludes_single_tag(monkeypatch):
    """`--exclude-tag WF` removes WF-tagged items."""
    todos = _make_todos([
        ("u1", "wf-only", ["WF"]),
        ("u2", "untagged", []),
        ("u3", "wf-and-work", ["WF", "work"]),
        ("u4", "work-only", ["work"]),
    ])
    result, _ = _invoke_todos(monkeypatch, todos, ["--exclude-tag", "WF"])

    assert result.exit_code == 0, result.stdout
    titles = sorted(t["title"] for t in json.loads(result.stdout))
    assert titles == ["untagged", "work-only"]


def test_todos_list_excludes_multiple_tags_union(monkeypatch):
    """`--exclude-tag WF --exclude-tag SomeOther` drops items tagged with EITHER."""
    todos = _make_todos([
        ("u1", "wf", ["WF"]),
        ("u2", "other", ["SomeOther"]),
        ("u3", "both", ["WF", "SomeOther"]),
        ("u4", "neither", ["work"]),
        ("u5", "untagged", []),
    ])
    result, _ = _invoke_todos(
        monkeypatch, todos, ["--exclude-tag", "WF", "--exclude-tag", "SomeOther"]
    )

    assert result.exit_code == 0, result.stdout
    titles = sorted(t["title"] for t in json.loads(result.stdout))
    assert titles == ["neither", "untagged"]


def test_todos_list_exclude_tag_is_case_sensitive(monkeypatch):
    """Lowercase `wf` must NOT match an uppercase `WF` tag (Things tags are case-sensitive)."""
    todos = _make_todos([
        ("u1", "upper", ["WF"]),
        ("u2", "lower", ["wf"]),
    ])
    result, _ = _invoke_todos(monkeypatch, todos, ["--exclude-tag", "wf"])

    assert result.exit_code == 0, result.stdout
    titles = sorted(t["title"] for t in json.loads(result.stdout))
    # Only the lowercase-tagged item is dropped.
    assert titles == ["upper"]


def test_todos_list_exclude_tag_combined_with_tag_filter(monkeypatch):
    """`--tag work --exclude-tag WF` selects work-tagged items that are NOT WF-tagged.

    The `--tag` filter is applied server-side by the client (verified via captured
    kwargs); the `--exclude-tag` filter is applied client-side on what comes back.
    """
    # Simulate what the SQLite query would return for `--tag work`: only work-tagged.
    todos = _make_todos([
        ("u1", "pure-work", ["work"]),
        ("u2", "work-and-wf", ["work", "WF"]),
    ])
    result, fake = _invoke_todos(
        monkeypatch, todos, ["--tag", "work", "--exclude-tag", "WF"]
    )

    assert result.exit_code == 0, result.stdout
    # `--tag` is forwarded to the client (server-side filter).
    assert fake.last_kwargs is not None and fake.last_kwargs.get("tag") == "work"
    # `--exclude-tag` is applied after the response.
    titles = sorted(t["title"] for t in json.loads(result.stdout))
    assert titles == ["pure-work"]


# ---------------------------------------------------------------------------
# projects list --exclude-tag
# ---------------------------------------------------------------------------


def _invoke_projects(monkeypatch, projects, args):
    fake = _FakeProjectsClient(projects)
    monkeypatch.setattr(projects_cmd, "get_client", lambda: fake)
    result = runner.invoke(projects_cmd.app, ["list", *args])
    return result, fake


def test_projects_list_no_exclude_tag_is_noop(monkeypatch):
    """Default behavior: every project returned, no filtering."""
    projects = _make_projects([
        ("p1", "Alpha", ["WF"]),
        ("p2", "Beta", []),
    ])
    result, _ = _invoke_projects(monkeypatch, projects, [])

    assert result.exit_code == 0, result.stdout
    titles = sorted(p["title"] for p in json.loads(result.stdout))
    assert titles == ["Alpha", "Beta"]


def test_projects_list_excludes_single_tag(monkeypatch):
    """`--exclude-tag WF` removes WF-tagged projects."""
    projects = _make_projects([
        ("p1", "WF-only", ["WF"]),
        ("p2", "Untagged", []),
        ("p3", "WF-and-Q1", ["WF", "Q1"]),
        ("p4", "Q1-only", ["Q1"]),
    ])
    result, _ = _invoke_projects(monkeypatch, projects, ["--exclude-tag", "WF"])

    assert result.exit_code == 0, result.stdout
    titles = sorted(p["title"] for p in json.loads(result.stdout))
    assert titles == ["Q1-only", "Untagged"]


def test_projects_list_excludes_multiple_tags_union(monkeypatch):
    """`--exclude-tag WF --exclude-tag Archive` drops items tagged with EITHER."""
    projects = _make_projects([
        ("p1", "wf", ["WF"]),
        ("p2", "archive", ["Archive"]),
        ("p3", "both", ["WF", "Archive"]),
        ("p4", "active", ["Q1"]),
        ("p5", "untagged", []),
    ])
    result, _ = _invoke_projects(
        monkeypatch, projects, ["--exclude-tag", "WF", "--exclude-tag", "Archive"]
    )

    assert result.exit_code == 0, result.stdout
    titles = sorted(p["title"] for p in json.loads(result.stdout))
    assert titles == ["active", "untagged"]


def test_projects_list_exclude_tag_combined_with_filter(monkeypatch):
    """`--exclude-tag` composes with `--filter` (both client-side)."""
    projects = _make_projects([
        ("p1", "Keep me", ["work"]),
        ("p2", "Keep me too", []),
        ("p3", "Drop me WF", ["WF"]),
        ("p4", "Skip me", []),
    ])
    result, _ = _invoke_projects(
        monkeypatch,
        projects,
        ["--exclude-tag", "WF", "--filter", "title:contains:Keep"],
    )

    assert result.exit_code == 0, result.stdout
    titles = sorted(p["title"] for p in json.loads(result.stdout))
    assert titles == ["Keep me", "Keep me too"]
