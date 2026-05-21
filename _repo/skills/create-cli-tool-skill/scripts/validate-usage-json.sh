#!/usr/bin/env bash
# Validates the complete output of create-cli-tool-skill:
#   1. SKILL.md structural fields
#   2. usage.json schema and usage_instructions coverage
#   3. Cross-references between SKILL.md and usage.json
#   4. Directory hygiene (file count, temp cleanup)
#
# Usage: validate-usage-json.sh [path/to/usage.json]
# If no path given, finds the most recently modified *-cli/usage.json.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [[ $# -ge 1 ]]; then
  JSON_FILE="$1"
else
  JSON_FILE=$(find "$SKILL_ROOT" -maxdepth 2 -path '*-cli/usage.json' -print0 \
    | xargs -0 ls -t 2>/dev/null | head -1)
fi

if [[ -z "$JSON_FILE" || ! -f "$JSON_FILE" ]]; then
  echo "ERROR: No usage.json found to validate" >&2
  exit 2
fi

SKILL_DIR=$(dirname "$JSON_FILE")
DIR_NAME=$(basename "$SKILL_DIR")
SKILL_MD="$SKILL_DIR/SKILL.md"

TOOL_NAME=$(jq -r '.tool // empty' "$JSON_FILE" 2>/dev/null)
if [[ -z "$TOOL_NAME" ]]; then
  echo "ERROR: $JSON_FILE is not valid JSON or missing .tool field" >&2
  exit 2
fi

echo "Validating: $SKILL_DIR (tool: $TOOL_NAME)"
echo ""

ERRORS=0
WARNINGS=0

error() { echo "  ERROR: $1" >&2; ERRORS=$((ERRORS + 1)); return 0; }
warn()  { echo "  WARN:  $1"; WARNINGS=$((WARNINGS + 1)); return 0; }
pass()  { echo "  PASS:  $1"; }

# ============================================================
# SECTION 1: SKILL.md structural validation
# ============================================================
echo "--- SKILL.md ---"

if [[ ! -f "$SKILL_MD" ]]; then
  error "Missing SKILL.md at $SKILL_MD"
else
  skill_name=$(awk -F': *' '/^name:/ {gsub(/"/, "", $2); print $2; exit}' "$SKILL_MD")
  if [[ "$skill_name" != "$DIR_NAME" ]]; then
    error "SKILL.md name '$skill_name' does not match directory '$DIR_NAME'"
  else
    pass "SKILL.md name matches directory"
  fi

  if grep -q '^description:' "$SKILL_MD"; then
    pass "SKILL.md description present"
  else
    error "SKILL.md missing description"
  fi
fi

# ============================================================
# SECTION 2: usage.json schema and usage_instructions
# ============================================================
echo ""
echo "--- usage.json ---"

# Root-level required fields
for field in tool description discovered_at total_commands usage_instructions commands; do
  val=$(jq -r ".$field // empty" "$JSON_FILE")
  if [[ -z "$val" ]]; then
    error "Missing root field: $field"
  else
    pass "Root .$field present"
  fi
done

# Root usage_instructions length
root_ui_len=$(jq -r '.usage_instructions | length' "$JSON_FILE")
if [[ "$root_ui_len" -lt 20 ]]; then
  warn "Root usage_instructions is very short ($root_ui_len chars)"
fi

# Commands and command groups
commands=$(jq -r '.commands | keys[]' "$JSON_FILE" 2>/dev/null)
if [[ -z "$commands" ]]; then
  error "No commands found in .commands"
else
  for command_name in $commands; do
    has_child_commands=$(jq -r "(.commands[\"$command_name\"].commands? | type) == \"object\"" "$JSON_FILE")
    command_ui=$(jq -r ".commands[\"$command_name\"].usage_instructions // empty" "$JSON_FILE")
    if [[ -z "$command_ui" ]]; then
      error "Command '$command_name' missing usage_instructions"
    else
      pass "Command '$command_name' has usage_instructions"
    fi

    command_help=$(jq -r ".commands[\"$command_name\"].help // empty" "$JSON_FILE")
    if [[ -z "$command_help" ]]; then
      warn "Command '$command_name' missing help text"
    fi

    if [[ "$has_child_commands" != "true" ]]; then
      continue
    fi

    leaves=$(jq -r ".commands[\"$command_name\"].commands | keys[]" "$JSON_FILE" 2>/dev/null)
    if [[ -z "$leaves" ]]; then
      warn "Command group '$command_name' has no leaf commands"
      continue
    fi

    for leaf in $leaves; do
      leaf_ui=$(jq -r ".commands[\"$command_name\"].commands[\"$leaf\"].usage_instructions // empty" "$JSON_FILE")
      if [[ -z "$leaf_ui" ]]; then
        error "Command '$command_name $leaf' missing usage_instructions"
      fi

      leaf_help=$(jq -r ".commands[\"$command_name\"].commands[\"$leaf\"].help // empty" "$JSON_FILE")
      if [[ -z "$leaf_help" ]]; then
        warn "Command '$command_name $leaf' missing help text"
      fi
    done
  done
fi

# total_commands accuracy
declared=$(jq -r '.total_commands' "$JSON_FILE")
actual=$(jq '
  def count_leaf(node):
    if (node.commands? | type) == "object" then
      [node.commands[] | count_leaf(.)] | add
    else
      1
    end;
  [.commands[] | count_leaf(.)] | add
' "$JSON_FILE")
if [[ "$declared" != "$actual" ]]; then
  warn "total_commands says $declared but found $actual leaf commands"
fi

# AI instruction metadata
ai_count=$(jq '
  [
    paths(objects)
    as $p
    | getpath($p)
    | select(has("ai_instruction_result"))
  ] | length
' "$JSON_FILE")
if [[ "$ai_count" -gt 0 ]]; then
  pass "Found $ai_count command(s) with ai_instruction_result metadata"

  invalid_ai=$(jq -r '
    paths(objects)
    as $p
    | getpath($p)
    | select(has("ai_instruction_result"))
    | select(
        (.ai_instruction_result | type != "object")
        or (.ai_instruction_result.may_return != true)
        or (.ai_instruction_result.result_type != "ai_instruction")
        or (.ai_instruction_result.schema_version != "1.0")
      )
    | ($p | join("."))
  ' "$JSON_FILE")
  if [[ -n "$invalid_ai" ]]; then
    error "Invalid ai_instruction_result metadata at: $invalid_ai"
  else
    pass "AI instruction metadata has required result type and schema version"
  fi

  forbidden_ai=$(jq -r '
    paths(objects)
    as $p
    | getpath($p)
    | select(has("ai_instruction_result"))
    | select(
        has("required_commands")
        or has("command_to_run")
        or has("commands_to_run")
        or (
          (.ai_instruction_result | type == "object")
          and (
            (.ai_instruction_result | has("required_commands"))
            or (.ai_instruction_result | has("command_to_run"))
            or (.ai_instruction_result | has("commands_to_run"))
          )
        )
      )
    | ($p | join("."))
  ' "$JSON_FILE")
  if [[ -n "$forbidden_ai" ]]; then
    error "AI instruction metadata includes forbidden pre-action command fields at: $forbidden_ai"
  else
    pass "AI instruction metadata has no forbidden pre-action command fields"
  fi
fi

# ============================================================
# SECTION 3: Cross-references (CLI-tool-specific)
# ============================================================
echo ""
echo "--- Cross-references ---"

if [[ -f "$SKILL_MD" ]]; then
  # Tool name in SKILL.md matches usage.json
  if grep -q "\`$TOOL_NAME\`" "$SKILL_MD"; then
    pass "SKILL.md references tool '$TOOL_NAME'"
  else
    error "SKILL.md does not reference tool '$TOOL_NAME' from usage.json"
  fi

  # reference_index mentions usage.json
  ref_section=$(sed -n '/<reference_index>/,/<\/reference_index>/p' "$SKILL_MD")
  if echo "$ref_section" | grep -q "usage.json"; then
    pass "reference_index points to usage.json"
  else
    error "reference_index does not mention usage.json"
  fi

  # Commands in SKILL.md match usage.json
  commands_in_json=$(jq -r '.commands | keys[]' "$JSON_FILE" | sort)
  commands_missing=""
  for command_name in $commands_in_json; do
    if ! grep -qi -- "\\*\\*$command_name\\*\\*" "$SKILL_MD" && \
       ! grep -qi -- "\`$command_name\`" "$SKILL_MD" && \
       ! grep -qi -- "|.*$TOOL_NAME $command_name" "$SKILL_MD" && \
       ! grep -qi -- "- $command_name " "$SKILL_MD" && \
       ! grep -qi -- "- \*\*$command_name\*\*" "$SKILL_MD"; then
      commands_missing="$commands_missing $command_name"
    fi
  done
  if [[ -z "$commands_missing" ]]; then
    pass "All usage.json commands referenced in SKILL.md"
  else
    warn "Commands not found in SKILL.md:$commands_missing"
  fi

  # quick_start has a commands table
  qs_section=$(sed -n '/<quick_start>/,/<\/quick_start>/p' "$SKILL_MD")
  if echo "$qs_section" | grep -qE '^\|.+\|$'; then
    pass "quick_start contains a commands table"
  else
    warn "quick_start has no markdown table of common commands"
  fi
fi

# ============================================================
# SECTION 4: Directory hygiene
# ============================================================
echo ""
echo "--- Directory ---"

file_count=$(find "$SKILL_DIR" -maxdepth 1 -type f | wc -l | tr -d ' ')
if [[ "$file_count" -eq 2 ]]; then
  pass "Directory has exactly 2 files"
else
  extra=$(find "$SKILL_DIR" -maxdepth 1 -type f ! -name 'SKILL.md' ! -name 'usage.json' -exec basename {} \;)
  warn "Expected 2 files, found $file_count. Extra: $extra"
fi

if [[ -f "/tmp/${TOOL_NAME}-discovery.json" ]]; then
  warn "Temp file /tmp/${TOOL_NAME}-discovery.json still exists"
else
  pass "No leftover temp files"
fi

# ============================================================
# Summary
# ============================================================
echo ""
if [[ $ERRORS -gt 0 ]]; then
  echo "FAILED: $ERRORS error(s), $WARNINGS warning(s)"
  exit 2
else
  echo "PASSED: 0 errors, $WARNINGS warning(s)"
  exit 0
fi
