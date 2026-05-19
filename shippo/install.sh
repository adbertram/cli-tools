#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI_NAME="shippo"

echo "Installing $CLI_NAME CLI..."

if ! command -v uv >/dev/null 2>&1; then
    echo "Error: uv is required but not found" >&2
    exit 1
fi

uv tool install -e "$SCRIPT_DIR" --force --refresh --python python3

if ! command -v "$CLI_NAME" >/dev/null 2>&1; then
    echo "Error: $CLI_NAME was installed but is not on PATH" >&2
    exit 1
fi

"$CLI_NAME" --help >/dev/null

echo "Installation complete: $(command -v "$CLI_NAME")"
