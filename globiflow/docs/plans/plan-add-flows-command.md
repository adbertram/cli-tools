# Implementation Plan: Add `flows` Command to Globiflow CLI

## One-Line Summary
Add `flows list` and `flows get` commands to list all flows across apps and retrieve detailed flow information.

## Why This Approach
This is the simplest approach that works - it follows existing patterns from `search.py` and `auth.py`, reuses the `BrowserService` for Playwright automation, and adds only two new methods to `client.py` plus one new command module.

## Discovery Summary

### Files Read
- `globiflow_cli/client.py` (257 lines) - Core client with browser automation
- `globiflow_cli/browser.py` (278 lines) - BrowserService with page access
- `globiflow_cli/commands/search.py` (178 lines) - Command patterns to follow
- `globiflow_cli/commands/auth.py` (185 lines) - Additional command patterns
- `globiflow_cli/output.py` (66 lines) - print_json, print_table helpers
- `globiflow_cli/main.py` (49 lines) - Command registration
- `globiflow_cli/config.py` (192 lines) - Configuration management

### Page Structure (via Playwright MCP)
- **URL**: `https://workflow-automation.podio.com/flows.php`
- **Tree navigation**: Level 1 (org), Level 2 (workspace), Level 3 (apps with flow counts)
- **Flow list**: Apps show flows when clicked; each flow is clickable
- **Flow details**: Shows name, ID, recipe steps, tabs (Recipe/Notes/Logs), time savings
- **Key selector**: `[role="treeitem"]` with `aria-level` attribute
- **Quick nav**: "g" key opens flow search dialog

### Integration Points
- `GlobiflowClient` in `client.py` wraps `BrowserService`
- Commands use `get_client()` singleton pattern
- Output via `print_json()` and `print_table()`
- Registration in `main.py` via `app.add_typer()`

---

## Implementation Steps

### Step 1: Add `list_flows()` method to client.py

**File**: `<cli-tools-root>/globiflow/globiflow_cli/client.py`
**Location**: After line 243 (before module-level singleton)

Add method that:
1. Navigates to `/flows.php`
2. Clicks "Expand All" link
3. Iterates tree items at level 3 (apps) matching pattern `(.+) \((\d+)\)`
4. For each app with flows, clicks and extracts flow names
5. Returns list of dicts with: name, app_name, workspace_name, org_name, enabled

### Step 2: Add `get_flow()` method to client.py

**File**: `<cli-tools-root>/globiflow/globiflow_cli/client.py`
**Location**: After `list_flows()` method

Add method that:
1. Navigates to `/flows.php`
2. Uses "g" keyboard shortcut to open flow search
3. Types flow ID and presses Enter
4. Parses flow details: name, ID, recipe steps, time savings, notes, has_logs
5. Returns dict with all flow details

### Step 3: Create commands/flows.py

**File**: `<cli-tools-root>/globiflow/globiflow_cli/commands/flows.py` (new)

Create with:
- `app = typer.Typer(help="Manage Globiflow flows")`

---

### CHECKPOINT: Verify Steps 1-3

**Run**: `globiflow flows --help`
**Expected**: Shows "list" and "get" subcommands
**If failing**: Check import/registration in main.py

---

### Step 4: Update main.py imports

**File**: `<cli-tools-root>/globiflow/globiflow_cli/main.py`
**Location**: Line 13

Change:
```python
from .commands import auth, search
```
To:
```python
from .commands import auth, search, flows
```

### Step 5: Register flows command in main.py

**File**: `<cli-tools-root>/globiflow/globiflow_cli/main.py`
**Location**: After line 15

Add:
```python
app.add_typer(flows.app, name="flows", help="Manage Globiflow flows")
```

### Step 6: Update commands/__init__.py

**File**: `<cli-tools-root>/globiflow/globiflow_cli/commands/__init__.py`

Change to:
```python
"""Command modules for Globiflow CLI."""
from . import auth, search, flows
```

---

### CHECKPOINT: Final Verification

**Run**:
```bash
globiflow auth status  # Verify logged in
globiflow flows list  # List all flows
globiflow flows get 4299675  # Get specific flow (use real ID)
```

**Expected**:
- `flows list` shows table of flows with name, app, workspace, org, enabled
- `flows get` shows flow details including recipe steps

---

## Testing Commands

```bash
# Ensure authenticated
globiflow auth login

# Test list
globiflow flows list
globiflow flows list
globiflow flows list --app "Content"

# Test get
globiflow flows get <flow_id>
globiflow flows get <flow_id>
```

## What's NOT Included (Intentionally)

- Enable/disable flow functionality (user confirmed read-only for now)
- Flow creation/editing
- Bulk operations
- Caching of flow data
- Parallel extraction (simpler to extract sequentially)

## Files Changed

| File | Action |
|------|--------|
| `globiflow_cli/client.py` | Add `list_flows()` and `get_flow()` methods |
| `globiflow_cli/commands/flows.py` | Create new file with `list` and `get` commands |
| `globiflow_cli/main.py` | Import and register flows command |
| `globiflow_cli/commands/__init__.py` | Add flows to imports |
