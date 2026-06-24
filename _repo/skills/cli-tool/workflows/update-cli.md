<required_reading>
Before modifying, understand the standards:
- `references/output-standards.md` - Output streams, format rules, list command requirements
- `references/secrets.md` - CLI-tools secret manager rules
- `references/auth-standards.md` - Authentication standards by credential type
- `references/command-standards.md` - Command naming, options, exit codes
- `references/templates.md` - Template structure and patterns
- `references/filtering.md` - Filtering requirements for list commands
</required_reading>

<root_cause_principle>
## Root Cause Principle

**CRITICAL: Before modifying CLI code, trace the dependency chain.**

CLI tools have deep dependency chains. When investigating an issue:

1. **Read the relevant source files first** - Commands, modules, utilities, filters, etc.
2. **Trace the full call path** - CLI command -> module -> utility function -> external API
3. **Identify where the issue originates** - Is the problem in:
   - A specific command file?
   - A shared utility module (e.g., filters.py, output.py)?
   - The API client?
   - External service behavior?
4. **Fix at the source** - If a utility module has a bug, fix the module. Don't work around it in command code.
5. **Prefer deterministic solutions** - Fix the actual bug rather than adding conditional logic to handle broken behavior.
</root_cause_principle>

<process>
## Step 1: Identify the Modification

Ask the user (if not clear):
1. Which CLI tool needs updating?
2. What change is needed?
   - Add new command/resource
   - Modify existing command
   - Add/change authentication
   - Fix output formatting
   - Update API endpoints

## Step 1.5: Implementation Planning

For non-trivial changes, run `/create-plan` before implementation so the change is grounded in the existing CLI structure and conventions.

```
/create-plan <cli-name> <modification-description>
```

The plan MUST document:

### Current State Analysis
- Existing code structure and patterns
- Files that will be modified
- Existing models and client methods

### Proposed Changes
- New models needed (if any)
- New client methods with signatures
- New command structure
- UI/output format decisions

### Integration Points
- How new code connects to existing code
- Dependencies between components
- Potential breaking changes

Understanding existing patterns before modifying prevents introducing inconsistencies. The plan ensures changes align with established conventions.

## Step 1.6: Browser Automation Approval Gate

When an added or changed command needs a web action that is not already covered
by the CLI's current API client, investigate in this order before writing code:

1. Public API or official SDK support for the exact action
2. Internal XHR/JSON API support in the authenticated web app
3. Browser automation only if neither API path is usable

If no public or internal API path is available and the command must use browser
automation, stop before adding browser code, browser credentials, or selectors
and ask Adam:

```
No usable public or internal API path is available for this action. Should I make this command browser-driven?
```

Continue only after explicit approval, then document the approval in the
implementation notes and validate browser selectors against real DOM captures.

## Step 1.7: Patch Against Current File Anchors

Before using `apply_patch` in this workflow, reread the exact target file and
copy anchors from the current on-disk lines. Do not build a hunk from a sentence
in the plan, prior diff, test failure, or expected converted text unless that
exact line currently exists. If the target text is embedded in a longer
paragraph, anchor on the whole current line or an existing verified heading and
insert relative to that.

## Step 2: Resolve and Navigate to CLI Source Directory

Before any source inspection command, prove the target CLI source directory.
Do not assume `<cli-tools-root>/<name>` exists, and do not pass that guessed
path to `cd`, `ls`, `find`, `rg`, `sed`, `cat`, `nl`, `wc`, `head`, `tail`, or
similar commands.

Use `<cli-tools-root>/_repo/scripts/find-cli-tools.sh` to enumerate available
CLI tools, match the exact `name` from its JSON output, and derive the source
directory from the matching record's `readme` parent. Then prove that directory
exists and contains `pyproject.toml` before navigating. If there is no exact
record, report `CLI_SOURCE_NOT_FOUND: <name>` and stop or ask which discovered
CLI name to update.

Only after the source directory is proven:

```bash
cd "$tool_dir"
```

Verify the CLI structure:
```bash
find . -maxdepth 1 -type d -name '*_cli' -print
find . -maxdepth 2 -type f | sort
```

When reading existing tests, discover the real test files first and pass only
those discovered paths to `sed`, `cat`, `nl`, or similar readers. Do not infer
conventional filenames such as `tests/test_commands.py`; if discovery returns
multiple candidates, inspect the candidate list or narrow it with `rg --files`
against the proven `tests` directory before reading a file.

If a test or cleanup step requires flattening a single
`<name>_cli/commands/<group>.py` package into `<name>_cli/commands.py`, move the
real module first, update imports, and delete `<name>_cli/commands/__init__.py`.
Before `rmdir <name>_cli/commands`, remove only generated cache directories:

```bash
find <name>_cli/commands -type d -name __pycache__ -prune -exec rm -rf {} +
rmdir <name>_cli/commands
```

Keep `rmdir` as the final deletion check. If it still fails, inspect and handle
the remaining real files instead of recursively deleting the package directory.

## Step 3: Implement Changes by Type

### Adding a New Command to Existing Resource

Edit `<name>_cli/main.py` for the scaffold-default layout, or
`<name>_cli/commands/<resource>.py` if this CLI is already split:

```python
@items_app.command("new-command")
def new_command(
    # Required parameters
    id: str = typer.Argument(..., help="Resource ID"),
    # Optional parameters with flags
    table: bool = typer.Option(False, "--table", "-t", help="Table output"),
):
    """Brief description of what this command does."""
    client = get_client()
    result = client.new_method(id)

    if table:
        print_table(result, columns=["id", "name"], headers=["ID", "Name"])
    else:
        print_json(result)
```

### Adding a New Resource (Command Group)

**Step 1: Define the Command Output Shape**

Start from the external command contract:
- command group and subcommand names
- required options (`--table`, `--filter`, `--limit`, `--properties`)
- exact JSON fields returned by list/get commands
- table columns and headers

Use plain dict records when they preserve that contract directly. Add local
models only when they remove real validation or serialization complexity.

```python
def normalize_new_resource(raw: dict) -> dict:
    return {
        "id": raw["id"],
        "name": raw["name"],
        "status": raw["status"],
    }
```

**Step 2: Create Command File**

For the scaffold-default layout, add the new command group in
`<name>_cli/main.py`. Only create `<name>_cli/commands/newresource.py` when the
CLI already uses split command modules or the extra group clearly justifies the
split:

```python
import typer
from typing import Optional, List
from ..client import get_client
from ..output import print_json, print_table, print_error, print_success

app = typer.Typer(help="Manage new resources")


@app.command("list")
def list_resources(
    table: bool = typer.Option(False, "--table", "-t", help="Table output"),
    limit: int = typer.Option(100, "--limit", "-l", help="Max results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value"),
):
    """List new resources."""
    client = get_client()
    results = client.list_new_resources(limit=limit, filters=filter)

    if table:
        print_table(results, columns=["id", "name"], headers=["ID", "Name"])
    else:
        print_json(results)


@app.command("get")
def get_resource(
    id: str = typer.Argument(..., help="Resource ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Table output"),
):
    """Get a specific resource."""
    client = get_client()
    result = client.get_new_resource(id)

    if table:
        print_table([result], columns=["id", "name"], headers=["ID", "Name"])
    else:
        print_json(result)
```

2. Mount the subcommand app in `<name>_cli/main.py`. If the command module
declares `COMMAND_CREDENTIALS`, use `register_commands()` so credential checks
and the shared `--profile` option are installed:

```python
from cli_tools_shared.command_registry import register_commands

register_commands(app, get_config, newresource, name="newresource", help="Manage new resources")
```

3. If you created `commands/newresource.py`, import it in `main.py` before the
mount:

```python
from .commands import newresource
```

4. Implement client methods in `<name>_cli/client.py`:

```python
def list_new_resources(self, limit: int = 100, filters: Optional[List[str]] = None) -> list[dict]:
    """List new resources with optional filtering."""
    params = {"limit": limit}

    # Server-side filtering if API supports it
    if filters:
        validate_filters(filters)
        api_params = self._filter_map.to_api_params(filters)
        params.update(api_params)

    response = self._make_request("GET", "/newresources", params=params)
    raw_items = response.get("items", response)
    return [normalize_new_resource(item) for item in raw_items]

def get_new_resource(self, id: str) -> dict:
    """Get a specific new resource."""
    response = self._make_request("GET", f"/newresources/{id}")
    return normalize_new_resource_detail(response)
```

### Modifying Authentication

Edit `<name>_cli/client.py` and the auth mount in `<name>_cli/main.py` (or
`<name>_cli/commands/auth.py` only if this CLI already uses split auth
modules):

1. Update auth methods in client:
```python
def auth_login(self, **kwargs):
    """Implement new auth flow."""
    # OAuth, API key, etc.
    pass

def auth_status(self) -> Dict:
    """Check authentication status."""
    # Return {"authenticated": bool, "user": str, ...}
    pass
```

2. Update auth commands:
```python
@app.command("login")
def login():
    """Authenticate with the service."""
    client = get_client()
    client.auth_login()
    print_success("Successfully authenticated")
```

3. Update `.env.example` and `config.py` with new variable names. Do not put real secrets in repo files. Reusable CLI credentials are governed by `references/secrets.md` and must not be stored in any `.env` file by an agent or human.

### Adding Multiple Credential Types

If a CLI needs both API and browser credentials (e.g., API for data + browser for actions):

1. Update `config.py` to use `CREDENTIAL_TYPES` list:
```python
class Config(BaseConfig):
    CREDENTIAL_TYPES = [CredentialType.API_KEY, CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://api.example.com"
```

2. `auth status` reports per-type results under `profiles[].credential_types`; command code must check the credential type it actually needs.

3. `auth login` prompts for all required fields across all types (shared fields like `USERNAME` are prompted once).

4. See `references/auth-standards.md` "Multiple Credential Types" section for full details.

### Updating API Endpoints

Edit `<name>_cli/client.py`:

```python
# Update endpoint paths
def list_items(self, ...):
    # Old: "/items"
    # New: "/v2/items"
    return self._make_request("GET", "/v2/items", params=params)
```

## Step 3.5: Code Simplification Pass (Post-Implementation)

After implementing changes, run `/debloat` to review all modified code for reuse, quality, and efficiency issues.

Invoke the `debloat` skill on the CLI directory.

**If `/debloat` identifies issues, fix them before proceeding.**

## Step 4: Reinstall the CLI

After changes, use the install script:

```bash
<cli-tools-root>/_repo/skills/cli-tool/scripts/install-cli-tool.sh <name>
```

The script returns JSON with `success`, `install_output`, and `help_works`. Verify `"success": true` before proceeding.

## Step 4.5: Wrapper Upstream CLI Provisioning Gate

For wrapper CLIs, read the configured `CLI_COMMAND` from the wrapper's runtime
config or `.env.example`, then verify the official upstream binary is installed
and executable before reporting the update complete:

```bash
command -v <cli-command>
<cli-command> --help
```

If the official upstream binary is missing, install or bootstrap it through the
wrapper source or repo-owned install path before continuing. For upstream CLIs
distributed outside Homebrew, use the official package manager or vendor
installer for that CLI instead of leaving the binary as a manual prerequisite.

Missing `CLI_COMMAND` is an implementation blocker, not a live API smoke-test or
API-key-auth blocker. API-key auth may remain user-configured only after the
official upstream binary is present and executable.

## Step 5: Test Changes

Test the specific changes:
```bash
# Test new command
<name> <resource> new-command --help
<name> <resource> new-command <args>

# Test new resource
<name> newresource list --table
<name> newresource get <id>
```

## Step 6: Run Full Test Suite (MANDATORY - ZERO FAILURES ALLOWED)

```bash
<cli-tools-root>/_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name <name>
```

The script returns JSON with `success`, `summary`, `failures[]`, and `auth_required`.

**⛔ ABSOLUTE REQUIREMENT: ALL test failures MUST be fixed before proceeding.**

- Zero tolerance for test failures
- Fix every failure in the JSON output
- Re-run until `"success": true`
- Warnings are acceptable; failures are not
- NEVER dismiss failures as "pre-existing", "auth-required", or "environment-related" without PROVING it by showing the same test passed before your changes
- If `"success": false`, you are NOT done. Investigate every failure -- even if you believe the cause is external.
- For auth-required CLIs without real credentials, follow `workflows/test-cli.md` live-auth blocker handling. Static/source work can be complete, but live compliance remains `LIVE_AUTH_BLOCKED` until real credentials authenticate.

## Step 6.5: Final Code Simplification

Run `/debloat` one final time on all changes before committing.

Invoke the `debloat` skill on the CLI directory.

**If issues are found:**
1. Fix them
2. Re-run `test-cli-tool.sh` to confirm zero failures
3. Only proceed when both `/debloat` is clean and tests pass

## Step 6.6: Refresh CLI Tool Skill Usage (if exists)

If commands or parameters were added, modified, or removed, check for a corresponding CLI tool skill:

```bash
test -f <cli-tools-root>/_repo/skills/<name>-cli/usage.json
```

If the file exists, refresh its command map with the repo-owned generator:

```bash
<cli-tools-root>/_repo/skills/cli-tool/scripts/regenerate-usage-json <name>
```

Do not import `cli_test_utils` from ad-hoc Python snippets. The generator owns
the test-helper import path and keeps the skill-folder `usage.json` in sync with
the installed CLI help.

## Step 7: Commit Changes

```bash
cd "$tool_dir"
git add -A
git commit -m "Add <description of changes>"
git push
```

## Step 8: Deploy to n8n Server (if applicable)

If the change involves new/modified commands, auth changes, or new resource groups, ask the user:

**Question:** "Should I deploy the updated CLI to the n8n server?"
**Options:**
- "Yes, deploy" - Invoke the n8n deployment workflow for `<name>`
- "No, skip" - Continue to summary

Internal fixes (parser logic, bug fixes, output formatting) typically don't need redeployment.

## Step 9: n8n Node Update (Optional)

Only ask if Step 8 deployed to n8n:

**Question:** "Would you like to rebuild and redeploy the n8n node for this CLI?"
**Options:**
- "Yes, rebuild n8n node" - Invoke `/n8n` skill to rebuild and redeploy
- "No, skip n8n node" - Continue to summary

If user selects yes, invoke the n8n skill:
```
/n8n build <name> --deploy
```

## Step 10: Work Summary (MANDATORY)

After completing the update, provide:
- Changes implemented
- Manual testing results
- Any issues encountered during implementation or testing
- If no issues: "No issues encountered"
- n8n deployment status
- Whether n8n node was rebuilt (if applicable)
- Whether full test validation is recommended

**Do NOT output the full updated CLI source code.** Focus on what changed and testing results only.
</process>

<success_criteria>
Update is complete when:
- [ ] `/create-plan` executed for non-trivial changes
- [ ] Changes implemented following standards
- [ ] New or modified command output shape is covered by tests
- [ ] Internal representation is minimal: no unused helpers, models, or dependencies
- [ ] Browser parsers validated against real DOM captures via BrowserAutomation (if adding/modifying browser parsers)
- [ ] `/debloat` post-implementation pass completed (Step 3.5)
- [ ] CLI reinstalled successfully (via install-cli-tool.sh)
- [ ] New/modified commands work as expected
- [ ] List commands have --table, --filter, --limit, --properties options
- [ ] Get commands have --table option
- [ ] **⛔ test-cli-tool.sh passes with ZERO FAILURES** (warnings acceptable)
- [ ] `/debloat` final pass completed (Step 6.5) — tests still pass after fixes
- [ ] Changes committed to git
- [ ] User asked about n8n deployment (if applicable — new/modified commands or auth changes)
- [ ] n8n node rebuild offered (if deployed)
- [ ] Work summary provided

**⛔ BLOCKING: Do NOT mark update as complete if test-cli-tool.sh shows ANY failures.**
</success_criteria>
