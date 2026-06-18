"""Tests for WordPress theme admin commands and file push support."""

from __future__ import annotations

import hashlib
import json
import subprocess
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from cli_tools_shared.exceptions import ClientError
from wordpress_cli.client import WordPressClient
from wordpress_cli.commands import themes
from wordpress_cli.theme_files import push_theme_file


def _status_stdout(*, exists: bool = True) -> str:
    return "\n".join(
        [
            "sha256sum_available=true",
            "theme_dir_exists=true",
            "remote_dir_exists=true",
            "theme_dir=/srv/www/wp-content/themes/ata",
            "remote_dir=/srv/www/wp-content/themes/ata",
            "remote_path=/srv/www/wp-content/themes/ata/front-page.php",
            f"exists={'true' if exists else 'false'}",
            "bytes=12" if exists else "bytes=",
            "sha256=oldsha" if exists else "sha256=",
            "",
        ]
    )


def test_get_theme_resolves_stylesheet_name_and_textdomain():
    client = WordPressClient.__new__(WordPressClient)
    client.list_themes = MagicMock(
        return_value=[
            {
                "theme": "ata",
                "name": "Adam The Automator",
                "version": "1.0",
                "status": "active",
                "textdomain": "ata-theme",
            }
        ]
    )

    assert client.get_theme("ata")["theme"] == "ata"
    assert client.get_theme("Adam The Automator")["theme"] == "ata"
    assert client.get_theme("ata-theme")["theme"] == "ata"


def test_get_theme_fails_clearly_when_missing():
    client = WordPressClient.__new__(WordPressClient)
    client.list_themes = MagicMock(return_value=[])

    with pytest.raises(ClientError, match="Theme not found: missing"):
        client.get_theme("missing")


def test_push_theme_file_defaults_to_dry_run_without_upload(tmp_path, monkeypatch):
    local_file = tmp_path / "front-page.php"
    local_file.write_text("new homepage", encoding="utf-8")
    calls = []

    def fake_run(cmd, input=None, capture_output=False, text=False):
        calls.append({"cmd": cmd, "input": input})
        assert cmd[0] == "ssh"
        return subprocess.CompletedProcess(cmd, 0, stdout=_status_stdout(), stderr="")

    monkeypatch.setattr("wordpress_cli.theme_files.subprocess.run", fake_run)

    result = push_theme_file(
        theme="ata",
        local_file=local_file,
        remote_file="front-page.php",
        remote_root="/srv/www",
        host="example.com",
        user="deploy",
        backup=True,
    )

    assert result["mode"] == "dry-run"
    assert result["mutated"] is False
    assert result["confirmation_required"] is True
    assert result["backup"]["would_create"] is True
    assert result["destination"]["remote_path"] == "/srv/www/wp-content/themes/ata/front-page.php"
    assert result["connection"] == {
        "host": "example.com",
        "user": "deploy",
        "port": 22,
        "identity_file_provided": False,
    }
    assert [call["cmd"][0] for call in calls] == ["ssh"]


def test_push_theme_file_reports_missing_remote_sha256sum(tmp_path, monkeypatch):
    local_file = tmp_path / "front-page.php"
    local_file.write_text("new homepage", encoding="utf-8")

    def fake_run(cmd, input=None, capture_output=False, text=False):
        stdout = "\n".join(
            [
                "sha256sum_available=false",
                "theme_dir_exists=true",
                "remote_dir_exists=true",
                "theme_dir=/srv/www/wp-content/themes/ata",
                "remote_dir=/srv/www/wp-content/themes/ata",
                "remote_path=/srv/www/wp-content/themes/ata/front-page.php",
                "exists=true",
                "bytes=12",
                "sha256=",
                "",
            ]
        )
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr("wordpress_cli.theme_files.subprocess.run", fake_run)

    with pytest.raises(ClientError, match="Remote host must provide sha256sum"):
        push_theme_file(
            theme="ata",
            local_file=local_file,
            remote_file="front-page.php",
            remote_root="/srv/www",
            host="example.com",
        )


def test_push_theme_file_yes_uploads_with_backup_and_verifies(tmp_path, monkeypatch):
    local_file = tmp_path / "front-page.php"
    content = b"new homepage"
    local_file.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    calls = []

    def fake_run(cmd, input=None, capture_output=False, text=False):
        calls.append({"cmd": cmd, "input": input})
        if cmd[0] == "ssh" and len(calls) == 1:
            return subprocess.CompletedProcess(cmd, 0, stdout=_status_stdout(), stderr="")
        if cmd[0] == "sftp":
            assert "put " in input
            assert str(local_file) in input
            assert "/srv/www/wp-content/themes/ata/.front-page.php.cli-upload-" in input
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if cmd[0] == "ssh":
            stdout = "\n".join(
                [
                    "remote_path=/srv/www/wp-content/themes/ata/front-page.php",
                    f"bytes={len(content)}",
                    f"sha256={digest}",
                    "backup_path=/srv/www/wp-content/themes/ata/front-page.php.bak-20260618T120000Z",
                    "",
                ]
            )
            return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr("wordpress_cli.theme_files.subprocess.run", fake_run)

    result = push_theme_file(
        theme="ata",
        local_file=local_file,
        remote_file="front-page.php",
        remote_root="/srv/www",
        host="example.com",
        port=2222,
        backup=True,
        yes=True,
    )

    assert result["mode"] == "applied"
    assert result["mutated"] is True
    assert result["backup"]["created"] is True
    assert result["readback"] == {
        "bytes": len(content),
        "sha256": digest,
        "matches_local": True,
    }
    assert [call["cmd"][0] for call in calls] == ["ssh", "sftp", "ssh"]
    assert calls[1]["cmd"] == ["sftp", "-b", "-", "-P", "2222", "example.com"]


def test_push_theme_file_rejects_path_traversal(tmp_path):
    local_file = tmp_path / "front-page.php"
    local_file.write_text("new homepage", encoding="utf-8")

    with pytest.raises(ValueError, match="REMOTE_FILE must be a relative path"):
        push_theme_file(
            theme="ata",
            local_file=local_file,
            remote_file="../front-page.php",
            remote_root="/srv/www",
            host="example.com",
        )


def test_themes_file_push_command_prints_json(monkeypatch, tmp_path):
    local_file = tmp_path / "front-page.php"
    local_file.write_text("new homepage", encoding="utf-8")

    def fake_push_theme_file(**kwargs):
        assert kwargs["theme"] == "ata"
        assert kwargs["local_file"] == local_file
        assert kwargs["remote_file"] == "front-page.php"
        assert kwargs["remote_root"] == "/srv/www"
        assert kwargs["host"] == "example.com"
        assert kwargs["backup"] is True
        return {"mode": "dry-run", "mutated": False}

    monkeypatch.setattr(themes, "push_theme_file", fake_push_theme_file)

    result = CliRunner().invoke(
        themes.app,
        [
            "file-push",
            "ata",
            str(local_file),
            "front-page.php",
            "--remote-root",
            "/srv/www",
            "--host",
            "example.com",
            "--backup",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"mode": "dry-run", "mutated": False}
