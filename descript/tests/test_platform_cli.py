"""Regression tests for the official Descript API CLI wrapper."""

import json
from types import SimpleNamespace

import click
import pytest
from typer.testing import CliRunner

from cli_tools_shared.config import get_tool_data_dir

import descript_cli.platform as platform
from descript_cli import main as main_cli
from descript_cli.commands import api, auth, config, projects
from descript_cli.config import Config
from descript_cli.platform import PlatformCLIError, official_config_validate


runner = CliRunner()


def test_root_import_delegates_to_official_cli(monkeypatch):
    captured = {}

    def fake_run(args, *, profile=None):
        captured["args"] = args
        captured["profile"] = profile
        return 0

    monkeypatch.setattr(api, "run_platform_passthrough", fake_run)

    result = runner.invoke(
        main_cli.app,
        [
            "import",
            "--name",
            "My Project",
            "--media",
            "https://example.com/video.mp4",
            "--no-wait",
            "--language",
            "en",
        ],
    )

    assert result.exit_code == 0
    assert captured["args"] == [
        "import",
        "--name",
        "My Project",
        "--media",
        "https://example.com/video.mp4",
        "--no-wait",
        "--language",
        "en",
    ]
    assert captured["profile"] is None


@pytest.mark.parametrize("team_access_args", [[], ["--team-access", "none"]])
def test_root_import_rejects_folder_without_drive_member_team_access(monkeypatch, team_access_args):
    captured = {}

    def fake_run(args, *, profile=None):
        captured["args"] = args
        return 0

    monkeypatch.setattr(api, "run_platform_passthrough", fake_run)

    result = runner.invoke(
        main_cli.app,
        [
            "import",
            "--name",
            "My Project",
            "--media",
            "https://example.com/video.mp4",
            "--folder",
            "Pluralsight",
            *team_access_args,
        ],
    )

    assert result.exit_code == 1
    assert "Importing into --folder requires --team-access edit, comment, or view." in result.stderr
    assert captured == {}


def test_root_import_with_folder_forwards_team_access(monkeypatch):
    captured = {}

    def fake_run(args, *, profile=None):
        captured["args"] = args
        captured["profile"] = profile
        return 0

    monkeypatch.setattr(api, "run_platform_passthrough", fake_run)

    result = runner.invoke(
        main_cli.app,
        [
            "import",
            "--name",
            "My Project",
            "--media",
            "https://example.com/video.mp4",
            "--folder",
            "Pluralsight",
            "--team-access",
            "edit",
        ],
    )

    assert result.exit_code == 0
    assert captured["args"] == [
        "import",
        "--name",
        "My Project",
        "--media",
        "https://example.com/video.mp4",
        "--folder",
        "Pluralsight",
        "--team-access",
        "edit",
    ]
    assert captured["profile"] is None


def test_root_help_promotes_official_commands_and_omits_api_group():
    result = runner.invoke(main_cli.app, ["--help"])

    assert result.exit_code == 0
    assert "│ api " not in result.stdout
    assert "│ import " in result.stdout
    assert "│ agent " in result.stdout
    assert "│ config " in result.stdout


def test_api_group_is_not_registered():
    result = runner.invoke(main_cli.app, ["api", "--help"])

    assert result.exit_code != 0


def test_auth_login_delegates_to_official_api_key_config(monkeypatch):
    captured = {}

    def fake_run(args, *, profile=None):
        captured["args"] = args
        captured["profile"] = profile
        return 0

    monkeypatch.setattr(auth, "run_platform_passthrough", fake_run)

    with pytest.raises(click.exceptions.Exit) as exc:
        auth._login_handler(SimpleNamespace(), force=False)

    assert exc.value.exit_code == 0
    assert captured["args"] == ["config", "set", "api-key"]
    assert captured["profile"] is None


def test_config_list_supports_standard_list_options(monkeypatch):
    captured = {}

    def fake_run(args, *, capture_output=False, check=True, profile=None):
        captured["args"] = args
        captured["capture_output"] = capture_output
        captured["profile"] = profile
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "Configuration (/tmp/descript-config.json):\n"
                "Active Profile: default\n"
                "\n"
                "  api-key: test-key\n"
                "  api-url: https://descriptapi.com/v1/ (default)\n"
                "  debug: disabled\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(config, "run_platform", fake_run)

    result = runner.invoke(
        main_cli.app,
        [
            "config",
            "list",
            "--limit",
            "1",
            "--filter",
            "key:contains:api",
            "--properties",
            "id,name",
            "--profile",
            "default",
        ],
    )

    assert result.exit_code == 0
    assert captured == {
        "args": ["config", "list"],
        "capture_output": True,
        "profile": "default",
    }
    assert json.loads(result.stdout) == [{"id": "api-key", "name": "api-key"}]


def test_config_list_table_output_uses_parsed_official_values(monkeypatch):
    def fake_run(args, *, capture_output=False, check=True, profile=None):
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "Configuration (/tmp/descript-config.json):\n"
                "Active Profile: default\n"
                "\n"
                "  api-url: https://descriptapi.com/v1/ (default)\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(config, "run_platform", fake_run)

    result = runner.invoke(main_cli.app, ["config", "list", "--table"])

    assert result.exit_code == 0
    assert "api-url" in result.stdout
    assert "default" in result.stdout


def test_config_get_returns_standard_json(monkeypatch):
    captured = {}

    def fake_run(args, *, capture_output=False, check=True, profile=None):
        captured["args"] = args
        captured["capture_output"] = capture_output
        captured["profile"] = profile
        return SimpleNamespace(returncode=0, stdout="test-key\n", stderr="")

    monkeypatch.setattr(config, "run_platform", fake_run)

    result = runner.invoke(
        main_cli.app,
        ["config", "get", "api-key", "--properties", "id,value", "--profile", "default"],
    )

    assert result.exit_code == 0
    assert captured == {
        "args": ["config", "get", "api-key"],
        "capture_output": True,
        "profile": "default",
    }
    assert json.loads(result.stdout) == {"id": "api-key", "value": "test-key"}


def test_config_get_supports_table_output(monkeypatch):
    def fake_run(args, *, capture_output=False, check=True, profile=None):
        return SimpleNamespace(returncode=0, stdout="https://descriptapi.com/v1/\n", stderr="")

    monkeypatch.setattr(config, "run_platform", fake_run)

    result = runner.invoke(main_cli.app, ["config", "get", "api-url", "--table"])

    assert result.exit_code == 0
    assert "api-url" in result.stdout


def test_config_status_uses_official_validate(monkeypatch):
    monkeypatch.setattr(
        "descript_cli.config.official_config_validate",
        lambda: {"api_test": "passed"},
        raising=False,
    )
    monkeypatch.setattr(
        "descript_cli.platform.official_config_validate",
        lambda: {"api_test": "passed"},
    )

    assert Config.__new__(Config).test_connection() == {"api_test": "passed"}


def test_official_config_validate_reports_missing_cli(monkeypatch):
    def missing_cli(*_args, **_kwargs):
        raise PlatformCLIError("Official Descript API CLI not found")

    monkeypatch.setattr("descript_cli.platform.run_platform", missing_cli)

    assert official_config_validate() == {
        "api_test": "failed: Official Descript API CLI not found"
    }


def test_missing_official_cli_bootstraps_platform_package(monkeypatch, tmp_path):
    calls = []

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.delenv("DESCRIPT_API_CLI", raising=False)
    monkeypatch.delenv("DESCRIPT_API_CLI_INSTALL_DIR", raising=False)
    install_dir = get_tool_data_dir("descript") / "platform-cli"
    executable = install_dir / "node_modules" / ".bin" / "descript-api"

    def fake_which(binary):
        if binary == "descript-api":
            return None
        if binary == "npm":
            return "/opt/homebrew/bin/npm"
        raise AssertionError(f"unexpected binary lookup: {binary}")

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        executable.parent.mkdir(parents=True)
        executable.write_text("#!/usr/bin/env node\n")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(platform.shutil, "which", fake_which)
    monkeypatch.setattr(platform.subprocess, "run", fake_run)

    assert platform.platform_executable_path() == str(executable)
    assert calls == [
        (
            [
                "/opt/homebrew/bin/npm",
                "install",
                "--prefix",
                str(install_dir),
                "@descript/platform-cli@latest",
            ],
            {"capture_output": True, "text": True, "timeout": 300},
        )
    ]


def test_projects_list_uses_official_json_helper(monkeypatch):
    monkeypatch.setattr(
        projects,
        "list_projects_json",
        lambda **_kwargs: [
            {
                "id": "project-1",
                "name": "Course Demo",
                "metadata": {"owner": "Adam"},
            }
        ],
    )

    result = runner.invoke(projects.app, ["list", "--properties", "id,metadata.owner"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [
        {"id": "project-1", "metadata.owner": "Adam"}
    ]
