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
