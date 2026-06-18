#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s <tool-name-or-folder>\n' "$(basename "$0")" >&2
}

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

if [[ ! -f "$TOOL_DIR/pyproject.toml" ]]; then
    printf 'Tool folder not found or missing pyproject.toml: %s\n' "$1" >&2
    exit 1
fi

uv tool install --force --editable "$TOOL_DIR"

LAUNCHER="$HOME/.local/bin/$CLI_NAME"
if [[ ! -x "$LAUNCHER" ]]; then
    printf 'uv tool install completed but did not create expected launcher: %s\n' "$LAUNCHER" >&2
    exit 1
fi

"$LAUNCHER" --help >/dev/null
