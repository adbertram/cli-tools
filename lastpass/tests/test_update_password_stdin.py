"""Tests for safe password input on ``lastpass items update``."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from typer.testing import CliRunner

from lastpass_cli.commands import items as items_module


SYNTHETIC_PASSWORD = "stdin-only-secret value"


class _FakeClient:
    def __init__(self):
        self.calls = []

    def update_item(self, **kwargs):
        self.calls.append(kwargs)
        return {"success": True, "message": "Updated password for 'Synthetic Entry'"}


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def fake_client(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(items_module, "get_client", lambda: client)
    return client


def test_update_reads_password_from_standard_input_without_output(runner, fake_client):
    result = runner.invoke(
        items_module.app,
        ["update", "Synthetic Entry", "--password-stdin"],
        input=SYNTHETIC_PASSWORD + "\n",
    )

    assert result.exit_code == 0, result.output
    assert fake_client.calls == [
        {
            "item_id": "Synthetic Entry",
            "username": None,
            "password": SYNTHETIC_PASSWORD,
            "url": None,
            "notes": None,
            "name": None,
        }
    ]
    assert SYNTHETIC_PASSWORD not in result.output


def test_update_rejects_password_and_password_stdin_together(runner, fake_client):
    result = runner.invoke(
        items_module.app,
        [
            "update",
            "Synthetic Entry",
            "--password",
            SYNTHETIC_PASSWORD,
            "--password-stdin",
        ],
        input="unused-input\n",
    )

    assert result.exit_code == 1
    assert fake_client.calls == []
    assert "--password and --password-stdin cannot be used together" in result.stderr
    assert SYNTHETIC_PASSWORD not in result.output


def test_update_rejects_empty_password_standard_input(runner, fake_client):
    result = runner.invoke(
        items_module.app,
        ["update", "Synthetic Entry", "--password-stdin"],
        input="\n",
    )

    assert result.exit_code == 1
    assert fake_client.calls == []
    assert "Password standard input is empty" in result.stderr


def _write_fake_lpass(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

Path(os.environ["FAKE_LPASS_ARGV_LOG"]).write_text(json.dumps(sys.argv[1:]))
Path(os.environ["FAKE_LPASS_STDIN_LOG"]).write_text(sys.stdin.read())
raise SystemExit(0)
"""
    )
    path.chmod(0o700)


def test_public_cli_passes_password_only_through_standard_input(tmp_path):
    launcher = shutil.which("lastpass")
    assert launcher is not None
    fake_lpass = tmp_path / "lpass"
    _write_fake_lpass(fake_lpass)
    argv_log = tmp_path / "argv.json"
    stdin_log = tmp_path / "stdin.txt"
    env = os.environ.copy()
    env.update(
        {
            "FAKE_LPASS_ARGV_LOG": str(argv_log),
            "FAKE_LPASS_STDIN_LOG": str(stdin_log),
            "PATH": f"{tmp_path}{os.pathsep}{env['PATH']}",
            "XDG_DATA_HOME": str(tmp_path / "xdg"),
        }
    )

    result = subprocess.run(
        [launcher, "items", "update", "Synthetic Entry", "--password-stdin"],
        input=SYNTHETIC_PASSWORD + "\n",
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(argv_log.read_text()) == [
        "edit",
        "--non-interactive",
        "--password",
        "Synthetic Entry",
    ]
    assert stdin_log.read_text() == SYNTHETIC_PASSWORD + "\n"
    assert SYNTHETIC_PASSWORD not in result.stdout
    assert SYNTHETIC_PASSWORD not in result.stderr
