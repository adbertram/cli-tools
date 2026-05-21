#!/usr/bin/env bash
# CLI tools secret store backed by macOS Keychain.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOTE_CONTEXT="${CLI_TOOLS_SECRETS_REMOTE_CONTEXT:-0}"
REMOTE_HOST_CONTEXT="${CLI_TOOLS_SECRETS_REMOTE_HOST:-}"

if [[ "$REMOTE_CONTEXT" == "1" ]]; then
    DEFAULT_LOG_FILE="${HOME}/.local/share/cli-tools/secrets.log"
else
    DEFAULT_LOG_FILE="${SCRIPT_DIR}/secrets.log"
fi
LOG_FILE="${LOG_FILE:-$DEFAULT_LOG_FILE}"
mkdir -p "$(dirname "$LOG_FILE")"

SERVICE="cli-tools"
KEYCHAIN="${CLI_TOOLS_KEYCHAIN:-$HOME/Library/Keychains/login.keychain-db}"
KEYCHAIN_ARGS=("$KEYCHAIN")

log_ts() {
    date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log_line() {
    local level="$1"
    shift
    printf '[%s] [%s] %s\n' "$(log_ts)" "$level" "$*" >>"$LOG_FILE"
}

log_info() {
    log_line "INFO" "$@"
}

log_error() {
    log_line "ERROR" "$@"
}

log_exit_trap() {
    local rc=$?
    printf 'Log: %s\n' "$LOG_FILE" >&2
    exit "$rc"
}
trap log_exit_trap EXIT

die() {
    log_error "$*"
    echo "secrets: $*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
secrets.sh - CLI tools secret store (macOS Keychain)

Usage:
  secrets.sh [--remote-host <host>] <command> [args]

Commands:
  set <name> [value]   Store secret. Value from arg, $SECRET_VALUE, or stdin.
  get <name>           Print secret value.
  delete <name>        Remove secret.
  has <name>           Exit 0 if exists, 1 if not.
  list                 List secret names.

Options:
  --remote-host <host> Run the command on the remote host over SSH.
                       If the remote keychain must be unlocked, re-run from an
                       interactive terminal so the remote session has a TTY.

Service namespace: cli-tools
EOF
}

shell_quote() {
    printf '%q' "$1"
}

has_tty() {
    [[ -t 1 || -t 2 ]]
}

resolve_set_value() {
    local value="${1:-}"
    if [[ -n "$value" ]]; then
        printf '%s' "$value"
        return 0
    fi

    if [[ -n "${SECRET_VALUE:-}" ]]; then
        log_info "secret value sourced from SECRET_VALUE"
        printf '%s' "$SECRET_VALUE"
        return 0
    fi

    if [[ ! -t 0 ]]; then
        log_info "secret value sourced from stdin"
        cat
        return 0
    fi

    die "no value provided (arg, SECRET_VALUE, or stdin)"
}

run_security() {
    local stdout_file
    local stderr_file
    local status

    stdout_file="$(mktemp "${TMPDIR:-/tmp}/cli-tools-secrets.stdout.XXXXXX")"
    stderr_file="$(mktemp "${TMPDIR:-/tmp}/cli-tools-secrets.stderr.XXXXXX")"

    if "$@" >"$stdout_file" 2>"$stderr_file"; then
        cat "$stdout_file"
        rm -f "$stdout_file" "$stderr_file"
        return 0
    else
        status=$?
    fi

    if [[ "$REMOTE_CONTEXT" == "1" ]] && grep -Fq "User interaction is not allowed." "$stderr_file"; then
        unlock_keychain_for_remote_host
        : >"$stdout_file"
        : >"$stderr_file"
        if "$@" >"$stdout_file" 2>"$stderr_file"; then
            cat "$stdout_file"
            rm -f "$stdout_file" "$stderr_file"
            return 0
        else
            status=$?
        fi
    fi

    cat "$stderr_file" >&2
    rm -f "$stdout_file" "$stderr_file"
    return "$status"
}

unlock_keychain_for_remote_host() {
    local host_label="${REMOTE_HOST_CONTEXT:-remote host}"
    if ! has_tty; then
        die "remote host ${host_label} requires an interactive TTY to unlock keychain ${KEYCHAIN}; re-run from a terminal"
    fi

    log_info "unlocking keychain for remote host ${host_label} keychain=${KEYCHAIN}"
    if ! security unlock-keychain "${KEYCHAIN_ARGS[@]}" </dev/tty >/dev/tty 2>&1; then
        die "failed to unlock keychain ${KEYCHAIN} on remote host ${host_label}"
    fi
    log_info "keychain unlocked for remote host ${host_label} keychain=${KEYCHAIN}"
}

cmd_set() {
    local name="${1:-}"
    [[ -n "$name" ]] || die "set requires <name>"

    local value
    value="$(resolve_set_value "${2:-}")"

    log_info "security add-generic-password (service=$SERVICE account=$name)"
    run_security security add-generic-password -U -s "$SERVICE" -a "$name" -w "$value" "${KEYCHAIN_ARGS[@]}" >/dev/null
    log_info "security add-generic-password completed (service=$SERVICE account=$name)"
}

cmd_get() {
    local name="${1:-}"
    [[ -n "$name" ]] || die "get requires <name>"

    log_info "security find-generic-password (service=$SERVICE account=$name)"
    run_security security find-generic-password -s "$SERVICE" -a "$name" -w "${KEYCHAIN_ARGS[@]}"
    log_info "security find-generic-password completed (service=$SERVICE account=$name)"
}

cmd_delete() {
    local name="${1:-}"
    [[ -n "$name" ]] || die "delete requires <name>"

    log_info "security delete-generic-password (service=$SERVICE account=$name)"
    run_security security delete-generic-password -s "$SERVICE" -a "$name" "${KEYCHAIN_ARGS[@]}" >/dev/null
    log_info "security delete-generic-password completed (service=$SERVICE account=$name)"
}

cmd_has() {
    local name="${1:-}"
    [[ -n "$name" ]] || die "has requires <name>"
    local status

    log_info "security find-generic-password check (service=$SERVICE account=$name)"
    if run_security security find-generic-password -s "$SERVICE" -a "$name" "${KEYCHAIN_ARGS[@]}" >/dev/null; then
        log_info "secret exists (service=$SERVICE account=$name)"
        return 0
    else
        status=$?
    fi

    if [[ "$status" -ne 44 ]]; then
        return "$status"
    fi

    log_info "secret absent (service=$SERVICE account=$name)"
    return 1
}

cmd_list() {
    log_info "security dump-keychain list (service=$SERVICE)"
    run_security security dump-keychain "${KEYCHAIN_ARGS[@]}" | awk -v svc="$SERVICE" '
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

cleanup_remote_dir() {
    local host="$1"
    local remote_dir="$2"
    local cleanup_command

    cleanup_command="rm -rf -- $(shell_quote "$remote_dir")"
    ssh "$host" "bash -lc $(shell_quote "$cleanup_command")" >/dev/null 2>&1 || true
}

dispatch_remote() {
    local host="$1"
    shift

    local sub="${1:-}"
    local remote_dir=""
    local remote_script=""
    local remote_payload_file=""
    local local_payload_file=""
    local create_dir_command='mktemp -d "${TMPDIR:-/tmp}/cli-tools-secrets.XXXXXX"'
    local remote_command=""
    local ssh_command_flags=()
    local remote_args=("$@")

    if [[ "$sub" == "set" ]]; then
        local name="${2:-}"
        [[ -n "$name" ]] || die "set requires <name>"
        local_payload_file="$(mktemp "${TMPDIR:-/tmp}/cli-tools-secrets.payload.XXXXXX")"
        chmod 600 "$local_payload_file"
        resolve_set_value "${3:-}" >"$local_payload_file"
        remote_args=("set" "$name")
    fi

    log_info "dispatching command to remote host=$host command=${sub:-help}"
    if ! remote_dir="$(ssh "$host" "bash -lc $(shell_quote "$create_dir_command")")"; then
        rm -f "$local_payload_file"
        die "failed to create remote temp directory on $host"
    fi
    remote_dir="${remote_dir%$'\n'}"
    if [[ -z "$remote_dir" ]]; then
        rm -f "$local_payload_file"
        die "remote host $host did not return a temp directory"
    fi
    remote_script="${remote_dir}/secrets.sh"

    if ! scp -q "$0" "$host:$remote_script"; then
        rm -f "$local_payload_file"
        cleanup_remote_dir "$host" "$remote_dir"
        die "failed to copy secrets.sh to remote host $host"
    fi

    if [[ "$sub" == "set" ]]; then
        remote_payload_file="${remote_dir}/secret.value"
        if ! scp -q "$local_payload_file" "$host:$remote_payload_file"; then
            rm -f "$local_payload_file"
            cleanup_remote_dir "$host" "$remote_dir"
            die "failed to copy secret payload to remote host $host"
        fi
        rm -f "$local_payload_file"
        local_payload_file=""
    fi

    remote_command="set -euo pipefail; "
    remote_command+="cleanup(){ rm -rf -- $(shell_quote "$remote_dir"); }; trap cleanup EXIT; "
    remote_command+="chmod 700 $(shell_quote "$remote_script"); "
    if [[ "$sub" == "set" ]]; then
        remote_command+="chmod 600 $(shell_quote "$remote_payload_file"); "
    fi
    remote_command+="CLI_TOOLS_SECRETS_REMOTE_CONTEXT=1 "
    remote_command+="CLI_TOOLS_SECRETS_REMOTE_HOST=$(shell_quote "$host") "
    if [[ -n "${CLI_TOOLS_KEYCHAIN:-}" ]]; then
        remote_command+="CLI_TOOLS_KEYCHAIN=$(shell_quote "$CLI_TOOLS_KEYCHAIN") "
    fi
    remote_command+="bash $(shell_quote "$remote_script")"
    for arg in "${remote_args[@]}"; do
        remote_command+=" $(shell_quote "$arg")"
    done
    if [[ "$sub" == "set" ]]; then
        remote_command+=" < $(shell_quote "$remote_payload_file")"
    fi

    if has_tty; then
        ssh_command_flags=(-tt)
    else
        ssh_command_flags=(-T)
    fi

    if ssh "${ssh_command_flags[@]}" "$host" "bash -lc $(shell_quote "$remote_command")"; then
        :
    else
        local status=$?
        cleanup_remote_dir "$host" "$remote_dir"
        return "$status"
    fi

    log_info "remote command completed host=$host command=${sub:-help}"
}

main() {
    local remote_host=""
    local argv=()

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --remote-host)
                [[ $# -ge 2 ]] || die "--remote-host requires <host>"
                remote_host="$2"
                shift 2
                ;;
            -h|--help|help)
                argv+=("$1")
                shift
                ;;
            --)
                shift
                while [[ $# -gt 0 ]]; do
                    argv+=("$1")
                    shift
                done
                ;;
            -*)
                die "unknown option: $1 (try --help)"
                ;;
            *)
                while [[ $# -gt 0 ]]; do
                    argv+=("$1")
                    shift
                done
                ;;
        esac
    done

    set -- "${argv[@]}"
    local sub="${1:-}"
    local status=0

    log_info "starting $(basename "$0") command=${sub:-help} service=$SERVICE remote_host=${remote_host:-local}"

    if [[ -n "$remote_host" && "$REMOTE_CONTEXT" != "1" && "$sub" != "" && "$sub" != "-h" && "$sub" != "--help" && "$sub" != "help" ]]; then
        if dispatch_remote "$remote_host" "$@"; then
            status=0
        else
            status=$?
        fi
        log_info "done $(basename "$0") command=${sub:-help}"
        return "$status"
    fi

    shift || true
    case "$sub" in
        set) if cmd_set "$@"; then status=0; else status=$?; fi ;;
        get) if cmd_get "$@"; then status=0; else status=$?; fi ;;
        delete) if cmd_delete "$@"; then status=0; else status=$?; fi ;;
        has) if cmd_has "$@"; then status=0; else status=$?; fi ;;
        list) if cmd_list; then status=0; else status=$?; fi ;;
        ""|-h|--help|help) usage ;;
        *) die "unknown command: $sub (try --help)" ;;
    esac

    log_info "done $(basename "$0") command=${sub:-help}"
    return "$status"
}

main "$@"
