"""Contract tests for read-only Microworkers Basic-task history."""

import json
from pathlib import Path

from typer.testing import CliRunner

import microworkers_cli.main as cli_main
from microworkers_cli.client import (
    HISTORY_DETAIL_JS,
    HISTORY_JS,
    MicroworkersClient,
)
from microworkers_cli.parsers import normalize_history_row


FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "history_pending.json").read_text()
)


def test_normalize_history_row_uses_same_task_detail_and_explicit_status():
    row = normalize_history_row(FIXTURE["page"]["rows"][0], FIXTURE["detail"])

    assert row == {
        "id": "120525231",
        "job_id": "c0e2efb7fbeb",
        "url": None,
        "provider": "microworkers",
        "title": "TNW: Visit 2x + Answer 2 Questions",
        "proof_preview": "1. Service Provider Pro\n2. https://wayfr...",
        "submitted_at": "09/05/2026 18:37:52",
        "submitted_age": "38 mins ago",
        "status": "Pending Employer review",
        "status_icon": "minus-circle",
        "payment": "$0.00",
        "payment_status": "pending",
    }


def test_normalize_history_row_ignores_mismatched_detail_and_unsafe_url():
    raw = {
        **FIXTURE["page"]["rows"][0],
        "url": "https://www.microworkers.com/worker/tasks/B/120525231/delete",
    }
    mismatched = {**FIXTURE["detail"], "task_id": "999"}

    row = normalize_history_row(raw, mismatched)

    assert row["id"] == "120525231"
    assert row["url"] is None
    assert row["job_id"] is None
    assert row["submitted_at"] is None
    assert row["payment"] is None


class _FakeConfig:
    base_url = "https://www.microworkers.com"


class _FakePage:
    def __init__(self, url):
        self.url = url

    def wait_for_timeout(self, _milliseconds):
        pass

    def evaluate(self, script):
        if script == HISTORY_JS:
            return FIXTURE["page"]
        if script == HISTORY_DETAIL_JS:
            return FIXTURE["detail"]
        raise AssertionError("unexpected browser script")


class _FakeBrowser:
    def __init__(self):
        self.urls = []
        self.close_calls = 0

    def ensure_fresh_session(self):  # pragma: no cover - refresh already marked checked
        raise AssertionError("refresh should not run")

    def get_page(self, url):
        self.urls.append(url)
        return _FakePage(url)

    def close(self):
        self.close_calls += 1


def test_list_history_reads_worker_page_and_safe_detail_get_only():
    browser = _FakeBrowser()
    client = object.__new__(MicroworkersClient)
    client.config = _FakeConfig()
    client._browser = browser
    client._refresh_checked = True

    rows = client.list_history(limit=1)

    assert rows[0]["id"] == "120525231"
    assert browser.urls == [
        "https://www.microworkers.com/worker.php",
        "https://www.microworkers.com/worker_tasks_details.php?Id=120525231",
    ]
    assert all("/delete" not in url for url in browser.urls)


class _CommandClient:
    def list_history(self, limit):
        assert limit == 1
        return [normalize_history_row(FIXTURE["page"]["rows"][0], FIXTURE["detail"])]


def test_tasks_history_supports_filter_limit_properties_and_table(monkeypatch):
    monkeypatch.setattr(cli_main, "get_client", lambda: _CommandClient())
    runner = CliRunner()

    result = runner.invoke(
        cli_main.app,
        [
            "tasks",
            "history",
            "--limit",
            "1",
            "--filter",
            "status:eq:Pending Employer review",
            "--properties",
            "id,status,payment",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [
        {
            "id": "120525231",
            "status": "Pending Employer review",
            "payment": "$0.00",
        }
    ]

    table = runner.invoke(
        cli_main.app,
        ["tasks", "history", "-l", "1", "-p", "id,status", "-t"],
    )
    assert table.exit_code == 0, table.output
    assert "Pending Employer review" in table.stdout
