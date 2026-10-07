#!/usr/bin/env bash
# SessionStart hook (Claude Code + Codex): inject the available CLI tool
# inventory into context at session start, so a session already knows what's
# available without deciding to go look it up mid-task.
#
# Both runtimes accept plain stdout text for SessionStart, so this script is
# shared as-is between ~/.claude/settings.json and ~/.codex/hooks.json.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/find-cli-tools.sh" --markdown --summary
