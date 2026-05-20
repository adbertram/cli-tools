# Command Standards

## Command Naming Standards

**MANDATORY**: Commands must follow the noun-verb pattern using Typer's subcommand structure. Never combine nouns and verbs with hyphens.

| Pattern | Example | Status |
|---------|---------|--------|
| `<noun> <verb>` | `labels list`, `users get`, `items create` | CORRECT |
| `<verb>-<noun>` | `list-labels`, `get-users`, `create-item` | FORBIDDEN |
| `<noun>-<verb>` | `labels-list`, `users-get` | FORBIDDEN |

**Why noun-verb pattern:**
- **Discoverability**: `mytool users --help` shows all user operations
- **Consistency**: Matches established CLI patterns (git, kubectl, aws)
- **Composability**: Easy to remember - resource first, then action

**Implementation:**
```python
# CORRECT - Noun (resource) as command group, verb as subcommand
users_app = typer.Typer(help="Manage users")
app.add_typer(users_app, name="users")

@users_app.command("list")
def users_list(): ...

@users_app.command("get")
def users_get(user_id: str): ...

# WRONG - Hyphenated verb-noun commands
@app.command("list-users")
def list_users(): ...

@app.command("get-user")
def get_user(user_id: str): ...
```

### Standard CRUD Patterns

| Pattern | Usage |
|---------|-------|
| `<resource> list` | List all resources |
| `<resource> get <id>` | Get single resource |
| `<resource> create` | Create new resource |
| `<resource> update <id>` | Update resource |
| `<resource> delete <id>` | Delete resource |

### Exception: Singular Aggregate Data

For commands that return singular aggregate data (not a collection of resources), the list/get pattern does not apply. Use only `get`:

```bash
# Correct - statistics is aggregate data
mycli statistics get
mycli statistics get --entity-id 123

# Wrong - statistics is not a collection
mycli statistics list  # NO - doesn't make sense
```

**When to use this exception:**
- The data is computed/aggregated (totals, averages, counts)
- There's no collection of individual items to list
- The endpoint returns a single summary object

**Examples:** statistics, summary, metrics, health, status (singular)

---

## Option Standards

| Pattern | Short | Long | Description |
|---------|-------|------|-------------|
| Version | `-v` | `--version` | Show version and exit |
| Force/confirm | `-F` | `--force` | Skip confirmation prompts |
| Filter | `-f` | `--filter` | Filter results (REQUIRED for list commands) |
| Limit | `-l` | `--limit` | Limit number of results (REQUIRED for list commands) |
| Properties | `-p` | `--properties` | Comma-separated list of fields to display (REQUIRED for list commands) |

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

---

## Bidirectional List/Get Requirement (MANDATORY)

**CRITICAL: The `list` and `get` commands are mutually dependent.**

### The Rule

| If you have... | You must also have... | Reason |
|----------------|----------------------|--------|
| `list` command | `get` command | Users can list items and then get details by ID |
| `get` command | `list` command | Users can discover IDs to use with `get` |

### Why Both Are Required

1. **List without get**: Users can see items exist but can't get details
2. **Get without list**: Users can't discover which IDs exist to query

Both scenarios leave users with incomplete functionality.

### Example: Compliant Structure

```bash
# CORRECT - both list and get exist
mycli database page list          # Discover page IDs
mycli database page get PAGE_ID   # Get specific page

# WRONG - get without list
mycli database page get PAGE_ID   # How do users discover PAGE_ID?
```

### Exceptions

Command groups that return **aggregate/computed data** (not collections) are exempt from requiring `list`:

- `statistics` - aggregate metrics
- `metrics` - computed values
- `health` - system status
- `summary` - aggregated summary
- `status` - current state

Command groups that are **query-based** (not ID-based) are exempt from requiring `get`:

- `search` - returns results based on query, not specific IDs

---

## No Args Shows Help (MANDATORY)

**CRITICAL: All CLI apps must show help when invoked without a command.**

### Main App Behavior

The main app uses a callback pattern to support `--version` and show help:

```python
app = typer.Typer(
    name="{{name}}",
    help="CLI interface for {{Name}} API",
    add_completion=True,
)

@app.callback(invoke_without_command=True)
def callback(
    ctx: typer.Context,
    version: Optional[bool] = typer.Option(
        None, "--version", "-v", help="Show version and exit", is_eager=True
    ),
):
    """Main callback for version and help."""
    if version:
        from . import __version__
        typer.echo(f"{{name}}-cli version {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()
```

### Subcommand App Behavior

All subcommand apps (auth, items, search, etc.) MUST use `no_args_is_help=True`:

```python
# CORRECT - shows help when user types: mycli auth (without subcommand)
app = typer.Typer(help="Manage authentication", no_args_is_help=True)

# WRONG - may not show help without subcommand
app = typer.Typer(help="Manage authentication")
```

### Why This Matters

When a user types `mycli auth` without specifying a command like `login` or `status`:
- **With `no_args_is_help=True`**: Shows available commands (login, status, logout)
- **Without**: May show nothing or an error

---

## Help Text Standards

Every command must have:
1. A docstring describing what it does
2. Help text for all options

```python
@app.command("list")
def list_items(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """List all items with optional filtering."""
    ...
```

---

## Search Command Standards

**MANDATORY**: Every CLI tool **should** implement a `search` command for resources that support querying.

**Purpose:** The `search` command provides wildcard/pattern matching across all fields in the output, regardless of API support.

| CLI Type | Preferred Method | Fallback |
|----------|------------------|----------|
| API | API-level search (if endpoint exists) | Client-side wildcard matching |
| Browser | Client-side wildcard matching | N/A |
| Wrapper | Underlying CLI's search option | Client-side wildcard matching |

**Required Behavior:**
- Search is **case-insensitive** by default
- Wildcards: `*` matches any characters (like shell glob patterns)
- Searches **all string fields** in the output by default
- Optionally specify fields to search with `--fields`

**Example Implementation:**

```python
import fnmatch

@app.command("search")
def item_search(
    query: str = typer.Argument(..., help="Search query (supports * wildcards)"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    fields: Optional[str] = typer.Option(None, "--fields", help="Comma-separated fields to search"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
):
    """Search items with wildcard pattern matching."""
    client = get_client()
    items = client.search_items(query=query, limit=limit)

    # Apply property field selection if specified
    if properties:
        output_fields = [f.strip() for f in properties.split(",")]
        items = [{k: v for k, v in item.items() if k in output_fields} for item in items]

    if table:
        print_table(items, list(items[0].keys()) if items else [])
    else:
        print_json(items)


# In client.py
def search_items(self, query: str, limit: int = 100, fields: List[str] = None) -> List[Dict]:
    """Search items with wildcard matching.

    Search: API-level if /search endpoint exists, otherwise client-side
    """
    # Try API search first if available
    if self._has_search_endpoint:
        return self._make_request("GET", "/items/search", params={"q": query, "limit": limit})

    # Fall back to client-side wildcard matching
    all_items = self.list_items(limit=limit)
    return self._apply_wildcard_search(all_items, query, fields)

def _apply_wildcard_search(self, items: List[Dict], query: str, fields: List[str] = None) -> List[Dict]:
    """Apply wildcard search to items.

    Searches all string fields unless specific fields are provided.
    Supports * wildcard (converted to fnmatch pattern).
    """
    # Convert query to fnmatch pattern (case-insensitive)
    pattern = query.lower()
    if '*' not in pattern:
        pattern = f'*{pattern}*'  # Default to contains match

    results = []
    for item in items:
        # Get fields to search
        search_fields = fields or [k for k, v in item.items() if isinstance(v, str)]

        # Check if any field matches
        for field in search_fields:
            value = str(item.get(field, '')).lower()
            if fnmatch.fnmatch(value, pattern):
                results.append(item)
                break

    return results
```

**Usage Examples:**

```bash
# Search all fields for "invoice"
mytool items search "*invoice*"

# Search with exact prefix
mytool items search "INV-2024*"

# Search specific fields only
mytool items search "*pending*" --fields "status,notes"

# Combine with property selection
mytool items search "*error*" --properties "id,name,status"
```
