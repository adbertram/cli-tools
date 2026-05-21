#!/bin/bash
set -o pipefail

usage() {
    cat <<'HELP'
Usage: test-cli-tool.sh --cli-name <name> [--command <cmd>] [--verbose]
       test-cli-tool.sh --file <path>

Options:
  --cli-name <name>   CLI tool name to test (e.g. ahrefs, notion)
  --command <cmd>     Test only a specific command (e.g. list, get)
  --file <path>       Auto-derive cli-name and command from a file path
  --verbose           Show verbose pytest output
  -h, --help          Show this help message
HELP
}

json_error() {
    MESSAGE="$1" python3 -c 'import json, os; print(json.dumps({"error": os.environ["MESSAGE"]}))'
}

CLI_NAME=""
COMMAND=""
VERBOSE=false
FILE_PATH=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        --cli-name) CLI_NAME="$2"; shift 2 ;;
        --command) COMMAND="$2"; shift 2 ;;
        --verbose) VERBOSE=true; shift ;;
        --file) FILE_PATH="$2"; shift 2 ;;
        *) json_error "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
REPO_ROOT="$(cd "$SKILL_DIR/../../.." && pwd -P)"

if [[ -n "$FILE_PATH" ]]; then
    [[ "$FILE_PATH" != /* ]] && FILE_PATH="$PWD/$FILE_PATH"
    ABS_FILE_PATH="$(cd "$(dirname "$FILE_PATH")" && pwd -P)/$(basename "$FILE_PATH")"
    if [[ "$ABS_FILE_PATH" != "$REPO_ROOT/"* ]]; then
        echo '{"skipped": true, "reason": "Not in cli-tools directory"}'
        exit 0
    fi
    RELATIVE_FILE_PATH="${ABS_FILE_PATH#"$REPO_ROOT"/}"
    CLI_NAME="${RELATIVE_FILE_PATH%%/*}"
    if [[ -z "$CLI_NAME" ]]; then
        echo '{"skipped": true, "reason": "Could not extract CLI name from path"}'
        exit 0
    fi
    if [[ "$RELATIVE_FILE_PATH" == *"/commands/"* ]]; then
        FILENAME="${RELATIVE_FILE_PATH##*/}"
        [[ "$FILENAME" != "__init__.py" && "$FILENAME" != "__pycache__" ]] && COMMAND="${FILENAME%.py}"
    fi
    echo "Running tests for $CLI_NAME${COMMAND:+ --command $COMMAND}..." >&2
fi

if [[ -z "$CLI_NAME" ]]; then
    json_error "--cli-name or --file is required" >&2
    exit 1
fi

if ! command -v uv &>/dev/null; then
    json_error "uv is not installed" >&2
    exit 1
fi

CLI_DIR="$REPO_ROOT/$CLI_NAME"
if [[ ! -d "$CLI_DIR" ]]; then
    json_error "CLI tool directory not found: $CLI_DIR" >&2
    exit 1
fi

FORBIDDEN_ROOT_ENV_FILES=()
for env_file in "$CLI_DIR"/.env "$CLI_DIR"/.env.*; do
    [[ "$(basename "$env_file")" == ".env.example" || ! -f "$env_file" ]] && continue
    FORBIDDEN_ROOT_ENV_FILES+=("${env_file#"$REPO_ROOT"/}")
done

if [[ ${#FORBIDDEN_ROOT_ENV_FILES[@]} -gt 0 ]]; then
    joined=$(printf '%s, ' "${FORBIDDEN_ROOT_ENV_FILES[@]}")
    json_error "Root .env files are not allowed in CLI tool folders. Store profile env files under ~/.local/share/cli-tools/<tool>/.profiles/<profile>/.env. Offending files: ${joined%, }" >&2
    exit 1
fi

cd "$SKILL_DIR" || exit 1

JUNIT=$(mktemp -t cli-tool-tests-XXXXXX.xml)
RAW_OUTPUT_FILE=$(mktemp -t cli-tool-tests-raw-XXXXXX.log)
trap 'rm -f "$JUNIT" "$RAW_OUTPUT_FILE"' EXIT
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-$HOME/.cache/uv/project-envs/cli-tool-skill-tests}"

PYTEST_ARGS=(--cli-name "$CLI_NAME" --tb=short --junitxml="$JUNIT")
[[ -n "$COMMAND" ]] && PYTEST_ARGS+=(--command "$COMMAND")
$VERBOSE && PYTEST_ARGS+=(-v) || PYTEST_ARGS+=(-q)

uv run pytest "${PYTEST_ARGS[@]}" 2>&1 | tee "$RAW_OUTPUT_FILE" >&2
EXIT_CODE=$?
RAW_OUTPUT=$(<"$RAW_OUTPUT_FILE")

CLI_NAME="$CLI_NAME" COMMAND="$COMMAND" JUNIT="$JUNIT" \
    EXIT_CODE="$EXIT_CODE" RAW_OUTPUT="$RAW_OUTPUT" \
    python3 "$SKILL_DIR/scripts/junit_to_json.py"
