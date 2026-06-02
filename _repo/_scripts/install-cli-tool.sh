#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s <tool-folder>\n' "$(basename "$0")" >&2
}

if [[ $# -ne 1 ]]; then
    usage
    exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TOOL_DIR="$REPO_ROOT/$1"

if [[ ! -f "$TOOL_DIR/pyproject.toml" ]]; then
    printf 'Tool folder not found or missing pyproject.toml: %s\n' "$1" >&2
    exit 1
fi

exec uv tool install --force --editable "$TOOL_DIR"
