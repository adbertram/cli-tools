"""Command-level tests for `lastpass items list --filter` / `--limit`.

`items list` is metadata-only (id/name/group/full_path). These tests lock in
three behaviors that previously produced misleading results:

1. `name:like:` is case-insensitive, so `%google%` matches an entry named
   "Google" (case-sensitive 'like' silently dropped it -> false "not found").
2. A filter on a non-metadata field (Username, URL) is a clear error with a
   non-zero exit, never a false-negative empty result.
3. `--limit` defaults to 50 but `--limit 0` returns everything, and a positive
   limit that truncates prints a notice to stderr (never to stdout/JSON).
"""
import json

import pytest
from typer.testing import CliRunner

from lastpass_cli.commands import items as items_module


# A small synthetic "vault" covering case variants and >50 entries for limit
# tests. `list_items` returns metadata-only dicts, mirroring _parse_lpass_ls.
SAMPLE_ITEMS = [
    {"id": "922335676", "name": "Google", "group": "Home", "full_path": "Home/Google"},
    {"id": "7600439653866760487", "name": "google.com", "group": "", "full_path": "google.com"},
    {"id": "2673791556", "name": "RF Google", "group": "Home", "full_path": "Home/RF Google"},
    {"id": "100", "name": "GitHub", "group": "Work", "full_path": "Work/GitHub"},
]


class _FakeClient:
    def __init__(self, items):
        self._items = items

    def list_items(self, group=None):
        if group:
            return [i for i in self._items if i.get("group") == group]
        return list(self._items)

    def filter_items_by_category(self, items, category):  # pragma: no cover - unused here
        return items


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def patch_client(monkeypatch):
    def _install(items):
        monkeypatch.setattr(items_module, "get_client", lambda: _FakeClient(items))
    return _install


def _json_ids(result):
    return {entry["id"] for entry in json.loads(result.stdout)}


def test_name_like_is_case_insensitive(runner, patch_client):
    patch_client(SAMPLE_ITEMS)

    result = runner.invoke(items_module.app, ["list", "--filter", "name:like:%google%", "--limit", "0"])

    assert result.exit_code == 0, result.stdout
    # "Google", "google.com", and "RF Google" all match; "GitHub" does not.
    assert _json_ids(result) == {"922335676", "7600439653866760487", "2673791556"}


def test_unsupported_filter_field_errors(runner, patch_client):
    patch_client(SAMPLE_ITEMS)

    result = runner.invoke(items_module.app, ["list", "--filter", "Username:like:%x%"])

    assert result.exit_code != 0
    # Stdout must NOT be a clean/empty JSON result that reads as "no matches".
    assert result.stdout.strip() in ("", "[]") or "not filterable" in result.output
    combined = result.output
    assert "Username" in combined and "not filterable" in combined
    # The error names the supported fields.
    assert "name" in combined and "group" in combined


def test_unsupported_filter_field_errors_in_table_mode(runner, patch_client):
    patch_client(SAMPLE_ITEMS)

    result = runner.invoke(items_module.app, ["list", "--filter", "URL:like:%x%", "--table"])

    assert result.exit_code != 0
    assert "No entries found" not in result.output
    assert "not filterable" in result.output


def test_supported_field_filter_still_works(runner, patch_client):
    patch_client(SAMPLE_ITEMS)

    result = runner.invoke(items_module.app, ["list", "--filter", "group:eq:Home", "--limit", "0"])

    assert result.exit_code == 0, result.stdout
    assert _json_ids(result) == {"922335676", "2673791556"}


def test_limit_zero_returns_everything(runner, patch_client):
    many = [
        {"id": str(n), "name": f"entry{n}", "group": "", "full_path": f"entry{n}"}
        for n in range(60)
    ]
    patch_client(many)

    result = runner.invoke(items_module.app, ["list", "--limit", "0"])

    assert result.exit_code == 0
    assert len(json.loads(result.stdout)) == 60


def test_default_limit_truncates_and_warns(runner, patch_client):
    many = [
        {"id": str(n), "name": f"entry{n}", "group": "", "full_path": f"entry{n}"}
        for n in range(60)
    ]
    patch_client(many)

    result = runner.invoke(items_module.app, ["list"])

    assert result.exit_code == 0
    # JSON payload is capped to the default 50...
    assert len(json.loads(result.stdout)) == 50
    # ...and the truncation notice goes to stderr, not into the JSON on stdout.
    assert "50 of 60" in result.stderr
    assert "50 of 60" not in result.stdout


def test_no_truncation_notice_when_results_fit(runner, patch_client):
    patch_client(SAMPLE_ITEMS)

    result = runner.invoke(items_module.app, ["list"])

    assert result.exit_code == 0
    assert "truncated" not in result.stderr
