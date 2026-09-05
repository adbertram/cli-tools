"""`enrich <site>`: ledger-bounded detail fetches -> task descriptions.

The runner is a scripted fake keyed on argv (same pattern as test_discover.py),
so no site CLI is ever executed. One microworkers task gets a real
instructions list, one gets a detail with no description text, and a third
task's detail fetch fails -- the summary has to say which is which, and a
second run must skip everything already handled.
"""

from __future__ import annotations

import json

import pytest
from cli_tools_shared.exceptions import ClientError

from microworker_cli import db, enrich, runner
from test_discover import FakeRunner, result

TIMEOUT = 7
AUTH = ("microworkers", "auth", "status")


def seed_task(site, task_id, url):
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO tasks (site, task_id, title, url, pay_amount, "
            "pay_currency, est_minutes, slots_open, expires_at, raw, "
            "first_seen_at, last_seen_at, first_seen_run_id, "
            "last_seen_run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (site, task_id, "t", url, None, None, None, None, None,
             json.dumps({"id": task_id}), "2026-09-01T00:00:00Z",
             "2026-09-01T00:00:00Z", "run-a", "run-a"))
        conn.commit()
    finally:
        conn.close()


def get_detail(argv, timeout):
    """The detail payload a `microworkers tasks get <url>` answers with."""
    assert timeout == TIMEOUT
    url = argv[3]
    if url.endswith("u3"):
        return result(argv, 1, stderr="boom")
    if url.endswith("u2"):
        payload = {"title": "t"}
    else:
        payload = {
            "title": "t",
            "instructions_and_proof": ["do this", "then that"],
            "work_summary": ["summary line"],
        }
    return result(argv, 0, stdout=json.dumps(payload))


def test_enrich_writes_skips_and_reports(project, monkeypatch):
    seed_task("microworkers", "t1", "https://www.microworkers.com/u1")
    seed_task("microworkers", "t2", "https://www.microworkers.com/u2")
    seed_task("microworkers", "fails", "https://www.microworkers.com/u3")

    class ScriptedRunner:
        def __call__(self, argv, timeout):
            assert timeout == TIMEOUT
            key = tuple(argv)
            if key == AUTH:
                return result(key, 0)
            if key[:3] == ("microworkers", "tasks", "get"):
                return get_detail(key, timeout)
            raise AssertionError(f"unexpected command {key}")

    monkeypatch.setattr(runner, "run", ScriptedRunner())
    summary = enrich.enrich("microworkers", TIMEOUT)
    assert summary == {
        "site": "microworkers",
        "checked": 3,
        "enriched": 1,
        "failed": 1,
        "skipped_no_description": 1,
        "failures": {"fails": "`microworkers tasks get "
                              "https://www.microworkers.com/u3` exited 1: boom"},
    }
    assert db.get_task("microworkers", "t1")["description"] == \
        "do this\nthen that\nsummary line"
    # A detail with no description text is marked with the empty string --
    # falsy to readers, but distinct from NULL so it is never refetched.
    assert db.get_task("microworkers", "t2")["description"] == ""
    assert db.get_task("microworkers", "fails")["description"] is None

    # Second run: t1 is enriched, t2 is marked, fails has one to retry -- so
    # only the failed task remains.
    calls: list = []
    class CountingRunner:
        def __call__(self, argv, timeout):
            calls.append(tuple(argv))
            if tuple(argv) == AUTH:
                return result(argv, 0)
            return get_detail(argv, timeout)

    monkeypatch.setattr(runner, "run", CountingRunner())
    second = enrich.enrich("microworkers", TIMEOUT)
    # Only the previously failed task remains pending; it fails again (the
    # scripted detail fetch is still broken), which is the point: enriched and
    # empty rows are never refetched.
    assert second["checked"] == 1 and second["failed"] == 1
    assert ("microworkers", "tasks", "get", "https://www.microworkers.com/u2") not in calls
    assert ("microworkers", "tasks", "get", "https://www.microworkers.com/u3") in calls


def test_enrich_refuses_site_without_extractor(project):
    with pytest.raises(ClientError, match="has no detail-page description"):
        enrich.enrich("humanrail", TIMEOUT)


def test_enrich_requires_authentication(project, monkeypatch):
    seed_task("microworkers", "t1", "u1")
    login = ("microworkers", "auth", "login", "--credential-type", "browser_session")
    monkeypatch.setattr(runner, "run", FakeRunner({
        AUTH: [result(AUTH, 2, stderr="not logged in"),   # status
               result(AUTH, 2, stderr="still not logged in")],  # recheck
        login: [result(login, 0)],
    }))
    with pytest.raises(ClientError, match="not authenticated"):
        enrich.enrich("microworkers", TIMEOUT)
