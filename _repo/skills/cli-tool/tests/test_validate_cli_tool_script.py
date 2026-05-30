"""Regression coverage for validate-cli-tool.sh auth requirements."""

from __future__ import annotations

import tomllib
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]


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


def test_install_script_resolves_personal_cli_dirs():
    script_text = (SKILL_ROOT / "scripts/install-cli-tool.sh").read_text()

    assert 'TOOL_DIR="$CLI_TOOLS_DIR/$CLI_NAME"' in script_text
    assert '[ ! -d "$TOOL_DIR" ] && [ -d "$CLI_TOOLS_DIR/_personal/$CLI_NAME" ]' in script_text
    assert 'TOOL_DIR="$CLI_TOOLS_DIR/_personal/$CLI_NAME"' in script_text


def test_validate_script_resolves_personal_cli_dirs():
    script_text = (SKILL_ROOT / "scripts/validate-cli-tool.sh").read_text()

    assert 'TOOL_DIR="$CLI_TOOLS_DIR/$CLI_NAME"' in script_text
    assert '[ ! -d "$TOOL_DIR" ] && [ -d "$CLI_TOOLS_DIR/_personal/$CLI_NAME" ]' in script_text
    assert 'TOOL_DIR="$CLI_TOOLS_DIR/_personal/$CLI_NAME"' in script_text
