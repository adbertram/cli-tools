#!/usr/bin/env bash
# Compatibility wrapper for the old _repo/tools helper path.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

exec "$REPO_ROOT/_repo/scripts/find-cli-tools.sh" "$@"
