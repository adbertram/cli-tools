#!/usr/bin/env bash
# Remove a CLI tool and every artifact that registers it
# Usage: remove-cli-tool.sh <tool-name>

set -e

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    printf '%s\n' 'Usage: remove-cli-tool.sh <tool-name>'
    exit 0
fi

TOOL_NAME="${1:-}"

if [ -z "$TOOL_NAME" ]; then
    echo "Error: Tool name required" >&2
    echo "Usage: remove-cli-tool.sh <tool-name>" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI_TOOLS_DIR="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
TOOL_DIR="$CLI_TOOLS_DIR/$TOOL_NAME"
SKILL_DIR="$CLI_TOOLS_DIR/_repo/skills/${TOOL_NAME}-cli"
TEST_CONFIG="$CLI_TOOLS_DIR/_repo/skills/cli-tool/tests/cli_test_config.toml"
README_PATH="$CLI_TOOLS_DIR/README.md"
DOCS_PATH="$CLI_TOOLS_DIR/_repo/docs/cli_tools.md"
SYMLINK_PATH="$HOME/.local/bin/$TOOL_NAME"

# Check if tool directory exists
if [ ! -d "$TOOL_DIR" ]; then
    echo "Error: CLI tool '$TOOL_NAME' not found at $TOOL_DIR" >&2
    exit 1
fi

# The harness-config and README rows are stripped with python3, so refuse before
# deleting anything when it is unavailable.
PYTHON_BIN="$(command -v python3 || :)"
if [ -z "$PYTHON_BIN" ]; then
    echo "Error: remove-cli-tool.sh needs python3 on PATH to strip the tool's registration rows." >&2
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
if [ -d "$SKILL_DIR" ]; then
    echo "  Skill: $SKILL_DIR"
else
    echo "  Skill: (not found)"
fi

# Remove directory
rm -rf "$TOOL_DIR"
echo "Removed: $TOOL_DIR"

# Remove symlink if exists
if [ -L "$SYMLINK_PATH" ]; then
    rm -f "$SYMLINK_PATH"
    echo "Removed: $SYMLINK_PATH"
fi

# Remove the tool's own service skill
if [ -d "$SKILL_DIR" ]; then
    rm -rf "$SKILL_DIR"
    echo "Removed: $SKILL_DIR"
fi

# Strip the tool's registration rows: its [cli_specific.<tool>] section (plus any
# nested sub-tables) in the harness test config, and its row in the root README.
"$PYTHON_BIN" - "$TEST_CONFIG" "$README_PATH" "$TOOL_NAME" <<'PY'
import re
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
readme_path = Path(sys.argv[2])
tool = sys.argv[3]
section = f"cli_specific.{tool}"

if config_path.is_file():
    lines = config_path.read_text().splitlines(keepends=True)
    kept = []
    skipping = False
    removed = 0
    for line in lines:
        header = line.strip()
        if header.startswith("["):
            table = header.split("]", 1)[0].lstrip("[")
            skipping = table == section or table.startswith(section + ".")
        if skipping:
            removed += 1
            continue
        kept.append(line)
    if removed:
        text = re.sub(r"\n{3,}", "\n\n", "".join(kept))
        config_path.write_text(text)
        print(f"Removed: [{section}] section from {config_path}")
    else:
        print(f"Unchanged: no [{section}] section in {config_path}")
else:
    print(f"Unchanged: {config_path} not found")

row = re.compile(rf"^\|\s*\[`{re.escape(tool)}`\]\({re.escape(tool)}/\)")
if readme_path.is_file():
    lines = readme_path.read_text().splitlines(keepends=True)
    kept = [line for line in lines if not row.match(line)]
    if len(kept) != len(lines):
        readme_path.write_text("".join(kept))
        print(f"Removed: README.md table row for '{tool}'")
    else:
        print(f"Unchanged: no README.md table row for '{tool}'")
else:
    print(f"Unchanged: {readme_path} not found")
PY

# Uninstall from uv tools. A tool that is not installed (uv exits non-zero) must
# not strand the rest of the removal, so this step is best-effort.
uv tool uninstall "${TOOL_NAME}-cli" 2>/dev/null || true

echo "Done. Remember to update $DOCS_PATH manually."
