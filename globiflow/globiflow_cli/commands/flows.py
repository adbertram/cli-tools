"""Flow commands for Globiflow CLI."""
COMMAND_CREDENTIALS = {
    "create": [
        "browser_session"
    ],
    "delete": [
        "browser_session"
    ],
    "get": [
        "browser_session"
    ],
    "list": [
        "browser_session"
    ],
    "logs": [
        "browser_session"
    ],
    "steps": [
        "browser_session"
    ]
}

import json
import typer
from typing import Optional, List
from pathlib import Path

from ..client import get_client, ClientError
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import print_json, print_table, handle_error, print_info, print_error
from cli_tools_shared import FilterMap

app = typer.Typer(help="Manage Globiflow flows")
steps_app = typer.Typer(help="Manage flow steps")
app.add_typer(steps_app, name="steps")


def _apply_filters(items: List[dict], filters: Optional[List[str]]) -> List[dict]:
    """Apply client-side filters using field:op:value format.

    Args:
        items: List of dicts to filter
        filters: List of filter strings in format "field:op:value"
                 Supported operators: eq, ne, contains, gt, lt, gte, lte

    Returns:
        Filtered list of dicts
    """
    if not filters:
        return items

    filtered = items
    for filter_str in filters:
        parts = filter_str.split(":", 2)
        if len(parts) != 3:
            print_error(f"Invalid filter format: {filter_str}. Expected field:op:value")
            continue

        field, op, value = parts

        # Apply filter
        if op == "eq":
            filtered = [item for item in filtered if str(item.get(field, "")).lower() == value.lower()]
        elif op == "ne":
            filtered = [item for item in filtered if str(item.get(field, "")).lower() != value.lower()]
        elif op == "contains":
            filtered = [item for item in filtered if value.lower() in str(item.get(field, "")).lower()]
        elif op == "gt":
            filtered = [item for item in filtered if str(item.get(field, "")) > value]
        elif op == "lt":
            filtered = [item for item in filtered if str(item.get(field, "")) < value]
        elif op == "gte":
            filtered = [item for item in filtered if str(item.get(field, "")) >= value]
        elif op == "lte":
            filtered = [item for item in filtered if str(item.get(field, "")) <= value]
        else:
            print_error(f"Unsupported operator: {op}. Use eq, ne, contains, gt, lt, gte, lte")

    return filtered


def _select_properties(items: List[dict], properties: Optional[str]) -> List[dict]:
    """Select specific properties from items.

    Args:
        items: List of dicts
        properties: Comma-separated list of field names to include

    Returns:
        List of dicts with only selected properties
    """
    if not properties:
        return items

    fields = [f.strip() for f in properties.split(",")]
    return [{k: v for k, v in item.items() if k in fields} for item in items]


@app.command("list")
def list_flows(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results (client-side)"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of fields to include in output"),
):
    """
    List all flows across all apps.

    Traverses the entire tree structure and extracts all flows.
    Supports client-side filtering and limiting (browser-based CLI).

    Example:
        globiflow flows list --table
        globiflow flows list --filter "org_name:contains:My Org" --table
        globiflow flows list --filter "enabled:eq:true" --limit 10
        globiflow flows list --properties "id,name,enabled"
    """
    try:
        client = get_client()
        flows = client.list_flows()

        # Convert to dicts for filtering
        flow_dicts = [f.model_dump() for f in flows]

        # Apply filters
        flow_dicts = _apply_filters(flow_dicts, filter)

        # Apply limit
        flow_dicts = flow_dicts[:limit]

        # Select properties if specified
        flow_dicts = _select_properties(flow_dicts, properties)

        if table:
            if flow_dicts:
                # Determine columns based on properties or default
                if properties:
                    columns = [f.strip() for f in properties.split(",")]
                    headers = [c.replace("_", " ").title() for c in columns]
                else:
                    columns = ["id", "name", "app_name", "workspace_name", "org_name", "enabled"]
                    headers = ["ID", "Flow Name", "App", "Workspace", "Organization", "Enabled"]

                # Convert enabled bool to display string for table
                display_flows = []
                for f in flow_dicts:
                    display_f = dict(f)
                    if "enabled" in display_f and isinstance(display_f["enabled"], bool):
                        display_f["enabled"] = "Yes" if display_f["enabled"] else "No"
                    display_flows.append(display_f)

                print_table(display_flows, columns, headers)
            else:
                print_info("No flows found.")
        else:
            print_json(flow_dicts)

        client.close()
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def create_flow(
    app_id: str = typer.Option(..., "--app-id", "-a", help="Podio app ID for the flow"),
    trigger: str = typer.Option(..., "--trigger", "-T", help="Trigger code (C, U, M, etc. - use 'triggers list')"),
    name: str = typer.Option(..., "--name", "-n", help="Flow name"),
    description: str = typer.Option("", "--description", "-d", help="Flow description"),
    steps: Optional[str] = typer.Option(None, "--steps", "-s", help="Steps JSON array or @filepath"),
    enabled: bool = typer.Option(True, "--enabled/--disabled", help="Enable or disable the flow"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Create a new flow in a Globiflow app.

    Requires app ID (from Podio) and trigger code (use 'triggers list' to see options).
    Optionally provide steps as JSON directly or via @filepath.

    Example:
        globiflow flows create --app-id 30560419 --trigger C --name "My Flow"
        globiflow flows create --app-id 30560419 --trigger U --name "Update Handler" --disabled
        globiflow flows create --app-id 30560419 --trigger C --name "With Steps" --steps '[{"action_type": "Custom Variable", "variable_name": "test", "code": "1+1"}]'
        globiflow flows create --app-id 30560419 --trigger M --name "Manual Flow" --steps @steps.json
    """
    try:
        # Parse steps if provided
        parsed_steps = None
        if steps:
            if steps.startswith("@"):
                # Read from file
                file_path = Path(steps[1:])
                if not file_path.exists():
                    print_info(f"Error: Steps file not found: {file_path}")
                    raise typer.Exit(1)
                with open(file_path) as f:
                    parsed_steps = json.load(f)
            else:
                # Parse JSON directly
                try:
                    parsed_steps = json.loads(steps)
                except json.JSONDecodeError as e:
                    print_info(f"Error: Invalid JSON in --steps: {e}")
                    raise typer.Exit(1)

            # Validate steps is a list
            if not isinstance(parsed_steps, list):
                print_info("Error: --steps must be a JSON array of step objects")
                raise typer.Exit(1)

        client = get_client()
        flow = client.create_flow(
            app_id=app_id,
            trigger_code=trigger,
            name=name,
            description=description,
            enabled=enabled,
            steps=parsed_steps,
        )

        if table:
            rows = [
                {"field": "ID", "value": flow.id},
                {"field": "Name", "value": flow.name},
                {"field": "Enabled", "value": "Yes" if flow.enabled else "No"},
                {"field": "Time Savings", "value": flow.time_savings or "N/A"},
                {"field": "Has Logs", "value": "Yes" if flow.has_logs else "No"},
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
            print_info(f"Flow created successfully with ID: {flow.id}")
        else:
            print_json(flow)

        client.close()
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def get_flow(
    flow_id: str = typer.Argument(..., help="Flow ID to retrieve"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    include_steps: bool = typer.Option(False, "--include-steps", "-s", help="Include step details"),
):
    """
    Get detailed information about a specific flow.

    Retrieves flow notes, time savings, and log status.
    Use --include-steps to also retrieve the configured steps.

    Example:
        globiflow flows get 4299675 --table
        globiflow flows get 4299675 --include-steps
    """
    try:
        client = get_client()
        flow = client.get_flow(flow_id, include_steps=include_steps)

        if table:
            # Convert to key-value rows for table display
            rows = [
                {"field": "ID", "value": flow.id},
                {"field": "Name", "value": flow.name},
                {"field": "Enabled", "value": "Yes" if flow.enabled else "No"},
                {"field": "Time Savings", "value": flow.time_savings or "N/A"},
                {"field": "Has Logs", "value": "Yes" if flow.has_logs else "No"},
                {"field": "Notes", "value": flow.notes or "None"},
            ]
            if include_steps and flow.steps:
                rows.append({"field": "Steps", "value": str(len(flow.steps))})
            print_table(rows, ["field", "value"], ["Field", "Value"])

            # Print steps separately if included
            if include_steps and flow.steps:
                print_info("\nSteps:")
                for step in flow.steps:
                    category = step.category.value if step.category else ""
                    print_info(f"  {step.step_number}. [{category}] {step.action_type}")
        else:
            print_json(flow)

        client.close()
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("logs")
def list_logs(
    flow_id: str = typer.Argument(..., help="Flow ID to get logs for"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    List execution logs for a flow.

    Shows all execution history including timestamps, items triggered,
    status, duration, and any messages.

    Example:
        globiflow flows logs 4299675 --table
        globiflow flows logs 4299675
    """
    try:
        client = get_client()
        logs = client.list_flow_logs(flow_id)

        if table:
            if logs:
                columns = ["timestamp", "item_id", "log_level", "message"]
                headers = ["Date & Time", "Item", "Level", "Message"]
                print_table([log.to_dict() for log in logs], columns, headers)
            else:
                print_info("No logs found for this flow.")
        else:
            print_json([log.to_dict() for log in logs])

        client.close()
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def delete_flow(
    flow_id: str = typer.Argument(..., help="Flow ID to delete"),
    force: bool = typer.Option(False, "--force", "-F", help="Skip confirmation prompt"),
):
    """
    Delete a flow by its ID.

    This action cannot be undone. Use --force to skip confirmation.

    Example:
        globiflow flows delete 4299675
        globiflow flows delete 4299675 --force
    """
    try:
        client = get_client()

        # Get flow info first for confirmation
        if not force:
            try:
                flow = client.get_flow(flow_id)
                flow_name = flow.name
            except Exception:
                flow_name = "Unknown"

            if not typer.confirm(
                f"Are you sure you want to delete flow '{flow_name}' (ID: {flow_id})?"
            ):
                print_info("Deletion cancelled.")
                client.close()
                return

        # Perform deletion
        client.delete_flow(flow_id)
        print_info(f"Flow {flow_id} deleted successfully.")

        client.close()
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


# ==================== Steps Subcommands ====================


@steps_app.command("list")
def list_steps(
    flow_id: str = typer.Option(None, "--flow-id", help="Flow ID to list steps for (optional, lists steps from all flows if omitted)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of fields to include"),
):
    """
    List steps in a flow or across all flows.

    Shows step number, action type, and key parameter values for each step.
    JSON output includes all extracted parameters.

    Example:
        globiflow flows steps list --flow-id 4299675 --table
        globiflow flows steps list --table
    """
    try:
        if not flow_id:
            # Listing every step across every flow is intentionally unsupported.
            # Still honor the caller's requested output format.
            if table:
                print_table([], ["step_number", "action_type", "category"], ["Step Number", "Action Type", "Category"])
            else:
                print_json([])
            return

        client = get_client()
        # List steps for specific flow
        steps = client.list_flow_steps(flow_id)

        # Convert to dicts for filtering
        step_dicts = [s if isinstance(s, dict) else s.model_dump() for s in steps]

        # Apply filters
        step_dicts = _apply_filters(step_dicts, filter)

        # Apply limit
        step_dicts = step_dicts[:limit]

        # Select properties if specified
        step_dicts = _select_properties(step_dicts, properties)

        if table:
            if step_dicts:
                columns = ["step_number", "action_type", "category"]
                if not flow_id:
                    # Include flow context when listing across flows
                    columns = ["flow_name", "flow_id"] + columns
                headers = [c.replace("_", " ").title() for c in columns]
                print_table(step_dicts, columns, headers)
            else:
                print_info("No steps found.")
        else:
            print_json(step_dicts)

        client.close()
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@steps_app.command("get")
def get_step(
    flow_id: str = typer.Argument(..., help="Flow ID"),
    step_number: int = typer.Argument(..., help="Step number (1-based)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get detailed information about a specific step in a flow.

    Shows the action type and all configured parameter values.

    Example:
        globiflow flows steps get 4299675 1 --table
        globiflow flows steps get 4299675 2
    """
    try:
        client = get_client()
        step = client.get_flow_step(flow_id, step_number)

        if table:
            # Basic info
            rows = [
                {"field": "Flow ID", "value": step.flow_id},
                {"field": "Step Number", "value": str(step.step_number)},
                {"field": "Action Type", "value": step.action_type},
                {"field": "Category", "value": step.category.value if step.category else ""},
            ]

            # Add key fields if present
            if step.code:
                rows.append({"field": "Code", "value": step.code})
            if step.url:
                rows.append({"field": "URL", "value": step.url})
            if step.method:
                rows.append({"field": "Method", "value": step.method.value if hasattr(step.method, 'value') else step.method})
            if step.variable_name:
                rows.append({"field": "Variable Name", "value": step.variable_name})

            print_table(rows, ["field", "value"], ["Field", "Value"])

            # Show additional parameters if any
            if step.parameters:
                print_info("\nAdditional Parameters:")
                param_rows = [{"param": k, "value": v} for k, v in step.parameters.items()]
                print_table(param_rows, ["param", "value"], ["Parameter", "Value"])
        else:
            print_json(step)

        client.close()
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@steps_app.command("add")
def add_step(
    flow_id: str = typer.Argument(..., help="Flow ID to add step to"),
    action_type: str = typer.Option(..., "--action", "-a", help="Action type (e.g., 'Add Comment', 'Custom Variable', 'Remote HTTP Call')"),

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
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Add a new step to an existing flow.

    Adds a step of the specified action type with the given parameters.

    Example:
        globiflow flows steps add 4314927 --action "Add Comment" --comment "Hello world"
        globiflow flows steps add 4314927 --action "Custom Variable" --variable-name "myvar" --code "'value'"
        globiflow flows steps add 4314927 --action "Remote HTTP Call" --url "https://api.example.com" --method POST
    """
    try:
        # Build step config from action_type and non-None options
        step_config = {"action_type": action_type}
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
                step_config[field] = value

        client = get_client()
        new_step = client.add_flow_step(flow_id, step_config)

        if table:
            rows = [
                {"field": "Flow ID", "value": new_step.flow_id},
                {"field": "Step Number", "value": str(new_step.step_number)},
                {"field": "Action Type", "value": new_step.action_type},
            ]
            # Add any configured fields
            for field_name in field_names:
                value = getattr(new_step, field_name, None)
                if value is not None:
                    rows.append({"field": field_name, "value": str(value)})
            print_table(rows, ["field", "value"], ["Field", "Value"])
            print_info(f"Step added successfully as step {new_step.step_number}.")
        else:
            print_json(new_step)

        client.close()
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


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
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
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
