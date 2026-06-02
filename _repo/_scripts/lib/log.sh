#!/usr/bin/env bash
# Shared append-only logger for cli-tools shell scripts.

if [[ -n "${_CLI_TOOLS_LOG_SH_LOADED:-}" ]]; then
    return 0 2>/dev/null || exit 0
fi
_CLI_TOOLS_LOG_SH_LOADED=1

_log_script_path="${BASH_SOURCE[1]:-$0}"
_log_script_dir="$(cd "$(dirname "$_log_script_path")" && pwd)"
_log_script_base="$(basename "$_log_script_path" .sh)"
LOG_FILE="${LOG_FILE:-$_log_script_dir/$_log_script_base.log}"
mkdir -p "$(dirname "$LOG_FILE")"

_log_ts() {
    date -u +"%Y-%m-%dT%H:%M:%SZ"
}

_log_line() {
    local level="$1"
    shift
    printf '[%s] [%s] %s\n' "$(_log_ts)" "$level" "$*" >>"$LOG_FILE"
}

log_info() {
    _log_line "INFO" "$@"
}

log_warn() {
    _log_line "WARN" "$@"
}

log_error() {
    _log_line "ERROR" "$@"
}

log_debug() {
    [[ "${LOG_DEBUG:-0}" == "1" ]] || return 0
    _log_line "DEBUG" "$@"
}

log_path() {
    printf '%s\n' "$LOG_FILE"
}

log_read() {
    local follow=0
    local lines=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -f) follow=1; shift ;;
            -n) lines="$2"; shift 2 ;;
            *) break ;;
        esac
    done

    local target="${1:-}"
    [[ -n "$target" ]] || { log_error "log_read requires a target"; return 2; }

    case "$target" in
        *.sh) target="${target%.sh}.log" ;;
        *.log) ;;
        *) [[ -f "$target.log" ]] && target="$target.log" ;;
    esac

    if [[ "$follow" == "1" && -n "$lines" ]]; then
        tail -n "$lines" -f "$target"
    elif [[ "$follow" == "1" ]]; then
        tail -f "$target"
    elif [[ -n "$lines" ]]; then
        tail -n "$lines" "$target"
    else
        cat "$target"
    fi
}

if [[ "${LOG_NO_EXIT_TRAP:-0}" != "1" ]]; then
    _log_exit_trap() {
        local rc=$?
        printf "Log: %s\n" "$LOG_FILE" >&2
        exit "$rc"
    }
    trap _log_exit_trap EXIT
fi

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    case "${1:-}" in
        read) shift; log_read "$@" ;;
        path)
            target="${2:-}"
            [[ -n "$target" ]] || { echo "log.sh path requires a target" >&2; exit 2; }
            case "$target" in
                /*) ;;
                *) target="$(pwd)/$target" ;;
            esac
            case "$target" in
                *.sh) printf '%s\n' "${target%.sh}.log" ;;
                *.log) printf '%s\n' "$target" ;;
                *) printf '%s\n' "$target.log" ;;
            esac
            ;;
        -h|--help|help|"")
            cat <<'EOF'
Usage:
  _repo/_scripts/lib/log.sh read [-f] [-n N] <script-or-log-path>
  _repo/_scripts/lib/log.sh path <script-or-log-path>
EOF
            ;;
        *)
            echo "unknown log.sh command: $1" >&2
            exit 2
            ;;
    esac
fi
