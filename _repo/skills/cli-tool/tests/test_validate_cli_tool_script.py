"""Regression coverage for validate-cli-tool.sh auth requirements."""

from __future__ import annotations

import tomllib
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]


def test_validate_script_skips_auth_group_for_no_auth_clis():
    script_text = (SKILL_ROOT / "scripts/validate-cli-tool.sh").read_text()
    with (SKILL_ROOT / "tests/cli_test_config.toml").open("rb") as fh:
        config = tomllib.load(fh)

    no_auth_clis = config["exclusions"]["no_auth_clis"]
    assert "imessage" in no_auth_clis
    assert 'TEST_CONFIG_PATH="$SCRIPT_DIR/../tests/cli_test_config.toml"' in script_text
    assert 'auth_group_exists=skipped' in script_text
    assert '[ "$is_no_auth_cli" = "true" ] || required+=(auth_group_exists)' in script_text


def test_test_script_validates_auth_profile_secret_placeholders():
    script_text = (SKILL_ROOT / "scripts/test-cli-tool.sh").read_text()

    assert "validate_auth_profile_secret_placeholders" in script_text
    assert 'PYTHONPATH="$CLI_DIR:$REPO_ROOT/_repo/cli-tools-shared${PYTHONPATH:+:$PYTHONPATH}"' in script_text


def test_test_script_runs_auth_status_schema_preflight():
    script_text = (SKILL_ROOT / "scripts/test-cli-tool.sh").read_text()

    assert "run_auth_status_schema_preflight" in script_text
    assert "parse_and_validate_stdout" in script_text
    assert 'auth status schema:' in script_text


def test_test_script_validates_readme_description_block():
    script_text = (SKILL_ROOT / "scripts/test-cli-tool.sh").read_text()

    assert "validate_readme_description_block" in script_text
    assert "DESCRIPTION block" in script_text
    assert 'readme_description_block' in script_text
    assert "found {sentence_count}" in script_text
    assert "json_test_failure" in script_text


def test_test_script_unknown_argument_points_to_supported_invocation():
    script_text = (SKILL_ROOT / "scripts/test-cli-tool.sh").read_text()

    assert "Unknown argument: $1. Use --cli-name <name> or --file <path>." in script_text


def test_test_script_reports_missing_launcher_as_structured_failure():
    script_text = (SKILL_ROOT / "scripts/test-cli-tool.sh").read_text()

    assert "json_test_failure()" in script_text
    assert "test_cli_executable_linked" in script_text
    assert "CLI executable link missing or not executable: $CANONICAL_UV_LAUNCHER" in script_text
    assert 'CLI_EXECUTABLE="$CANONICAL_UV_LAUNCHER"' in script_text


def test_new_cli_tool_requires_uv_launcher_symlink():
    script_text = (SKILL_ROOT / "scripts/new-cli-tool").read_text()

    assert "launcher = LOCAL_BIN_DIR / tool_name" in script_text
    assert "if not launcher.is_symlink():" in script_text
    assert "uv install did not create the expected launcher symlink" in script_text
    assert "sys.exit(1)" in script_text


def test_install_script_resolves_personal_cli_dirs():
    script_text = (SKILL_ROOT / "scripts/install-cli-tool.sh").read_text()

    assert 'TOOL_DIR="$CLI_TOOLS_DIR/$CLI_NAME"' in script_text
    assert '[ ! -d "$TOOL_DIR" ] && [ -d "$CLI_TOOLS_DIR/_personal/$CLI_NAME" ]' in script_text
    assert 'TOOL_DIR="$CLI_TOOLS_DIR/_personal/$CLI_NAME"' in script_text


def test_install_script_requires_launcher_symlink_for_success():
    script_text = (SKILL_ROOT / "scripts/install-cli-tool.sh").read_text()

    assert 'SYMLINK_EXISTS="false"' in script_text
    assert 'SYMLINK_EXISTS="true"' in script_text
    assert "did not create expected launcher" in script_text
    assert 'SMOKE_BIN=$(command -v "$CLI_NAME" 2>/dev/null)' not in script_text
    assert '[ "$SYMLINK_EXISTS" = "true" ]' in script_text
    assert '"symlink_exists": $SYMLINK_EXISTS' in script_text


def test_repo_install_script_requires_uv_managed_global_launcher():
    script_text = (REPO_ROOT / "_repo/_scripts/install-cli-tool.sh").read_text()

    assert 'LAUNCHER="$HOME/.local/bin/$CLI_NAME"' in script_text
    assert "did not create expected launcher" in script_text
    assert 'command -v "$CLI_NAME"' not in script_text


def test_validate_script_resolves_personal_cli_dirs():
    script_text = (SKILL_ROOT / "scripts/validate-cli-tool.sh").read_text()

    assert 'TOOL_DIR="$CLI_TOOLS_DIR/$CLI_NAME"' in script_text
    assert '[ ! -d "$TOOL_DIR" ] && [ -d "$CLI_TOOLS_DIR/_personal/$CLI_NAME" ]' in script_text
    assert 'TOOL_DIR="$CLI_TOOLS_DIR/_personal/$CLI_NAME"' in script_text
