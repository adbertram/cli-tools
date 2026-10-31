#!/usr/bin/env bash
# SessionStart hook: inject the CLI tool names into context at session start,
# so a session knows what's available without deciding to look it up mid-task.
# Names only, to keep the per-session context cost small; per-tool details
# come from find-cli-tools.sh through the cli-tool skill.
#
# Wired as a Claude Code SessionStart hook in ~/.claude/settings.json; plain
# stdout is the injected context, so nothing else may print to stdout.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
printf '%s\n' 'Available CLI tools. Before running one, load the `cli-tool` skill to learn its command structure — do not guess syntax; that skill gets each tool'"'"'s details from `find-cli-tools.sh`:'
exec "$SCRIPT_DIR/find-cli-tools.sh" --names
