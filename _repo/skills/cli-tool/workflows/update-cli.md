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

## Step 2: Navigate to CLI Directory

```bash
cd <cli-tools-root>/<name>
```

Verify the CLI structure:
```bash
ls -la <name>_cli/
ls -la <name>_cli/commands/
```

## Step 3: Implement Changes by Type

### Adding a New Command to Existing Resource

Edit `<name>_cli/commands/<resource>.py`:

```python
@app.command("new-command")
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

Create `<name>_cli/commands/newresource.py`:

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

2. Register in `<name>_cli/commands/__init__.py`:

```python
from . import auth, existingresource, newresource
```

3. Add to `<name>_cli/main.py`:

```python
from .commands import newresource
app.add_typer(newresource.app, name="newresource")
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

Edit `<name>_cli/client.py` and `<name>_cli/commands/auth.py`:

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

## Step 6.5: Final Code Simplification

Run `/debloat` one final time on all changes before committing.

Invoke the `debloat` skill on the CLI directory.

**If issues are found:**
1. Fix them
2. Re-run `test-cli-tool.sh` to confirm zero failures
3. Only proceed when both `/debloat` is clean and tests pass

## Step 6.6: Update CLI Tool Skill (if exists)

If commands or parameters were added, modified, or removed, check for a corresponding CLI tool skill:

```bash
ls <cli-tools-root>/_repo/skills/<name>-cli/usage.json 2>/dev/null
```

If the file exists, invoke the `create-cli-tool-skill` skill with "update" intent to re-discover commands and merge changes into `usage.json`:

```
/create-cli-tool-skill update <name>
```

This keeps the skill's command reference in sync with the actual CLI.

## Step 7: Commit Changes

```bash
cd <cli-tools-root>/<name>
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
