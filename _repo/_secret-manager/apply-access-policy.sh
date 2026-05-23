#!/usr/bin/env bash
# Apply the CLI-tools Keychain item access policy.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck disable=SC1091
. "$INSTALL_ROOT/_repo/_scripts/lib/log.sh"

DEFAULT_POLICY="$SCRIPT_DIR/access-policy.conf"
DEFAULT_MANAGED_KEYCHAIN="$HOME/.local/share/cli-tools/cli-tools.keychain-db"

POLICY_FILE="$DEFAULT_POLICY"
DRY_RUN=0
KEYCHAIN_PASSWORD_SECRET=""
KEYCHAIN_PASSWORD_STDIN=0
PROMPT_KEYCHAIN_PASSWORD=0

POLICY_KEYCHAIN=""
POLICY_SERVICE=""
TARGET_ALL=0
TARGETS=()
PROCESS_PATHS=()
PROCESS_PARTITION_IDS=()
PARTITION_IDS=()
KEYCHAIN_PASSWORD=""

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Apply _repo/_secret-manager/access-policy.conf to CLI-tools Keychain secrets.

Options:
  --policy <path>                 Policy file to apply.
  --dry-run                       Validate and show the planned target count.
  --keychain-password-secret <n>  Read the keychain password from a CLI-tools secret.
  --keychain-password-stdin       Read the keychain password from stdin.
  --prompt-keychain-password      Prompt for the keychain password using /dev/tty.
  -h, --help                      Show this help.
EOF
}

die() {
    log_error "$*"
    echo "apply-access-policy: $*" >&2
    exit 1
}

trim() {
    local value="$1"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    printf '%s' "$value"
}

expand_policy_path() {
    local path="$1"
    case "$path" in
        \~)
            printf '%s\n' "$HOME"
            ;;
        \~/*)
            printf '%s/%s\n' "$HOME" "${path#\~/}"
            ;;
        /*)
            printf '%s\n' "$path"
            ;;
        *)
            die "policy path must be absolute or start with ~: $path"
            ;;
    esac
}

is_default_managed_keychain() {
    [[ "$POLICY_KEYCHAIN" == "$DEFAULT_MANAGED_KEYCHAIN" ]]
}

ensure_default_managed_keychain() {
    is_default_managed_keychain || return 0

    mkdir -p "$(dirname "$POLICY_KEYCHAIN")"
    if [[ ! -e "$POLICY_KEYCHAIN" ]]; then
        log_info "security create-keychain keychain=$POLICY_KEYCHAIN"
        security create-keychain -p "" "$POLICY_KEYCHAIN" >/dev/null
        log_info "security create-keychain completed keychain=$POLICY_KEYCHAIN"
    fi
    chmod 600 "$POLICY_KEYCHAIN"
    log_info "security unlock-keychain keychain=$POLICY_KEYCHAIN"
    security unlock-keychain -p "" "$POLICY_KEYCHAIN" >/dev/null
    log_info "security unlock-keychain completed keychain=$POLICY_KEYCHAIN"
}

validate_partition_id() {
    local partition_id="$1"
    case "$partition_id" in
        apple:|apple-tool:|codesign:|unsigned:|teamid:*|cdhash:*)
            ;;
        *)
            die "unsupported partition id: $partition_id"
            ;;
    esac
}

append_unique_partition_id() {
    local partition_id="$1"
    local existing
    if [[ "${#PARTITION_IDS[@]}" -gt 0 ]]; then
        for existing in "${PARTITION_IDS[@]}"; do
            [[ "$existing" == "$partition_id" ]] && return 0
        done
    fi
    PARTITION_IDS+=("$partition_id")
}

parse_one_token_directive() {
    local directive="$1"
    local remainder="$2"
    local line_no="$3"
    local token extra

    read -r token extra <<<"$remainder"
    [[ -n "${token:-}" ]] || die "policy line $line_no: $directive requires a value"
    [[ -z "${extra:-}" ]] || die "policy line $line_no: $directive accepts one value"
    printf '%s\n' "$token"
}

parse_policy() {
    local raw_line line directive remainder line_no
    line_no=0

    log_info "reading policy file=$POLICY_FILE"
    while IFS= read -r raw_line || [[ -n "$raw_line" ]]; do
        line_no=$((line_no + 1))
        line="$(trim "${raw_line%%#*}")"
        [[ -z "$line" ]] && continue

        directive="${line%%[[:space:]]*}"
        if [[ "$directive" == "$line" ]]; then
            remainder=""
        else
            remainder="$(trim "${line#"$directive"}")"
        fi

        case "$directive" in
            keychain)
                POLICY_KEYCHAIN="$(expand_policy_path "$(parse_one_token_directive "$directive" "$remainder" "$line_no")")"
                ;;
            service)
                POLICY_SERVICE="$(parse_one_token_directive "$directive" "$remainder" "$line_no")"
                ;;
            target)
                local target
                target="$(parse_one_token_directive "$directive" "$remainder" "$line_no")"
                if [[ "$target" == "*" ]]; then
                    TARGET_ALL=1
                else
                    TARGETS+=("$target")
                fi
                ;;
            allow-process)
                local partition_id process_path
                partition_id="${remainder%%[[:space:]]*}"
                process_path="$(trim "${remainder#"$partition_id"}")"
                [[ -n "$partition_id" && -n "$process_path" ]] || die "policy line $line_no: allow-process requires <partition-id> <path>"
                validate_partition_id "$partition_id"
                PROCESS_PATHS+=("$process_path")
                PROCESS_PARTITION_IDS+=("$partition_id")
                append_unique_partition_id "$partition_id"
                ;;
            *)
                die "policy line $line_no: unknown directive: $directive"
                ;;
        esac
    done <"$POLICY_FILE"
    log_info "policy file read"
}

validate_policy() {
    local index process_path partition_id

    [[ -f "$POLICY_FILE" ]] || die "policy file not found: $POLICY_FILE"
    [[ -n "$POLICY_KEYCHAIN" ]] || die "policy missing keychain"
    ensure_default_managed_keychain
    [[ -e "$POLICY_KEYCHAIN" ]] || die "keychain not found: $POLICY_KEYCHAIN"
    [[ "$POLICY_SERVICE" == "cli-tools" ]] || die "policy service must be cli-tools"
    [[ "$TARGET_ALL" == "1" || "${#TARGETS[@]}" -gt 0 ]] || die "policy must include at least one target"
    [[ "${#PARTITION_IDS[@]}" -gt 0 ]] || die "policy must include at least one allow-process"

    for partition_id in "${PARTITION_IDS[@]}"; do
        validate_partition_id "$partition_id"
    done

    for (( index=0; index<${#PROCESS_PATHS[@]}; index++ )); do
        process_path="${PROCESS_PATHS[$index]}"
        partition_id="${PROCESS_PARTITION_IDS[$index]}"
        [[ -e "$process_path" ]] || die "process path not found: $process_path"

        if [[ "$partition_id" == "unsigned:" ]]; then
            log_info "codesign validation skipped for unsigned process=$process_path"
        else
            log_info "codesign validate process=$process_path"
            codesign -dv "$process_path" >/dev/null 2>&1
            log_info "codesign validate completed process=$process_path"
        fi
    done
}

partition_csv() {
    local IFS=,
    printf '%s' "${PARTITION_IDS[*]}"
}

resolve_targets() {
    local target

    if [[ "$TARGET_ALL" == "1" ]]; then
        log_info "listing policy wildcard targets service=$POLICY_SERVICE keychain=$POLICY_KEYCHAIN"
        while IFS= read -r target; do
            [[ -n "$target" ]] && TARGETS+=("$target")
        done < <(security dump-keychain "$POLICY_KEYCHAIN" | awk -v svc="$POLICY_SERVICE" '
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
        ' | sort -u)
        log_info "policy wildcard targets listed count=${#TARGETS[@]}"
    fi

    [[ "${#TARGETS[@]}" -gt 0 ]] || die "policy resolved zero targets"

    for target in "${TARGETS[@]}"; do
        log_info "checking secret target account=$target"
        security find-generic-password -s "$POLICY_SERVICE" -a "$target" "$POLICY_KEYCHAIN" >/dev/null
        log_info "secret target exists account=$target"
    done
}

load_keychain_password() {
    if [[ "$DRY_RUN" == "1" ]]; then
        log_info "dry-run selected; keychain password not loaded"
        return 0
    fi

    if [[ -n "$KEYCHAIN_PASSWORD_SECRET" ]]; then
        log_info "reading keychain password from secret-manager account=$KEYCHAIN_PASSWORD_SECRET"
        KEYCHAIN_PASSWORD="$(security find-generic-password -s "$POLICY_SERVICE" -a "$KEYCHAIN_PASSWORD_SECRET" -w "$POLICY_KEYCHAIN")"
        log_info "keychain password loaded from secret-manager account=$KEYCHAIN_PASSWORD_SECRET"
        return 0
    fi

    if [[ "$KEYCHAIN_PASSWORD_STDIN" == "1" ]]; then
        log_info "reading keychain password from stdin"
        IFS= read -r KEYCHAIN_PASSWORD
        log_info "keychain password loaded from stdin"
        return 0
    fi

    if [[ "$PROMPT_KEYCHAIN_PASSWORD" == "1" ]]; then
        [[ -r /dev/tty ]] || die "--prompt-keychain-password requires a TTY"
        log_info "prompting for keychain password"
        printf 'Keychain password: ' >/dev/tty
        IFS= read -r -s KEYCHAIN_PASSWORD </dev/tty
        printf '\n' >/dev/tty
        log_info "keychain password loaded from prompt"
        return 0
    fi

    if is_default_managed_keychain; then
        log_info "using managed CLI-tools keychain password"
        KEYCHAIN_PASSWORD=""
        return 0
    fi

    die "applying policy requires --keychain-password-secret, --keychain-password-stdin, or --prompt-keychain-password"
}

apply_policy() {
    local partitions target
    partitions="$(partition_csv)"

    if [[ "$DRY_RUN" == "1" ]]; then
        echo "Policy: $POLICY_FILE"
        echo "Keychain: $POLICY_KEYCHAIN"
        echo "Service: $POLICY_SERVICE"
        echo "Targets: ${#TARGETS[@]}"
        echo "Partition IDs: $partitions"
        log_info "dry-run complete targets=${#TARGETS[@]} partitions=$partitions"
        return 0
    fi

    log_info "security unlock-keychain keychain=$POLICY_KEYCHAIN"
    security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$POLICY_KEYCHAIN" >/dev/null
    log_info "security unlock-keychain completed keychain=$POLICY_KEYCHAIN"

    for target in "${TARGETS[@]}"; do
        log_info "security set-generic-password-partition-list account=$target partitions=$partitions"
        security set-generic-password-partition-list -s "$POLICY_SERVICE" -a "$target" -S "$partitions" -k "$KEYCHAIN_PASSWORD" "$POLICY_KEYCHAIN" >/dev/null
        log_info "security set-generic-password-partition-list completed account=$target"
    done
}

main() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --policy)
                [[ $# -ge 2 ]] || die "--policy requires <path>"
                POLICY_FILE="$2"
                shift 2
                ;;
            --dry-run)
                DRY_RUN=1
                shift
                ;;
            --keychain-password-secret)
                [[ $# -ge 2 ]] || die "--keychain-password-secret requires <name>"
                KEYCHAIN_PASSWORD_SECRET="$2"
                shift 2
                ;;
            --keychain-password-stdin)
                KEYCHAIN_PASSWORD_STDIN=1
                shift
                ;;
            --prompt-keychain-password)
                PROMPT_KEYCHAIN_PASSWORD=1
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                die "unknown option: $1"
                ;;
        esac
    done

    [[ "$KEYCHAIN_PASSWORD_STDIN" == "0" || -z "$KEYCHAIN_PASSWORD_SECRET" ]] || die "choose one keychain password source"
    [[ "$PROMPT_KEYCHAIN_PASSWORD" == "0" || "$KEYCHAIN_PASSWORD_STDIN" == "0" ]] || die "choose one keychain password source"
    [[ "$PROMPT_KEYCHAIN_PASSWORD" == "0" || -z "$KEYCHAIN_PASSWORD_SECRET" ]] || die "choose one keychain password source"

    log_info "starting $(basename "$0") policy=$POLICY_FILE dry_run=$DRY_RUN"
    parse_policy
    validate_policy
    resolve_targets
    load_keychain_password
    apply_policy
    log_info "done"
}

main "$@"
