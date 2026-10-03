"""Regression tests for the CLI selection gate in conftest.py."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

import conftest as cli_conftest
from cli_test_utils import get_uv_tool_venv_dir

from conftest import (
    CLI_NAME_REQUIRED_MESSAGE,
    _resolve_cli_dir_from_executable,
    _resolve_cli_executable,
    _required_credential_types_for_list_commands,
    _required_profile_auth_types_for_list_commands,
    _selected_tests_need_cli_name,
)


def _item_with_fixtures(*fixturenames: str):
    return SimpleNamespace(fixturenames=fixturenames)


def test_selected_tests_need_cli_name_when_cli_fixture_is_selected() -> None:
    items = [
        _item_with_fixtures("tmp_path"),
        _item_with_fixtures("cli_dir", "cli_name", "test_config"),
    ]

    assert _selected_tests_need_cli_name(items) is True


def test_selected_tests_do_not_need_cli_name_for_self_contained_harness_units() -> None:
    items = [
        _item_with_fixtures("tmp_path", "monkeypatch"),
        _item_with_fixtures(),
    ]

    assert _selected_tests_need_cli_name(items) is False


def test_cli_gate_message_clarifies_force_is_not_live_cli_execution() -> None:
    assert "Use --cli-name <name> to execute CLI-dependent tests." in CLI_NAME_REQUIRED_MESSAGE
    assert "--force only confirms batch/collect-only harness work" in CLI_NAME_REQUIRED_MESSAGE


def test_cli_executable_override_is_used_before_shared_launcher(tmp_path) -> None:
    executable = tmp_path / "worktree-cli"
    executable.write_text("#!/usr/bin/env bash\nexit 0\n")
    executable.chmod(0o755)

    assert _resolve_cli_executable("demo", tmp_path, str(executable)) == str(executable.resolve())


@pytest.mark.parametrize("name", ["missing", "not-executable"])
def test_cli_executable_override_must_be_an_executable_file(tmp_path, name) -> None:
    executable = tmp_path / name
    if name == "not-executable":
        executable.write_text("#!/usr/bin/env bash\nexit 0\n")

    with pytest.raises(pytest.fail.Exception, match="CLI executable override is missing"):
        _resolve_cli_executable("demo", tmp_path, str(executable))


def test_personal_worktree_override_resolves_source_before_global_launcher(
    tmp_path, monkeypatch
) -> None:
    cli_tools_root = tmp_path / "worktree"
    tool_dir = cli_tools_root / "_personal" / "demo"
    tool_dir.mkdir(parents=True)
    (tool_dir / "pyproject.toml").write_text("[project]\nname = 'demo'\n")
    executable = tool_dir / ".venv" / "bin" / "demo"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/usr/bin/env bash\nexit 0\n")
    executable.chmod(0o755)

    monkeypatch.setattr(
        cli_conftest,
        "_resolve_cli_dir_from_launcher",
        lambda _cli_name: pytest.fail("must not use the shared launcher"),
    )

    assert _resolve_cli_dir_from_executable(str(executable)) == tool_dir
    assert cli_conftest.cli_dir.__wrapped__(
        "demo", cli_tools_root, str(executable)
    ) == tool_dir


def test_personal_installed_cli_uses_launcher_source_without_override(
    tmp_path, monkeypatch
) -> None:
    cli_tools_root = tmp_path / "worktree"
    tool_dir = cli_tools_root / "_personal" / "ata-blog"
    tool_dir.mkdir(parents=True)
    (tool_dir / "pyproject.toml").write_text("[project]\nname = 'ata-blog-cli'\n")

    monkeypatch.setattr(
        cli_conftest,
        "_resolve_cli_dir_from_executable",
        lambda _cli_executable: pytest.fail("must not parse a launcher as a worktree override"),
    )
    monkeypatch.setattr(
        cli_conftest,
        "_resolve_cli_dir_from_launcher",
        lambda cli_name: tool_dir if cli_name == "ata-blog" else pytest.fail("wrong CLI"),
    )

    assert cli_conftest.cli_dir.__wrapped__("ata-blog", cli_tools_root, None) == tool_dir


def test_worktree_override_requires_project_virtualenv_layout(tmp_path) -> None:
    executable = tmp_path / "not-a-worktree-executable"
    executable.write_text("#!/usr/bin/env bash\nexit 0\n")
    executable.chmod(0o755)

    with pytest.raises(RuntimeError, match="must be under <tool-dir>/.venv/bin/<tool>"):
        _resolve_cli_dir_from_executable(str(executable))


def test_explicit_worktree_executable_selects_its_project_environment(
    tmp_path, monkeypatch
) -> None:
    venv_dir = tmp_path / "worktree" / "demo" / ".venv"
    venv_bin = venv_dir / "bin"
    venv_bin.mkdir(parents=True)
    (venv_dir / "pyvenv.cfg").write_text("home = /usr/bin\n")
    (venv_bin / "python").write_text("")
    executable = venv_bin / "demo"
    executable.write_text("#!/usr/bin/env bash\nexit 0\n")
    executable.chmod(0o755)
    monkeypatch.setenv("CLI_TOOL_TEST_EXECUTABLE", str(executable))

    assert get_uv_tool_venv_dir(tmp_path, "uninstalled-demo") == venv_dir


def test_pytest_configure_exposes_the_executable_override(tmp_path) -> None:
    environment_key = "CLI_TOOL_TEST_EXECUTABLE"
    original_was_set = environment_key in os.environ
    original_value = os.environ.get(environment_key)
    executable = tmp_path / "worktree-cli"
    executable.write_text("#!/usr/bin/env bash\nexit 0\n")
    executable.chmod(0o755)
    config = SimpleNamespace(getoption=lambda option: str(executable))

    try:
        cli_conftest.pytest_configure(config)

        assert os.environ[environment_key] == str(executable.resolve())

        cli_conftest.pytest_configure(SimpleNamespace(getoption=lambda option: None))
        assert environment_key not in os.environ
    finally:
        if original_was_set:
            assert original_value is not None
            os.environ[environment_key] = original_value
        else:
            os.environ.pop(environment_key, None)


def test_list_command_auth_gate_ignores_no_auth_marker(tmp_path, monkeypatch) -> None:
    cli_dir = tmp_path / "tool"
    package_dir = cli_dir / "demo_cli"
    commands_dir = package_dir / "commands"
    commands_dir.mkdir(parents=True)
    (package_dir / "config.py").write_text(
        "CREDENTIAL_TYPES = [CredentialType.CUSTOM]\n"
    )
    (commands_dir / "projects.py").write_text(
        'COMMAND_CREDENTIALS = {"list": ["custom"]}\n'
    )
    (commands_dir / "config.py").write_text(
        'COMMAND_CREDENTIALS = {"list": ["no_auth"]}\n'
    )
    monkeypatch.setattr(
        cli_conftest,
        "get_config_auth_metadata",
        lambda *_args: {"credential_types": ["custom"], "profile_auth_types": []},
    )

    required_types = _required_credential_types_for_list_commands(
        cli_dir,
        "demo",
        ["projects list", "config list"],
    )

    assert required_types == ["custom"]


def test_list_command_auth_gate_excludes_profile_auth_types(tmp_path, monkeypatch) -> None:
    cli_dir = tmp_path / "tool"
    package_dir = cli_dir / "demo_cli"
    commands_dir = package_dir / "commands"
    commands_dir.mkdir(parents=True)
    (package_dir / "config.py").write_text(
        "CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]\n"
    )
    (commands_dir / "icons.py").write_text(
        'COMMAND_CREDENTIALS = {"list": ["author_kit", "no_auth"]}\n'
    )
    (commands_dir / "opportunities.py").write_text(
        'COMMAND_CREDENTIALS = {"list": ["opportunities", "browser_session"]}\n'
    )
    monkeypatch.setattr(
        cli_conftest,
        "get_config_auth_metadata",
        lambda *_args: {
            "credential_types": ["browser_session"],
            "profile_auth_types": ["author_kit", "opportunities"],
        },
    )

    required_types = _required_credential_types_for_list_commands(
        cli_dir,
        "demo",
        ["icons list", "opportunities list"],
    )

    assert required_types == ["browser_session"]


def test_list_command_auth_gate_selects_profile_auth_types(tmp_path, monkeypatch) -> None:
    cli_dir = tmp_path / "tool"
    package_dir = cli_dir / "demo_cli"
    commands_dir = package_dir / "commands"
    commands_dir.mkdir(parents=True)
    (package_dir / "config.py").write_text(
        "CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]\n"
        'PROFILE_AUTH_TYPES = {"author_kit": [], "opportunities": []}\n'
    )
    (commands_dir / "icons.py").write_text(
        'COMMAND_CREDENTIALS = {"list": ["author_kit", "no_auth"]}\n'
    )
    monkeypatch.setattr(
        cli_conftest,
        "get_config_auth_metadata",
        lambda *_args: {
            "credential_types": ["browser_session"],
            "profile_auth_types": ["author_kit", "opportunities"],
        },
    )

    required_types = _required_profile_auth_types_for_list_commands(
        cli_dir,
        "demo",
        ["icons list"],
    )

    assert required_types == ["author_kit"]
