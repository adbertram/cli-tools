# Output Standards

## Output Stream Standards (MANDATORY)

### stdout (fd 1): DATA ONLY

All data output goes to stdout:
- JSON data (default format)
- Table data (via --table flag)
- AI instruction results (`type: "ai_instruction"`)

**Required functions from output.py:**
```python
print_json(data)                    # JSON to stdout
print_table(data, columns, headers) # Table to stdout
print_ai_instruction(instruction)   # AI handoff JSON to stdout
```

### stderr (fd 2): MESSAGES ONLY

All messages go to stderr:
```python
print_error(message)    # "Error: {message}"
print_warning(message)  # Yellow "Warning: {message}"
print_success(message)  # "✓ {message}"
print_info(message)     # Plain informational text
handle_error(error)     # Centralized error handling
```

**Why this matters:** Enables clean piping: `mycli list | jq '.field'`

### No Color/Escape Bytes On Non-TTY stdout

The shared Rich console (`cli_tools_shared.output.console`) is gated at
construction so it emits color and terminal control/detection escape sequences
**only** when stdout is a genuine interactive TTY and the environment has not
opted out of color. When stdout is a pipe or file — or a PTY-backed capture
sets `FORCE_COLOR` / `TTY_COMPATIBLE` to fake a terminal — the console is built
with `force_terminal=False, no_color=True`, so `print_table` output is plain
and `NO_COLOR` / `TERM=dumb` are honored even on a real terminal. `print_json`
writes raw UTF-8 bytes to `sys.stdout.buffer` and never touches the console.

Consequence: a CLI's piped stdout is byte-clean JSON/data with no leading
escape prefix. Do NOT add a "slice at the first `{`" / strip-leading-escape
workaround in calling automation — if you ever see an OSC color response such
as `]11;<rgb>` leading captured output, it came from the surrounding shell or
terminal responding to its own query, not from the CLI; fix the capture
environment, not the parser. This policy lives in exactly one place
(`_build_console` in the shared `output.py`); do not re-gate per command.

### Parsing Wrapper Output In Smokes

Smoke probes that validate wrapper commands must preserve the stdout/stderr
contract. Do not merge streams and then parse the combined transcript as JSON;
stderr may contain log paths or status messages after valid stdout JSON.

Use this shape:

```bash
stdout_file="$(mktemp)"
stderr_file="$(mktemp)"
trap 'rm -f "$stdout_file" "$stderr_file"' EXIT

set +e
./scripts/invoke-gmail.sh filters list --profile adbertram --limit 1 --properties id \
  >"$stdout_file" 2>"$stderr_file"
rc=$?
set -e

if [ "$rc" -ne 0 ]; then
  printf 'COMMAND_FAILED rc=%s stderr_lines=%s\n' \
    "$rc" "$(wc -l < "$stderr_file" | tr -d ' ')" >&2
  exit "$rc"
fi

python3 - "$stdout_file" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
json.loads(path.read_text())
PY
```

Only parse the saved stdout file. Keep stderr available as diagnostic evidence,
but do not feed it to `json.loads`, `jq`, or another structured parser. For
sensitive probes, report stderr metadata instead of printing raw stderr content.

---

## AI Instruction Results

Commands may return an AI instruction result when they have reached a boundary where the next step requires AI judgment. This is a successful data result on stdout, not a warning, prompt, or stderr message.

Required behavior:
- Return the shared `AIInstruction` model from `cli_tools_shared.models`.
- Print it with `print_ai_instruction()`.
- Include both structured context and narrative context when both help the agent act correctly.
- Include constraints and success criteria so the agent can complete the handoff without inventing missing details.
- Use `verification_commands` and `follow_up_commands` only for commands that run after the AI agent completes the instructed work.

Forbidden behavior:
- Do not call an LLM from inside the CLI.
- Do not emit plain-text instructions on stdout.
- Do not create a tool-local instruction schema.
- Do not include required pre-action command lists such as `required_commands`; the point of the handoff is that the deterministic command path is not known yet.

---

## Output Format Rules

| Rule | Status |
|------|--------|
| JSON is always the DEFAULT | REQUIRED |
| Use `--table` or `-t` for table format | REQUIRED |
| Never add `--json` flag | FORBIDDEN |
| Get/list commands have `--table/-t` option | REQUIRED |
| Table output must display ALL rows (no truncation) | REQUIRED |

### Table Output Truncation (FORBIDDEN)

**CRITICAL: CLI tools must NEVER truncate table output (rows).**

- `print_table()` must display ALL data rows passed to it
- Row limits should ONLY be applied at the API level via `--limit` flag
- Users rely on `--table` showing complete data
- Column limits (`max_columns = 6`) are acceptable for readability
- Row limits at display level are FORBIDDEN

**Why this matters:**
- Users expect `--table` to show everything returned by the API
- If users want fewer rows, they use `--limit` to control the query
- Truncating at display hides data users explicitly requested

```python
# CORRECT - show all rows
def print_table(data, ...):
    for row in rows:  # Iterate ALL rows
        table.add_row(...)

# WRONG - never truncate rows
def print_table(data, ...):
    max_rows = 50  # FORBIDDEN
    for row in rows[:max_rows]:  # FORBIDDEN
        table.add_row(...)
```

### JSON Output Truncation (FORBIDDEN)

**CRITICAL: JSON output must NEVER be truncated.**

JSON is the default output format and is designed for programmatic consumption. Truncating values breaks downstream processing (jq, scripts, piping).

**The truncate parameter pattern:**

Format functions that prepare data for display must have a `truncate` parameter:

```python
# CORRECT - truncate parameter controls truncation
def format_item_for_display(item: dict, truncate: bool = False) -> dict:
    description = item.get("description", "")
    if truncate and len(description) > 60:  # Only truncate when explicitly requested
        description = description[:57] + "..."
    return {"name": item["name"], "description": description}

# In command code:
use_table = table or output == "table"
formatted = format_item_for_display(item, truncate=use_table)  # Only truncate for table
if use_table:
    print_table([formatted], ...)
else:
    print_json(formatted)
```

```python
# WRONG - unconditional truncation affects JSON output
def format_item_for_display(item: dict) -> dict:
    description = item.get("description", "")
    if len(description) > 60:  # Always truncates - breaks JSON output!
        description = description[:57] + "..."
    return {"name": item["name"], "description": description}
```

**Rules:**
- Format functions MUST have `truncate: bool = False` parameter if they contain truncation logic
- Truncation MUST be conditional: `if truncate and len(x) > N:`
- JSON output (default) MUST use `truncate=False`
- Table output (`--table`) may use `truncate=True`

**Why this matters:**
- JSON is for machine consumption - scripts expect complete data
- Users piping to `jq` need full values for filtering/transformation
- Ellipsis (`...`) in JSON breaks parsing and comparison

---

## Response Format Rules

| Rule | Status |
|------|--------|
| `get` commands return only the resource object | REQUIRED |
| `list` commands return only the array | REQUIRED |
| Never wrap in `{"data": [...], "count": 10}` | FORBIDDEN |
| Never include pagination info in response | FORBIDDEN |

**Correct:**
```json
// list command output
[{"id": "1", "name": "Item 1"}, {"id": "2", "name": "Item 2"}]

// get command output
{"id": "1", "name": "Item 1", "details": "..."}
```

**Wrong:**
```json
// DON'T DO THIS
{"data": [...], "total": 100, "page": 1}
```

### Verifying JSON Root Shape Before Slicing

Live verification scripts must parse stdout, inspect the top-level JSON shape,
and require a list before slicing preview rows. Do not assume a decoded JSON
document is sliceable.

Use the shared test helper when running inside the cli-tool compliance harness:

```python
from cli_test_utils import require_json_array_output

valid, rows, error = require_json_array_output(stdout, command="amazon orders match")
if not valid:
    raise AssertionError(error)
preview = rows[:5]
```

For standalone scripts, copy the same shape check instead of slicing directly:

```python
payload = json.loads(stdout)
if not isinstance(payload, list):
    raise AssertionError(f"expected top-level JSON array, got {type(payload).__name__}")
preview = payload[:5]
```

---

## List Command Requirements

Every `list` command MUST have:

```python
@app.command("list")
def list_items(
    table: bool = typer.Option(False, "--table", "-t", help="Table output"),
    limit: int = typer.Option(100, "--limit", "-l", help="Max results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f",
        help="Filter: field:op:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p",
        help="Comma-separated list of fields to include in output"),
):
```

The `--properties/-p` option allows users to select which fields appear in the output, reducing response size and focusing on relevant data.

**Dot-notation for nested properties:**
```bash
# Select top-level fields
mycli items list --properties "id,name,status"

# Select nested fields using dot-notation
mycli items list --properties "id,name,metadata.created_at,owner.email"

# Mix of top-level and nested
mycli items list --properties "title,properties.Status,properties.Priority"
```

When implementing, parse dot-notation to extract nested values:
```python
def get_nested_value(obj: dict, path: str):
    """Get value from nested dict using dot notation."""
    keys = path.split(".")
    value = obj
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return None
    return value
```

---

## Hard Requirements (NEVER Remove)

**CRITICAL: The following are MANDATORY for ALL CLI tools and cannot be removed under ANY circumstance.**

| Requirement | Applies To | Status |
|-------------|------------|--------|
| `--filter/-f` | All `list` commands | **INVIOLABLE** |
| `--limit/-l` | All `list` commands | **INVIOLABLE** |
| `--table/-t` | All commands with output | **INVIOLABLE** |
| `--properties/-p` | All `list` commands | **INVIOLABLE** |

### When API Doesn't Support a Required Feature

If an API doesn't support filtering, pagination, or property selection:

1. **NEVER remove the flag** - The flag MUST exist
2. **ASK the user** how to proceed with one of these options:
   - Implement client-side fallback (if user approves)
   - Return error message explaining API limitation
   - Investigate API further for hidden support

**Example error for unsupported feature:**
```python
if filter and not api_supports_filtering:
    print_error("Filtering not supported by API. Use --help for alternatives.")
    raise typer.Exit(1)
```

**FORBIDDEN**: Removing flags because "API doesn't support it"
**REQUIRED**: Keep flags, implement fallback or error gracefully

---

## Output Field Selection

**MANDATORY**: All `list` and `get` commands **must** implement the `--properties` / `-p` option to limit which fields are displayed.

**Purpose:** Users often only need specific fields from large result sets. The `--properties` option allows selecting only the needed fields, reducing noise and enabling easier piping.

**Syntax:** Comma-separated list of field names with dot-notation support for nested fields:
- Simple fields: `--properties "id,name,status"`
- Nested fields: `--properties "id,assignee.name,project.id"`

**Dot-Notation:** Use `parent.child` to extract nested field values. For example, if an item has `{"assignee": {"name": "John", "id": 123}}`, then `--properties "assignee.name"` extracts `"John"`.

**Implementation:**

```python
def extract_field(item: dict, field: str):
    """Extract a field value, supporting dot-notation for nested fields."""
    parts = field.split(".")
    value = item
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value

def extract_fields(items: list, fields: list) -> list:
    """Extract specified fields from items, supporting dot-notation."""
    result = []
    for item in items:
        extracted = {}
        for field in fields:
            value = extract_field(item, field)
            extracted[field] = value
        result.append(extracted)
    return result

@app.command("list")
def item_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display (supports dot-notation)"),
):
    """List all items."""
    client = get_client()
    items = client.list_items(limit=limit, filters=filter)

    # Apply property field selection with dot-notation support
    if properties:
        fields = [f.strip() for f in properties.split(",")]
        items = extract_fields(items, fields)

    if table:
        columns = fields if properties else ["id", "name", "status"]
        print_table(items, columns, columns)
    else:
        print_json(items)
```

**Usage Examples:**

```bash
# Show only id and name
mytool items list --properties "id,name"

# Extract nested field (assignee.name from {"assignee": {"name": "John"}})
mytool items get 12345 --properties "assignee.name"

# Multiple nested fields
mytool items list --properties "id,name,assignee.name,project.id"

# Combine with filter and limit
mytool items list --filter "status:active" --limit 10 --properties "id,name,created_at"

# Pipe specific fields to jq
mytool items list --properties "id,email" | jq '.[].email'
```
