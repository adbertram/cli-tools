"""Regression coverage for validate-cli-tool.sh auth requirements."""

from __future__ import annotations

import json
import os
import pytest
import shutil
import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]


def test_validate_script_skips_auth_group_for_no_auth_clis():
    script_text = (SKILL_ROOT / "scripts/validate-cli-tool.sh").read_text()

    assert "config_declares_no_auth" in script_text
    assert 'target.id == "CREDENTIAL_TYPES"' in script_text
    assert "TEST_CONFIG_PATH" not in script_text
    assert "tomllib" not in script_text
    assert "python3.11" not in script_text
    assert 'PYTHON_BIN="$(command -v python3 || :)"' in script_text
    assert 'auth_group_exists=skipped' in script_text
    assert '[ "$is_no_auth_cli" = "true" ] || required+=(auth_group_exists)' in script_text


def test_validate_script_accepts_config_declared_no_auth_cli(tmp_path):
    cli_name = "no-auth"
    script_dir = tmp_path / "_repo" / "skills" / "cli-tool" / "scripts"
    script_dir.mkdir(parents=True)
    script = script_dir / "validate-cli-tool.sh"
    shutil.copy2(SKILL_ROOT / "scripts" / "validate-cli-tool.sh", script)
    script.chmod(0o755)

    tool_dir = tmp_path / cli_name
    package_dir = tool_dir / "no_auth_cli"
    package_dir.mkdir(parents=True)
    (tool_dir / "pyproject.toml").write_text(
        "[project]\nname = \"no-auth-cli\"\n",
        encoding="utf-8",
    )
    (package_dir / "config.py").write_text(
        "class Config:\n    CREDENTIAL_TYPES = []\n",
        encoding="utf-8",
    )
    (package_dir / "main.py").write_text(
        "from cli_tools_shared import create_app, run_app\n",
        encoding="utf-8",
    )

    home_dir = tmp_path / "home"
    fake_bin_dir = tmp_path / "bin"
    fake_bin_dir.mkdir()
    uv_tool_python = home_dir / ".local" / "share" / "uv" / "tools" / "no-auth-cli" / "bin" / "python"
    uv_tool_python.parent.mkdir(parents=True)
    uv_tool_python.symlink_to(sys.executable)

    launcher_target = home_dir / "launcher-target"
    launcher_target.parent.mkdir(parents=True, exist_ok=True)
    launcher_target.write_text(
        f"#!{uv_tool_python}\n"
        "import sys\n"
        "raise SystemExit(1 if sys.argv[1:] == ['auth', '--help'] else 0)\n",
        encoding="utf-8",
    )
    launcher_target.chmod(0o755)
    launcher = home_dir / ".local" / "bin" / cli_name
    launcher.parent.mkdir(parents=True)
    launcher.symlink_to(launcher_target)

    fake_uv = fake_bin_dir / "uv"
    fake_uv.write_text(
        "#!/usr/bin/env bash\n"
        "if [ \"$1\" = \"tool\" ] && [ \"$2\" = \"list\" ]; then\n"
        "    printf '%s\\n' 'no-auth v0.1.0'\n"
        "    exit 0\n"
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)

    result = subprocess.run(
        [str(script), cli_name],
        cwd=tmp_path,
        env={
            **os.environ,
            "HOME": str(home_dir),
            "PATH": f"{fake_bin_dir}{os.pathsep}{os.environ['PATH']}",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["all_passed"] is True
    assert payload["checks"]["auth_group_exists"] == "skipped"


def test_validate_script_uses_canonical_uv_registry():
    script_text = (SKILL_ROOT / "scripts/validate-cli-tool.sh").read_text()

    assert 'CANONICAL_UV_TOOL_DIR="$HOME/.local/share/uv/tools"' in script_text
    assert 'CANONICAL_UV_BIN_DIR="$HOME/.local/bin"' in script_text
    assert 'export UV_TOOL_DIR="$CANONICAL_UV_TOOL_DIR"' in script_text
    assert 'export UV_TOOL_BIN_DIR="$CANONICAL_UV_BIN_DIR"' in script_text
    assert 'SYMLINK_PATH="$UV_TOOL_BIN_DIR/$CLI_NAME"' in script_text
    assert 'UV_VENV="$UV_TOOL_DIR/$UV_TOOL_DIR_NAME"' in script_text
    assert 'EXPECTED_SHEBANG_PREFIX="#!$UV_TOOL_DIR/$UV_TOOL_DIR_NAME/bin/python"' in script_text


def test_test_script_validates_auth_profile_secret_placeholders():
    script_text = (SKILL_ROOT / "scripts/test-cli-tool.sh").read_text()

    assert "validate_auth_profile_secret_placeholders" in script_text
    assert 'PYTHONPATH="$CLI_DIR:$REPO_ROOT/_repo/cli-tools-shared${PYTHONPATH:+:$PYTHONPATH}"' in script_text


def test_test_script_runs_auth_status_schema_preflight():
    script_text = (SKILL_ROOT / "scripts/test-cli-tool.sh").read_text()

    assert "run_auth_status_schema_preflight" in script_text
    assert "parse_and_validate_stdout" in script_text
    assert 'auth status schema:' in script_text


def test_test_script_skips_auth_status_preflight_for_command_filter():
    script_text = (SKILL_ROOT / "scripts/test-cli-tool.sh").read_text()

    assert 'COMMAND="$COMMAND" \\' in script_text
    assert 'command_filter = os.environ.get("COMMAND")' in script_text
    assert 'if command_filter:' in script_text
    assert 'emit("skipped", "Skipping (command filter active)")' in script_text


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
    assert '[[ ! -f "$CANONICAL_UV_LAUNCHER" || ! -x "$CANONICAL_UV_LAUNCHER" ]]' in script_text
    assert "CLI executable link missing, not a regular file, or not executable: $CANONICAL_UV_LAUNCHER" in script_text
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

    assert 'FORCE_REFRESH="false"' in script_text
    assert 'CANONICAL_UV_TOOL_DIR="$HOME/.local/share/uv/tools"' in script_text
    assert 'CANONICAL_UV_BIN_DIR="$HOME/.local/bin"' in script_text
    assert 'export UV_TOOL_DIR="$CANONICAL_UV_TOOL_DIR"' in script_text
    assert 'export UV_TOOL_BIN_DIR="$CANONICAL_UV_BIN_DIR"' in script_text
    assert 'UV_VENV="$UV_TOOL_DIR/$UV_TOOL_DIR_NAME"' in script_text
    assert 'LAUNCHER="$UV_TOOL_BIN_DIR/$CLI_NAME"' in script_text
    assert 'metadata_refresh_needed="false"' in script_text
    assert 'PYTHON_REQUEST="$(python3 "$SCRIPT_DIR/resolve_uv_python.py" "$TOOL_DIR/pyproject.toml")"' in script_text
    assert 'existing_python_matches_request="false"' in script_text
    assert '[ "$existing_python_matches_request" = "true" ]' in script_text
    assert '[ "$metadata_file" -nt "$LAUNCHER" ]' in script_text
    assert 'Existing editable install is healthy; skipped uv tool force refresh.' in script_text
    assert 'uv tool install -e "$TOOL_DIR" --force --refresh' in script_text
    assert 'SYMLINK_EXISTS="false"' in script_text
    assert 'SYMLINK_EXISTS="true"' in script_text
    assert "did not create expected launcher" in script_text
    assert 'SMOKE_BIN=$(command -v "$CLI_NAME" 2>/dev/null)' not in script_text
    assert '[ "$SYMLINK_EXISTS" = "true" ]' in script_text
    assert '"symlink_exists": $SYMLINK_EXISTS' in script_text


def test_repo_install_script_requires_uv_managed_global_launcher():
    script_text = (REPO_ROOT / "_repo/_scripts/install-cli-tool.sh").read_text()

    assert "FORCE_REFRESH=false" in script_text
    assert "Existing launcher is healthy; skipped uv tool force refresh:" in script_text
    assert 'PERSONAL_TOOL_DIR="$REPO_ROOT/_personal/$REQUESTED_TOOL"' in script_text
    assert 'TOOL_DIR="$PERSONAL_TOOL_DIR"' in script_text
    assert 'LAUNCHER="$HOME/.local/bin/$CLI_NAME"' in script_text
    assert "did not create expected launcher" in script_text
    assert 'command -v "$CLI_NAME"' not in script_text


def test_repo_install_script_installs_personal_cli_by_name_with_fake_uv(tmp_path):
    if not (REPO_ROOT / "_personal" / "ata-blog" / "pyproject.toml").is_file():
        pytest.skip(
            "_personal/ata-blog not present (gitignored, worktree-local); "
            "run from the primary checkout to exercise this fixture"
        )

    script = REPO_ROOT / "_repo/_scripts/install-cli-tool.sh"
    fake_bin = tmp_path / "bin"
    fake_home = tmp_path / "home"
    uv_args_file = tmp_path / "uv-args.txt"
    fake_bin.mkdir()
    fake_home.mkdir()

    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" > "$UV_ARGS_FILE"
case "$*" in
    *"/_personal/ata-blog"*) ;;
    *)
        printf 'unexpected uv args: %s\\n' "$*" >&2
        exit 9
        ;;
esac
mkdir -p "$HOME/.local/bin"
printf '%s\\n' '#!/usr/bin/env bash' 'if [[ "${1:-}" == "--help" ]]; then exit 0; fi' 'exit 0' > "$HOME/.local/bin/ata-blog"
chmod +x "$HOME/.local/bin/ata-blog"
"""
    )
    fake_uv.chmod(0o755)

    env = {
        **os.environ,
        "HOME": str(fake_home),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "UV_ARGS_FILE": str(uv_args_file),
    }
    result = subprocess.run(
        [str(script), "ata-blog"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "/_personal/ata-blog" in uv_args_file.read_text()


def test_create_cli_tool_skill_help_does_not_create_option_named_skill():
    script = SKILL_ROOT / "scripts/create-cli-tool-skill"
    accidental_skill_dir = REPO_ROOT / "_repo/skills/--help-cli"

    assert not accidental_skill_dir.exists(), "pre-existing --help-cli scaffold must be removed first"

    try:
        result = subprocess.run(
            [str(script), "--help"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "Usage: create-cli-tool-skill <tool-name>" in result.stdout
        assert result.stderr == ""
        assert not accidental_skill_dir.exists()
    finally:
        shutil.rmtree(accidental_skill_dir, ignore_errors=True)


def test_create_cli_tool_skill_rejects_option_like_tool_name_without_scaffold():
    script = SKILL_ROOT / "scripts/create-cli-tool-skill"
    accidental_skill_dir = REPO_ROOT / "_repo/skills/--not-a-tool-cli"

    assert not accidental_skill_dir.exists(), "pre-existing --not-a-tool-cli scaffold must be removed first"

    try:
        result = subprocess.run(
            [str(script), "--not-a-tool"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 2
        assert "Error: tool name must not start with '-': --not-a-tool" in result.stderr
        assert "Usage: create-cli-tool-skill <tool-name>" in result.stderr
        assert result.stdout == ""
        assert not accidental_skill_dir.exists()
    finally:
        shutil.rmtree(accidental_skill_dir, ignore_errors=True)


def test_validate_script_resolves_personal_cli_dirs():
    script_text = (SKILL_ROOT / "scripts/validate-cli-tool.sh").read_text()

    assert 'TOOL_DIR="$CLI_TOOLS_DIR/$CLI_NAME"' in script_text
    assert '[ ! -d "$TOOL_DIR" ] && [ -d "$CLI_TOOLS_DIR/_personal/$CLI_NAME" ]' in script_text
    assert 'TOOL_DIR="$CLI_TOOLS_DIR/_personal/$CLI_NAME"' in script_text


def test_find_cli_tools_discovers_personal_cli_dirs():
    script_text = (REPO_ROOT / "_repo/scripts/find-cli-tools.sh").read_text()

    assert 'personal_root = repo_root / "_personal"' in script_text
    assert "personal_root.glob(\"*/pyproject.toml\")" in script_text


def test_find_cli_tools_accepts_explicit_json_mode():
    script = REPO_ROOT / "_repo/scripts/find-cli-tools.sh"

    result = subprocess.run(
        [str(script), "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    records = json.loads(result.stdout)
    assert isinstance(records, list)
    assert records
    assert {"name", "readme", "description"} <= set(records[0])


def test_find_cli_tools_accepts_exact_tool_name_filter():
    script = REPO_ROOT / "_repo/scripts/find-cli-tools.sh"

    result = subprocess.run(
        [str(script), "--json", "upwork"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    records = json.loads(result.stdout)
    assert [record["name"] for record in records] == ["upwork"]


def test_find_cli_tools_compatibility_wrapper_for_old_tools_path():
    script = REPO_ROOT / "_repo/tools/find-cli-tools.sh"

    result = subprocess.run(
        [str(script), "--json", "upwork"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    records = json.loads(result.stdout)
    assert [record["name"] for record in records] == ["upwork"]
