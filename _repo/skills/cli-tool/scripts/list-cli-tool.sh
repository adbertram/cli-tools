#!/usr/bin/env bash
# List all CLI tools in the cli-tools repository
# Usage: list-cli-tool.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI_TOOLS_DIR="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
SYMLINK_DIR="$HOME/.local/bin"

if [ ! -d "$CLI_TOOLS_DIR" ]; then
    echo "Error: CLI tools directory not found at $CLI_TOOLS_DIR" >&2
    exit 1
fi

# Get all installable CLI tool directories.
# A top-level folder counts only if it has a pyproject.toml.
for tool_dir in "$CLI_TOOLS_DIR"/*/; do
    [ -d "$tool_dir" ] || continue
    tool_name=$(basename "$tool_dir")

    # Skip non-tool directories
    [[ "$tool_name" == _* ]] && continue
    [[ ! -f "$tool_dir/pyproject.toml" ]] && continue

    # Check if symlink exists
    symlink_path="$SYMLINK_DIR/$tool_name"
    if [ -L "$symlink_path" ]; then
        status="✓"
    else
        status="✗"
    fi

    echo "$status $tool_name"
done | sort -t' ' -k2
