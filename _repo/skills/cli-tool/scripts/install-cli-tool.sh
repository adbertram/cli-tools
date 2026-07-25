#!/usr/bin/env bash
# install-cli-tool.sh - Install a CLI tool via uv tool install
# Usage: install-cli-tool.sh [--force-refresh] <name>
# Returns JSON with install results

set -o pipefail

FORCE_REFRESH="false"
if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    printf '%s\n' 'Usage: install-cli-tool.sh [--force-refresh] <name>'
    exit 0
fi
if [ "${1:-}" = "--force-refresh" ]; then
    FORCE_REFRESH="true"
    shift
fi

CLI_NAME="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI_TOOLS_DIR="$(cd "$SCRIPT_DIR/../../../.." && pwd)"

if [ -z "$CLI_NAME" ] || [ $# -ne 1 ]; then
    echo '{"error": "CLI name required. Usage: install-cli-tool.sh [--force-refresh] <name>"}' >&2
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

PYPROJECT_NAME=""
if [ -f "$TOOL_DIR/pyproject.toml" ]; then
    PYPROJECT_NAME=$(awk -F'"' '/^name[[:space:]]*=/ { print $2; exit }' "$TOOL_DIR/pyproject.toml")
fi
TOOL_PACKAGE_NAME="${PYPROJECT_NAME:-${CLI_NAME}-cli}"
UV_TOOL_DIR_NAME=$(printf '%s' "$TOOL_PACKAGE_NAME" | python3 -c 'import re,sys; print(re.sub(r"[-_.]+", "-", sys.stdin.read().strip()).lower())')
UV_VENV="$HOME/.local/share/uv/tools/$UV_TOOL_DIR_NAME"
LAUNCHER="$HOME/.local/bin/$CLI_NAME"
USES_CLI_TOOLS_SHARED="false"
if [ -f "$TOOL_DIR/pyproject.toml" ] && grep -q "cli-tools-shared" "$TOOL_DIR/pyproject.toml"; then
    USES_CLI_TOOLS_SHARED="true"
fi

# uv builds/resolves the tool against the interpreter it is given. Forcing the
# ambient python3 breaks when it is older than the tool's requires-python (e.g.
# macOS system 3.9 vs a >=3.11 tool: uv reports "requirements are
# unsatisfiable"). resolve_uv_python.py returns the ambient interpreter when it
# already satisfies the constraint, otherwise a compatible "3.X" version request
# for uv to find or download. Compute this before the fast-path health check so
# an editable install with a stale uv-managed interpreter is refreshed.
PYTHON_REQUEST="$(python3 "$SCRIPT_DIR/resolve_uv_python.py" "$TOOL_DIR/pyproject.toml")"

existing_editable_install="false"
existing_editable_location=""
existing_shared_editable_install="skipped"
existing_shared_editable_location=""
existing_help_works="false"
existing_python_matches_request="false"
metadata_refresh_needed="false"
if [ "$FORCE_REFRESH" = "false" ] && [ -L "$LAUNCHER" ] && [ -x "$LAUNCHER" ] && [ -d "$UV_VENV" ]; then
    for metadata_file in "$TOOL_DIR/pyproject.toml" "$TOOL_DIR/uv.lock"; do
        if [ -f "$metadata_file" ] && [ "$metadata_file" -nt "$LAUNCHER" ]; then
            metadata_refresh_needed="true"
        fi
    done
    if [ "$USES_CLI_TOOLS_SHARED" = "true" ] && [ -d "$LOCAL_SHARED_DIR" ]; then
        for metadata_file in "$LOCAL_SHARED_DIR/pyproject.toml" "$LOCAL_SHARED_DIR/uv.lock"; do
            if [ -f "$metadata_file" ] && [ "$metadata_file" -nt "$LAUNCHER" ]; then
                metadata_refresh_needed="true"
            fi
        done
    fi

    for pkg_try in "$PYPROJECT_NAME" "${CLI_NAME}_cli" "${CLI_NAME}-cli" "$CLI_NAME"; do
        [ -z "$pkg_try" ] && continue
        PIP_SHOW=$(VIRTUAL_ENV="$UV_VENV" uv pip show "$pkg_try" 2>/dev/null)
        if [ -n "$PIP_SHOW" ]; then
            existing_editable_location=$(echo "$PIP_SHOW" | awk -F': ' '/^Editable project location:/ { print $2; exit }')
            if [ "$existing_editable_location" = "$TOOL_DIR" ]; then
                existing_editable_install="true"
            fi
            break
        fi
    done

    if [ "$USES_CLI_TOOLS_SHARED" = "true" ] && [ -d "$LOCAL_SHARED_DIR" ]; then
        SHARED_PIP_SHOW=$(VIRTUAL_ENV="$UV_VENV" uv pip show cli-tools-shared 2>/dev/null)
        existing_shared_editable_location=$(echo "$SHARED_PIP_SHOW" | awk -F': ' '/^Editable project location:/ { print $2; exit }')
        if [ "$existing_shared_editable_location" = "$LOCAL_SHARED_DIR" ]; then
            existing_shared_editable_install="true"
        else
            existing_shared_editable_install="false"
        fi
    fi

    "$LAUNCHER" --help >/dev/null 2>&1 && existing_help_works="true"

    existing_python_exe=""
    if [ -x "$UV_VENV/bin/python3" ]; then
        existing_python_exe="$UV_VENV/bin/python3"
    elif [ -x "$UV_VENV/bin/python" ]; then
        existing_python_exe="$UV_VENV/bin/python"
    fi
    if [ -n "$existing_python_exe" ]; then
        existing_python_version=""
        if existing_python_version=$("$existing_python_exe" --version 2>&1); then
            if [ -z "$PYTHON_REQUEST" ]; then
                existing_python_matches_request="true"
            elif [[ "$PYTHON_REQUEST" = /* ]]; then
                requested_python_version=""
                if [ -x "$PYTHON_REQUEST" ] && requested_python_version=$("$PYTHON_REQUEST" --version 2>&1); then
                    existing_python_major_minor=$(printf '%s\n' "$existing_python_version" | awk '{ print $2 }' | awk -F. '{ print $1 "." $2 }')
                    requested_python_major_minor=$(printf '%s\n' "$requested_python_version" | awk '{ print $2 }' | awk -F. '{ print $1 "." $2 }')
                    [ -n "$existing_python_major_minor" ] && [ "$existing_python_major_minor" = "$requested_python_major_minor" ] && existing_python_matches_request="true"
                fi
            else
                existing_python_major_minor=$(printf '%s\n' "$existing_python_version" | awk '{ print $2 }' | awk -F. '{ print $1 "." $2 }')
                [ "$existing_python_major_minor" = "$PYTHON_REQUEST" ] && existing_python_matches_request="true"
            fi
        fi
    fi

    if [ "$metadata_refresh_needed" = "false" ] && [ "$existing_editable_install" = "true" ] && [ "$existing_help_works" = "true" ] && [ "$existing_python_matches_request" = "true" ] && { [ "$existing_shared_editable_install" = "true" ] || [ "$existing_shared_editable_install" = "skipped" ]; }; then
        existing_shared_editable_location_json="null"
        [ -n "$existing_shared_editable_location" ] && existing_shared_editable_location_json="\"$existing_shared_editable_location\""
        cat <<EOF
{
  "success": true,
  "cli_name": "$CLI_NAME",
  "install_exit_code": 0,
  "install_output": "Existing editable install is healthy; skipped uv tool force refresh.",
  "editable_install": true,
  "editable_location": "$existing_editable_location",
  "shared_editable_install": "$existing_shared_editable_install",
  "shared_editable_location": $existing_shared_editable_location_json,
  "symlink_exists": true,
  "help_works": true
}
EOF
        exit 0
    fi
fi

# ============================================================================
# Install via uv tool install (editable mode, force reinstall)
# ============================================================================
# uv builds/resolves the tool against the interpreter it is given. Forcing the
# ambient python3 breaks when it is older than the tool's requires-python (e.g.
# macOS system 3.9 vs a >=3.11 tool: uv reports "requirements are
# unsatisfiable"). resolve_uv_python.py returns the ambient interpreter when it
# already satisfies the constraint, otherwise a compatible "3.X" version request
# for uv to find or download.
PY_FLAG=()
[ -n "$PYTHON_REQUEST" ] && PY_FLAG=(--python "$PYTHON_REQUEST")

OVERRIDE_FLAG=()
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
