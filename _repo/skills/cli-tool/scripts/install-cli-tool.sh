#!/usr/bin/env bash
# install-cli-tool.sh - Install a CLI tool via uv tool install
# Usage: install-cli-tool.sh <name>
# Returns JSON with install results

set -o pipefail

CLI_NAME="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI_TOOLS_DIR="$(cd "$SCRIPT_DIR/../../../.." && pwd)"

if [ -z "$CLI_NAME" ]; then
    echo '{"error": "CLI name required. Usage: install-cli-tool.sh <name>"}' >&2
    exit 1
fi

TOOL_DIR="$CLI_TOOLS_DIR/$CLI_NAME"
if [ ! -d "$TOOL_DIR" ] && [ -d "$CLI_TOOLS_DIR/_personal/$CLI_NAME" ]; then
    TOOL_DIR="$CLI_TOOLS_DIR/_personal/$CLI_NAME"
fi
LOCAL_SHARED_DIR="$CLI_TOOLS_DIR/_repo/cli-tools-shared"

if [ ! -d "$TOOL_DIR" ]; then
    echo '{"error": "CLI tool directory not found: '"$TOOL_DIR"'"}' >&2
    exit 1
fi

# ============================================================================
# Install via uv tool install (editable mode, force reinstall)
# ============================================================================
# When pyproject.toml's requires-python has an upper bound (e.g. ">=3.13,<3.14"),
# uv tool install would otherwise pick the system python and ignore that bound,
# leading to source-build failures. Honor the bound by passing --python.
SYSTEM_PYTHON3="$(command -v python3 2>/dev/null || true)"
[ -z "$SYSTEM_PYTHON3" ] && SYSTEM_PYTHON3="python3"
PY_FLAG=(--python "$SYSTEM_PYTHON3")
OVERRIDE_FLAG=()
if [ -f "$TOOL_DIR/pyproject.toml" ]; then
    UPPER_PY=$(python3 - <<PYEOF 2>/dev/null
import re
with open("$TOOL_DIR/pyproject.toml") as f:
    for line in f:
        m = re.match(r'\s*requires-python\s*=\s*"([^"]+)"', line)
        if not m:
            continue
        spec = m.group(1)
        upper = re.search(r'<\s*3\.(\d+)', spec)
        if upper:
            print(f"3.{int(upper.group(1)) - 1}")
        break
PYEOF
)
    if [ -n "$UPPER_PY" ]; then
        PY_FLAG=(--python "$UPPER_PY")
    fi
fi

if [ -f "$TOOL_DIR/uv-overrides.txt" ]; then
    OVERRIDE_FLAG=(--overrides "$TOOL_DIR/uv-overrides.txt")
fi

INSTALL_OUTPUT=$(uv tool install -e "$TOOL_DIR" --force --refresh "${PY_FLAG[@]}" "${OVERRIDE_FLAG[@]}" 2>&1)
INSTALL_EXIT=$?

# ============================================================================
# Windows: Remove stale extension-less binary that shadows .exe
# ============================================================================
if [ $INSTALL_EXIT -eq 0 ] && [[ "$(uname -s)" == MINGW* || "$(uname -s)" == MSYS* || "$(uname -s)" == CYGWIN* ]]; then
    NOEXT="$HOME/.local/bin/$CLI_NAME"
    WITHEXT="$HOME/.local/bin/$CLI_NAME.exe"
    if [ -f "$NOEXT" ] && [ -f "$WITHEXT" ]; then
        # Skip if they are hardlinks to the same file (same inode)
        NOEXT_INODE=$(stat -c '%i' "$NOEXT" 2>/dev/null)
        WITHEXT_INODE=$(stat -c '%i' "$WITHEXT" 2>/dev/null)
        if [ "$NOEXT_INODE" != "$WITHEXT_INODE" ]; then
            FILE_TYPE=$(file -b "$NOEXT")
            case "$FILE_TYPE" in
                *text*|*script*|*ASCII*)
                    # It's a text/script file -- leave it alone
                    ;;
                *)
                    # Stale binary shadowing the .exe -- remove it
                    rm "$NOEXT"
                    hash -r
                    ;;
            esac
        fi
    fi
fi

# ============================================================================
# Browser dependency note (browser-based CLIs)
# ============================================================================
# Browser CLIs depend on cli-tools-shared, which transitively pulls in
# browser-harness. The harness drives Chrome via CDP, so there is no separate
# "install browsers" step here. If the daemon fails to launch at runtime,
# verify that browser-harness is installed in the CLI's uv tool venv.

# ============================================================================
# Verify editable install stuck
# ============================================================================
# `uv tool install -e` can silently fall back to a regular (non-editable)
# install in some edge cases (stale venv, missing pyproject, etc.). Confirm
# the package actually reports an "Editable project location" — otherwise
# source edits won't be picked up and we should fail loudly.
EDITABLE_INSTALL="false"
EDITABLE_LOCATION=""
SHARED_EDITABLE_INSTALL="skipped"
SHARED_EDITABLE_LOCATION=""
if [ $INSTALL_EXIT -eq 0 ]; then
    PYPROJECT_NAME=""
    if [ -f "$TOOL_DIR/pyproject.toml" ]; then
        PYPROJECT_NAME=$(awk -F'"' '/^name[[:space:]]*=/ { print $2; exit }' "$TOOL_DIR/pyproject.toml")
    fi
    TOOL_PACKAGE_NAME="${PYPROJECT_NAME:-${CLI_NAME}-cli}"
    UV_TOOL_DIR_NAME=$(printf '%s' "$TOOL_PACKAGE_NAME" | python3 -c 'import re,sys; print(re.sub(r"[-_.]+", "-", sys.stdin.read().strip()).lower())')
    UV_VENV="$HOME/.local/share/uv/tools/$UV_TOOL_DIR_NAME"

    if [ -d "$UV_VENV" ]; then
        for pkg_try in "$PYPROJECT_NAME" "${CLI_NAME}_cli" "${CLI_NAME}-cli" "$CLI_NAME"; do
            [ -z "$pkg_try" ] && continue
            PIP_SHOW=$(VIRTUAL_ENV="$UV_VENV" uv pip show "$pkg_try" 2>/dev/null)
            if [ -n "$PIP_SHOW" ]; then
                EDITABLE_LOCATION=$(echo "$PIP_SHOW" | awk -F': ' '/^Editable project location:/ { print $2; exit }')
                if [ -n "$EDITABLE_LOCATION" ]; then
                    EDITABLE_INSTALL="true"
                fi
                break
            fi
        done
    fi

    if [ "$EDITABLE_INSTALL" = "false" ]; then
        # Editable install did not stick — fail the install so callers
        # can't silently keep a broken non-editable copy.
        INSTALL_EXIT=1
        INSTALL_OUTPUT="${INSTALL_OUTPUT}
ERROR: uv tool install completed but package is NOT in editable mode.
Expected 'Editable project location:' in uv pip show output, got none.
Fix: rm -rf $UV_VENV && uv tool install -e $TOOL_DIR --force --refresh"
    fi
fi

# ============================================================================
# Local shared dependency overlay: keep cli-tools-shared editable from repo
# ============================================================================
# CLI repos declare cli-tools-shared as a repo-local uv source. Reinstall it as
# editable inside the target uv tool venv whenever the local shared repo exists
# and the CLI declares that dependency, so source edits are reflected
# immediately.
USES_CLI_TOOLS_SHARED="false"
if [ -f "$TOOL_DIR/pyproject.toml" ] && grep -q "cli-tools-shared" "$TOOL_DIR/pyproject.toml"; then
    USES_CLI_TOOLS_SHARED="true"
fi

if [ $INSTALL_EXIT -eq 0 ] && [ "$USES_CLI_TOOLS_SHARED" = "true" ] && [ -d "$LOCAL_SHARED_DIR" ]; then
    SHARED_INSTALL_OUTPUT=$(uv pip install --python "$UV_VENV/bin/python3" --editable "$LOCAL_SHARED_DIR" --reinstall 2>&1)
    SHARED_INSTALL_EXIT=$?
    INSTALL_OUTPUT="${INSTALL_OUTPUT}
${SHARED_INSTALL_OUTPUT}"

    if [ $SHARED_INSTALL_EXIT -ne 0 ]; then
        INSTALL_EXIT=$SHARED_INSTALL_EXIT
        INSTALL_OUTPUT="${INSTALL_OUTPUT}
ERROR: Failed to overlay local cli-tools-shared editable install from $LOCAL_SHARED_DIR"
    else
        SHARED_PIP_SHOW=$(VIRTUAL_ENV="$UV_VENV" uv pip show cli-tools-shared 2>/dev/null)
        SHARED_EDITABLE_LOCATION=$(echo "$SHARED_PIP_SHOW" | awk -F': ' '/^Editable project location:/ { print $2; exit }')
        if [ "$SHARED_EDITABLE_LOCATION" = "$LOCAL_SHARED_DIR" ]; then
            SHARED_EDITABLE_INSTALL="true"
        else
            SHARED_EDITABLE_INSTALL="false"
            INSTALL_EXIT=1
            INSTALL_OUTPUT="${INSTALL_OUTPUT}
ERROR: cli-tools-shared was not left in editable mode from $LOCAL_SHARED_DIR.
Got Editable project location: ${SHARED_EDITABLE_LOCATION:-<none>}"
        fi
    fi
fi

# ============================================================================
# Smoke test: --help
# ============================================================================
HELP_WORKS="false"
SYMLINK_EXISTS="false"
if [ $INSTALL_EXIT -eq 0 ]; then
    # Prefer the uv-managed launcher we just installed; PATH may resolve to an
    # unrelated system binary with the same command name.
    SMOKE_BIN=""
    if [ -L "$HOME/.local/bin/$CLI_NAME" ]; then
        SYMLINK_EXISTS="true"
        SMOKE_BIN="$HOME/.local/bin/$CLI_NAME"
    elif [ -f "$HOME/.local/bin/$CLI_NAME.exe" ]; then
        SYMLINK_EXISTS="true"
        SMOKE_BIN="$HOME/.local/bin/$CLI_NAME.exe"
    else
        INSTALL_EXIT=1
        INSTALL_OUTPUT="${INSTALL_OUTPUT}
ERROR: uv tool install completed but did not create expected launcher: $HOME/.local/bin/$CLI_NAME"
    fi
    if [ -n "$SMOKE_BIN" ]; then
        "$SMOKE_BIN" --help >/dev/null 2>&1 && HELP_WORKS="true"
    fi
fi

# ============================================================================
# Determine success
# ============================================================================
SUCCESS="false"
[ $INSTALL_EXIT -eq 0 ] && [ "$SYMLINK_EXISTS" = "true" ] && [ "$HELP_WORKS" = "true" ] && SUCCESS="true"

# ============================================================================
# Escape install output for JSON
# ============================================================================
INSTALL_OUTPUT_ESCAPED=$(printf '%s' "$INSTALL_OUTPUT" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read())[1:-1],end='')")

# ============================================================================
# Output JSON
# ============================================================================
EDITABLE_LOCATION_JSON="null"
[ -n "$EDITABLE_LOCATION" ] && EDITABLE_LOCATION_JSON="\"$EDITABLE_LOCATION\""
SHARED_EDITABLE_LOCATION_JSON="null"
[ -n "$SHARED_EDITABLE_LOCATION" ] && SHARED_EDITABLE_LOCATION_JSON="\"$SHARED_EDITABLE_LOCATION\""

cat <<EOF
{
  "success": $SUCCESS,
  "cli_name": "$CLI_NAME",
  "install_exit_code": $INSTALL_EXIT,
  "install_output": "$INSTALL_OUTPUT_ESCAPED",
  "editable_install": $EDITABLE_INSTALL,
  "editable_location": $EDITABLE_LOCATION_JSON,
  "shared_editable_install": "$SHARED_EDITABLE_INSTALL",
  "shared_editable_location": $SHARED_EDITABLE_LOCATION_JSON,
  "symlink_exists": $SYMLINK_EXISTS,
  "help_works": $HELP_WORKS
}
EOF
