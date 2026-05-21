# Plan: Add `globiflow flows <id> logs` Command

## One-line Summary
Add a command to retrieve and display all execution logs for a specific flow.

## Why This Approach
This is the simplest approach because:
- Adds a single subcommand to the existing `flows` command group
- Reuses existing patterns (client method → command → output)
- Adds only one new model (FlowLog) to existing flow.py
- Leverages existing browser automation patterns in client.py
- No filtering or pagination complexity (load all logs at once)

## Discovery Summary

### Files Read
| File | Purpose | Key Patterns |
|------|---------|--------------|
| `commands/flows.py` | Existing flow commands | L13-62: list_flows pattern, L64-106: get_flow pattern |
| `client.py` | Browser automation | L580-654: _extract_flow_details, L638-640: logs tab detection |
| `models/flow.py` | Flow models | CLIModel base class, FlowDetail structure |
| `output.py` | Output helpers | print_json, print_table patterns |

### Integration Points
- `commands/flows.py:8` - Typer app for flows commands
- `client.py:510` - get_flow method (navigates to flow, can reuse pattern)
- `models/flow.py` - Add FlowLog model here (same file as Flow)
- `models/__init__.py` - Export FlowLog

### Existing Patterns to Follow
1. **Command pattern** (from flows.py:64-106):
   ```python
   @app.command("logs")
   def list_logs(
       flow_id: str = typer.Argument(..., help="Flow ID"),
   ):
   ```

2. **Client method pattern** (from client.py:510-578):
   - Navigate to flow page
   - Click Logs tab
   - Extract data from table/list

3. **Model pattern** (from models/flow.py):
   - Extend CLIModel
   - Required fields have no default
   - Optional fields use `Optional[Type] = None`

## Implementation Steps

### Step 1: Add FlowLog model to models/flow.py
**File:** `globiflow_cli/models/flow.py`
**Action:** Add FlowLog class after FlowDetail

```python
class FlowLog(CLIModel):
    """A single flow execution log entry."""
    timestamp: str
    item_id: Optional[str] = None
    item_title: Optional[str] = None
    status: str  # "Success", "Failed", etc.
    duration: Optional[str] = None
    message: Optional[str] = None
```

### Step 2: Export FlowLog from models/__init__.py
**File:** `globiflow_cli/models/__init__.py`
**Action:** Add FlowLog to imports and __all__

Line 15: Add `FlowLog` to import from flow
Line 88-89: Add `"FlowLog"` to __all__ after `"FlowDetail"`

### Step 3: Add list_flow_logs method to client.py
**File:** `globiflow_cli/client.py`
**Action:** Add method after get_flow (around line 578)

Pattern: Reuse get_flow's navigation logic, then click Logs tab and extract table

```python
def list_flow_logs(self, flow_id: str) -> List[FlowLog]:
    """Get all execution logs for a flow.

    Args:
        flow_id: The flow ID

    Returns:
        List of FlowLog entries
    """
    # Navigate to flow (reuse get_flow pattern)
    # Click Logs tab
    # Extract log entries from table
    # Return list of FlowLog models
```

### Step 4: Add logs command to commands/flows.py
**File:** `globiflow_cli/commands/flows.py`
**Action:** Add command after get_flow (around line 107)

```python
@app.command("logs")
def list_logs(
    flow_id: str = typer.Argument(..., help="Flow ID to get logs for"),
):
    """
    List execution logs for a flow.

    Example:
        globiflow flows logs 4299675
    """
```

──────────────────────────
🧪 CHECKPOINT: Verify all 4 steps
   - Run: `globiflow flows logs --help`
   - Expected: Displays log entries in table format
   - If failing: Check browser navigation and log extraction selectors
──────────────────────────

### Step 5: Reinstall and test
**Action:** Reinstall CLI and run test-cli-tool

```bash
cd <cli-tools-root>/globiflow
source venv/bin/activate
pip install -e .
<cli-tools-root>/_repo/skills/cli-tool/scripts/test-cli-tool.sh globiflow
```

## Testing Strategy
- Verify `globiflow flows logs --help` shows correct options
- Test JSON output: `globiflow flows logs <id> | jq '.'`
- Test with flow that has no logs (should show empty list or message)

## What's NOT Included
- ❌ Date range filtering (--from, --to) - user said not needed
- ❌ Status filtering (--status) - user said not needed
- ❌ Pagination/limit - loading all logs at once
- ❌ Log detail view - just the list for now

## Todo List

1. Add FlowLog model to models/flow.py
2. Export FlowLog from models/__init__.py
3. Add list_flow_logs method to client.py
4. Add logs command to commands/flows.py
5. Run checkpoint test (help and table output)
6. Reinstall CLI and run test-cli-tool.sh
7. Commit changes
