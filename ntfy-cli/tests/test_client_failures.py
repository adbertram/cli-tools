import subprocess
from pathlib import Path

import pytest

import ntfy_cli_cli.client as client_module
from ntfy_cli_cli.client import ClientError, NtfyClient, Result


class FakeConfig:
    def __init__(self, executable: str):
        self.executable = executable

    def get_cli_executable(self) -> str:
        return self.executable


def _client(executable: str) -> NtfyClient:
    client = NtfyClient.__new__(NtfyClient)
    client.config = FakeConfig(executable)
    return client


def test_missing_upstream_executable_has_install_guidance(monkeypatch):
    client = _client("ntfy-not-installed")
    monkeypatch.setattr(client_module.shutil, "which", lambda _name: None)
    with pytest.raises(ClientError, match="executable not found.*Homebrew"):
        _ = client.executable


def test_finite_command_timeout_is_wrapped(monkeypatch, tmp_path):
    executable = tmp_path / "ntfy"
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)
    client = _client(str(executable))

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired([str(executable), "publish"], 7)

    monkeypatch.setattr(client_module.subprocess, "run", timeout)
    with pytest.raises(ClientError, match="timed out after 7 seconds"):
        client.run(("publish",), timeout=7)


def test_nonzero_finite_command_uses_upstream_error(monkeypatch, tmp_path):
    executable = tmp_path / "ntfy"
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)
    client = _client(str(executable))
    completed = subprocess.CompletedProcess([str(executable)], 23, stdout="", stderr="upstream broke\n")
    monkeypatch.setattr(client_module.subprocess, "run", lambda *_args, **_kwargs: completed)
    with pytest.raises(ClientError, match="upstream broke"):
        client.run(("user", "list"))


def test_run_can_return_nonzero_without_check(monkeypatch, tmp_path):
    executable = tmp_path / "ntfy"
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)
    client = _client(str(executable))
    completed = subprocess.CompletedProcess([str(executable)], 19, stdout="data", stderr="warning")
    monkeypatch.setattr(client_module.subprocess, "run", lambda *_args, **_kwargs: completed)
    assert client.run(("x",), check=False) == Result("data", "warning", 19)


def test_successful_upstream_warning_is_forwarded_to_stderr(monkeypatch, tmp_path, capsys):
    executable = tmp_path / "ntfy"
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)
    client = _client(str(executable))
    completed = subprocess.CompletedProcess([str(executable)], 0, stdout='{"id":"one"}', stderr="upstream warning\n")
    monkeypatch.setattr(client_module.subprocess, "run", lambda *_args, **_kwargs: completed)

    result = client.run(("publish",))

    captured = capsys.readouterr()
    assert result.stdout == '{"id":"one"}'
    assert captured.out == ""
    assert captured.err == "upstream warning\n"


def test_publish_rejects_malformed_json(monkeypatch, tmp_path):
    executable = tmp_path / "ntfy"
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)
    client = _client(str(executable))
    monkeypatch.setattr(client, "run", lambda *_args, **_kwargs: Result("not json", "", 0))
    with pytest.raises(ClientError, match="malformed JSON"):
        client.publish(("topic",), "body")


@pytest.mark.parametrize("payload", ["not json\n", "[]\n"])
def test_poll_rejects_malformed_ndjson_rows(monkeypatch, tmp_path, payload):
    executable = tmp_path / "ntfy"
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)
    client = _client(str(executable))
    monkeypatch.setattr(client, "run", lambda *_args, **_kwargs: Result(payload, "", 0))
    with pytest.raises(ClientError, match="malformed NDJSON|non-object NDJSON"):
        client.poll(("topic",))


def test_passthrough_preserves_signal_and_interrupt_codes(monkeypatch, tmp_path):
    executable = tmp_path / "ntfy"
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)
    client = _client(str(executable))

    class Process:
        def __init__(self, code):
            self.code = code

        def wait(self):
            return self.code

    for code in (-15, 130):
        monkeypatch.setattr(client_module.subprocess, "Popen", lambda _argv, code=code: Process(code))
        assert client.passthrough(("subscribe", "topic")) == code


def test_passthrough_process_error_is_wrapped(monkeypatch, tmp_path):
    executable = tmp_path / "ntfy"
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)
    client = _client(str(executable))

    def fail(_argv):
        raise OSError("cannot execute")

    monkeypatch.setattr(client_module.subprocess, "Popen", fail)
    with pytest.raises(ClientError, match="cannot execute"):
        client.passthrough(("--help",))


def test_server_capability_probe_detects_supported_and_unsupported(monkeypatch, tmp_path):
    executable = tmp_path / "ntfy"
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)
    client = _client(str(executable))
    monkeypatch.setattr(
        client,
        "run",
        lambda *_args, **_kwargs: Result("COMMANDS:\n  serve    Run server\n  user     Manage users\n  access   Manage access\n  token    Manage tokens\n", "", 0),
    )
    assert client.capabilities() == {"serve", "user", "access", "token"}
    client.require_server()

    monkeypatch.setattr(client, "run", lambda *_args, **_kwargs: Result("COMMANDS:\n  publish  Publish\n", "", 0))
    with pytest.raises(ClientError, match="macOS packages support publish and subscribe only"):
        client.require_server()


def test_activity_log_never_receives_stdin_or_token_value(monkeypatch, tmp_path):
    executable = tmp_path / "ntfy"
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)
    client = _client(str(executable))
    completed = subprocess.CompletedProcess([str(executable)], 0, stdout='{"id":"one"}', stderr="")
    monkeypatch.setattr(client_module.subprocess, "run", lambda *_args, **_kwargs: completed)
    messages = []
    monkeypatch.setattr(client_module.activity, "info", lambda message, *args: messages.append(message % args))

    body = "body-secret-193"
    token = "plain-secret-token-812"
    client.run(("publish", "--token", token, "topic"), stdin=body)

    transcript = "\n".join(messages)
    assert body not in transcript
    assert token not in transcript


def test_publish_body_is_forwarded_as_stdin_not_argv(monkeypatch, tmp_path):
    executable = tmp_path / "ntfy"
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)
    client = _client(str(executable))
    seen = {}

    def run(argv, **kwargs):
        seen["argv"] = argv
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout='{"id":"one"}', stderr="")

    monkeypatch.setattr(client_module.subprocess, "run", run)
    body = "stdin-only-body"
    client.publish(("topic",), body)
    assert seen["input"] == body
    assert body not in seen["argv"]
