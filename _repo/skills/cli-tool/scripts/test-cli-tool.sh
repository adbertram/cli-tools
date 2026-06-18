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

json_test_failure() {
    local test_name="$1"
    local file_name="$2"
    local message="$3"
    CLI_NAME="$CLI_NAME" COMMAND="$COMMAND" TEST_NAME="$test_name" FILE_NAME="$file_name" MESSAGE="$message" \
        python3 - <<'PY'
import json
import os

message = os.environ["MESSAGE"]
test_name = os.environ["TEST_NAME"]
payload = {
    "success": False,
    "cli_name": os.environ["CLI_NAME"],
    "command_filter": os.environ.get("COMMAND") or None,
    "summary": {"passed": 0, "failed": 1, "skipped": 0, "errors": 0},
    "auth_required": False,
    "auth_command": None,
    "failures": [{
        "test_name": test_name,
        "file": os.environ["FILE_NAME"],
        "message": message[:300],
        "todo": {
            "content": f"Fix: {message}"[:150],
            "activeForm": f"Fixing {test_name}"[:100],
            "status": "pending",
        },
    }],
    "raw_output": message,
}
print(json.dumps(payload, indent=2))
PY
}

validate_readme_description_block() {
    local readme_path="$CLI_DIR/README.md"
    local readme_file="${readme_path#"$REPO_ROOT"/}"
    if [[ ! -f "$readme_path" ]]; then
        json_test_failure \
            "readme_description_block" \
            "$readme_file" \
            "README.md is required for CLI tool: $CLI_NAME"
        exit 1
    fi

    if ! README_DESCRIPTION_ERROR="$(
        README_PATH="$readme_path" \
        UV_PROJECT_ENVIRONMENT="$SKILL_UV_ENV" \
        uv run --project "$SKILL_DIR" python3 - <<'PY'
import os
import re
from pathlib import Path


def fail(message: str) -> None:
    print(message)
    raise SystemExit(1)


path = Path(os.environ["README_PATH"])
lines = path.read_text().splitlines()

try:
    start = lines.index("## DESCRIPTION")
except ValueError:
    fail("README.md must contain a ## DESCRIPTION block")

end = len(lines)
for index in range(start + 1, len(lines)):
    if lines[index].startswith("## ") and index != start:
        end = index
        break

block = "\n".join(lines[start + 1 : end]).strip()
sentences = re.findall(r"[^.!?]+[.!?]", block)
sentence_count = len(sentences)
if sentence_count < 2 or sentence_count > 3:
    preview = re.sub(r"\s+", " ", block).strip()
    if len(preview) > 180:
        preview = f"{preview[:177]}..."
    fail(
        "README.md DESCRIPTION block must contain 2-3 sentences; "
        f"found {sentence_count}. Current block: {preview!r}"
    )

if "use" not in block.lower():
    fail(
        "README.md DESCRIPTION block must explain why someone would use the CLI; "
        "include a sentence that contains 'use'."
    )
PY
    )"; then
        json_test_failure \
            "readme_description_block" \
            "$readme_file" \
            "$README_DESCRIPTION_ERROR"
        exit 1
    fi

    echo "[PASS] readme_description_block: README.md contains DESCRIPTION block" >&2
}

run_auth_status_schema_preflight() {
    UV_PROJECT_ENVIRONMENT="$SKILL_UV_ENV" \
    PYTHONPATH="$SKILL_DIR/tests${PYTHONPATH:+:$PYTHONPATH}" \
    CLI_NAME="$CLI_NAME" \
    CLI_EXECUTABLE="$CLI_EXECUTABLE" \
    uv run --project "$SKILL_DIR" python3 - <<'PY'
import json
import os
import subprocess
import sys

from auth_status_schema import parse_and_validate_stdout


def emit(status: str, message: str) -> None:
    label = {"passed": "PASS", "skipped": "SKIP", "failed": "FAIL"}[status]
    print(f"[{label}] auth status schema: {message}", file=sys.stderr)
    print(json.dumps({"status": status, "message": message}))


def has_subcommand(help_text: str, name: str) -> bool:
    return any(name in line.split() for line in help_text.splitlines() if name in line)


def run_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True)


cli_name = os.environ["CLI_NAME"]
cli_executable = os.environ["CLI_EXECUTABLE"]

root_help = run_command([cli_executable, "--help"])
if root_help.returncode != 0:
    detail = root_help.stderr.strip() or root_help.stdout.strip()
    emit("failed", f"'{cli_name} --help' exited {root_help.returncode}: {detail[:300]}")
    raise SystemExit(0)

if not has_subcommand(root_help.stdout, "auth"):
    emit("skipped", f"{cli_name} has no auth subcommand")
    raise SystemExit(0)

auth_help = run_command([cli_executable, "auth", "--help"])
if auth_help.returncode != 0:
    detail = auth_help.stderr.strip() or auth_help.stdout.strip()
    emit("failed", f"'{cli_name} auth --help' exited {auth_help.returncode}: {detail[:300]}")
    raise SystemExit(0)

if not has_subcommand(auth_help.stdout, "status"):
    emit("skipped", f"{cli_name} has no 'auth status' subcommand")
    raise SystemExit(0)

status_result = run_command([cli_executable, "auth", "status"])
if status_result.returncode not in (0, 2):
    detail = status_result.stderr.strip() or status_result.stdout.strip()
    emit("failed", f"'{cli_name} auth status' exited {status_result.returncode}: {detail[:300]}")
    raise SystemExit(0)

payload, errors = parse_and_validate_stdout(
    status_result.stdout,
    require_authenticated=False,
)
if errors:
    emit("failed", "; ".join(errors))
    raise SystemExit(0)

profiles = payload.get("profiles", []) if isinstance(payload, dict) else []
if status_result.returncode == 2 or not any(
    isinstance(profile, dict) and profile.get("authenticated") is True
    for profile in profiles
):
    emit("failed", f"'{cli_name} auth status' is not authenticated. Run '{cli_name} auth login'.")
    raise SystemExit(0)

emit("passed", f"'{cli_name} auth status' matches canonical schema")
PY
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
        *) json_error "Unknown argument: $1. Use --cli-name <name> or --file <path>." >&2; exit 1 ;;
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

SKILL_UV_ENV="${UV_PROJECT_ENVIRONMENT:-$HOME/.cache/uv/project-envs/cli-tool-skill-tests}"

CLI_DIR="$REPO_ROOT/$CLI_NAME"
if [[ ! -d "$CLI_DIR" ]]; then
    RESOLVED_CLI_DIR="$(
        CLI_NAME="$CLI_NAME" \
        UV_PROJECT_ENVIRONMENT="$SKILL_UV_ENV" \
        uv run --project "$SKILL_DIR" python3 - <<'PY'
import os
import sys
from pathlib import Path
import subprocess

cli_name = os.environ["CLI_NAME"]
exe = Path.home() / ".local" / "bin" / cli_name
if not exe.exists():
    raise SystemExit(1)

first_line = exe.read_text().splitlines()[0].strip()
if not first_line.startswith("#!"):
    raise SystemExit(1)

launcher_python = first_line[2:]
dist_name = f"{cli_name}-cli"
result = subprocess.run(
    [
        launcher_python,
        "-c",
        "from cli_tools_shared.config import resolve_tool_dir; "
        f"print(resolve_tool_dir({dist_name!r}))",
    ],
    capture_output=True,
    text=True,
)
if result.returncode != 0:
    raise SystemExit(1)

print(result.stdout.strip())
PY
    )"

    if [[ -n "$RESOLVED_CLI_DIR" && -d "$RESOLVED_CLI_DIR" ]]; then
        CLI_DIR="$RESOLVED_CLI_DIR"
    else
        json_error "CLI tool directory not found: $CLI_DIR" >&2
        exit 1
    fi
fi

CANONICAL_UV_LAUNCHER="$HOME/.local/bin/$CLI_NAME"
if [[ ! -x "$CANONICAL_UV_LAUNCHER" ]]; then
    json_test_failure \
        "test_cli_executable_linked" \
        "test-cli-tool.sh" \
        "CLI executable link missing or not executable: $CANONICAL_UV_LAUNCHER"
    exit 1
fi
CLI_EXECUTABLE="$CANONICAL_UV_LAUNCHER"

validate_readme_description_block

FORBIDDEN_ROOT_ENV_FILES=()
for env_file in "$CLI_DIR"/.env "$CLI_DIR"/.env.*; do
    [[ "$(basename "$env_file")" == ".env.example" || ! -f "$env_file" ]] && continue
    FORBIDDEN_ROOT_ENV_FILES+=("${env_file#"$REPO_ROOT"/}")
done

if [[ ${#FORBIDDEN_ROOT_ENV_FILES[@]} -gt 0 ]]; then
    joined=$(printf '%s, ' "${FORBIDDEN_ROOT_ENV_FILES[@]}")
    json_error "Root .env files are not allowed in CLI tool source folders. Store non-auth config under ~/.local/share/cli-tools/<tool>/.env and auth profile env files under ~/.local/share/cli-tools/<tool>/authentication_profiles/<profile>/.env. Offending files: ${joined%, }" >&2
    exit 1
fi

if ! PLACEHOLDER_VALIDATION_ERROR="$(
    PYTHONPATH="$CLI_DIR:$REPO_ROOT/_repo/cli-tools-shared${PYTHONPATH:+:$PYTHONPATH}" \
    CLI_NAME="$CLI_NAME" \
    UV_PROJECT_ENVIRONMENT="$SKILL_UV_ENV" \
    uv run --project "$SKILL_DIR" python3 - <<'PY'
import os

from cli_tools_shared.config import validate_auth_profile_secret_placeholders
from cli_tools_shared.exceptions import ConfigError

try:
    validate_auth_profile_secret_placeholders(os.environ["CLI_NAME"])
except ConfigError as exc:
    print(str(exc))
    raise SystemExit(1)
PY
)"; then
    json_error "$PLACEHOLDER_VALIDATION_ERROR" >&2
    exit 1
fi

cd "$SKILL_DIR" || exit 1

JUNIT=$(mktemp -t cli-tool-tests-XXXXXX.xml)
RAW_OUTPUT_FILE=$(mktemp -t cli-tool-tests-raw-XXXXXX.log)
trap 'rm -f "$JUNIT" "$RAW_OUTPUT_FILE"' EXIT
export UV_PROJECT_ENVIRONMENT="$SKILL_UV_ENV"

PRECHECK_JSON="$(
    run_auth_status_schema_preflight 2> >(tee -a "$RAW_OUTPUT_FILE" >&2)
)"
PRECHECK_STATUS="$(PRECHECK_JSON="$PRECHECK_JSON" \
    UV_PROJECT_ENVIRONMENT="$SKILL_UV_ENV" \
    uv run --project "$SKILL_DIR" python3 - <<'PY'
import json
import os

print(json.loads(os.environ["PRECHECK_JSON"])["status"])
PY
)"
PRECHECK_MESSAGE="$(PRECHECK_JSON="$PRECHECK_JSON" \
    UV_PROJECT_ENVIRONMENT="$SKILL_UV_ENV" \
    uv run --project "$SKILL_DIR" python3 - <<'PY'
import json
import os

print(json.loads(os.environ["PRECHECK_JSON"])["message"])
PY
)"

PYTEST_ARGS=(--cli-name "$CLI_NAME" --tb=short --junitxml="$JUNIT")
PYTEST_ARGS+=(-k "not test_auth_status_schema")
[[ -n "$COMMAND" ]] && PYTEST_ARGS+=(--command "$COMMAND")
$VERBOSE && PYTEST_ARGS+=(-v) || PYTEST_ARGS+=(-q)

uv run python -m pytest "${PYTEST_ARGS[@]}" 2>&1 | tee -a "$RAW_OUTPUT_FILE" >&2
EXIT_CODE=$?

CLI_NAME="$CLI_NAME" COMMAND="$COMMAND" JUNIT="$JUNIT" \
    EXIT_CODE="$EXIT_CODE" RAW_OUTPUT_FILE="$RAW_OUTPUT_FILE" \
    PRECHECK_STATUS="$PRECHECK_STATUS" PRECHECK_MESSAGE="$PRECHECK_MESSAGE" \
    UV_PROJECT_ENVIRONMENT="$SKILL_UV_ENV" \
    uv run --project "$SKILL_DIR" python3 "$SKILL_DIR/scripts/junit_to_json.py"
