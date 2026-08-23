"""Synthetic tests for metadata-only LastPass item-field discovery."""
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from typer.testing import CliRunner

from lastpass_cli.client import LastpassClient, MULTIPLE_MATCHES_SENTINEL
from lastpass_cli.commands import items as items_module


SYNTHETIC_PASSWORD = "field-discovery-password-value"
SYNTHETIC_OTP = "field-discovery-otp-value"
SYNTHETIC_TOTP = "field-discovery-totp-seed"
SYNTHETIC_NOTES = "field-discovery-notes-value"
SHOW_OUTPUT = "\n".join(
    [
        "Work/Synthetic Entry [id: 1234567890]",
        "URL: https://example.invalid",
        "Username: synthetic-user",
        f"Password: {SYNTHETIC_PASSWORD}",
        f"OTP: {SYNTHETIC_OTP}",
        f"TOTP Seed: {SYNTHETIC_TOTP}",
        "Environment: synthetic-staging",
        f"Notes: {SYNTHETIC_NOTES}",
    ]
)
EXPECTED_FIELDS = [
    {"name": "URL", "sensitive": False},
    {"name": "Username", "sensitive": False},
    {"name": "Password", "sensitive": True},
    {"name": "OTP", "sensitive": True},
    {"name": "TOTP Seed", "sensitive": True},
    {"name": "Environment", "sensitive": False},
    {"name": "Notes", "sensitive": False},
]
EXPECTED_MATCHES = [
    {
        "id": "1234567890",
        "name": "Synthetic Entry",
        "group": "Work",
        "full_path": "Work/Synthetic Entry",
    },
    {
        "id": "9876543210",
        "name": "Synthetic Entry",
        "group": "Personal",
        "full_path": "Personal/Synthetic Entry",
    },
]
MULTIPLE_MATCH_OUTPUT = "\n".join(
    [
        MULTIPLE_MATCHES_SENTINEL,
        "Work/Synthetic Entry [id: 1234567890]",
        "Personal/Synthetic Entry [id: 9876543210]",
    ]
)
HEADER_ONLY_OUTPUT = "Work/Synthetic Entry [id: 1234567890]"


def _client_with_show_output(output: str) -> LastpassClient:
    client = LastpassClient.__new__(LastpassClient)

    def fake_run_command(args, **kwargs):
        assert args == ["show", "Synthetic Entry"]
        assert kwargs == {}
        return subprocess.CompletedProcess(args, 0, output, "")

    client._run_command = fake_run_command
    return client


def _client_with_subprocess() -> LastpassClient:
    client = LastpassClient.__new__(LastpassClient)
    client.config = type(
        "_Config",
        (),
        {
            "cli_command": "lpass",
            "get_cli_executable": lambda self: "/synthetic/lpass",
        },
    )()
    return client


def _assert_no_field_values(text: str) -> None:
    assert SYNTHETIC_PASSWORD not in text
    assert SYNTHETIC_OTP not in text
    assert SYNTHETIC_TOTP not in text
    assert SYNTHETIC_NOTES not in text


def test_fields_command_outputs_exact_metadata_only_json(monkeypatch):
    monkeypatch.setattr(
        items_module,
        "get_client",
        lambda: _client_with_show_output(SHOW_OUTPUT),
    )

    result = CliRunner().invoke(items_module.app, ["fields", "Synthetic Entry"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == EXPECTED_FIELDS
    _assert_no_field_values(result.output)


def test_fields_command_excludes_header_metadata(monkeypatch):
    monkeypatch.setattr(
        items_module,
        "get_client",
        lambda: _client_with_show_output(HEADER_ONLY_OUTPUT),
    )

    result = CliRunner().invoke(items_module.app, ["fields", "Synthetic Entry"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == []


def test_fields_command_outputs_metadata_only_table(monkeypatch):
    monkeypatch.setattr(
        items_module,
        "get_client",
        lambda: _client_with_show_output(SHOW_OUTPUT),
    )

    result = CliRunner().invoke(
        items_module.app,
        ["fields", "Synthetic Entry", "--table"],
    )

    assert result.exit_code == 0, result.output
    assert "Field" in result.stdout
    assert "Sensitive" in result.stdout
    assert "TOTP Seed" in result.stdout
    _assert_no_field_values(result.output)


@pytest.mark.parametrize("extra_args", [[], ["--table"]])
def test_fields_command_preserves_exact_ambiguous_match_contract(
    monkeypatch,
    extra_args,
):
    monkeypatch.setattr(
        items_module,
        "get_client",
        lambda: _client_with_show_output(MULTIPLE_MATCH_OUTPUT),
    )

    result = CliRunner().invoke(
        items_module.app,
        ["fields", "Synthetic Entry", *extra_args],
    )

    assert result.exit_code == 3
    assert json.loads(result.stdout) == {
        "error": "multiple_matches",
        "query": "Synthetic Entry",
        "matches": EXPECTED_MATCHES,
    }
    _assert_no_field_values(result.output)


def test_run_command_never_logs_raw_output(monkeypatch, caplog):
    client = _client_with_subprocess()
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            0,
            SYNTHETIC_PASSWORD,
            SYNTHETIC_TOTP,
        ),
    )
    caplog.set_level(logging.DEBUG, logger="lastpass.debug")

    result = client._run_command(["show", "Synthetic Entry"])

    assert result.stdout == SYNTHETIC_PASSWORD
    _assert_no_field_values(caplog.text)
    assert "stdout_bytes=" in caplog.text
    assert "stderr_bytes=" in caplog.text


@pytest.mark.parametrize(
    ("stdout", "stderr"),
    [
        (SYNTHETIC_PASSWORD, ""),
        ("", SYNTHETIC_TOTP),
    ],
)
def test_fields_command_failure_never_discloses_upstream_output(
    monkeypatch,
    caplog,
    stdout,
    stderr,
):
    client = _client_with_subprocess()
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            1,
            stdout,
            stderr,
        ),
    )
    monkeypatch.setattr(items_module, "get_client", lambda: client)
    caplog.set_level(logging.DEBUG, logger="lastpass.debug")

    result = CliRunner().invoke(items_module.app, ["fields", "Synthetic Entry"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "lpass command failed (exit 1)" in result.stderr
    _assert_no_field_values(result.output)
    _assert_no_field_values(caplog.text)


def _write_fake_lpass(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

Path(os.environ["FAKE_LPASS_ARGV_LOG"]).write_text(json.dumps(sys.argv[1:]))
mode = os.environ["FAKE_LPASS_MODE"]
if sys.argv[1:] != ["show", "Synthetic Entry"]:
    print("unexpected fake lpass arguments", file=sys.stderr)
    raise SystemExit(9)
if mode == "show":
    print(os.environ["FAKE_LPASS_SHOW_OUTPUT"])
    raise SystemExit(0)
if mode == "multiple":
    print(os.environ["FAKE_LPASS_MULTIPLE_OUTPUT"])
    raise SystemExit(0)
if mode == "failure_stdout":
    print(os.environ["FAKE_LPASS_FAILURE_VALUE"])
    raise SystemExit(1)
if mode == "failure_stderr":
    print(os.environ["FAKE_LPASS_FAILURE_VALUE"], file=sys.stderr)
    raise SystemExit(1)
raise SystemExit(8)
"""
    )
    path.chmod(0o700)


def _public_cli_env(tmp_path: Path, *, mode: str) -> tuple[dict, Path]:
    fake_lpass = tmp_path / "lpass"
    _write_fake_lpass(fake_lpass)
    argv_log = tmp_path / "argv.json"
    env = os.environ.copy()
    env.update(
        {
            "DEBUG": "1",
            "FAKE_LPASS_ARGV_LOG": str(argv_log),
            "FAKE_LPASS_FAILURE_VALUE": SYNTHETIC_TOTP,
            "FAKE_LPASS_MODE": mode,
            "FAKE_LPASS_MULTIPLE_OUTPUT": MULTIPLE_MATCH_OUTPUT,
            "FAKE_LPASS_SHOW_OUTPUT": SHOW_OUTPUT,
            "PATH": f"{tmp_path}{os.pathsep}{env['PATH']}",
            "XDG_DATA_HOME": str(tmp_path / "xdg"),
        }
    )
    return env, argv_log


def _run_public_fields(
    tmp_path: Path,
    *,
    mode: str,
    table: bool = False,
) -> subprocess.CompletedProcess:
    launcher = shutil.which("lastpass")
    assert launcher is not None
    env, argv_log = _public_cli_env(tmp_path, mode=mode)
    args = [launcher, "items", "fields", "Synthetic Entry"]
    if table:
        args.append("--table")

    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert json.loads(argv_log.read_text()) == ["show", "Synthetic Entry"]
    return result


@pytest.mark.parametrize("table", [False, True])
def test_public_cli_uses_fake_lpass_without_value_leakage(tmp_path, table):
    result = _run_public_fields(tmp_path, mode="show", table=table)

    assert result.returncode == 0, result.stderr
    if table:
        assert "TOTP Seed" in result.stdout
        assert "Sensitive" in result.stdout
    else:
        assert json.loads(result.stdout) == EXPECTED_FIELDS
    _assert_no_field_values(result.stdout)
    _assert_no_field_values(result.stderr)


@pytest.mark.parametrize("table", [False, True])
def test_public_cli_preserves_ambiguous_exit_three_with_fake_lpass(
    tmp_path,
    table,
):
    result = _run_public_fields(tmp_path, mode="multiple", table=table)

    assert result.returncode == 3
    assert json.loads(result.stdout) == {
        "error": "multiple_matches",
        "query": "Synthetic Entry",
        "matches": EXPECTED_MATCHES,
    }
    _assert_no_field_values(result.stdout)
    _assert_no_field_values(result.stderr)


@pytest.mark.parametrize("mode", ["failure_stdout", "failure_stderr"])
def test_public_cli_redacts_fake_lpass_failures(tmp_path, mode):
    result = _run_public_fields(tmp_path, mode=mode)

    assert result.returncode == 1
    assert result.stdout == ""
    assert "lpass command failed (exit 1)" in result.stderr
    _assert_no_field_values(result.stdout)
    _assert_no_field_values(result.stderr)


def test_fields_command_declares_custom_credentials():
    assert items_module.COMMAND_CREDENTIALS["fields"] == ["custom"]
