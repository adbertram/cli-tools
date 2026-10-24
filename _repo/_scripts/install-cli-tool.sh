#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s [--force-refresh] <tool-name-or-folder>\n' "$(basename "$0")" >&2
}

FORCE_REFRESH=false
if [[ "${1:-}" == "--force-refresh" ]]; then
    FORCE_REFRESH=true
    shift
fi

if [[ $# -ne 1 ]]; then
    usage
    exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
REQUESTED_TOOL="$1"
TOOL_DIR="$REPO_ROOT/$REQUESTED_TOOL"
if [[ ! -f "$TOOL_DIR/pyproject.toml" && "$REQUESTED_TOOL" != */* ]]; then
    PERSONAL_TOOL_DIR="$REPO_ROOT/_personal/$REQUESTED_TOOL"
    if [[ -f "$PERSONAL_TOOL_DIR/pyproject.toml" ]]; then
        TOOL_DIR="$PERSONAL_TOOL_DIR"
    fi
fi
CLI_NAME="$(basename "$TOOL_DIR")"

# ============================================================================
# Refuse to run from a linked git worktree
# ============================================================================
# Same defect as _repo/skills/cli-tool/scripts/install-cli-tool.sh: `uv tool
# install` writes into a single global registry shared by every checkout
# (~/.local/share/uv/tools/<pkg>), so running this installer from a linked
# worktree overlays cli-tools-shared from that worktree's copy into the
# global registry -- once the worktree is removed, every CLI installed from
# here keeps resolving to the now-missing path. This is the failure that
# broke the production bricklink and garrul CLIs.
#
# CLI_TOOLS_ALLOW_WORKTREE_INSTALL=1 bypasses this refusal, for tests/CI that
# redirect HOME to a throwaway fixture so there is no real global registry to
# corrupt. Do not set it for an actual repair or update run.
if [[ "${CLI_TOOLS_ALLOW_WORKTREE_INSTALL:-}" != "1" ]]; then
    GIT_DIR_RAW="$(git -C "$REPO_ROOT" rev-parse --git-dir 2>/dev/null || true)"
    GIT_COMMON_DIR_RAW="$(git -C "$REPO_ROOT" rev-parse --git-common-dir 2>/dev/null || true)"
    if [[ -n "$GIT_DIR_RAW" && -n "$GIT_COMMON_DIR_RAW" ]]; then
        [[ "$GIT_DIR_RAW" = /* ]] || GIT_DIR_RAW="$REPO_ROOT/$GIT_DIR_RAW"
        [[ "$GIT_COMMON_DIR_RAW" = /* ]] || GIT_COMMON_DIR_RAW="$REPO_ROOT/$GIT_COMMON_DIR_RAW"
        GIT_DIR_ABS="$(cd "$GIT_DIR_RAW" 2>/dev/null && pwd || true)"
        GIT_COMMON_DIR_ABS="$(cd "$GIT_COMMON_DIR_RAW" 2>/dev/null && pwd || true)"
        if [[ -n "$GIT_DIR_ABS" && -n "$GIT_COMMON_DIR_ABS" && "$GIT_DIR_ABS" != "$GIT_COMMON_DIR_ABS" ]]; then
            printf 'install-cli-tool.sh refuses to run from a linked git worktree (%s). uv tool install writes into a single global registry shared by every checkout, so this run would overlay cli-tools-shared from this worktree'"'"'s copy -- once the worktree is removed, that dependency silently breaks for every CLI installed from here. Run this from the canonical cli-tools checkout instead.\n' "$REPO_ROOT" >&2
            exit 1
        fi
    fi
fi

if [[ ! -f "$TOOL_DIR/pyproject.toml" ]]; then
    printf 'Tool folder not found or missing pyproject.toml: %s\n' "$1" >&2
    exit 1
fi

LAUNCHER="$HOME/.local/bin/$CLI_NAME"
if [[ "$FORCE_REFRESH" == false && -x "$LAUNCHER" ]]; then
    "$LAUNCHER" --help >/dev/null
    printf 'Existing launcher is healthy; skipped uv tool force refresh: %s\n' "$LAUNCHER"
    exit 0
fi

# Pin the interpreter. An unpinned `uv tool install` uses uv's default
# python-preference = "managed", which installs the CLI against a uv-managed
# interpreter (observed: CPython 3.12.10) instead of the system python3 and
# fails tests/test_python_version.py::test_cli_uses_system_python.
PYTHON_RESOLVER="$REPO_ROOT/_repo/skills/cli-tool/scripts/resolve_uv_python.py"
if [[ ! -f "$PYTHON_RESOLVER" ]]; then
    printf 'Interpreter resolver not found: %s\n' "$PYTHON_RESOLVER" >&2
    exit 1
fi
PYTHON_REQUEST="$(python3 "$PYTHON_RESOLVER" "$TOOL_DIR/pyproject.toml")"
if [[ -z "$PYTHON_REQUEST" ]]; then
    printf 'resolve_uv_python.py returned an empty interpreter request for %s\n' "$TOOL_DIR" >&2
    exit 1
fi

uv tool install --force --editable "$TOOL_DIR" --python "$PYTHON_REQUEST"

if [[ ! -x "$LAUNCHER" ]]; then
    printf 'uv tool install completed but did not create expected launcher: %s\n' "$LAUNCHER" >&2
    exit 1
fi

"$LAUNCHER" --help >/dev/null
