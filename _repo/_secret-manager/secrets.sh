#!/usr/bin/env bash
# CLI tools secret store backed by macOS Keychain.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOTE_CONTEXT="${CLI_TOOLS_SECRETS_REMOTE_CONTEXT:-0}"
REMOTE_HOST_CONTEXT="${CLI_TOOLS_SECRETS_REMOTE_HOST:-}"

cli_tools_data_root() {
    local data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
    printf '%s/cli-tools\n' "$data_home"
}

if [[ "$REMOTE_CONTEXT" == "1" ]]; then
    DEFAULT_LOG_FILE="${HOME}/.local/share/cli-tools/secrets.log"
else
    DEFAULT_LOG_FILE="${SCRIPT_DIR}/secrets.log"
fi
LOG_FILE="${LOG_FILE:-$DEFAULT_LOG_FILE}"
mkdir -p "$(dirname "$LOG_FILE")"

SERVICE="cli-tools"
DEFAULT_KEYCHAIN="$(cli_tools_data_root)/cli-tools.keychain-db"
KEYCHAIN="${CLI_TOOLS_KEYCHAIN:-$DEFAULT_KEYCHAIN}"
MANAGED_DEFAULT_KEYCHAIN=0
if [[ -z "${CLI_TOOLS_KEYCHAIN:-}" ]]; then
    MANAGED_DEFAULT_KEYCHAIN=1
fi
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
  secrets.sh [--remote-host <host>] [--remote-unlock-secret <name>] <command> [args]

Commands:
  set --tool <cli-tool> --type <type> [value]
                       Store secret as <cli-tool>-<type>. Value from arg,
                       $SECRET_VALUE, or stdin.
  set <name> [value]   Store secret with an already-canonical full name.
  rename <old-name> --tool <cli-tool> --type <type>
                       Rename an existing secret to <cli-tool>-<type>.
  rename <old-name> <new-name>
                       Rename an existing secret to an already-canonical name.
  get <name>           Print secret value.
  delete <name>        Remove secret.
  has <name>           Exit 0 if exists, 1 if not.
  list                 List secret names.

Options:
  --remote-host <host> Run the command on the remote host over SSH.
                       If the remote keychain must be unlocked, re-run from an
                       interactive terminal so the remote session has a TTY.
  --remote-unlock-secret <name>
                       Local secret-manager entry containing the remote
                       keychain password. With --remote-host, the password is
                       copied to a private remote temp file and used to unlock
                       the remote keychain in the same SSH command before the
                       requested secret operation runs.

Service namespace: cli-tools
EOF
}

shell_quote() {
    printf '%q' "$1"
}

normalize_secret_part() {
    local value="$1"
    [[ "$value" =~ ^[a-z0-9][a-z0-9-]*$ ]] || die "invalid secret name part '$value' (use lowercase letters, numbers, and hyphens)"
    printf '%s' "$value"
}

canonical_secret_name() {
    local tool="$1"
    local type="$2"
    printf '%s-%s' "$(normalize_secret_part "$tool")" "$(normalize_secret_part "$type")"
}

parse_secret_name_args() {
    local tool=""
    local type=""
    local positional=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --tool)
                [[ $# -ge 2 ]] || die "--tool requires <cli-tool>"
                tool="$2"
                shift 2
                ;;
            --type)
                [[ $# -ge 2 ]] || die "--type requires <type>"
                type="$2"
                shift 2
                ;;
            --)
                shift
                while [[ $# -gt 0 ]]; do
                    positional+=("$1")
                    shift
                done
                ;;
            -*)
                die "unknown secret-name option: $1"
                ;;
            *)
                positional+=("$1")
                shift
                ;;
        esac
    done

    local name=""
    if [[ -n "$tool" || -n "$type" ]]; then
        [[ -n "$tool" ]] || die "--type requires --tool"
        [[ -n "$type" ]] || die "--tool requires --type"
        [[ "${#positional[@]}" -eq 0 ]] || die "--tool/--type cannot be combined with a full secret name"
        name="$(canonical_secret_name "$tool" "$type")"
    else
        [[ "${#positional[@]}" -eq 1 ]] || die "expected <name> or --tool <cli-tool> --type <type>"
        name="${positional[0]}"
        normalize_secret_part "$name" >/dev/null
    fi

    printf '%s' "$name"
}

parse_set_invocation() {
    PARSED_SET_NAME=""
    PARSED_SET_VALUE_ARG=""

    local tool=""
    local type=""
    local positional=()

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --tool)
                [[ $# -ge 2 ]] || die "--tool requires <cli-tool>"
                tool="$2"
                shift 2
                ;;
            --type)
                [[ $# -ge 2 ]] || die "--type requires <type>"
                type="$2"
                shift 2
                ;;
            --)
                shift
                while [[ $# -gt 0 ]]; do
                    positional+=("$1")
                    shift
                done
                ;;
            -*)
                die "unknown set option: $1"
                ;;
            *)
                positional+=("$1")
                shift
                ;;
        esac
    done

    if [[ -n "$tool" || -n "$type" ]]; then
        [[ -n "$tool" ]] || die "--type requires --tool"
        [[ -n "$type" ]] || die "--tool requires --type"
        [[ "${#positional[@]}" -le 1 ]] || die "set accepts only one secret value argument"
        PARSED_SET_NAME="$(canonical_secret_name "$tool" "$type")"
        if [[ "${#positional[@]}" -eq 1 ]]; then
            PARSED_SET_VALUE_ARG="${positional[0]}"
        fi
        return 0
    fi

    [[ "${#positional[@]}" -ge 1 ]] || die "set requires <name> or --tool <cli-tool> --type <type>"
    [[ "${#positional[@]}" -le 2 ]] || die "set accepts only one secret value argument"
    PARSED_SET_NAME="${positional[0]}"
    normalize_secret_part "$PARSED_SET_NAME" >/dev/null
    if [[ "${#positional[@]}" -eq 2 ]]; then
        PARSED_SET_VALUE_ARG="${positional[1]}"
    fi
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
        status=0
    else
        status=$?
    fi

    if [[ -s "$stderr_file" && "$REMOTE_CONTEXT" == "1" ]] && grep -Fq "User interaction is not allowed." "$stderr_file"; then
        unlock_keychain_for_remote_host
        : >"$stdout_file"
        : >"$stderr_file"
        if "$@" >"$stdout_file" 2>"$stderr_file"; then
            status=0
        else
            status=$?
        fi
    fi

    if [[ "$status" -eq 0 && -s "$stderr_file" ]] && ! grep -Fxq "password has been deleted." "$stderr_file"; then
        status=1
    fi

    if [[ "$status" -eq 0 ]]; then
        cat "$stdout_file"
        rm -f "$stdout_file" "$stderr_file"
        return 0
    fi

    cat "$stderr_file" >&2
    rm -f "$stdout_file" "$stderr_file"
    return "$status"
}

ensure_managed_keychain() {
    [[ "$MANAGED_DEFAULT_KEYCHAIN" == "1" ]] || return 0

    mkdir -p "$(dirname "$KEYCHAIN")"
    if [[ ! -e "$KEYCHAIN" ]]; then
        log_info "security create-keychain keychain=$KEYCHAIN"
        run_security security create-keychain -p "" "$KEYCHAIN" >/dev/null || return $?
        log_info "security create-keychain completed keychain=$KEYCHAIN"
    fi
    chmod 600 "$KEYCHAIN"

    log_info "security unlock-keychain keychain=$KEYCHAIN"
    run_security security unlock-keychain -p "" "${KEYCHAIN_ARGS[@]}" >/dev/null || return $?
    log_info "security unlock-keychain completed keychain=$KEYCHAIN"
}

unlock_keychain_for_remote_host() {
    local host_label="${REMOTE_HOST_CONTEXT:-remote host}"
    if [[ "$MANAGED_DEFAULT_KEYCHAIN" == "1" ]]; then
        log_info "unlocking managed keychain for remote host ${host_label} keychain=${KEYCHAIN}"
        if ! security unlock-keychain -p "" "${KEYCHAIN_ARGS[@]}" >/dev/null; then
            die "failed to unlock managed keychain ${KEYCHAIN} on remote host ${host_label}"
        fi
        log_info "managed keychain unlocked for remote host ${host_label} keychain=${KEYCHAIN}"
        return 0
    fi

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
    parse_set_invocation "$@"
    local name="$PARSED_SET_NAME"
    local value_arg="$PARSED_SET_VALUE_ARG"
    ensure_managed_keychain

    local value
    value="$(resolve_set_value "$value_arg")"

    log_info "security add-generic-password (service=$SERVICE account=$name)"
    run_security security add-generic-password -U -s "$SERVICE" -a "$name" -w "$value" "${KEYCHAIN_ARGS[@]}" >/dev/null || return $?
    log_info "security add-generic-password completed (service=$SERVICE account=$name)"
}

cmd_rename() {
    local old_name="${1:-}"
    [[ -n "$old_name" ]] || die "rename requires <old-name>"
    shift || true

    local new_name=""
    new_name="$(parse_secret_name_args "$@")"
    [[ "$old_name" != "$new_name" ]] || die "old and new secret names are the same: $old_name"
    ensure_managed_keychain

    local status=0
    if cmd_has "$new_name"; then
        die "target secret already exists: $new_name"
    else
        status=$?
        [[ "$status" -eq 1 ]] || return "$status"
    fi

    local value
    value="$(cmd_get "$old_name")"
    cmd_set "$new_name" "$value"
    cmd_delete "$old_name"
}

cmd_get() {
    local name="${1:-}"
    [[ -n "$name" ]] || die "get requires <name>"
    ensure_managed_keychain

    log_info "security find-generic-password (service=$SERVICE account=$name)"
    run_security security find-generic-password -s "$SERVICE" -a "$name" -w "${KEYCHAIN_ARGS[@]}" || return $?
    log_info "security find-generic-password completed (service=$SERVICE account=$name)"
}

cmd_delete() {
    local name="${1:-}"
    [[ -n "$name" ]] || die "delete requires <name>"
    ensure_managed_keychain

    log_info "security delete-generic-password (service=$SERVICE account=$name)"
    run_security security delete-generic-password -s "$SERVICE" -a "$name" "${KEYCHAIN_ARGS[@]}" >/dev/null || return $?
    log_info "security delete-generic-password completed (service=$SERVICE account=$name)"
}

cmd_has() {
    local name="${1:-}"
    [[ -n "$name" ]] || die "has requires <name>"
    ensure_managed_keychain
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
    ensure_managed_keychain
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
    ' | sort -u || return $?
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
    local remote_unlock_secret="$2"
    shift 2

    local sub="${1:-}"
    local remote_dir=""
    local remote_script=""
    local remote_payload_file=""
    local remote_unlock_file=""
    local local_payload_file=""
    local local_unlock_file=""
    local create_dir_command='mktemp -d "${TMPDIR:-/tmp}/cli-tools-secrets.XXXXXX"'
    local remote_command=""
    local ssh_command_flags=()
    local remote_args=("$@")

    if [[ "$sub" == "set" ]]; then
        parse_set_invocation "${@:2}"
        local name="$PARSED_SET_NAME"
        local_payload_file="$(mktemp "${TMPDIR:-/tmp}/cli-tools-secrets.payload.XXXXXX")"
        chmod 600 "$local_payload_file"
        resolve_set_value "$PARSED_SET_VALUE_ARG" >"$local_payload_file"
        remote_args=("set" "$name")
    fi

    if [[ -n "$remote_unlock_secret" ]]; then
        local keychain_password
        keychain_password="$(cmd_get "$remote_unlock_secret")"
        local_unlock_file="$(mktemp "${TMPDIR:-/tmp}/cli-tools-secrets.unlock.XXXXXX")"
        chmod 600 "$local_unlock_file"
        printf '%s' "$keychain_password" >"$local_unlock_file"
        unset keychain_password
    fi

    log_info "dispatching command to remote host=$host command=${sub:-help}"
    if ! remote_dir="$(ssh "$host" "bash -lc $(shell_quote "$create_dir_command")")"; then
        rm -f "$local_payload_file"
        rm -f "$local_unlock_file"
        die "failed to create remote temp directory on $host"
    fi
    remote_dir="${remote_dir%$'\n'}"
    if [[ -z "$remote_dir" ]]; then
        rm -f "$local_payload_file"
        rm -f "$local_unlock_file"
        die "remote host $host did not return a temp directory"
    fi
    remote_script="${remote_dir}/secrets.sh"

    if ! scp -q "$0" "$host:$remote_script"; then
        rm -f "$local_payload_file"
        rm -f "$local_unlock_file"
        cleanup_remote_dir "$host" "$remote_dir"
        die "failed to copy secrets.sh to remote host $host"
    fi

    if [[ -n "$remote_unlock_secret" ]]; then
        remote_unlock_file="${remote_dir}/keychain-password"
        if ! scp -q "$local_unlock_file" "$host:$remote_unlock_file"; then
            rm -f "$local_payload_file" "$local_unlock_file"
            cleanup_remote_dir "$host" "$remote_dir"
            die "failed to copy keychain password to remote host $host"
        fi
        rm -f "$local_unlock_file"
        local_unlock_file=""
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
    if [[ -n "$remote_unlock_secret" ]]; then
        remote_command+="chmod 600 $(shell_quote "$remote_unlock_file"); "
        remote_command+="keychain_password=\"\$(cat $(shell_quote "$remote_unlock_file"))\"; "
        remote_command+="security unlock-keychain -p \"\$keychain_password\" "
        remote_command+="$(shell_quote "$KEYCHAIN") >/dev/null; "
        remote_command+="unset keychain_password; "
    fi
    if [[ "$sub" == "set" ]]; then
        remote_command+="chmod 600 $(shell_quote "$remote_payload_file"); "
    fi
    remote_command+="CLI_TOOLS_SECRETS_REMOTE_CONTEXT=1 "
    remote_command+="CLI_TOOLS_SECRETS_REMOTE_HOST=$(shell_quote "$host") "
    if [[ -n "${CLI_TOOLS_KEYCHAIN:-}" ]]; then
        remote_command+="CLI_TOOLS_KEYCHAIN=$(shell_quote "$CLI_TOOLS_KEYCHAIN") "
    fi
    if [[ "$sub" == "set" ]]; then
        remote_command+="SECRET_VALUE=\"\$(cat $(shell_quote "$remote_payload_file"))\" "
    fi
    remote_command+="bash $(shell_quote "$remote_script")"
    for arg in "${remote_args[@]}"; do
        remote_command+=" $(shell_quote "$arg")"
    done

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
    local remote_unlock_secret=""
    local argv=()

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --remote-host)
                [[ $# -ge 2 ]] || die "--remote-host requires <host>"
                remote_host="$2"
                shift 2
                ;;
            --remote-unlock-secret)
                [[ $# -ge 2 ]] || die "--remote-unlock-secret requires <name>"
                remote_unlock_secret="$2"
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

    if [[ -n "$remote_unlock_secret" && -z "$remote_host" ]]; then
        die "--remote-unlock-secret requires --remote-host"
    fi
    if [[ -n "$remote_unlock_secret" && -z "${CLI_TOOLS_KEYCHAIN:-}" ]]; then
        die "--remote-unlock-secret requires CLI_TOOLS_KEYCHAIN; the default CLI-tools keychain unlocks itself"
    fi

    if [[ -n "$remote_host" && "$REMOTE_CONTEXT" != "1" && "$sub" != "" && "$sub" != "-h" && "$sub" != "--help" && "$sub" != "help" ]]; then
        if dispatch_remote "$remote_host" "$remote_unlock_secret" "$@"; then
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
        rename) if cmd_rename "$@"; then status=0; else status=$?; fi ;;
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
