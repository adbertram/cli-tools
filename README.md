# CLI Tools

A collection of Python CLI tools using Typer for consistent command-line interfaces with shell completion support.

## Standards

All CLI tools **must** follow these standards for consistency.

### Output Stream Standards

**MANDATORY**: All CLI tools **must** use the correct output streams. This enables piping and automation.

```
┌─────────────────────────────────────────────────────────────┐
│  stdout (file descriptor 1)  →  DATA ONLY (JSON, tables)   │
│  stderr (file descriptor 2)  →  MESSAGES (status, errors)  │
└─────────────────────────────────────────────────────────────┘
```

| Stream | Purpose | Examples |
|--------|---------|----------|
| **stdout** | Data responses only | JSON output, table output |
| **stderr** | All human messages | Status, progress, warnings, errors, success confirmations |

**Why this matters:**
```bash
# stdout contains only JSON, so piping works cleanly
mytool users list | jq '.[0].email'

# Messages appear on screen but don't pollute the pipe
mytool users create --email foo@bar.com | jq '.id'
# Output: "✓ User created" (stderr, visible)
# Pipe receives: {"id": "123", ...} (stdout, clean JSON)
```

**Rules:**
- ✅ `print()` or `sys.stdout` → JSON data, table data
- ✅ `print(..., file=sys.stderr)` → Status messages, warnings, errors
- ❌ NEVER print status/progress/confirmation messages to stdout
- ❌ NEVER use `print()` directly for messages—use the required functions below

### Required Output Functions (output.py)

**MANDATORY**: Every CLI **must** implement these exact functions in `output.py`. Commands **must** use these functions—never raw `print()` for messages.

| Function | Stream | Format | Purpose |
|----------|--------|--------|---------|
| `print_json(data)` | stdout | `json.dumps(data)` | All JSON data responses |
| `print_table(data, columns, headers)` | stdout | Formatted table | Human-readable data display |
| `print_error(message)` | stderr | `Error: {message}` | Error messages |
| `print_warning(message)` | stderr | `Warning: {message}` (yellow) | Warning messages |
| `print_success(message)` | stderr | `✓ {message}` | Success confirmations |
| `print_info(message)` | stderr | `{message}` | Informational messages |
| `handle_error(error)` | stderr | Via `print_error` | Centralized error handling, returns exit code |

**Additional requirements:**
- Table output goes to stdout (it's still data, just formatted differently)

**Output Format Rules:**
- ✅ JSON is **always** the default output format - no flag needed
- ❌ **NEVER add a `--json` flag** - JSON is the default, not an option

**Why no `--json` flag:**
```bash
# ✅ CORRECT - JSON is default, no flag needed
mytool users list | jq '.[]'
mytool users list  # Switch to table when needed

# ❌ WRONG - Don't create --json flags
mytool users list --json  # Redundant, JSON is already default
mytool users list --format json  # Over-engineered
```

This keeps the CLI simple: data commands output JSON by default (for piping).

**Response Format Rules:**
- ✅ `get` commands return **only the resource object** - no wrapper, no metadata
- ✅ `list` commands return **only the array of resources** - no pagination info, no count, no metadata
- ❌ **NEVER wrap responses** in objects like `{"data": [...], "count": 10, "page": 1}`
- ❌ **NEVER include metadata** like total count, pagination cursors, or request info

**Why pure resources only:**
```bash
# ✅ CORRECT - Direct array, easy to process
mytool items list | jq '.[0].name'
mytool items list | jq 'length'  # Count items yourself

# ❌ WRONG - Wrapped response, requires unwrapping
mytool items list | jq '.data[0].name'  # Extra .data required
mytool items list | jq '.items | length'  # Inconsistent paths
```

**If API returns wrapped responses:**
```python
def list_items(self, limit: int = 100) -> List[Dict]:
    """List items - returns only the resource array."""
    response = self._make_request("GET", "/items", params={"limit": limit})
    # API returns {"data": [...], "meta": {...}} - extract just the array
    return response.get("data", response)
```

### Configuration Standards

**MANDATORY**: Every CLI tool **must** use a `.env` file for all configuration. No credentials or tokens should ever be hardcoded or stored elsewhere.

| Rule | Description |
|------|-------------|
| **`.env` file required** | All credentials, OAuth tokens, API keys, and config stored in `.env` |
| **`.env.example` file** | Template documenting all required variables (committed to git) |
| **`.env` gitignored** | Actual `.env` file must be in `.gitignore` |
| **Singleton pattern** | Use `get_config()` to access configuration |
| **Token persistence** | OAuth tokens must be saved back to `.env` after refresh |
| **Use `.resolve()`** | Always use `Path(__file__).resolve()` to get absolute paths (see below) |

**CRITICAL - Absolute Path Resolution:**

The CLI must find its `.env` file regardless of where the user runs the command from. This is achieved by using `.resolve()`:

```python
# ✅ CORRECT - works from any directory
config_dir = Path(__file__).resolve().parent.parent

# ❌ WRONG - may fail when running from different directories
config_dir = Path(__file__).parent.parent
```

Without `.resolve()`, the path is relative and may not resolve correctly when:
- Running from a different directory (e.g., `cd ~ && mytool command`)
- Running via symlinks
- Running in non-interactive shells (scripts, automation, IDE terminals)

**What goes in `.env`:**
- API keys and secrets
- OAuth client IDs and secrets
- OAuth access tokens and refresh tokens
- Token expiration timestamps
- Account/workspace IDs
- Any other service-specific configuration

**Example `.env` file:**
```bash
# API Credentials
MYTOOL_API_KEY=abc123
MYTOOL_CLIENT_ID=client_xxx
MYTOOL_CLIENT_SECRET=secret_xxx

# OAuth Tokens (updated automatically on refresh)
MYTOOL_ACCESS_TOKEN=access_xxx
MYTOOL_REFRESH_TOKEN=refresh_xxx
MYTOOL_TOKEN_EXPIRES_AT=1234567890

# Account Configuration
MYTOOL_ACCOUNT_ID=acct_123
```

**Token Refresh Pattern:**
When OAuth tokens are refreshed, the new tokens must be saved back to `.env` using `python-dotenv`'s `set_key()`.

**CRITICAL:** `set_key()` only writes to the file - it does NOT update `os.environ`. You must manually update `os.environ` after calling `set_key()`, otherwise subsequent reads via `os.getenv()` will return stale values.

```python
import os
from dotenv import set_key

def save_tokens(self, access_token: str, refresh_token: str, expires_at: str):
    """Save OAuth tokens to .env file and update environment."""
    set_key(str(self.env_file_path), "MYTOOL_ACCESS_TOKEN", access_token)
    set_key(str(self.env_file_path), "MYTOOL_REFRESH_TOKEN", refresh_token)
    set_key(str(self.env_file_path), "MYTOOL_TOKEN_EXPIRES_AT", expires_at)
    # CRITICAL: Also update os.environ so subsequent reads get the new values
    os.environ["MYTOOL_ACCESS_TOKEN"] = access_token
    os.environ["MYTOOL_REFRESH_TOKEN"] = refresh_token
    os.environ["MYTOOL_TOKEN_EXPIRES_AT"] = expires_at

def clear_credentials(self):
    """Clear credentials from .env file and environment."""
    set_key(str(self.env_file_path), "MYTOOL_ACCESS_TOKEN", "")
    set_key(str(self.env_file_path), "MYTOOL_REFRESH_TOKEN", "")
    set_key(str(self.env_file_path), "MYTOOL_TOKEN_EXPIRES_AT", "")
    # CRITICAL: Also clear from os.environ
    os.environ.pop("MYTOOL_ACCESS_TOKEN", None)
    os.environ.pop("MYTOOL_REFRESH_TOKEN", None)
    os.environ.pop("MYTOOL_TOKEN_EXPIRES_AT", None)
```

### Authentication Standards

**MANDATORY**: Every API that requires authentication **must** implement an `auth` command group with the following subcommands:

| Command | Description | Required |
|---------|-------------|----------|
| `auth login` | Initiate authentication flow (OAuth, API key setup, etc.) | ✅ Yes |
| `auth status` | Check authentication status and display current credentials info | ✅ Yes |
| `auth logout` | Clear stored credentials/tokens | Recommended |

**Implementation Requirements:**
- `auth status` must return exit code `0` if authenticated, `2` if not authenticated
- `auth status` should output credential info as JSON (e.g., email, expiry, scopes)
- `auth login` should guide the user through the authentication process
- All other commands should fail gracefully with exit code `2` if not authenticated

**Example:**
```bash
# Check if authenticated
mytool auth status

# Authenticate
mytool auth login

# Check status with table output
mytool auth status

# Logout
mytool auth logout
```

### OAuth Login Flow Standard

**MANDATORY**: For OAuth-based authentication with authorization code grant, the `auth login` command **must** implement an interactive flow that handles both direct codes and redirect URLs.

**Required Behavior:**

1. **Open browser** for authorization URL
2. **Interactively prompt** user for input (not just print instructions)
3. **Accept either:**
   - The authorization code directly (e.g., `v^1.1#i^1#...`)
   - The full redirect URL (e.g., `https://mysite.com/?code=v%5E1.1%23...&expires_in=299`)
4. **Auto-detect input type** and URL-decode if needed
5. **Exchange code** for tokens

**Implementation Pattern:**

```python
from urllib.parse import urlparse, parse_qs, unquote

def _extract_code_from_input(user_input: str) -> str:
    """Extract authorization code from user input.

    Accepts either:
    - Direct code: v^1.1#i^1#...
    - Full redirect URL: https://example.com/?code=v%5E1.1%23...

    Returns the URL-decoded authorization code.
    """
    user_input = user_input.strip()

    # Check if input looks like a URL
    if user_input.startswith("http://") or user_input.startswith("https://"):
        parsed = urlparse(user_input)
        query_params = parse_qs(parsed.query)

        if "code" not in query_params:
            raise ValueError("No 'code' parameter found in URL")

        # parse_qs returns lists, get first value and URL-decode
        code = query_params["code"][0]
        return unquote(code)

    # Assume direct code - URL decode in case it's encoded
    return unquote(user_input)


def _start_oauth_flow(config):
    """Start OAuth flow with interactive code input."""
    import webbrowser

    # Build and open authorization URL
    auth_url = build_auth_url(config)
    print_info("Opening browser for authorization...")
    print_info(f"\nIf browser doesn't open, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    # Interactive prompt for code or URL
    print_info("After authorizing, you'll be redirected.")
    print_info("Paste the authorization code OR the full redirect URL below:\n")

    user_input = typer.prompt("Code or URL")

    try:
        code = _extract_code_from_input(user_input)
        _exchange_code_for_tokens(config, code)
    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)
```

**User Experience:**

```
$ mytool auth login
Opening browser for authorization...

If browser doesn't open, visit:
https://auth.example.com/oauth2/authorize?client_id=xxx&...

After authorizing, you'll be redirected.
Paste the authorization code OR the full redirect URL below:

Code or URL: https://mysite.com/?code=v%5E1.1%23i%5E1%23...&expires_in=299
✓ Authentication successful! Tokens saved to .env file.
```

**Why This Pattern:**
- Users don't need to manually extract/decode the code parameter
- Works whether user copies the code or the full URL
- Handles URL encoding automatically (e.g., `%5E` → `^`, `%23` → `#`)
- Single interactive session instead of two separate commands

### Repository Standards

**MANDATORY**: `/Users/adam/Dropbox/GitRepos/cli-tools` is the only Git repository for CLI tools. Individual tool folders must not contain nested `.git` directories and must not have their own GitHub repositories.

| Requirement | Description |
|-------------|-------------|
| **Parent Git repo required** | The `cli-tools` parent directory is initialized as one Git repository |
| **No nested repos** | Individual CLI tool directories must not contain `.git` directories or `.git` files |
| **Single private GitHub repo** | The parent repo remote is `adbertram/cli-tools` |

**Naming Convention:**
- Local tool directory: `toolname/` (lowercase)
- Parent GitHub repo: `adbertram/cli-tools`

**Setup Commands:**
```bash
cd ~/Dropbox/GitRepos/cli-tools
git status --short --branch
```

**Why one private monorepo?**
- Shared package changes and individual CLI changes land in one atomic commit history
- Tooling can update dependencies, tests, and documentation consistently across all CLIs
- The whole CLI toolchain stays private without maintaining one repo per service

### Documentation Standards

**MANDATORY**: Every CLI tool **must** have a `README.md` file that follows the standard template.

| Requirement | Description |
|-------------|-------------|
| **README.md required** | Every CLI tool must have a README in the tool's root directory |
| **Use template** | Follow `README_TEMPLATE.md` in the cli-tools root |
| **Complete sections** | All template sections must be filled out |
| **All commands documented** | Every command and subcommand must be documented in the README |

**Command Documentation Requirement:**

Every command available via `<tool> --help` must be documented in the tool's README.md. This includes:
- All command groups (e.g., `users`, `items`, `auth`)
- All subcommands within each group (e.g., `list`, `get`, `create`)
- Brief description and at least one usage example per command

The `test-cli-tool.sh` script validates this by comparing `<tool> --help` output against README content.

**Required README Sections:**
1. **Title & Description** - What the tool does and what service it interfaces with
2. **Installation** - How to install the CLI
3. **Quick Start** - 3-5 essential commands to get started immediately
4. **Commands** - All command groups with examples for each subcommand
5. **Output Formats** - JSON and table output examples
6. **Options Reference** - Table of all common options with descriptions
7. **Configuration** - Environment variables and .env file details
8. **Exit Codes** - Standard exit codes table
9. **Examples** - Real-world usage examples for common tasks
10. **Requirements** - Python version and dependencies

See `README_TEMPLATE.md` for the complete template.

### Warning Suppression

All CLI tools **must** suppress known benign warnings to keep output clean. Add this to `__init__.py` (loads first):

```python
# In __init__.py - must be before any other imports
import warnings
warnings.filterwarnings("ignore", module="urllib3")
```

This suppresses the LibreSSL compatibility warning from urllib3 on macOS systems. The filter must be set before urllib3 is imported by any dependency.

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | General error |
| `2` | Authentication/credentials error |
| `130` | Interrupted (Ctrl+C) |

### Command Naming Standards

**MANDATORY**: Commands must follow the noun-verb pattern using Typer's subcommand structure. Never combine nouns and verbs with hyphens.

| Pattern | Example | Status |
|---------|---------|--------|
| `<noun> <verb>` | `labels list`, `users get`, `items create` | ✅ **CORRECT** |
| `<verb>-<noun>` | `list-labels`, `get-users`, `create-item` | ❌ **FORBIDDEN** |
| `<noun>-<verb>` | `labels-list`, `users-get` | ❌ **FORBIDDEN** |

**Why noun-verb pattern:**
- **Discoverability**: `mytool users --help` shows all user operations
- **Consistency**: Matches established CLI patterns (git, kubectl, aws)
- **Composability**: Easy to remember - resource first, then action

**Implementation:**
```python
# ✅ CORRECT - Noun (resource) as command group, verb as subcommand
users_app = typer.Typer(help="Manage users")
app.add_typer(users_app, name="users")

@users_app.command("list")
def users_list(): ...

@users_app.command("get")
def users_get(user_id: str): ...

# ❌ WRONG - Hyphenated verb-noun commands
@app.command("list-users")
def list_users(): ...

@app.command("get-user")
def get_user(user_id: str): ...
```

**Usage examples:**
```bash
# ✅ CORRECT
mytool users list
mytool users get 123
mytool labels create --name "urgent"
mytool items search "query"

# ❌ WRONG
mytool list-users
mytool get-user 123
mytool create-label --name "urgent"
mytool search-items "query"
```

### Option Standards

| Pattern | Short | Long | Description |
|---------|-------|------|-------------|
| Version | `-v` | `--version` | Show version and exit |
| Force/confirm | `-F` | `--force` | Skip confirmation prompts |
| Filter | `-f` | `--filter` | Filter results (REQUIRED for list commands) |
| Limit | `-l` | `--limit` | Limit number of results (REQUIRED for list commands) |
| Output fields | `-o` | `--output` | Comma-separated list of fields to display (REQUIRED for list commands) |

### Limit and Filter Standards

**MANDATORY**: All `list` commands **must** implement both `--limit` and `--filter` options.

**CRITICAL: No Dedicated Filter Commands**

CLI tools **must NOT** have a dedicated `filter` command group or subcommand. Filtering is implemented **exclusively** via the `--filter` / `-f` parameter on `list` commands.

| Pattern | Status |
|---------|--------|
| `mytool items list --filter "status:active"` | ✅ **CORRECT** |
| `mytool items filter --status active` | ❌ **FORBIDDEN** |
| `mytool items filter 12345 --filters '{...}'` | ❌ **FORBIDDEN** |

**Why no dedicated filter commands:**
- **Consistency**: All CLIs filter via `--filter` on `list` - users learn one pattern
- **Composability**: Filter syntax works the same way everywhere
- **Simplicity**: No confusion about when to use `list` vs `filter`

#### `--limit` / `-l` Implementation

| CLI Type | Preferred Method | Fallback |
|----------|------------------|----------|
| API | API-level limiting (query param) | Client-side truncation |
| Browser | Client-side limiting | N/A |
| Wrapper | Underlying CLI's limit option | Client-side truncation |

**Implementation Priority:**
1. **Always prefer API-level limiting** - Pass limit to API query parameters when supported
2. **Fall back to client-side** - Truncate results after fetching only when API doesn't support limiting
3. **Document which method is used** - In client.py, comment whether limiting is API or client-side

**Example:**
```python
def list_items(self, limit: int = 100, **kwargs) -> List[Dict]:
    """List items with limit.

    Limiting: API-level (uses 'per_page' query param)
    """
    params = {"per_page": limit}
    return self._make_request("GET", "/items", params=params)
```

#### `--filter` / `-f` Implementation

| CLI Type | Preferred Method | Fallback |
|----------|------------------|----------|
| API | API-level filtering (query params) | Client-side filtering |
| Browser | Client-side filtering | N/A |
| Wrapper | Underlying CLI's filter options | Client-side filtering |

**Implementation Priority:**
1. **Always prefer API-level filtering** - Translate filters to API query parameters when supported
2. **Fall back to client-side** - Filter results after fetching only when API doesn't support the filter
3. **Use FilterMap** - Map CLI filters to API parameters using the FilterMap module
4. **Document filter support** - In client.py, comment which filters are API vs client-side

**Example:**
```python
def list_items(self, filters: List[str] = None, **kwargs) -> List[Dict]:
    """List items with filtering.

    API-level filters: status, created_after, type
    Client-side filters: name (API doesn't support)
    """
    api_params = self.filter_map.to_api_params(filters)
    results = self._make_request("GET", "/items", params=api_params)
    return self.filter_map.apply_client_filters(results, filters)
```

### Output Field Selection

**MANDATORY**: All `list` and `get` commands **must** implement the `--output` / `-o` option to limit which fields are displayed.

**Purpose:** Users often only need specific fields from large result sets. The `--output` option allows selecting only the needed fields, reducing noise and enabling easier piping.

**Syntax:** Comma-separated list of field names with dot-notation support for nested fields:
- Simple fields: `--output "id,name,status"`
- Nested fields: `--output "id,assignee.name,project.id"`

**Dot-Notation:** Use `parent.child` to extract nested field values. For example, if an item has `{"assignee": {"name": "John", "id": 123}}`, then `--output "assignee.name"` extracts `"John"`.

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
            # Use the full path as key, or just the final part for simple display
            extracted[field] = value
        result.append(extracted)
    return result

@app.command("list")
def item_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Comma-separated fields to display (supports dot-notation)"),
):
    """List all items."""
    client = get_client()
    items = client.list_items(limit=limit, filters=filter)

    # Apply output field selection with dot-notation support
    if output:
        fields = [f.strip() for f in output.split(",")]
        items = extract_fields(items, fields)

    if table:
        columns = fields if output else ["id", "name", "status"]
        print_table(items, columns, columns)
    else:
        print_json(items)

@app.command("get")
def item_get(
    item_id: str = typer.Argument(..., help="Item ID"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Comma-separated fields to display (supports dot-notation)"),
):
    """Get a specific item."""
    client = get_client()
    item = client.get_item(item_id)

    # Apply output field selection with dot-notation support
    if output:
        fields = [f.strip() for f in output.split(",")]
        item = extract_fields([item], fields)[0]

    if table:
        print_table([item], list(item.keys()), list(item.keys()))
    else:
        print_json(item)
```

**Usage Examples:**

```bash
# Show only id and name
mytool items list --output "id,name"

# Extract nested field (assignee.name from {"assignee": {"name": "John"}})
mytool items get 12345 --output "assignee.name"

# Multiple nested fields
mytool items list --output "id,name,assignee.name,project.id"

# Combine with filter and limit
mytool items list --filter "status:active" --limit 10 --output "id,name,created_at"

# Pipe specific fields to jq
mytool items list --output "id,email" | jq '.[].email'
```

### Search Command Standards

**MANDATORY**: Every CLI tool **should** implement a `search` command for resources that support querying.

**Purpose:** The `search` command provides wildcard/pattern matching across all fields in the output, regardless of API support.

| CLI Type | Preferred Method | Fallback |
|----------|------------------|----------|
| API | API-level search (if endpoint exists) | Client-side wildcard matching |
| Browser | Client-side wildcard matching | N/A |
| Wrapper | Underlying CLI's search option | Client-side wildcard matching |

**Implementation Priority:**
1. **Use API search if available** - Pass search query to API endpoint
2. **Fall back to client-side** - Fetch results and apply wildcard matching on all string fields
3. **Support wildcards** - Use `*` for wildcard matching (e.g., `*pattern*` matches anywhere)

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
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Comma-separated fields to display"),
):
    """Search items with wildcard pattern matching."""
    client = get_client()
    items = client.search_items(query=query, limit=limit)

    # Apply output field selection if specified
    if output:
        output_fields = [f.strip() for f in output.split(",")]
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

# Combine with output selection
mytool items search "*error*" --output "id,name,status"
```

### Filtering Syntax

CLI tools support advanced filtering using the `--filter` option.

**Format:** `field:operator:value` or `field:value` (defaults to equals).

**Supported Operators:**

| Operator | Syntax Example | Meaning |
|----------|----------------|---------|
| `eq` | `id:eq:1` | Equals (default) |
| `ne` | `status:ne:archived` | Not Equals |
| `gt` | `quantity:gt:0` | Greater Than |
| `gte` | `quantity:gte:5` | Greater Than or Equal |
| `lt` | `price:lt:10` | Less Than |
| `lte` | `price:lte:100` | Less Than or Equal |
| `in` | `status:in:active\|pending` | In Array (pipe-separated) |
| `nin` | `status:nin:deleted` | Not In Array |
| `like` | `name:like:%brick%` | LIKE pattern |
| `ilike` | `name:ilike:lego` | Case-insensitive LIKE |
| `null` | `deleted_at:null` | Is Null |
| `notnull` | `updated_at:notnull` | Is Not Null |

**Logic:**
- **AND**: Comma-separated pairs within a single flag: `--filter "status:active,price:lt:100"`
- **OR**: Multiple flags: `--filter "status:active" --filter "status:pending"`

### FilterMap Module

The `FilterMap` module (`filter_map.py`) provides a structured way to bridge the gap between CLI arguments, standard filter syntax, and API-specific parameters.

**Key Responsibilities:**
- Map CLI kwargs to standard filter strings.
- Translate standard filters to API-specific query parameters (server-side filtering).

**Usage Example:**

```python
# In client.py
from .filter_map import FilterMap

def _setup_filters(self):
    self.filter_map = FilterMap()
    
    # Map CLI arg 'status' to filter 'order_status:eq'
    self.filter_map.add_argument_mapping('status', 'order_status')
    
    # Define how to translate 'order_status' filter to API query param
    self.filter_map.register_api_translator(
        'order_status', 
        lambda op, val: {'status': val}
    )

def list_items(self, **kwargs):
    # 1. Convert CLI args to standard filters
    filters = self.filter_map.args_to_filters(**kwargs)
    
    # 2. Convert standard filters to API params
    params = self.filter_map.to_api_params(filters)
    
    # 3. Make request
    return self._make_request("GET", "/items", params=params)
```

## Architecture

Each CLI tool follows the same structure:

```
cli-tools/
├── README.md
└── <tool-name>/
    ├── .env                    # Credentials (gitignored)
    ├── .env.example            # Template for required variables
    ├── .gitignore
    ├── pyproject.toml          # Project config & dependencies
    ├── venv/                   # Virtual environment
    └── <tool_name>_cli/        # Main package (underscore, not hyphen)
        ├── __init__.py         # Version info
        ├── main.py             # Typer app entry point
        ├── client.py           # Service client class
        ├── config.py           # Configuration/credentials management
        ├── output.py           # Formatting helpers (JSON, tables, errors)
        └── commands/           # Command modules
            ├── __init__.py
            ├── <resource1>.py  # e.g., invoice.py
            └── <resource2>.py  # e.g., customer.py
```

### Wrapper CLI Structure

For wrapper CLIs that wrap existing CLI tools (like `lpass`, `aws`, `gh`):

```
<tool-name>/
├── .env                    # Minimal config (CLI command path)
├── .env.example            # Template
├── .gitignore
├── pyproject.toml          # No requests dependency
├── venv/                   # Virtual environment
└── <tool_name>_cli/
    ├── __init__.py         # Version info
    ├── main.py             # Typer app entry point
    ├── client.py           # Subprocess-based client (calls underlying CLI)
    ├── config.py           # CLI path configuration
    ├── output.py           # Formatting helpers
    ├── parsers.py          # Output parsing utilities (new for wrappers)
    ├── filters.py          # Filter validation
    ├── filter_map.py       # Filter translation
    └── commands/
        ├── __init__.py
        ├── auth.py         # Delegated auth commands
        └── <resource>.py   # Resource commands
```

## File Responsibilities

### `pyproject.toml`
Project metadata and entry point configuration:

```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "mytool-cli"
version = "0.1.0"
description = "CLI interface for MyTool API"
requires-python = ">=3.9"
dependencies = [
    "typer[all]>=0.9.0",
    "python-dotenv>=1.0.0",
    "requests>=2.31.0",
]

[project.scripts]
mytool = "mytool_cli.main:app"

[tool.setuptools.packages.find]
where = ["."]
include = ["mytool_cli*"]
```

### `__init__.py`
Package initialization with warning suppression:

```python
"""MyTool CLI - Command-line interface for MyTool API."""
# Suppress urllib3 SSL warnings (LibreSSL compatibility) - must be before urllib3 import
import warnings
warnings.filterwarnings("ignore", module="urllib3")

__version__ = "0.1.0"
```

### `main.py`
Main Typer application that registers command groups:

```python
"""Main entry point for MyTool CLI."""
import typer
from typing import Optional
from .client import ClientError

app = typer.Typer(
    name="mytool",
    help="CLI interface for MyTool API",
    add_completion=True,  # Enables --install-completion
)

# Register command modules
from .commands import resource1, resource2
app.add_typer(resource1.app, name="resource1", help="Manage resource1")
app.add_typer(resource2.app, name="resource2", help="Manage resource2")

@app.callback(invoke_without_command=True)
def callback(
    ctx: typer.Context,
    version: Optional[bool] = typer.Option(
        None, "--version", "-v", help="Show version and exit", is_eager=True
    ),
):
    """MyTool CLI - Manage MyTool from the command line."""
    if version:
        typer.echo("mytool-cli version 0.1.0")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()

def main():
    """Main entry point."""
    try:
        app()
    except ClientError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(2)
    except KeyboardInterrupt:
        typer.echo("\nAborted!", err=True)
        raise typer.Exit(130)

if __name__ == "__main__":
    main()
```

### `config.py`
Configuration management using environment variables:

**CRITICAL**: Always use `.resolve()` when computing the config directory path. This ensures the CLI finds its `.env` file regardless of the current working directory.

```python
"""Configuration management for MyTool CLI."""
import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv, set_key

class Config:
    def __init__(self):
        # IMPORTANT: Use resolve() to get absolute path - ensures .env is found regardless of cwd
        config_dir = Path(__file__).resolve().parent.parent
        self.env_file_path = config_dir / ".env"
        if self.env_file_path.exists():
            load_dotenv(self.env_file_path, override=True)

    @property
    def api_key(self) -> Optional[str]:
        return os.getenv("MYTOOL_API_KEY")

    def get_missing_credentials(self) -> list[str]:
        missing = []
        if not self.api_key:
            missing.append("MYTOOL_API_KEY")
        return missing

_config: Optional[Config] = None

def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config
```

### `client.py`
Service client with error handling:

```python
"""MyTool service client."""
from typing import Any, Dict, List, Optional
from .config import get_config
from .filter_map import FilterMap

class ClientError(Exception):
    """Custom exception for client errors."""
    pass

class MyToolClient:
    def __init__(self):
        self.config = get_config()
        missing = self.config.get_missing_credentials()
        if missing:
            raise ClientError(f"Missing credentials: {', '.join(missing)}")
        self._setup_filters()

    def _setup_filters(self):
        """Configure filter mappings for API translation."""
        self.filter_map = FilterMap()
        # Map CLI filter fields to API query parameters
        self.filter_map.register_api_translator(
            'status', lambda op, val: {'status': val}
        )

    def list_items(
        self,
        limit: int = 100,
        filters: Optional[List[str]] = None,
    ) -> List[Dict]:
        """List items with limit and filtering.

        Limiting: API-level (uses 'per_page' query param)
        Filtering:
            API-level: status, type, created_after
            Client-side: name (API doesn't support text search)
        """
        # Build API params from limit and filters
        params = {"per_page": limit}
        if filters:
            api_params = self.filter_map.to_api_params(filters)
            params.update(api_params)

        # Make request
        response = self._make_request("GET", "/items", params=params)

        # Extract array from wrapped response if needed
        items = response.get("data", response) if isinstance(response, dict) else response

        # Apply client-side filters for fields API doesn't support
        if filters:
            items = self.filter_map.apply_client_filters(items, filters)

        return items

    def get_item(self, item_id: str) -> Dict:
        """Get a specific item - returns only the resource object."""
        response = self._make_request("GET", f"/items/{item_id}")
        # Extract from wrapper if API wraps single resources
        return response.get("data", response) if isinstance(response, dict) and "data" in response else response

_client: Optional[MyToolClient] = None

def get_client() -> MyToolClient:
    """Get or create the global client instance."""
    global _client
    if _client is None:
        _client = MyToolClient()
    return _client
```

### `client.py` (Wrapper Type)

For wrapper CLIs, the client uses subprocess instead of HTTP requests:

```python
"""MyTool wrapper client."""
import subprocess
from typing import Dict, List, Optional
from .config import get_config
from .parsers import parse_cli_output
from .filter_map import FilterMap

class ClientError(Exception):
    pass

class MyToolClient:
    def __init__(self):
        self.config = get_config()
        if not self.config.is_cli_available():
            raise ClientError(f"CLI '{self.config.cli_command}' not found in PATH")
        self._setup_filters()

    def _setup_filters(self):
        """Configure filter mappings."""
        self.filter_map = FilterMap()

    def _run_command(self, args: List[str], check: bool = True) -> subprocess.CompletedProcess:
        """Run underlying CLI command."""
        cmd = [self.config.get_cli_executable()] + args
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if check and result.returncode != 0:
            raise ClientError(f"Command failed: {result.stderr}")
        return result

    def auth_login(self) -> Dict:
        """Delegate login to underlying CLI."""
        result = self._run_command(["login"], check=False)
        return {"success": result.returncode == 0, "message": result.stdout.strip()}

    def auth_status(self) -> Dict:
        """Check auth via underlying CLI's status command."""
        result = self._run_command(["status"], check=False)
        return {
            "authenticated": result.returncode == 0,
            "cli_command": self.config.cli_command,
            "cli_version": self.config.get_cli_version(),
        }

    def list_items(
        self,
        limit: int = 100,
        filters: Optional[List[str]] = None,
    ) -> List[Dict]:
        """List items from underlying CLI.

        Limiting: CLI-level if supported, otherwise client-side
        Filtering: Client-side (underlying CLI doesn't support filtering)
        """
        # Build command args - include limit if CLI supports it
        args = ["ls"]
        if hasattr(self, '_cli_supports_limit') and self._cli_supports_limit:
            args.extend(["--limit", str(limit)])

        result = self._run_command(args)
        items = parse_cli_output(result.stdout)

        # Client-side limiting if CLI doesn't support it
        if not hasattr(self, '_cli_supports_limit') or not self._cli_supports_limit:
            items = items[:limit]

        # Client-side filtering (most CLIs don't support filtering)
        if filters:
            items = self.filter_map.apply_client_filters(items, filters)

        return items
```

### Exponential Retry Support

**API-type CLIs include built-in exponential retry** for transient errors. This improves reliability when dealing with rate limits, temporary server issues, or network problems.

**Retryable Conditions:**
| Type | Conditions |
|------|------------|
| HTTP Status Codes | 429 (Rate Limit), 500, 502, 503, 504 (Server Errors) |
| Network Errors | Connection errors, timeouts, chunked encoding errors |

**Default Configuration:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_retries` | `3` | Maximum retry attempts |
| `base_delay` | `1.0s` | Initial delay before first retry |
| `max_delay` | `30.0s` | Maximum delay between retries |
| `jitter` | `0.1` | Random jitter factor (±10%) to prevent thundering herd |

**Backoff Formula:** `delay = min(base_delay * 2^attempt + jitter, max_delay)`

**Example delays:** 1s → 2s → 4s → 8s → ... (capped at 30s)

**Features:**
- Honors `Retry-After` header when present (common with 429 responses)
- Jitter prevents synchronized retries from multiple clients
- Authentication errors (401) trigger token refresh, not retry counting
- Disable retry per-request with `retry=False` parameter

**Customizing Retry Behavior:**

```python
# In client.py - customize at initialization
class MyToolClient:
    def __init__(self):
        # ... existing init code ...

        # Custom retry settings
        self.max_retries = 5       # More retries for flaky APIs
        self.base_delay = 0.5      # Faster initial retry
        self.max_delay = 60.0      # Allow longer waits
        self.jitter = 0.2          # More jitter (±20%)
```

**Disabling Retry for Specific Requests:**

```python
# Skip retry for time-sensitive operations
response = self._make_request("POST", "/urgent-action", data=payload, retry=False)
```

### `output.py`
Formatting helpers for consistent output streams:

```python
"""Output formatting helpers.

Stream Usage:
    stdout (fd 1) → Data only (JSON, tables) - via print_json(), print_table()
    stderr (fd 2) → Messages only - via print_error(), print_warning(), print_success(), print_info()

This separation enables clean piping: `mytool list | jq '.field'`
"""
import json
import sys
from typing import Any

def print_json(data: Any, indent: int = 2):
    """Print data as JSON to stdout."""
    print(json.dumps(data, indent=indent, ensure_ascii=False))

def print_table(data: list[dict], columns: list[str], headers: list[str] = None):
    """Print data as formatted table to stdout."""
    if not data:
        print("No results found.")
        return
    headers = headers or columns
    widths = [max(len(h), max(len(str(row.get(c, ""))) for row in data))
              for c, h in zip(columns, headers)]
    print("  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print("-" * sum(widths) + "-" * (len(widths) - 1) * 2)
    for row in data:
        print("  ".join(str(row.get(c, "")).ljust(w) for c, w in zip(columns, widths)))

def print_error(message: str):
    """Print error message to stderr."""
    print(f"Error: {message}", file=sys.stderr)

def print_warning(message: str):
    """Print warning message to stderr (yellow)."""
    yellow = "\033[93m"
    reset = "\033[0m"
    print(f"{yellow}Warning: {message}{reset}", file=sys.stderr)

def print_success(message: str):
    """Print success message to stderr."""
    print(f"✓ {message}", file=sys.stderr)

def print_info(message: str):
    """Print informational message to stderr."""
    print(message, file=sys.stderr)

def handle_error(error: Exception) -> int:
    """Handle errors and return appropriate exit code."""
    from .client import ClientError
    if isinstance(error, ClientError):
        print_error(str(error))
        # Return 2 for credential errors, 1 for others
        if "credential" in str(error).lower() or "missing" in str(error).lower():
            return 2
        return 1
    print_error(str(error))
    return 1
```

### `commands/<resource>.py`
Individual command modules:

```python
"""Item commands for MyTool CLI."""
import typer
from typing import List, Optional
from ..client import get_client
from ..output import print_json, print_table, handle_error, print_success

app = typer.Typer(help="Manage items")


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
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Comma-separated fields to display (supports dot-notation)"),
):
    """List all items."""
    try:
        client = get_client()
        items = client.list_items(limit=limit, filters=filter)

        # Apply output field selection with dot-notation support
        if output:
            fields = [f.strip() for f in output.split(",")]
            items = extract_fields(items, fields)

        if table:
            columns = fields if output else ["id", "name"]
            print_table(items, columns, columns)
        else:
            print_json(items)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def item_get(
    item_id: str = typer.Argument(..., help="Item ID"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Comma-separated fields to display (supports dot-notation)"),
):
    """Get a specific item."""
    try:
        client = get_client()
        item = client.get_item(item_id)

        # Apply output field selection with dot-notation support
        if output:
            fields = [f.strip() for f in output.split(",")]
            item = extract_fields([item], fields)[0]

        if table:
            columns = list(item.keys())
            print_table([item], columns, columns)
        else:
            print_json(item)
    except Exception as e:
        raise typer.Exit(handle_error(e))
```

## Creating a New CLI Tool

### Using the `new-cli-tool` Script (Recommended)

The `new-cli-tool` script automates the entire scaffolding process:

```bash
# For REST API CLIs:
~/Dropbox/GitRepos/cli-tools/new-cli-tool --name stripe --type api --base-url https://api.stripe.com/v1

# For browser automation CLIs:
~/Dropbox/GitRepos/cli-tools/new-cli-tool --name shopsite --type browser --base-url https://shopsite.com

# For CLI wrappers (wrapping existing CLI tools):
~/Dropbox/GitRepos/cli-tools/new-cli-tool --name lastpass --type wrapper --cli-command lpass \
  --description "LastPass password manager" --docs-url https://github.com/lastpass/lastpass-cli
```

**Script Options:**
| Option | Description |
|--------|-------------|
| `--name, -n` | CLI tool name (required) |
| `--type, -t` | Template type: `api`, `browser`, or `wrapper` (required) |
| `--base-url, -u` | Base URL (required for api/browser) |
| `--cli-command, -c` | Underlying CLI command (required for wrapper) |
| `--description, -d` | Short description |
| `--docs-url` | Documentation URL |
| `--no-venv` | Skip virtual environment creation |

The script will:
1. Create directory structure from templates
2. Set up virtual environment and install package
3. Create symlinks in `~/.local/bin`
4. Leave the tool inside the parent `cli-tools` monorepo

### Manual Setup (Alternative)

### 1. Create Directory Structure

```bash
cd ~/Dropbox/GitRepos/cli-tools
mkdir -p newtool/newtool_cli/commands
```

### 2. Create Files

Copy the templates above into:
- `newtool/pyproject.toml`
- `newtool/newtool_cli/__init__.py`
- `newtool/newtool_cli/main.py`
- `newtool/newtool_cli/config.py`
- `newtool/newtool_cli/client.py`
- `newtool/newtool_cli/output.py`
- `newtool/newtool_cli/commands/__init__.py`
- `newtool/newtool_cli/commands/<resource>.py`

### 3. Create .gitignore

```bash
cat > newtool/.gitignore << 'EOF'
__pycache__/
*.py[cod]
venv/
.env
*.egg-info/
dist/
build/
.DS_Store
EOF
```

### 4. Keep the Tool in the Parent Monorepo

Do not run `git init` inside `newtool`. Commit the new folder from `/Users/adam/Dropbox/GitRepos/cli-tools`.

### 5. Create Virtual Environment and Install

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -e .
deactivate
```

### 6. Create .env and .env.example Files

```bash
# Create .env.example (committed to git - documents required variables)
cat > .env.example << 'EOF'
# Required credentials for MyTool CLI
MYTOOL_API_KEY=
MYTOOL_ACCOUNT_ID=
EOF

# Create .env (gitignored - contains actual values)
cat > .env << 'EOF'
MYTOOL_API_KEY=your_api_key_here
MYTOOL_ACCOUNT_ID=your_account_id_here
EOF
```

### 7. Add Symlink for Global Access

**MANDATORY**: Every CLI tool **must** have a symlink in `~/.local/bin` to ensure the tool is available in all shell contexts, including non-interactive shells (like Cursor IDE, scripts, CI/CD).

```bash
# Create symlink (run once after installing the CLI)
ln -sf ~/Dropbox/GitRepos/cli-tools/newtool/venv/bin/newtool ~/.local/bin/newtool
```

**Why symlinks instead of aliases?**
- ✅ Works in non-interactive shells (Cursor, scripts, automation)
- ✅ Works with `which` and `command -v`
- ✅ Single configuration point (no need to update multiple shell configs)
- ✅ Works in PowerShell (when `~/.local/bin` is in PATH)
- ❌ Aliases only work in interactive shells

### 8. Install Shell Completion

Shell completion enables Tab auto-complete for commands and options.

**From each shell, run:**

```bash
# zsh (run from zsh)
newtool --install-completion

# bash (run from bash)
bash
newtool --install-completion
exit

# PowerShell (run from pwsh)
pwsh
newtool --install-completion
exit
```

**Important:** The `--install-completion` command detects your current shell. You must run it from within each shell you want completion for.

After installation, restart your terminal or source your profile:
```bash
source ~/.zshrc  # or ~/.bashrc
```

### 9. Update CLAUDE.md

**MANDATORY**: Add a row to the CLI tools table in `~/.claude/CLAUDE.md`.

**Add ONLY a table row:**
```markdown
| `newtool` | Service Name | API/Service Type | Brief description of what it does |
```

**NEVER add:**
- Detailed command syntax examples
- Command lists or usage patterns
- Extended documentation sections

Claude discovers CLI capabilities by running `<tool> --help` at runtime. Keeping CLAUDE.md minimal ensures it stays current and reduces context window usage.

## Testing Your CLI

```bash
# Show help
newtool --help
newtool resource --help

# List resources
newtool resource list
newtool resource list

# Get specific resource
newtool resource get <id>
```

## Existing CLI Tools

| Tool | Command | Description |
|------|---------|-------------|
| Copilot | `copilot` | Microsoft Copilot Studio agents via Dataverse API |
| eBay | `ebay` | eBay Fulfillment API for order management |
| FreshBooks | `freshbooks` | FreshBooks accounting API |
| Manus | `manus` | Manus AI API for AI task creation and management |
| Notion | `notion` | Notion API with database query filtering |

## Global Access

All CLI tools are accessible globally from any directory. Each tool runs from its own virtual environment but is invoked via symlinks in `~/.local/bin`.

**MANDATORY**: Every CLI tool **must** have a symlink in `~/.local/bin`.

### Why Symlinks?

Symlinks work in **all shell contexts**, including:
- Interactive shells (Terminal, iTerm)
- Non-interactive shells (Cursor IDE agent, scripts, CI/CD)
- Subprocess calls from Python/Node/etc.

Aliases only work in interactive shells and fail in automation contexts.

### Setup Symlinks

**Create symlink for a new CLI tool:**
```bash
ln -sf ~/Dropbox/GitRepos/cli-tools/toolname/venv/bin/toolname ~/.local/bin/toolname
```

**Verify it works:**
```bash
which toolname  # Should show ~/.local/bin/toolname
toolname --version
```

### Current Symlinks

All CLI tools are symlinked to `~/.local/bin/`:

```bash
# List all CLI tool symlinks
ls -la ~/.local/bin/ | grep -E 'copilot|ebay|freshbooks|manus|notion|google|dbxcli|shopgoodwill|shopsalvationarmy|testapi|paypal'
```

| Tool | Symlink | Target |
|------|---------|--------|
| copilot | `~/.local/bin/copilot` | `~/Dropbox/GitRepos/cli-tools/copilot/venv/bin/copilot` |
| ebay | `~/.local/bin/ebay` | `~/Dropbox/GitRepos/cli-tools/ebay/venv/bin/ebay` |
| freshbooks | `~/.local/bin/freshbooks` | `~/Dropbox/GitRepos/cli-tools/freshbooks/venv/bin/freshbooks` |
| google | `~/.local/bin/google` | `~/Dropbox/GitRepos/cli-tools/google/venv/bin/google` |
| manus | `~/.local/bin/manus` | `~/Dropbox/GitRepos/cli-tools/manus/venv/bin/manus` |
| notion | `~/.local/bin/notion` | `~/Dropbox/GitRepos/cli-tools/notion/venv/bin/notion` |
| dbxcli | `~/.local/bin/dbxcli` | `~/Dropbox/GitRepos/cli-tools/dropbox/dbxcli` |
| shopgoodwill | `~/.local/bin/shopgoodwill` | `~/Dropbox/GitRepos/cli-tools/shopgoodwill/venv/bin/shopgoodwill` |
| shopsalvationarmy | `~/.local/bin/shopsalvationarmy` | `~/Dropbox/GitRepos/cli-tools/shopsalvationarmy/venv/bin/shopsalvationarmy` |
| testapi | `~/.local/bin/testapi` | `~/Dropbox/GitRepos/cli-tools/testapi/venv/bin/testapi` |
| paypal | `~/.local/bin/paypal` | `~/Dropbox/GitRepos/cli-tools/paypal/venv/bin/paypal` |

### Shell Completion Files

Tab completion is installed per-shell. Completion files reference the CLI via the alias/function.

| Shell | Completion Location | Env Variable Pattern |
|-------|---------------------|---------------------|
| zsh | `~/.zfunc/_toolname` | `_TOOLNAME_COMPLETE=complete_zsh` |
| bash | `~/.bash_completions/toolname.sh` | `_TOOLNAME_COMPLETE=complete_bash` |
| PowerShell | In profile via `Register-ArgumentCompleter` | `_TOOLNAME_COMPLETE=complete_powershell` |

**Note:** The environment variable name is derived from the CLI name: `_{NAME}_COMPLETE` where `{NAME}` is uppercase with hyphens replaced by underscores.

## Common Patterns

### Confirmation Prompts
```python
# Use --force / -F to skip confirmation
force: bool = typer.Option(False, "--force", "-F", help="Skip confirmation")

if not force and not typer.confirm("Are you sure?"):
    raise typer.Exit(0)
```

### Required Options
```python
email: str = typer.Option(..., "--email", "-e", help="Email address")
```

### Optional with Default
```python
limit: int = typer.Option(100, "--limit", "-l", help="Max results")
```

### Arguments
```python
item_id: str = typer.Argument(..., help="The item ID")
```
