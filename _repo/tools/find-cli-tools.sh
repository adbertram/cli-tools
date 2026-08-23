#!/usr/bin/env bash
# Compatibility wrapper for the old _repo/tools helper path.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"

exec "$REPO_ROOT/_repo/scripts/find-cli-tools.sh" "$@"
