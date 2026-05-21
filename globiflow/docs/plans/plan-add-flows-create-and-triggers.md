# Plan: Add `flows create` and `triggers list` Commands

## One-line Summary
Add `globiflow triggers list` to show available trigger types and `globiflow flows create` to create new flows with optional steps.

## Why This Approach
This is the simplest approach because:
1. Reuses existing browser automation patterns from `client.py`
2. Follows the established command structure in `commands/flows.py`
3. Uses existing Pydantic models pattern for Trigger type
4. Leverages discovered Globiflow URL patterns for flow creation

## Discovery Summary

### Browser Automation Findings
From Playwright exploration of Globiflow UI:

**Trigger Types and Codes:**
| Code | Name | Description |
|------|------|-------------|
| T | Every Day | Scheduled daily trigger |
| C | When a new Item is Created | Item creation trigger |
| U | When an Item is Updated | Item update trigger |
| Q | When a Comment is Added | Comment trigger |
| M | Manually by Another Flow | Manual/flow-triggered |
| K | When a Task is Completed | Task completion trigger |
| F | By an Item's Date Field | Date field trigger |
| R | When an Email Reply is Received | Email reply trigger |
| S | When an SMS Text Reply is Received | SMS reply trigger |
| X | When a File is signed in RightSignature | RightSignature trigger |
| L | When a special link is clicked | External link trigger |
| W | By an External Webhook Event | Webhook trigger |
| FU | When a new file is uploaded in an item | File upload trigger |

**URL Patterns:**
- Create new flow: `/configureflow.php?i={app_id}&t={trigger_code}`
- After save redirects to: `/flows.php?node={flow_id}`
- Edit flow: `/configureflow.php?id={flow_id}`

**Flow Creation Form Elements:**
- Flow Name: textbox `#flowName`
- Description: textbox (after Flow Name)
- Enabled: checkbox in div `#enabled`
- Trigger: combobox (pre-selected based on URL `t` param)
- Actions: List with "+" button to add steps

**Step Addition Process:**
1. Click "+" button in Actions section (ref for actions list `#actions`)
2. Select action type from dropdown
3. Fill in action-specific fields
4. Click Save

### Files Read
- `globiflow_cli/commands/flows.py` (lines 1-403): Existing flow commands pattern
- `globiflow_cli/client.py` (lines 1-1479): Client methods including `delete_flow`, `list_flows`, `update_flow_step`
- `globiflow_cli/models/flow.py` (lines 1-49): Flow and FlowDetail models
- `globiflow_cli/models/step.py` (lines 1-516): Step models and factory

### Integration Points
- New `Trigger` model in `models/flow.py`
- New `list_triggers()` method in `client.py`
- New `create_flow()` method in `client.py`
- New `triggers.py` commands file
- Update `flows.py` with `create` command
- Update `main.py` to register triggers command group

## The Plan

### Step 1: Add Trigger Model
**File:** `globiflow_cli/models/flow.py`
**Action:** Add `TriggerType` enum and `Trigger` model

```python
class TriggerType(str, Enum):
    """Available flow trigger types."""
    EVERY_DAY = "T"
    ITEM_CREATED = "C"
    ITEM_UPDATED = "U"
    COMMENT_ADDED = "Q"
    MANUAL = "M"
    TASK_COMPLETED = "K"
    DATE_FIELD = "F"
    EMAIL_REPLY = "R"
    SMS_REPLY = "S"
    RIGHTSIGNATURE = "X"
    EXTERNAL_LINK = "L"
    WEBHOOK = "W"
    FILE_UPLOAD = "FU"

class Trigger(CLIModel):
    """A Globiflow trigger type."""
    code: str
    name: str
    description: str
```

### Step 2: Add `list_triggers()` Method to Client
**File:** `globiflow_cli/client.py`
**Action:** Add method that returns static list of trigger types

The triggers are global/static (not app-specific), so this can return a hardcoded list based on UI discovery.

### Step 3: Create Triggers Command File
**File:** `globiflow_cli/commands/triggers.py` (new file)
**Action:** Create command group with `list` subcommand

```
globiflow triggers list
```

### Step 4: Register Triggers Command in Main
**File:** `globiflow_cli/main.py`
**Action:** Import and add triggers app to main app

### Step 5: Add `create_flow()` Method to Client
**File:** `globiflow_cli/client.py`
**Action:** Add browser automation method to create flows

Process:
1. Navigate to `/configureflow.php?i={app_id}&t={trigger_code}`
2. Fill flow name in `#flowName`
3. Optionally fill description
4. Optionally uncheck enabled if `--disabled` flag
5. Add steps if provided (iterate, click "+", select type, fill fields)
6. Click Save link
7. Extract flow_id from redirect URL
8. Return FlowDetail

### Step 6: Add `create` Command to Flows
**File:** `globiflow_cli/commands/flows.py`
**Action:** Add create subcommand

```
globiflow flows create --app-id APP_ID --trigger TRIGGER_CODE --name "Flow Name" [--steps JSON|@file] [--enabled/--disabled]
```

Parameters:
- `--app-id` (required): Podio app ID
- `--trigger` (required): Trigger code (C, U, M, etc.)
- `--name` (required): Flow name
- `--description` (optional): Flow description
- `--steps` (optional): JSON array of steps or @filepath
- `--enabled/--disabled` (optional, default enabled)

### Step 7: Update models/__init__.py
**File:** `globiflow_cli/models/__init__.py`
**Action:** Export new Trigger and TriggerType

---

## Test Checkpoints

### Checkpoint 1: After Steps 1-4
```bash
globiflow triggers list
```
Expected: Table showing all 13 trigger types with code, name, description

### Checkpoint 2: After Steps 5-7
**Verify:** `globiflow flows create` works
```bash
# Create simple flow without steps
globiflow flows create --app-id 30560419 --trigger C --name "Test CLI Create"

# Verify it exists
globiflow flows list --app "Topics"

# Delete test flow
globiflow flows delete <NEW_FLOW_ID> --force
```

---

## The Todo List

1. Add TriggerType enum and Trigger model to models/flow.py
2. Add list_triggers() method to client.py
3. Create commands/triggers.py with list command
4. Register triggers command group in main.py
5. Test triggers list command
6. Add create_flow() method to client.py
7. Add create command to commands/flows.py
8. Update models/__init__.py exports
9. Test flows create command (with and without steps)

---

## Complexity Avoided

- **No app-specific trigger lookups**: Triggers are global, using static list
- **No complex step validation during creation**: Steps use same format as existing models
- **No API integration**: Reusing browser automation pattern
- **No new dependencies**: Using existing typer, pydantic, playwright
