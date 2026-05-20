#!/bin/bash
# test-cli-tool.sh - Run CLI tool tests and return structured JSON output
#
# Usage:
#   test-cli-tool.sh --cli-name <name> [--command <cmd>] [--verbose]
#   test-cli-tool.sh --file <path>  (auto-derives cli-name and command from file path)
#
# Returns JSON with test results, failures as todos, and auth status.
#
# Implementation: this script is now a thin wrapper around pytest. Behaviours
# that used to live inline as bash + jq (auth-status schema validation, source
# venv preflight, fragile regex parsing of pytest text output) have been moved
# into the compliance test suite itself; the script just invokes pytest with
# --junitxml and a small Python emitter converts that XML into the JSON
# contract this script's callers expect.

set -o pipefail

export CLI_TOOL_TEST_NO_HEADED_BROWSER=1
export HEADLESS=true
export BROWSER_HEADLESS=true

CLI_NAME=""
COMMAND=""
VERBOSE="false"
FILE_PATH=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
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
            exit 0
            ;;
        --cli-name) CLI_NAME="$2"; shift 2 ;;
        --command) COMMAND="$2"; shift 2 ;;
        --verbose) VERBOSE="true"; shift ;;
        --file) FILE_PATH="$2"; shift 2 ;;
        *) echo '{"error": "Unknown argument: '"$1"'"}' >&2; exit 1 ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd -P)"
REPO_ROOT="$(cd "$SKILL_DIR/../.." && pwd -P)"

if [[ -n "$FILE_PATH" ]]; then
    case "$FILE_PATH" in
        /*) ABS_FILE_PATH="$FILE_PATH" ;;
        *) ABS_FILE_PATH="$(pwd)/$FILE_PATH" ;;
    esac
    ABS_FILE_PATH="$(cd "$(dirname "$ABS_FILE_PATH")" && pwd -P)/$(basename "$ABS_FILE_PATH")"
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
        FILENAME=$(basename "$RELATIVE_FILE_PATH")
        if [[ "$FILENAME" != "__init__.py" && "$FILENAME" != "__pycache__" ]]; then
            COMMAND="${FILENAME%.py}"
        fi
    fi
    echo "Running tests for $CLI_NAME${COMMAND:+ --command $COMMAND}..." >&2
fi

if [[ -z "$CLI_NAME" ]]; then
    echo '{"error": "--cli-name or --file is required"}' >&2
    exit 1
fi

if [[ ! -d "$SKILL_DIR" ]]; then
    echo '{"error": "CLI tool skill directory not found: '"$SKILL_DIR"'"}' >&2
    exit 1
fi
if ! command -v uv &>/dev/null; then
    echo '{"error": "uv is not installed"}' >&2
    exit 1
fi

cd "$SKILL_DIR" || exit 1

JUNIT=$(mktemp -t cli-tool-tests-XXXXXX.xml)
trap 'rm -f "$JUNIT"' EXIT
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-$HOME/.cache/uv/project-envs/cli-tool-skill-tests}"

PYTEST_ARGS=(--cli-name "$CLI_NAME" --tb=short --junitxml="$JUNIT")
[[ -n "$COMMAND" ]] && PYTEST_ARGS+=(--command "$COMMAND")
[[ "$VERBOSE" == "true" ]] && PYTEST_ARGS+=(-v) || PYTEST_ARGS+=(-q)

RAW_OUTPUT=$(uv run pytest "${PYTEST_ARGS[@]}" 2>&1)
EXIT_CODE=$?

CLI_NAME="$CLI_NAME" COMMAND="$COMMAND" JUNIT="$JUNIT" \
    EXIT_CODE="$EXIT_CODE" RAW_OUTPUT="$RAW_OUTPUT" \
    python3 "$SKILL_DIR/scripts/junit_to_json.py"
