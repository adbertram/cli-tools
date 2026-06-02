#!/usr/bin/env bash
# validate-cli-tool.sh - Post-creation validation for a CLI tool
# Usage: validate-cli-tool.sh <name>
# Emits one JSON document describing per-check results.

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_CONFIG_PATH="$SCRIPT_DIR/../tests/cli_test_config.toml"
CLI_TOOLS_DIR="$(cd "$SCRIPT_DIR/../../../.." && pwd)"

CLI_NAME="$1"
if [ -z "$CLI_NAME" ]; then
    echo '{"error": "CLI name required. Usage: validate-cli-tool.sh <name>"}' >&2
    exit 1
fi

TOOL_DIR="$CLI_TOOLS_DIR/$CLI_NAME"
if [ ! -d "$TOOL_DIR" ] && [ -d "$CLI_TOOLS_DIR/_personal/$CLI_NAME" ]; then
    TOOL_DIR="$CLI_TOOLS_DIR/_personal/$CLI_NAME"
fi
SYMLINK_PATH="$HOME/.local/bin/$CLI_NAME"
LOCAL_SHARED_DIR="$CLI_TOOLS_DIR/_repo/cli-tools-shared"
PKG_DIR_NAME="${CLI_NAME}-cli"
if [ -f "$TOOL_DIR/pyproject.toml" ]; then
    PYPROJECT_NAME=$(awk -F'"' '/^name[[:space:]]*=/ { print $2; exit }' "$TOOL_DIR/pyproject.toml")
    [ -n "$PYPROJECT_NAME" ] && PKG_DIR_NAME="$PYPROJECT_NAME"
fi
UV_TOOL_DIR_NAME=$(printf '%s' "$PKG_DIR_NAME" | python3 -c 'import re,sys; print(re.sub(r"[-_.]+", "-", sys.stdin.read().strip()).lower())')
UV_VENV="$HOME/.local/share/uv/tools/$UV_TOOL_DIR_NAME"
PKG_NAME="$(echo "$CLI_NAME" | tr '-' '_')_cli"
MAIN_PY="$TOOL_DIR/$PKG_NAME/main.py"
EXPECTED_SHEBANG_PREFIX="#!$HOME/.local/share/uv/tools/$UV_TOOL_DIR_NAME/bin/python"

# Each check sets one of these patterns:
#   <var>=true | <var>=false | <var>=skipped
# Loop with python at the bottom assembles them into JSON.

dir_exists=false
[ -d "$TOOL_DIR" ] && dir_exists=true

uv_tool_installed=false
uv tool list 2>/dev/null | grep -q "$CLI_NAME" && uv_tool_installed=true

executable_exists=false
[ -f "$SYMLINK_PATH" ] && executable_exists=true

pkg_py_grep() {
    local pattern="$1"
    find "$TOOL_DIR/$PKG_NAME" -path '*/__pycache__' -prune -o -type f -name '*.py' -print0 \
        | xargs -0 grep -E "$pattern" >/dev/null 2>&1
}

run_silent() {
    [ "$executable_exists" = "true" ] || return 1
    "$SYMLINK_PATH" "$@" >/dev/null 2>&1
}

help_works=false; run_silent --help && help_works=true
version_works=false; run_silent --version && version_works=true
is_no_auth_cli=$(python3 - "$TEST_CONFIG_PATH" "$CLI_NAME" <<'PY'
import sys
import tomllib
from pathlib import Path

config_path = Path(sys.argv[1])
cli_name = sys.argv[2]

with config_path.open("rb") as fh:
    config = tomllib.load(fh)

no_auth_clis = config.get("exclusions", {}).get("no_auth_clis", [])
print("true" if cli_name in no_auth_clis else "false")
PY
)

auth_group_exists=false
if [ "$is_no_auth_cli" = "true" ]; then
    auth_group_exists=skipped
elif run_silent auth --help; then
    auth_group_exists=true
fi

symlink_exists=false
symlink_target=""
if [ -L "$SYMLINK_PATH" ]; then
    symlink_exists=true
    symlink_target=$(readlink "$SYMLINK_PATH")
fi

shebang_correct=false
shebang_actual=""
if [ -f "$SYMLINK_PATH" ]; then
    shebang_actual=$(head -1 "$SYMLINK_PATH" 2>/dev/null)
    case "$shebang_actual" in
        "$EXPECTED_SHEBANG_PREFIX"|"$EXPECTED_SHEBANG_PREFIX"3) shebang_correct=true ;;
    esac
fi

is_wrapper=false
no_cache_works=false
if [ -f "$MAIN_PY" ] && grep -q "cache_support=False" "$MAIN_PY"; then
    is_wrapper=true
    no_cache_works=skipped
elif run_silent --no-cache --help; then
    no_cache_works=true
fi

uses_create_app=false
uses_run_app=false
if [ -f "$MAIN_PY" ]; then
    grep -q "create_app" "$MAIN_PY" && grep -q "from cli_tools_shared" "$MAIN_PY" && uses_create_app=true
    grep -q "run_app" "$MAIN_PY" && uses_run_app=true
fi

ai_instruction_contract=skipped
ai_instruction_forbidden_fields=skipped
if [ -d "$TOOL_DIR/$PKG_NAME" ] && pkg_py_grep "AIInstruction|print_ai_instruction|ai_instruction"; then
    ai_instruction_contract=false
    ai_instruction_forbidden_fields=false
    if pkg_py_grep "from cli_tools_shared.models import AIInstruction|from cli_tools_shared import AIInstruction" \
        && pkg_py_grep "print_ai_instruction" \
        && ! pkg_py_grep "class AIInstruction"; then
        ai_instruction_contract=true
    fi
    pkg_py_grep "required_commands|command_to_run|commands_to_run" \
        || ai_instruction_forbidden_fields=true
fi

shared_local_editable=skipped
shared_editable_location=""
if [ -f "$TOOL_DIR/pyproject.toml" ] && grep -q "cli-tools-shared" "$TOOL_DIR/pyproject.toml" \
   && [ -d "$LOCAL_SHARED_DIR" ] && [ -d "$UV_VENV" ]; then
    shared_local_editable=false
    shared_editable_location=$(VIRTUAL_ENV="$UV_VENV" uv pip show cli-tools-shared 2>/dev/null \
        | awk -F': ' '/^Editable project location:/ { print $2; exit }')
    [ "$shared_editable_location" = "$LOCAL_SHARED_DIR" ] && shared_local_editable=true
fi

# Required checks (must all be true for all_passed).
required=(dir_exists uv_tool_installed executable_exists help_works
          symlink_exists shebang_correct uses_create_app uses_run_app)
[ "$is_no_auth_cli" = "true" ] || required+=(auth_group_exists)
[ "$is_wrapper" = "true" ] || required+=(no_cache_works)

all_passed=true
for var in "${required[@]}"; do
    [ "${!var}" = "true" ] || { all_passed=false; break; }
done
[ "$ai_instruction_contract" = "false" ] && all_passed=false
[ "$ai_instruction_forbidden_fields" = "false" ] && all_passed=false
[ "$shared_local_editable" = "false" ] && all_passed=false

CLI_NAME="$CLI_NAME" \
ALL_PASSED="$all_passed" \
DIR_EXISTS="$dir_exists" \
UV_TOOL_INSTALLED="$uv_tool_installed" \
EXECUTABLE_EXISTS="$executable_exists" \
HELP_WORKS="$help_works" \
VERSION_WORKS="$version_works" \
SYMLINK_EXISTS="$symlink_exists" \
SYMLINK_TARGET="$symlink_target" \
SHEBANG_CORRECT="$shebang_correct" \
SHEBANG_ACTUAL="$shebang_actual" \
SHEBANG_EXPECTED="$EXPECTED_SHEBANG_PREFIX" \
SHARED_LOCAL_EDITABLE="$shared_local_editable" \
SHARED_EDITABLE_LOCATION="$shared_editable_location" \
AUTH_GROUP_EXISTS="$auth_group_exists" \
NO_CACHE_WORKS="$no_cache_works" \
USES_CREATE_APP="$uses_create_app" \
USES_RUN_APP="$uses_run_app" \
AI_INSTRUCTION_CONTRACT="$ai_instruction_contract" \
AI_INSTRUCTION_FORBIDDEN_FIELDS="$ai_instruction_forbidden_fields" \
python3 - <<'PY'
import json, os

def coerce(v):
    if v == "true": return True
    if v == "false": return False
    if v == "skipped": return "skipped"
    return v or None

print(json.dumps({
    "cli_name": os.environ["CLI_NAME"],
    "all_passed": coerce(os.environ["ALL_PASSED"]),
    "checks": {
        "dir_exists": coerce(os.environ["DIR_EXISTS"]),
        "uv_tool_installed": coerce(os.environ["UV_TOOL_INSTALLED"]),
        "executable_exists": coerce(os.environ["EXECUTABLE_EXISTS"]),
        "help_works": coerce(os.environ["HELP_WORKS"]),
        "version_works": coerce(os.environ["VERSION_WORKS"]),
        "symlink_exists": coerce(os.environ["SYMLINK_EXISTS"]),
        "symlink_target": coerce(os.environ["SYMLINK_TARGET"]),
        "shebang_correct": coerce(os.environ["SHEBANG_CORRECT"]),
        "shebang_actual": coerce(os.environ["SHEBANG_ACTUAL"]),
        "shebang_expected": os.environ["SHEBANG_EXPECTED"],
        "shared_local_editable": coerce(os.environ["SHARED_LOCAL_EDITABLE"]),
        "shared_editable_location": coerce(os.environ["SHARED_EDITABLE_LOCATION"]),
        "auth_group_exists": coerce(os.environ["AUTH_GROUP_EXISTS"]),
        "no_cache_works": coerce(os.environ["NO_CACHE_WORKS"]),
        "uses_create_app": coerce(os.environ["USES_CREATE_APP"]),
        "uses_run_app": coerce(os.environ["USES_RUN_APP"]),
        "ai_instruction_contract": coerce(os.environ["AI_INSTRUCTION_CONTRACT"]),
        "ai_instruction_forbidden_fields": coerce(os.environ["AI_INSTRUCTION_FORBIDDEN_FIELDS"]),
    },
}, indent=2))
PY
