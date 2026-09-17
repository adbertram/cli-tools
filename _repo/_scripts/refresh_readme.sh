#!/usr/bin/env bash
# Refresh the root README tool catalog from current CLI tool folders.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
# shellcheck source=_repo/_scripts/lib/log.sh
. "$REPO_ROOT/_repo/_scripts/lib/log.sh"

usage() {
    printf 'Usage: %s [--check]\n' "$(basename "$0")"
    printf '\n'
    printf 'Refresh README.md from top-level CLI tool folders.\n'
    printf '\n'
    printf 'Options:\n'
    printf '  --check   Exit non-zero if README.md is not current; do not write it.\n'
    printf '  -h, --help\n'
}

check_only=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --check)
            check_only=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            log_error "unknown argument: $1"
            usage >&2
            exit 2
            ;;
    esac
done

log_info "starting $(basename "$0") check_only=$check_only"
log_info "refreshing README.md from top-level pyproject.toml files"
python3 "$SCRIPT_DIR/refresh_readme.py" "$REPO_ROOT" "$check_only"
log_info "README.md refresh completed"
log_info "done"
