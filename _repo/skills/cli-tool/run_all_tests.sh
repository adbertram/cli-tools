#!/usr/bin/env bash
# Run the CLI-tool compliance suite against every top-level CLI package.

set -u

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
CLI_TOOLS_DIR="$(cd "$SKILL_DIR/../../.." && pwd -P)"
TEST_SCRIPT="$SKILL_DIR/scripts/test-cli-tool.sh"

TOTAL=0
PASSED=0
FAILED=0
FAILED_CLIS=()

for pyproject in "$CLI_TOOLS_DIR"/*/pyproject.toml; do
    CLI_DIR="$(dirname "$pyproject")"
    CLI_NAME="$(basename "$CLI_DIR")"

    if [[ "$CLI_NAME" == _* || "$CLI_NAME" == .* || "$CLI_NAME" == "cli-tools-shared" ]]; then
        continue
    fi

    TOTAL=$((TOTAL + 1))
    printf 'Testing %s\n' "$CLI_NAME" >&2

    RESULT="$("$TEST_SCRIPT" --cli-name "$CLI_NAME")"
    printf '%s\n' "$RESULT"

    if RESULT_JSON="$RESULT" python3 - <<'PY'
import json
import os
import sys

payload = json.loads(os.environ["RESULT_JSON"])
sys.exit(0 if payload["success"] else 1)
PY
    then
        PASSED=$((PASSED + 1))
    else
        FAILED=$((FAILED + 1))
        FAILED_CLIS+=("$CLI_NAME")
    fi
done

printf 'SUMMARY total=%d passed=%d failed=%d\n' "$TOTAL" "$PASSED" "$FAILED" >&2

if [[ "$FAILED" -ne 0 ]]; then
    printf 'FAILED_CLIS %s\n' "${FAILED_CLIS[*]}" >&2
    exit 1
fi
