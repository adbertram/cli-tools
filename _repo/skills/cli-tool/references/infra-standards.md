# Infrastructure Standards

## AI Review Checklist

**These items require manual AI verification because they cannot be tested deterministically by the test script.**

The test script outputs these as `[AI REVIEW REQUIRED]` items. When running `/test-cli-tool`, create a todo for each item and verify by reading the source code.

### For All API CLIs:

| Check | What to Verify |
|-------|----------------|
| `--limit` is API-level | Limit is passed to API, not just truncating client-side results |
| `--filter` is API-level | Filters are sent to API, not filtering after fetching all data |
| `--filter` syntax is standard | Uses `field:op:value` format (e.g., `status:eq:active`, `price:gte:100`) per filtering.md |
| Exponential retry implemented | API calls use exponential backoff with jitter for transient errors |

### Verification Approach:

1. **--limit**: Check client.py for `limit` parameter being passed to API request
2. **--filter**: Check if filters are translated to API params vs applied after fetch
3. **--filter syntax**: Check command help text and filter parsing in client/commands
4. **Retry logic**: Look for retry loops with `delay * 2^attempt` and random jitter

---

## Warning Suppression

All CLI tools **must** suppress known benign warnings to keep output clean. Add this to `__init__.py` (loads first):

```python
# In __init__.py - must be before any other imports
import warnings
warnings.filterwarnings("ignore", module="urllib3")
```

This suppresses the LibreSSL compatibility warning from urllib3 on macOS systems. The filter must be set before urllib3 is imported by any dependency.

---

## Activity Logging Standards

All CLI tools **must** use the centralized activity logger from `cli_tools_shared` to track operational activity. This provides an always-on file-based log for debugging and auditing, without interfering with stdout/stderr stream separation.

### Why

- Debug logging (`DEBUG=1` to stderr) is opt-in and ephemeral — activity logging is always on and persistent
- A single shared log file makes it easy to trace cross-tool workflows (e.g. `geeklife` calling `shippo`)
- File-based logging with rotation prevents unbounded disk usage

### Requirements

1. **Initialize in client.py** at module level:
   ```python
   from cli_tools_shared.activity_log import get_activity_logger

   activity = get_activity_logger("toolname")
   ```

2. **Import in command files** that perform significant operations:
   ```python
   from ..client import activity
   # or initialize directly:
   from cli_tools_shared.activity_log import get_activity_logger
   activity = get_activity_logger("toolname")
   ```

3. **What to log:**
   - Commands executed (e.g. `activity.info("Listing orders with status=%s", status)`)
   - API requests: method, endpoint, response status code
   - Errors and retries
   - State changes (order status updates, inventory changes)
   - Auth flow steps (login initiated, token refreshed)

4. **What NOT to log:**
   - Credentials, tokens, API keys, or secrets
   - Full request/response bodies that may contain PII
   - Routine data that would flood the log (e.g. every item in a bulk list response)

### Per CLI Type

| CLI Type | What to Log |
|----------|-------------|
| **API CLIs** (bricklink, brickowl, shippo, ebay, fedex, brickbuddy) | Request method + endpoint, response status code, errors, retries |
| **Browser CLIs** (brickfreedom, paypal, royalmailers) | Page navigation URLs, auth flow steps, parsing results |
| **Wrapper CLIs** (geeklife) | Delegated commands, exit codes, subprocess errors |

### Log File Location

All loggers write to the same shared file:
```
~/Library/Application Support/cli-tools/cli_tool_activity.txt
```

Rotation: 5 MB max, 3 backups (20 MB total cap). The `[toolname]` tag in each line identifies which CLI produced it.

### Example

```python
# In client.py
from cli_tools_shared.activity_log import get_activity_logger

activity = get_activity_logger("bricklink")

class BricklinkClient:
    def get_orders(self, status=None):
        activity.info("Fetching orders with status=%s", status)
        response = self._request("GET", "/orders", params={"status": status})
        activity.info("GET /orders -> %s (%d results)", response.status_code, len(response.json()))
        return response.json()
```

```
2026-03-02 14:23:05 [bricklink] INFO: Fetching orders with status=PAID
2026-03-02 14:23:06 [bricklink] INFO: GET /orders -> 200 (5 results)
```

---

## Repository Standards

**MANDATORY**: `<cli-tools-root>` is the only Git repository for CLI tools. Individual tool folders must not contain nested `.git` directories and must not have their own GitHub repositories.

| Requirement | Description |
|-------------|-------------|
| **Parent Git repo required** | The `cli-tools` parent directory is initialized as one Git repository |
| **No nested repos** | Individual CLI tool directories must not contain `.git` directories or `.git` files |
| **Single parent GitHub repo** | The parent repo remote is the shared `cli-tools` repository |

**Naming Convention:**
- Local tool directory: `toolname/` (lowercase)
- Parent GitHub repo: the shared `cli-tools` repository

**Setup Commands:**
```bash
cd <cli-tools-root>
git status --short --branch
```

---

## Documentation Standards

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

---

## Global Access / Symlinks

All CLI tools are accessible globally from any directory. Each tool runs from its own virtual environment but is invoked via symlinks in `~/.local/bin`.

**MANDATORY**: Every CLI tool **must** have a symlink in `~/.local/bin`.

### Why Symlinks (Not Aliases)

Symlinks work in **all shell contexts**, including:
- Interactive shells (Terminal, iTerm)
- Non-interactive shells (Cursor IDE agent, scripts, CI/CD)
- Subprocess calls from Python/Node/etc.

Aliases only work in interactive shells and fail in automation contexts.

### Setup via uv

CLI tools are installed via `uv tool install`, which automatically creates the symlink:

```bash
# Install a CLI tool (creates venv + symlink automatically)
uv tool install -e <cli-tools-root>/toolname --force --refresh

# Or use the install script
<cli-tools-root>/_repo/skills/cli-tool/scripts/install-cli-tool.sh toolname

# Verify it works
which toolname  # Should show ~/.local/bin/toolname
toolname --version
```

### How It Works

`uv tool install -e <path>` does three things:
1. Creates an isolated venv at `~/.local/share/uv/tools/<package-name>`
2. Installs the package in editable mode (source changes take effect immediately)
3. Creates a symlink at `~/.local/bin/<cli-name>` pointing to the venv's entry point

---

## Shell Completion Files

Tab completion is installed per-shell. Completion files reference the CLI via the alias/function.

| Shell | Completion Location | Env Variable Pattern |
|-------|---------------------|---------------------|
| zsh | `~/.zfunc/_toolname` | `_TOOLNAME_COMPLETE=complete_zsh` |
| bash | `~/.bash_completions/toolname.sh` | `_TOOLNAME_COMPLETE=complete_bash` |
| PowerShell | In profile via `Register-ArgumentCompleter` | `_TOOLNAME_COMPLETE=complete_powershell` |

**Note:** The environment variable name is derived from the CLI name: `_{NAME}_COMPLETE` where `{NAME}` is uppercase with hyphens replaced by underscores.

---

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
