"""`discover` status mapping, one test per branch of the decision table.

`runner.run` is replaced by a scripted fake keyed on argv, so no site CLI is
ever executed. Each case asserts the envelope on disk, the schema, and the
summary the command prints.
"""

from __future__ import annotations

import json

import pytest
from cli_tools_shared.exceptions import ConfigError

from microworker_cli import discover, paths, runner, schema
from microworker_cli.main import app

RUN = "20260902T000000Z"
TIMEOUT = 7


class FakeRunner:
    """argv tuple -> RunResult, an exception to raise, or a list consumed in order."""

    def __init__(self, script: dict):
        self.script = {key: (list(value) if isinstance(value, list) else [value])
                       for key, value in script.items()}
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv, timeout):
        assert timeout == TIMEOUT
        key = tuple(argv)
        self.calls.append(key)
        if key not in self.script or not self.script[key]:
            raise AssertionError(f"unexpected command {key}")
        outcome = self.script[key].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def result(argv, returncode, stdout="", stderr=""):
    return runner.RunResult(argv=tuple(argv), returncode=returncode,
                            stdout=stdout, stderr=stderr)


AUTH = ("microworkers", "auth", "status")
LOGIN = ("microworkers", "auth", "login", "--credential-type", "browser_session")
TASKS = ("microworkers", "tasks", "list", "--limit", "2500")
RAW_TASKS = [{"campaign_id": "abc", "title": "t", "url": "u", "payment": "$0.10",
              "ttf_minutes": 5, "positions_done": 1, "positions_total": 3}]


@pytest.fixture
def fake(monkeypatch):
    def install(script):
        fake_runner = FakeRunner(script)
        monkeypatch.setattr(runner, "run", fake_runner)
        return fake_runner
    return install


def run_discover(site):
    return discover.discover(site, RUN, TIMEOUT)


def envelope_on_disk(site):
    path = paths.envelope_path(RUN, site)
    data = json.loads(path.read_text(encoding="utf-8"))
    schema.validate_envelope(data)
    return data


def test_unknown_site_is_config_error_and_writes_nothing(project, fake):
    fake({})
    with pytest.raises(ConfigError, match="unknown site 'nope'"):
        run_discover("nope")
    assert not paths.run_dir(RUN).exists()


def test_disabled_site_is_config_error_and_writes_nothing(project, tmp_path, fake):
    """`disabled: true` is an operator off-switch: exit 2, no envelope, no CLI run."""
    from conftest import SITES, write_config
    fake_runner = fake({})
    sites = dict(SITES)
    sites["outlier"] = dict(sites["outlier"], disabled=True)
    write_config(tmp_path, sites)
    with pytest.raises(ConfigError, match="site 'outlier' is disabled"):
        run_discover("outlier")
    assert not paths.run_dir(RUN).exists()
    assert fake_runner.calls == []


def test_no_account(project, fake):
    fake_runner = fake({})
    summary = run_discover("humanrail")
    data = envelope_on_disk("humanrail")
    assert summary == {"site": "humanrail", "status": "no_account",
                       "path": str(paths.envelope_path(RUN, "humanrail")),
                       "task_count": 0}
    assert data["status"] == "no_account" and data["tasks"] == []
    assert data["error"]
    assert fake_runner.calls == []


def test_no_cli(project, fake):
    fake_runner = fake({})
    summary = run_discover("oneforma")
    data = envelope_on_disk("oneforma")
    assert summary["status"] == "no_cli"
    assert data["status"] == "no_cli" and data["tasks"] == [] and data["error"]
    assert fake_runner.calls == []


def test_ok_keeps_raw_list_untouched(project, fake):
    fake_runner = fake({
        AUTH: result(AUTH, 0),
        TASKS: result(TASKS, 0, stdout=json.dumps(RAW_TASKS)),
    })
    summary = run_discover("microworkers")
    data = envelope_on_disk("microworkers")
    assert summary["status"] == "ok" and summary["task_count"] == 1
    assert data["status"] == "ok" and data["error"] is None
    assert data["tasks"] == RAW_TASKS
    assert fake_runner.calls == [AUTH, TASKS]


def test_tasks_list_requests_full_catalog_limit_for_every_site(project, fake):
    """Discovery must never fall back to a site CLI's small default limit."""
    assert discover.TASKS_LIST_LIMIT == 2500
    fake_runner = fake({
        AUTH: result(AUTH, 0),
        TASKS: result(TASKS, 0, stdout="[]"),
    })
    run_discover("microworkers")
    assert fake_runner.calls[-1] == TASKS
    assert TASKS[-2:] == ("--limit", str(discover.TASKS_LIST_LIMIT))


def test_auto_login_success(project, fake):
    fake_runner = fake({
        AUTH: [result(AUTH, 2, stderr="not authenticated"), result(AUTH, 0)],
        LOGIN: result(LOGIN, 0),
        TASKS: result(TASKS, 0, stdout="[]"),
    })
    summary = run_discover("microworkers")
    assert summary["status"] == "ok" and summary["task_count"] == 0
    assert fake_runner.calls == [AUTH, LOGIN, AUTH, TASKS]


def test_auto_login_failure_records_login_stderr(project, fake):
    fake_runner = fake({
        AUTH: [result(AUTH, 2, stderr="not authenticated"),
               result(AUTH, 2, stderr="still not authenticated")],
        LOGIN: result(LOGIN, 1, stderr="stale password rejected"),
    })
    summary = run_discover("microworkers")
    data = envelope_on_disk("microworkers")
    assert summary["status"] == "auth_failed"
    assert data["status"] == "auth_failed" and data["tasks"] == []
    assert "stale password rejected" in data["error"]
    assert fake_runner.calls == [AUTH, LOGIN, AUTH]


def test_auth_status_other_exit_is_error(project, fake):
    fake_runner = fake({AUTH: result(AUTH, 1, stderr="boom")})
    summary = run_discover("microworkers")
    data = envelope_on_disk("microworkers")
    assert summary["status"] == "error"
    assert "exited 1" in data["error"] and "boom" in data["error"]
    assert fake_runner.calls == [AUTH]


def test_recheck_other_exit_after_login_is_error(project, fake):
    fake_runner = fake({
        AUTH: [result(AUTH, 2), result(AUTH, 1, stderr="broken after login")],
        LOGIN: result(LOGIN, 0),
    })
    summary = run_discover("microworkers")
    assert summary["status"] == "error"
    assert "broken after login" in envelope_on_disk("microworkers")["error"]
    assert fake_runner.calls == [AUTH, LOGIN, AUTH]


def test_tasks_list_nonzero_exit_is_error(project, fake):
    fake({AUTH: result(AUTH, 0), TASKS: result(TASKS, 2, stderr="site down")})
    assert run_discover("microworkers")["status"] == "error"
    assert "site down" in envelope_on_disk("microworkers")["error"]


def test_tasks_list_non_json_is_error(project, fake):
    fake({AUTH: result(AUTH, 0), TASKS: result(TASKS, 0, stdout="not json")})
    assert run_discover("microworkers")["status"] == "error"
    assert "not JSON" in envelope_on_disk("microworkers")["error"]


def test_tasks_list_non_list_json_is_error(project, fake):
    fake({AUTH: result(AUTH, 0), TASKS: result(TASKS, 0, stdout='{"a": 1}')})
    data_summary = run_discover("microworkers")
    assert data_summary["status"] == "error"
    data = envelope_on_disk("microworkers")
    assert "expected a list" in data["error"] and data["tasks"] == []


def test_timeout_is_error(project, fake):
    fake({AUTH: result(AUTH, 0),
          TASKS: runner.RunnerError("`microworkers tasks list` timed out after 7s")})
    assert run_discover("microworkers")["status"] == "error"
    assert "timed out" in envelope_on_disk("microworkers")["error"]


def test_missing_executable_is_error(project, fake):
    fake({AUTH: runner.RunnerError("`microworkers` is not installed")})
    assert run_discover("microworkers")["status"] == "error"
    assert "not installed" in envelope_on_disk("microworkers")["error"]


def test_null_auth_command_skips_login(project, fake, tmp_path):
    from conftest import SITES, write_config
    sites = dict(SITES)
    sites["microworkers"] = dict(sites["microworkers"], auth_command=None)
    write_config(tmp_path, sites)
    fake_runner = fake({AUTH: result(AUTH, 2)})
    assert run_discover("microworkers")["status"] == "auth_failed"
    assert fake_runner.calls == [AUTH]


def test_cli_command_prints_summary_and_exits_0(project, fake, runner):
    fake({})
    outcome = runner.invoke(app, ["discover", "humanrail", "--run-id", RUN,
                                  "--timeout", str(TIMEOUT)])
    assert outcome.exit_code == 0, outcome.output
    assert json.loads(outcome.stdout)["status"] == "no_account"


def test_cli_command_unknown_site_exits_2(project, fake, runner):
    fake({})
    outcome = runner.invoke(app, ["discover", "nope", "--run-id", RUN])
    assert outcome.exit_code == 2, outcome.output
    assert "unknown site 'nope'" in outcome.output


def test_missing_config_key_is_config_error(project, tmp_path, fake):
    from conftest import SITES, write_config
    sites = dict(SITES)
    sites["microworkers"] = {k: v for k, v in SITES["microworkers"].items() if k != "account"}
    write_config(tmp_path, sites)
    fake({})
    with pytest.raises(ConfigError, match="missing keys: account"):
        run_discover("microworkers")


def test_timeout_is_passed_to_runner(project, monkeypatch):
    seen = []

    def spy(argv, timeout):
        seen.append(timeout)
        return result(argv, 0, stdout="[]")

    monkeypatch.setattr(runner, "run", spy)
    discover.discover("microworkers", RUN, 42)
    assert seen == [42, 42]
