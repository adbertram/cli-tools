#!/usr/bin/env bash
set -euo pipefail

# Delegate to the canonical cli-tools installer so shippo inherits the shared
# interpreter-resolution logic (resolve_uv_python.py -> an ABSOLUTE python path),
# the editable cli-tools-shared overlay, the editable-install verification, and
# the --help smoke test.
#
# Do NOT hand-roll `uv tool install ... --python python3` here. A bare `python3`
# request is resolved by uv against its own discovery order and can silently
# reuse a uv-managed interpreter (e.g. 3.12) instead of the system python3
# (e.g. 3.14), which then fails `test_cli_uses_system_python`. The canonical
# installer passes an absolute interpreter path, which avoids that pitfall.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI_NAME="shippo"
CLI_TOOLS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTALLER="$CLI_TOOLS_ROOT/_repo/skills/cli-tool/scripts/install-cli-tool.sh"

echo "Installing $CLI_NAME CLI..."

if ! command -v uv >/dev/null 2>&1; then
    echo "Error: uv is required but not found" >&2
    exit 1
fi

if [ ! -x "$INSTALLER" ]; then
    echo "Error: canonical installer not found or not executable: $INSTALLER" >&2
    exit 1
fi

# install-cli-tool.sh prints a JSON result and exits non-zero on failure (set -e
# below propagates that). It already verifies the launcher and runs --help.
"$INSTALLER" "$CLI_NAME"

echo "Installation complete: $(command -v "$CLI_NAME")"
