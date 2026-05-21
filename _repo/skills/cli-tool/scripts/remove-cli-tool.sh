#!/usr/bin/env bash
# Remove a CLI tool's directory and symlink
# Usage: remove-cli-tool.sh <tool-name>

set -e

TOOL_NAME="$1"

if [ -z "$TOOL_NAME" ]; then
    echo "Error: Tool name required" >&2
    echo "Usage: remove-cli-tool.sh <tool-name>" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI_TOOLS_DIR="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
TOOL_DIR="$CLI_TOOLS_DIR/$TOOL_NAME"
SYMLINK_PATH="$HOME/.local/bin/$TOOL_NAME"

# Check if tool directory exists
if [ ! -d "$TOOL_DIR" ]; then
    echo "Error: CLI tool '$TOOL_NAME' not found at $TOOL_DIR" >&2
    exit 1
fi

# Show what will be removed
echo "Found:"
echo "  Directory: $TOOL_DIR"
if [ -L "$SYMLINK_PATH" ]; then
    echo "  Symlink: $SYMLINK_PATH"
else
    echo "  Symlink: (not found)"
fi

# Remove directory
rm -rf "$TOOL_DIR"
echo "Removed: $TOOL_DIR"

# Remove symlink if exists
if [ -L "$SYMLINK_PATH" ]; then
    rm -f "$SYMLINK_PATH"
    echo "Removed: $SYMLINK_PATH"
fi

# Uninstall from uv tools
uv tool uninstall "${TOOL_NAME}-cli" 2>/dev/null

echo "Done. Remember to update $CLI_TOOLS_DIR/docs/cli_tools.md manually."
