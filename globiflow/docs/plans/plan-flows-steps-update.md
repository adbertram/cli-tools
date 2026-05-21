# Implementation Plan: `globiflow flows steps update` Command

## One-Line Summary
Add a `flows steps update` command that auto-detects step type, validates fields, and updates step parameters via browser automation.

## Why This Approach
This is the simplest approach - it extends existing patterns in `flows.py`, reuses the `get_flow_step()` navigation logic, and leverages Pydantic models for field validation. No new abstractions needed.

## Discovery Summary

### Files Read
- `globiflow_cli/commands/flows.py` - Existing flow/step commands pattern
- `globiflow_cli/client.py` - Browser automation with `get_flow_step()`, `_extract_step_parameters()`, `_normalize_parameters()`
- `globiflow_cli/models/step.py` - Step models with `_STEP_TYPE_MAPPINGS` and field definitions
- `globiflow_cli/step_schema.json` - Parameter types and UI element mappings

### UI Exploration (via Playwright)
- **URL**: `/configureflow.php?id={flow_id}`
- Steps are inline-editable with textboxes/dropdowns
- Variable Calc: `input[placeholder='Variable Name']`, textarea for expression
- HTTP Call: Variable Name, Method dropdown, URL textbox, POST Params, Headers (expandable), Follow Redirects checkbox
- "Save" link persists all changes

---

## Implementation Steps

### Step 1: Add `FIELD_SELECTORS` constant to client.py

**File**: `<cli-tools-root>/globiflow/globiflow_cli/client.py`
**Location**: After imports, before `ClientError` class

```python
# Field name to UI selector mapping for step updates
FIELD_SELECTORS = {
    # Variable/Calc fields
    "variable_name": ["input[placeholder='Variable Name']", "input[name*='varname']"],
    "code": ["textarea[name*='gmvalue']", "textarea[name*='expression']"],

    # HTTP Call fields
    "url": ["input[name*='gmurl']", "input[name*='url']"],
    "method": ["select[name*='method']"],
    "headers": ["textarea[name*='gmheaders']", "textarea[name*='headers']"],
    "get_params": ["textarea[name*='gmget']", "textarea[name*='getparams']"],
    "post_params": ["textarea[name*='gmpost']", "textarea[name*='postparams']"],
    "follow_redirect": ["input[type='checkbox'][name*='redirect']"],

    # Email fields
    "to": ["input[name*='to']", "textarea[name*='to']"],
    "subject": ["input[name*='subject']"],
    "body": ["textarea[name*='body']"],
    "from_name": ["input[name*='from']"],
    "reply_to": ["input[name*='replyto']"],
    "cc": ["input[name*='cc']"],
    "bcc": ["input[name*='bcc']"],

    # Comment fields
    "comment_body": ["textarea[name*='comment']"],
    "silent": ["input[type='checkbox'][name*='silent']"],

    # SMS/Message fields
    "message": ["textarea[name*='message']"],

    # Task fields
    "assignee": ["input[name*='assignee']"],
    "task_text": ["textarea[name*='task']"],
    "due_date": ["input[name*='duedate']", "input[name*='due']"],

    # PDF/File fields
    "filename": ["input[name*='filename']"],
    "template": ["textarea[name*='template']"],
}
```

### Step 2: Add `_get_field_selector()` method to GlobiflowClient

**File**: `<cli-tools-root>/globiflow/globiflow_cli/client.py`
**Location**: After `_normalize_parameters()` method

```python
def _get_field_selector(self, action_div: "Locator", field_name: str) -> "Locator":
    """Get the UI element selector for a model field name.

    Args:
        action_div: The step's main content locator
        field_name: Model field name (e.g., 'variable_name', 'code', 'url')

    Returns:
        Playwright Locator for the field's input element

    Raises:
        ClientError: If field selector not found
    """
    selectors = FIELD_SELECTORS.get(field_name, [])
    for selector in selectors:
        element = action_div.locator(selector).first
        if element.count() > 0:
            return element
    raise ClientError(f"Cannot find UI element for field '{field_name}'")
```

### Step 3: Add `_validate_fields_for_step_type()` method to GlobiflowClient

**File**: `<cli-tools-root>/globiflow/globiflow_cli/client.py`
**Location**: After `_get_field_selector()` method

```python
def _validate_fields_for_step_type(self, action_type: str, fields: dict) -> None:
    """Validate that fields are appropriate for the step type.

    Args:
        action_type: The action type string from the step
        fields: Dict of field_name -> value to validate

    Raises:
        ClientError: If any field is not valid for this step type
    """
    from .models.step import _STEP_TYPE_MAPPINGS, StepDetail

    # Find the matching step class
    step_class = None
    for pattern, cls, cat in _STEP_TYPE_MAPPINGS:
        if pattern.lower() in action_type.lower():
            step_class = cls
            break

    if step_class is None:
        raise ClientError(f"Unknown action type: {action_type}")

    # Get valid fields for this step class
    valid_fields = set(step_class.model_fields.keys())
    step_detail_fields = set(StepDetail.model_fields.keys())

    # Exclude base fields that aren't updatable
    base_fields = {'step_number', 'action_type', 'category', 'action_cost', 'parameters', 'flow_id'}
    updatable_fields = (valid_fields | step_detail_fields) - base_fields

    # Check each provided field
    for field_name in fields.keys():
        if field_name not in updatable_fields:
            raise ClientError(
                f"Field '{field_name}' is not valid for step type '{action_type}'. "
                f"Valid fields: {sorted(valid_fields - base_fields)}"
            )
```

### Step 4: Add `update_flow_step()` method to GlobiflowClient

**File**: `<cli-tools-root>/globiflow/globiflow_cli/client.py`
**Location**: After `get_flow_step()` method

```python
def update_flow_step(
    self,
    flow_id: str,
    step_number: int,
    updates: dict
) -> StepDetail:
    """Update specific fields of a step in a flow.

    Args:
        flow_id: The flow ID
        step_number: The step number (1-based)
        updates: Dict of field_name -> new_value to update

    Returns:
        Updated StepDetail model

    Raises:
        ClientError: If step not found or fields don't match step type
    """
    self.ensure_authenticated(f"/configureflow.php?id={flow_id}")
    page = self.browser.page

    # Wait for the actions section to load
    page.wait_for_selector("h4:has-text('Actions')", timeout=10000)
    page.wait_for_timeout(2000)

    # Find the step
    actions_heading = page.locator("h4:has-text('Actions')")
    if actions_heading.count() == 0:
        raise ClientError(f"Actions section not found in flow {flow_id}")

    actions_section = actions_heading.locator("..").locator("ul").first
    if actions_section.count() == 0:
        raise ClientError(f"No steps found in flow {flow_id}")

    step_items = actions_section.locator("> li").all()
    if step_number < 1 or step_number > len(step_items):
        raise ClientError(f"Step {step_number} not found in flow {flow_id} (has {len(step_items)} steps)")

    step_item = step_items[step_number - 1]
    action_div = step_item.locator("> div").first
    if action_div.count() == 0:
        raise ClientError(f"Step {step_number} has no content")

    # Get action type for validation
    full_text = action_div.inner_text()
    lines = [l.strip() for l in full_text.split("\n") if l.strip()]
    action_type = lines[0] if lines else "Unknown"
    for pattern in [" (opt)", " (a=", "(a=", "Options:", "Select ", "Get Items from", " = "]:
        if pattern in action_type:
            action_type = action_type[:action_type.find(pattern)].strip()
            break
    action_type = action_type.rstrip(":").rstrip("(").rstrip("=").strip()

    # Validate fields for this step type
    self._validate_fields_for_step_type(action_type, updates)

    # Expand options section if needed (for fields like headers, follow_redirect)
    opt_link = action_div.locator("a:has-text('(opt)')").first
    if opt_link.count() > 0:
        opt_link.click()
        page.wait_for_timeout(500)

    # Fill in the updated fields
    for field_name, new_value in updates.items():
        try:
            selector = self._get_field_selector(action_div, field_name)
        except ClientError:
            # Field might not be visible in UI, skip with warning
            continue

        # Handle different input types
        tag_name = selector.evaluate("el => el.tagName.toLowerCase()")
        if tag_name == "select":
            selector.select_option(label=str(new_value))
        elif tag_name == "textarea":
            selector.fill(str(new_value))
        elif tag_name == "input":
            input_type = selector.get_attribute("type") or "text"
            if input_type == "checkbox":
                if new_value:
                    selector.check()
                else:
                    selector.uncheck()
            else:
                selector.fill(str(new_value))

    # Save the flow
    save_link = page.get_by_role("link", name="Save")
    if save_link.count() > 0:
        save_link.click()
        page.wait_for_timeout(2000)
    else:
        raise ClientError("Save button not found")

    # Return updated step details
    return self.get_flow_step(flow_id, step_number)
```

──────────────────────────
🧪 CHECKPOINT: Verify steps 1-4
   - Run: `globiflow flows steps get 4314927 1` to ensure existing functionality still works
   - Expected: Step details returned without errors
   - If failing: Fix before proceeding
──────────────────────────

### Step 5: Add `update` command to flows.py

**File**: `<cli-tools-root>/globiflow/globiflow_cli/commands/flows.py`
**Location**: After `get_step()` command

```python
@steps_app.command("update")
def update_step(
    flow_id: str = typer.Argument(..., help="Flow ID"),
    step_number: int = typer.Argument(..., help="Step number (1-based)"),

    # Variable/Calc fields
    variable_name: Optional[str] = typer.Option(None, "--variable-name", "-v",
        help="Variable name for calc/HTTP steps"),
    code: Optional[str] = typer.Option(None, "--code", "-c",
        help="PHP expression for calc/filter steps"),

    # HTTP Call fields
    url: Optional[str] = typer.Option(None, "--url",
        help="URL for HTTP call steps"),
    method: Optional[str] = typer.Option(None, "--method", "-m",
        help="HTTP method (GET, POST, PUT, PATCH, DELETE)"),
    headers: Optional[str] = typer.Option(None, "--headers",
        help="Custom headers for HTTP calls"),
    get_params: Optional[str] = typer.Option(None, "--get-params",
        help="GET parameters for HTTP calls"),
    post_params: Optional[str] = typer.Option(None, "--post-params",
        help="POST/body parameters for HTTP calls"),
    follow_redirect: Optional[bool] = typer.Option(None, "--follow-redirect/--no-follow-redirect",
        help="Follow HTTP redirects"),

    # Email fields
    to: Optional[str] = typer.Option(None, "--to",
        help="Recipient email address(es)"),
    subject: Optional[str] = typer.Option(None, "--subject",
        help="Email subject"),
    body: Optional[str] = typer.Option(None, "--body",
        help="Email body content"),
    from_name: Optional[str] = typer.Option(None, "--from-name",
        help="Sender name"),
    reply_to: Optional[str] = typer.Option(None, "--reply-to",
        help="Reply-to email address"),
    cc: Optional[str] = typer.Option(None, "--cc",
        help="CC email address(es)"),
    bcc: Optional[str] = typer.Option(None, "--bcc",
        help="BCC email address(es)"),

    # Comment fields
    comment_body: Optional[str] = typer.Option(None, "--comment",
        help="Comment body text"),
    silent: Optional[bool] = typer.Option(None, "--silent/--no-silent",
        help="Silent mode (no notifications)"),

    # SMS/Message fields
    message: Optional[str] = typer.Option(None, "--message",
        help="Message text for SMS/chat"),

    # Task fields
    assignee: Optional[str] = typer.Option(None, "--assignee",
        help="Task assignee"),
    task_text: Optional[str] = typer.Option(None, "--task-text",
        help="Task description"),
    due_date: Optional[str] = typer.Option(None, "--due-date",
        help="Task due date"),

    # Output format
):
    """
    Update fields of a specific step in a flow.

    Auto-detects the step type and validates that only appropriate fields
    are updated. Supports all step types.

    Example:
        globiflow flows steps update 4314927 1 --variable-name "new_name" --code "'expr'"
        globiflow flows steps update 4314927 3 --url "https://api.example.com" --method POST
        globiflow flows steps update 4314927 5 --to "email@example.com" --subject "Subject"
    """
    try:
        # Build updates dict from non-None options
        updates = {}
        local_vars = locals()
        field_names = [
            'variable_name', 'code', 'url', 'method', 'headers', 'get_params',
            'post_params', 'follow_redirect', 'to', 'subject', 'body', 'from_name',
            'reply_to', 'cc', 'bcc', 'comment_body', 'silent', 'message',
            'assignee', 'task_text', 'due_date'
        ]
        for field in field_names:
            value = local_vars.get(field)
            if value is not None:
                updates[field] = value

        # Validate at least one field provided
        if not updates:
            print_info("No fields provided to update. Use --help to see available options.")
            raise typer.Exit(1)

        client = get_client()
        updated_step = client.update_flow_step(flow_id, step_number, updates)

        if table:
            rows = [
                {"field": "Flow ID", "value": updated_step.flow_id},
                {"field": "Step Number", "value": str(updated_step.step_number)},
                {"field": "Action Type", "value": updated_step.action_type},
            ]
            for field_name in updates.keys():
                value = getattr(updated_step, field_name, None)
                if value is not None:
                    rows.append({"field": field_name, "value": str(value)})
            print_table(rows, ["field", "value"], ["Field", "Value"])
            print_info(f"Step {step_number} updated successfully.")
        else:
            print_json(updated_step)

        client.close()
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))
```

──────────────────────────
🧪 CHECKPOINT: Verify step 5
   - Run: `globiflow flows steps update --help`
   - Expected: Help text showing all options
   - If failing: Fix syntax errors before proceeding
──────────────────────────

### Step 6: Test with Variable Calc step

- Expected: Step updated, new variable name shown
- Verify in Globiflow UI that value persisted

### Step 7: Test with HTTP Call step

- Expected: Step updated, new URL and method shown
- Verify in Globiflow UI that values persisted

──────────────────────────
🧪 FINAL CHECKPOINT: Full integration test
   - Update a variable calc step
   - Update an HTTP call step
   - Verify strict validation rejects invalid fields (e.g., --url on a variable calc step)
   - Expected: All pass
──────────────────────────

---

## The Todo List

1. Add FIELD_SELECTORS constant to client.py
2. Add _get_field_selector() method to GlobiflowClient
3. Add _validate_fields_for_step_type() method to GlobiflowClient
4. Add update_flow_step() method to GlobiflowClient
5. Run checkpoint: verify existing step commands work
6. Add update command to steps_app in flows.py
7. Run checkpoint: verify --help works
8. Test with Variable Calc step
9. Test with HTTP Call step
10. Run final checkpoint: full integration test

---

## What's NOT Included

- **Field discovery command**: Not adding a command to list valid fields per step type (can use `--help`)
- **Batch updates**: Not supporting updating multiple steps at once
- **Step type conversion**: Not supporting changing a step's type, only its field values
- **Undo/rollback**: Not implementing undo functionality (Globiflow has version history)
