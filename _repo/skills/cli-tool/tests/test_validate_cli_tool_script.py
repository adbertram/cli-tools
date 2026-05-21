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

