"""Regression tests for the new-cli-tool scaffold generator."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from cli_tools_shared.config import config_env_path_for_tool, get_profiles_base_dir


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
CLI_TOOLS_DOC = REPO_ROOT / "_repo" / "docs" / "cli_tools.md"


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, value = stripped.split("=", 1)
        values[key] = value
    return values


@pytest.mark.parametrize(
    ("tool_name", "auth_args"),
    [
        ("scaffold-env-regression", []),
        ("scaffold-noauth-regression", ["--auth-type", "none"]),
    ],
)
def test_new_cli_tool_creates_runtime_default_profile_without_source_env(
    tmp_path: Path,
    monkeypatch,
    tool_name: str,
    auth_args: list[str],
) -> None:
    tool_dir = REPO_ROOT / tool_name
    data_home = tmp_path / "data"
    home = tmp_path / "home"
    original_cli_tools_doc = CLI_TOOLS_DOC.read_text()
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setenv("HOME", str(home))
    env = os.environ.copy()

    try:
        result = subprocess.run(
            [
                str(SKILL_ROOT / "scripts/new-cli-tool"),
                "--name",
                tool_name,
                "--type",
                "api",
                "--base-url",
                "https://api.example.test",
                "--no-install",
                *auth_args,
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, result.stderr
        assert not (tool_dir / ".env").exists()
        assert sorted(path.name for path in tool_dir.glob(".env*")) == [".env.example"]

        profile_env = get_profiles_base_dir(tool_name) / "default" / ".env"
        assert profile_env.exists()
        profile_values = _read_env_file(profile_env)
        assert profile_values["ACTIVE"] == "true"
        assert "BASE_URL" not in profile_values

        config_env = config_env_path_for_tool(tool_name)
        assert config_env.exists()
        assert _read_env_file(config_env)["BASE_URL"] == "https://api.example.test"
    finally:
        CLI_TOOLS_DOC.write_text(original_cli_tools_doc)
        shutil.rmtree(tool_dir, ignore_errors=True)
        shutil.rmtree(data_home / "cli-tools" / tool_name, ignore_errors=True)
