import json
import subprocess

import pytest
from typer.testing import CliRunner

from ntfy_cli_cli.client import ClientError, Result
from ntfy_cli_cli.main import app


runner = CliRunner()


def _json(result):
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def _run_calls(client):
    return [call for call in client.calls if call[0] == "run"]


def test_auth_status_has_canonical_readiness_schema(fake_client):
    payload = _json(runner.invoke(app, ["auth", "status"]))

    assert list(payload) == ["profiles"]
    assert len(payload["profiles"]) == 1
    profile = payload["profiles"][0]
    assert {"name", "auth_type", "active", "authenticated", "credential_types"} <= profile.keys()
    assert profile["name"] == "default"
    assert profile["auth_type"] == "upstream"
    assert profile["active"] is True
    assert profile["authenticated"] is True
    assert profile["credential_types"]["custom"]["credentials_saved"] is True
    assert profile["credential_types"]["custom"]["authenticated"] is True
    assert profile["readiness"] == {"upstream_available": True, "upstream_version": "ntfy version 2.28.0"}
    assert _run_calls(fake_client) == [("run", ("--version",), None, 10, True)]


def test_publish_maps_every_option_and_sends_body_only_on_stdin(fake_client):
    secret_body = "body that must never appear in argv"
    result = runner.invoke(
        app,
        [
            "messages", "publish", "alerts", secret_body,
            "--title", "Title", "--priority", "urgent", "--tags", "warning,phone",
            "--delay", "10m", "--click", "https://example.com", "--icon", "https://example.com/icon.png",
            "--actions", "view, Open", "--attach", "https://example.com/file", "--markdown",
            "--template", "compact", "--filename", "report.txt", "--sequence-id", "sequence-1",
            "--file", "payload.txt", "--email", "adam@example.com", "--token", "tk_secret",
            "--no-cache", "--no-firebase",
        ],
    )

    payload = _json(result)
    assert payload["id"] == "msg-1"
    call = fake_client.calls[-1]
    assert call == (
        "publish",
        (
            "--title", "Title", "--priority", "urgent", "--tags", "warning,phone",
            "--delay", "10m", "--click", "https://example.com", "--icon", "https://example.com/icon.png",
            "--actions", "view, Open", "--attach", "https://example.com/file", "--template", "compact",
            "--filename", "report.txt", "--sequence-id", "sequence-1", "--file", "payload.txt",
            "--email", "adam@example.com", "--token", "tk_secret", "--markdown", "--no-cache",
            "--no-firebase", "alerts",
        ),
        secret_body,
    )
    assert secret_body not in call[1]


def test_publish_rejects_user_and_token_together(fake_client):
    result = runner.invoke(app, ["messages", "publish", "alerts", "body", "--user", "a:b", "--token", "tk_secret"])
    assert result.exit_code == 2
    assert "either --user or --token" in result.output
    assert not fake_client.calls


def test_publish_table_has_stable_headers_and_row(fake_client):
    result = runner.invoke(app, ["messages", "publish", "alerts", "hello", "--table"])
    assert result.exit_code == 0, result.output
    assert "Topic" in result.stdout
    assert "Message" in result.stdout
    assert "alerts" in result.stdout


def test_trigger_is_topic_only_publish(fake_client):
    payload = _json(runner.invoke(app, ["messages", "trigger", "alerts"]))
    assert payload["topic"] == "alerts"
    assert fake_client.calls[-1] == ("publish", ("alerts",), None)


def test_poll_maps_flags_limits_rows_and_returns_array(fake_client):
    payload = _json(
        runner.invoke(
            app,
            ["messages", "poll", "alerts", "--since", "1h", "--scheduled", "--token", "tk_secret", "--limit", "1"],
        )
    )
    assert payload == [fake_client.poll_result[0]]
    assert fake_client.calls[-1] == (
        "poll",
        ("--since", "1h", "--token", "tk_secret", "--scheduled", "alerts"),
    )


def test_poll_table_has_headers_and_all_limited_rows(fake_client):
    result = runner.invoke(app, ["messages", "poll", "alerts", "--limit", "2", "--table"])
    assert result.exit_code == 0, result.output
    assert "Topic" in result.stdout
    assert "Message" in result.stdout
    assert "first" in result.stdout
    assert "second" in result.stdout


class FakeProcess:
    def __init__(self, argv, *, returncode=0):
        self.argv = argv
        self.returncode = returncode

    def wait(self):
        return self.returncode


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (["messages", "subscribe", "alerts", "--since", "1h", "--scheduled", "--token", "tk_secret"], ["/fake/ntfy", "subscribe", "--since", "1h", "--token", "tk_secret", "--scheduled", "alerts"]),
        (["messages", "subscribe-config", "--config", "/tmp/client.yml"], ["/fake/ntfy", "subscribe", "--from-config", "--config", "/tmp/client.yml"]),
    ],
)
def test_stream_commands_forward_exact_argv(monkeypatch, fake_client, command, expected):
    seen = []

    def popen(argv):
        seen.append(argv)
        return FakeProcess(argv)

    monkeypatch.setattr(subprocess, "Popen", popen)
    result = runner.invoke(app, command)
    assert result.exit_code == 0, result.output
    assert seen == [expected]


def test_subscribe_preserves_interrupt_exit_code(monkeypatch, fake_client):
    monkeypatch.setattr(subprocess, "Popen", lambda argv: FakeProcess(argv, returncode=130))
    result = runner.invoke(app, ["messages", "subscribe", "alerts"])
    assert result.exit_code == 130


def test_subscribe_wraps_process_start_error(monkeypatch, fake_client):
    def fail(_argv):
        raise OSError("process unavailable")

    monkeypatch.setattr(subprocess, "Popen", fail)
    result = runner.invoke(app, ["messages", "subscribe", "alerts"])
    assert result.exit_code == 1
    assert "process unavailable" in result.output
    assert result.exception is None or not isinstance(result.exception, OSError)


@pytest.mark.parametrize(
    ("command", "expected_argv"),
    [
        (["server", "users", "list"], ("user", "list")),
        (["server", "users", "get", "alice"], ("user", "list", "alice")),
        (["server", "users", "create", "alice", "--role", "admin"], ("user", "add", "--role", "admin", "alice")),
        (["server", "users", "delete", "alice", "--force"], ("user", "del", "alice")),
        (["server", "users", "role", "update", "alice", "admin"], ("user", "change-role", "alice", "admin")),
        (["server", "access", "list"], ("access",)),
        (["server", "access", "get", "alice"], ("access", "alice")),
        (["server", "access", "set", "alice", "alerts", "rw", "--force"], ("access", "alice", "alerts", "rw")),
        (["server", "access", "reset", "--username", "alice", "--topic", "alerts", "--force"], ("access", "--reset", "alice", "alerts")),
        (["server", "tokens", "list", "--username", "alice"], ("token", "list", "alice")),
        (["server", "tokens", "get", "alice"], ("token", "list", "alice")),
        (["server", "tokens", "create", "alice", "--expires", "24h", "--label", "phone", "--force"], ("token", "add", "--expires", "24h", "--label", "phone", "alice")),
        (["server", "tokens", "delete", "alice", "tk_secret", "--force"], ("token", "remove", "alice", "tk_secret")),
        (["server", "tokens", "generate"], ("token", "generate")),
    ],
)
def test_server_commands_map_exact_upstream_argv(fake_client, command, expected_argv):
    result = runner.invoke(app, command)
    assert result.exit_code == 0, result.output
    assert ("require_server",) in fake_client.calls
    assert _run_calls(fake_client)[-1][1] == expected_argv


def test_serve_forwards_extra_arguments(monkeypatch, fake_client):
    seen = []

    def popen(argv):
        seen.append(argv)
        return FakeProcess(argv)

    monkeypatch.setattr(subprocess, "Popen", popen)
    result = runner.invoke(app, ["server", "serve", "--listen-http", ":8081"])
    assert result.exit_code == 0, result.output
    assert seen == [["/fake/ntfy", "serve", "--listen-http", ":8081"]]


def test_user_password_uses_stdin_not_argv(fake_client):
    secret = "correct horse battery staple"
    result = runner.invoke(app, ["server", "users", "password", "update", "alice", "--password-stdin"], input=f"{secret}\n")
    assert result.exit_code == 0, result.output
    call = _run_calls(fake_client)[-1]
    assert call[1] == ("user", "change-pass", "alice")
    assert secret not in call[1]
    assert call[2] == secret or call[2] == secret + "\n"


@pytest.mark.parametrize(
    "command",
    [
        ["server", "users", "delete", "alice"],
        ["server", "access", "set", "alice", "alerts", "rw"],
        ["server", "access", "reset", "--username", "alice", "--topic", "alerts"],
        ["server", "tokens", "create", "alice"],
        ["server", "tokens", "delete", "alice", "tk_secret"],
    ],
)
def test_destructive_server_commands_require_force(fake_client, command):
    result = runner.invoke(app, command)
    assert result.exit_code == 1
    assert "Re-run with --force" in result.output
    assert not _run_calls(fake_client)


@pytest.mark.parametrize(
    "command",
    [
        ["server", "users", "list"],
        ["server", "access", "list"],
        ["server", "tokens", "list"],
    ],
)
def test_every_server_list_exposes_required_options(command):
    result = runner.invoke(app, [*command, "--help"])
    assert result.exit_code == 0, result.output
    for option in ("--table", "--limit", "--filter", "--properties"):
        assert option in result.stdout


@pytest.mark.parametrize(
    ("command", "expected_key"),
    [
        (["server", "users", "list"], "user"),
        (["server", "access", "list"], "access"),
        (["server", "tokens", "list"], "token"),
    ],
)
def test_server_lists_emit_json_arrays(fake_client, command, expected_key):
    payload = _json(runner.invoke(app, command))
    assert isinstance(payload, list)
    assert payload
    assert expected_key in payload[0]


@pytest.mark.parametrize(
    "command",
    [
        ["server", "users", "get", "alice"],
        ["server", "access", "get", "alice"],
        ["server", "tokens", "get", "alice"],
    ],
)
def test_server_get_commands_preserve_every_upstream_row(fake_client, command):
    payload = _json(runner.invoke(app, command))

    assert len(payload) == 2


@pytest.mark.parametrize(
    "command",
    [
        ["server", "users", "list"],
        ["server", "access", "list"],
        ["server", "tokens", "list"],
    ],
)
def test_server_lists_apply_filter_limit_properties_and_table(fake_client, command):
    result = runner.invoke(
        app,
        [*command, "--filter", "user:eq:alice", "--limit", "1", "--properties", "user", "--table"],
    )
    assert result.exit_code == 0, result.output
    assert "User" in result.stdout
    assert "alice" in result.stdout
    assert "root" not in result.stdout


def test_server_capability_gate_is_clear(fake_client):
    fake_client.server_error = ClientError("This ntfy build has no server commands. macOS packages support publish and subscribe only.")
    result = runner.invoke(app, ["server", "users", "list"])
    assert result.exit_code == 1
    assert "no server commands" in result.output
    assert not _run_calls(fake_client)


def test_upstream_preserves_arguments_and_exit_code(fake_client):
    fake_client.passthrough = lambda args: fake_client.calls.append(("passthrough", tuple(args))) or 17
    result = runner.invoke(app, ["upstream", "publish", "--unknown", "value", "topic"])
    assert result.exit_code == 17
    assert fake_client.calls[-1] == ("passthrough", ("publish", "--unknown", "value", "topic"))


def test_command_error_stays_on_stderr_contract(fake_client):
    fake_client.run_result = Result("", "permission denied", 1)
    result = runner.invoke(app, ["server", "users", "list"])
    assert result.exit_code != 0
    assert "permission denied" in result.output
