"""Named browser sessions travel only through private files and SSH stdin."""
import json
import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from n8n_cli.commands import server as commands
from n8n_cli import server
from cli_tools_shared.config import get_tool_data_dir


SENTINEL = "fake-cookie-private-stdin-sentinel"


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "runtime"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    executable = tmp_path / ".local" / "bin" / "sample"
    executable.parent.mkdir(parents=True)
    executable.write_text("fake owning CLI")
    executable.chmod(0o700)
    payload = {"version": 1, "tool": "sample", "profile": "account", "auth_type": "browser_session",
               "identity": {"account_id": "actor-1", "username": "owner"}, "origins": [],
               "cookies": [{"value": SENTINEL}]}
    calls = []
    def local(arguments, **kwargs):
        calls.append(("local", arguments, kwargs))
        output = Path(arguments[arguments.index("--output") + 1])
        output.write_text(json.dumps(payload))
        output.chmod(0o600)
        return subprocess.CompletedProcess(arguments, 0, "{}", SENTINEL)
    def remote(command, **kwargs):
        calls.append(("remote", command, kwargs))
        if command.endswith("--help"):
            return subprocess.CompletedProcess(command, 0, "--stdin --expected-account-id --profile", "")
        result = {"tool": "sample", "profile": "account", "identity": payload["identity"],
                  "imported": True, "verified": True, "active": False}
        return subprocess.CompletedProcess(command, 0, json.dumps(result), "")
    monkeypatch.setattr(subprocess, "run", local)
    monkeypatch.setattr(commands, "run_on_server_raw", remote)
    return calls, payload


def invoke():
    return CliRunner().invoke(commands.app, ["deploy-browser-session", "sample", "--browser-profile", "account",
                                            "--expected-account-id", "actor-1", "--expected-username", "owner"])


def test_bundle_only_on_stdin_and_private_file_removed(deployment):
    calls, payload = deployment
    result = invoke()
    assert result.exit_code == 0, result.output
    transfer = [call for call in calls if call[0] == "remote" and "--stdin" in call[1]][0]
    assert json.loads(transfer[2]["input_data"]) == payload
    assert "--profile account" in transfer[1]
    assert SENTINEL not in str([call[:2] for call in calls]) + result.output
    assert not list((get_tool_data_dir("n8n") / "session-transfers").rglob("session.json"))
    assert not any("npm" in str(call) or "restart" in str(call) for call in calls)


@pytest.mark.parametrize("kind", ["failure", "wrong_actor", "unverified"])
def test_remote_failure_never_claims_ready_or_discloses_bundle(deployment, monkeypatch, kind, caplog):
    calls, payload = deployment
    original = commands.run_on_server_raw
    def remote(command, **kwargs):
        if command.endswith("--help"):
            return original(command, **kwargs)
        result = {"tool": "sample", "profile": "account", "identity": {"account_id": "other", "username": "owner"}, "imported": True, "verified": kind != "unverified"}
        return subprocess.CompletedProcess(command, 1 if kind == "failure" else 0, json.dumps(result), SENTINEL)
    monkeypatch.setattr(commands, "run_on_server_raw", remote)
    caplog.set_level("DEBUG")
    result = invoke()
    assert result.exit_code != 0
    assert SENTINEL not in result.output + caplog.text
    backups = list((get_tool_data_dir("n8n") / "session-transfers").rglob("session.json"))
    assert len(backups) == 1 and backups[0].stat().st_mode & 0o777 == 0o600


def test_missing_remote_capability_fails_before_export(deployment, monkeypatch):
    calls, _ = deployment
    monkeypatch.setattr(commands, "run_on_server_raw", lambda *args, **kwargs: subprocess.CompletedProcess([], 1, "", SENTINEL))
    result = invoke()
    assert result.exit_code != 0
    assert not calls
    assert SENTINEL not in result.output


@pytest.mark.parametrize("local", [True, False])
def test_existing_server_helper_transports_payload_only_as_stdin(monkeypatch, local):
    calls = []
    monkeypatch.setattr(server, "is_local", lambda: local)
    monkeypatch.setattr(server, "get_server_host", lambda: "adam-server")
    def run(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return subprocess.CompletedProcess(arguments, 0, "{}", "")
    monkeypatch.setattr(server.subprocess, "run", run)
    server.run_on_server_raw("owning-cli auth session-import --stdin", input_data=SENTINEL)
    arguments, options = calls[0]
    assert options["input"] == SENTINEL and SENTINEL not in str(arguments)
    assert arguments[0] == ("bash" if local else "ssh")
