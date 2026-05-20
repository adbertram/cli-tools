#!/usr/bin/env bash
# CLI tools secret store backed by macOS Keychain.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
. "$REPO_ROOT/scripts/lib/log.sh"

SERVICE="cli-tools"

die() {
    log_error "$*"
    echo "secrets: $*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
secrets.sh - CLI tools secret store (macOS Keychain)

Commands:
  set <name> [value]   Store secret. Value from arg, $SECRET_VALUE, or stdin.
  get <name>           Print secret value.
  delete <name>        Remove secret.
  has <name>           Exit 0 if exists, 1 if not.
  list                 List secret names.

Service namespace: cli-tools
EOF
}

cmd_set() {
    local name="${1:-}"
    [[ -n "$name" ]] || die "set requires <name>"

    local value="${2:-}"
    if [[ -z "$value" ]]; then
        if [[ -n "${SECRET_VALUE:-}" ]]; then
            value="$SECRET_VALUE"
            log_info "secret value sourced from SECRET_VALUE"
        elif [[ ! -t 0 ]]; then
            log_info "secret value sourced from stdin"
            value="$(cat)"
        else
            die "no value provided (arg, SECRET_VALUE, or stdin)"
        fi
    fi

    log_info "security add-generic-password (service=$SERVICE account=$name)"
    security add-generic-password -U -s "$SERVICE" -a "$name" -w "$value"
    log_info "security add-generic-password completed (service=$SERVICE account=$name)"
}

cmd_get() {
    local name="${1:-}"
    [[ -n "$name" ]] || die "get requires <name>"

    log_info "security find-generic-password (service=$SERVICE account=$name)"
    security find-generic-password -s "$SERVICE" -a "$name" -w
    log_info "security find-generic-password completed (service=$SERVICE account=$name)"
}

cmd_delete() {
    local name="${1:-}"
    [[ -n "$name" ]] || die "delete requires <name>"

    log_info "security delete-generic-password (service=$SERVICE account=$name)"
    security delete-generic-password -s "$SERVICE" -a "$name" >/dev/null
    log_info "security delete-generic-password completed (service=$SERVICE account=$name)"
}

cmd_has() {
    local name="${1:-}"
    [[ -n "$name" ]] || die "has requires <name>"

    log_info "security find-generic-password check (service=$SERVICE account=$name)"
    if security find-generic-password -s "$SERVICE" -a "$name" >/dev/null 2>&1; then
        log_info "secret exists (service=$SERVICE account=$name)"
        return 0
    fi
    log_info "secret absent (service=$SERVICE account=$name)"
    return 1
}

cmd_list() {
    log_info "security dump-keychain list (service=$SERVICE)"
    security dump-keychain 2>/dev/null | awk -v svc="$SERVICE" '
        /^keychain:/ { svc_match=0; acct="" }
        /"svce"<blob>=/ {
            line=$0
            sub(/.*"svce"<blob>="/, "", line)
            sub(/".*/, "", line)
            if (line == svc) svc_match=1
        }
        /"acct"<blob>=/ {
            line=$0
            sub(/.*"acct"<blob>="/, "", line)
            sub(/".*/, "", line)
            acct=line
        }
        svc_match && acct { print acct; svc_match=0; acct="" }
    ' | sort -u
    log_info "security dump-keychain list completed (service=$SERVICE)"
}

main() {
    local sub="${1:-}"
    shift || true
    log_info "starting $(basename "$0") command=${sub:-help} service=$SERVICE"

    case "$sub" in
        set) cmd_set "$@" ;;
        get) cmd_get "$@" ;;
        delete) cmd_delete "$@" ;;
        has) cmd_has "$@" ;;
        list) cmd_list "$@" ;;
        ""|-h|--help|help) usage ;;
        *) die "unknown command: $sub (try --help)" ;;
    esac

    log_info "done $(basename "$0") command=${sub:-help}"
}

main "$@"
