"""Regression tests for the new-cli-tool scaffold generator."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import textwrap
import tomllib
from pathlib import Path

import pytest

from cli_tools_shared.config import config_env_path_for_tool, get_profiles_base_dir


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
CLI_TOOLS_DOC = REPO_ROOT / "_repo" / "docs" / "cli_tools.md"


def _markdown_section(text: str, heading: str) -> str:
    lines = text.splitlines()
    start = lines.index(heading)
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return "\n".join(lines[start + 1 : end]).strip()


def _sentence_count(text: str) -> int:
    return len(re.findall(r"[^.!?]+[.!?]", text))


def _template_names() -> list[str]:
    return sorted(
        path.name
        for path in (SKILL_ROOT / "templates").iterdir()
        if path.is_dir()
    )


@pytest.mark.parametrize("template_name", _template_names())
def test_all_cli_tool_templates_include_readme(template_name: str) -> None:
    readme_path = SKILL_ROOT / "templates" / template_name / "README.md"

    assert readme_path.is_file()


@pytest.mark.parametrize("template_name", _template_names())
def test_pyproject_templates_include_pytest_dev_dependency(template_name: str) -> None:
    pyproject_path = SKILL_ROOT / "templates" / template_name / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text())

    assert "pytest>=7.0.0" in pyproject["dependency-groups"]["dev"]


@pytest.mark.parametrize("template_name", _template_names())
def test_readme_templates_include_description_block(template_name: str) -> None:
    readme_path = SKILL_ROOT / "templates" / template_name / "README.md"
    readme_text = readme_path.read_text()
    lines = readme_text.splitlines()
    block = _markdown_section(readme_text, "## DESCRIPTION")

    assert lines[0] == "# {{Name}} CLI"
    assert lines[2] == "## DESCRIPTION"
    assert "{{description}}" in lines[4]
    assert "Use this CLI when" in lines[6]
    assert "{{DOCS_SECTION}}" in readme_text
    assert "{{docs_url}}" not in block
    assert "{{base_url}}" not in block
    assert _sentence_count(block) == 3


def test_generic_readme_template_includes_bounded_description_block() -> None:
    readme_text = (SKILL_ROOT / "templates" / "README_TEMPLATE.md").read_text()
    block = _markdown_section(readme_text, "## DESCRIPTION")

    assert readme_text.splitlines()[2] == "## DESCRIPTION"
    assert "Use this CLI when" in block
    assert "{service_url}" not in block
    assert _sentence_count(block) == 3


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
        expected_display_name = "".join(part.capitalize() for part in tool_name.split("-"))
        readme_lines = (tool_dir / "README.md").read_text().splitlines()
        assert readme_lines[2] == "## DESCRIPTION"
        assert f"Interact with {expected_display_name}" in readme_lines[4]
        assert "Use this CLI when" in readme_lines[6]

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


def test_new_cli_tool_bounds_readme_description_and_moves_docs_to_docs_section(
    tmp_path: Path,
    monkeypatch,
) -> None:
    tool_name = "scaffold-readme-bounds"
    tool_dir = REPO_ROOT / tool_name
    data_home = tmp_path / "data"
    home = tmp_path / "home"
    original_cli_tools_doc = CLI_TOOLS_DOC.read_text()
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setenv("HOME", str(home))
    env = os.environ.copy()
    description = textwrap.dedent(
        """\
        Command-line access to the WP Engine Hosting Platform API.

        Docs:
        - API overview: https://developers.wpengine.com/docs/managed-hosting-platform/api/
        - API reference: https://api.wpengineapi.com/
        """
    )

    try:
        result = subprocess.run(
            [
                str(SKILL_ROOT / "scripts/new-cli-tool"),
                "--name",
                tool_name,
                "--type",
                "api",
                "--base-url",
                "https://api.wpengineapi.com",
                "--docs-url",
                "https://developers.wpengine.com/docs/managed-hosting-platform/api/",
                "--description",
                description,
                "--no-install",
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, result.stderr
        readme_text = (tool_dir / "README.md").read_text()
        description_block = _markdown_section(readme_text, "## DESCRIPTION")
        docs_block = _markdown_section(readme_text, "## Docs")

        assert _sentence_count(description_block) == 3
        assert "Docs:" not in description_block
        assert "https://" not in description_block
        assert readme_text.index("## DESCRIPTION") < readme_text.index("## Docs")
        assert readme_text.index("## Docs") < readme_text.index("## Installation")
        assert "- API documentation: https://developers.wpengine.com/docs/managed-hosting-platform/api/" in docs_block
        assert "- Base URL: https://api.wpengineapi.com" in docs_block
    finally:
        CLI_TOOLS_DOC.write_text(original_cli_tools_doc)
        shutil.rmtree(tool_dir, ignore_errors=True)
        shutil.rmtree(data_home / "cli-tools" / tool_name, ignore_errors=True)
