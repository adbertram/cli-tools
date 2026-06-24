"""Agent flow commands for Copilot Studio agent flows.

Agent flows are Power Automate flows designed specifically to work with
Copilot Studio agents. They have the "When an agent calls the flow" trigger
and "Respond to the agent" action.
"""
import json
import time
import typer
from pathlib import Path
from typing import Optional

import yaml as yaml_lib

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, print_success, print_error, handle_error, safe_symbol, command
from ..validation import FlowYAMLValidator, validate_agent_flow_yaml


app = typer.Typer(help="Manage Copilot Studio agent flows")

COMMAND_CREDENTIALS = {
    "actions": [
        "custom"
    ],
    "create": [
        "custom"
    ],
    "disable": [
        "custom"
    ],
    "enable": [
        "custom"
    ],
    "export": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "import": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "permissions": [
        "custom"
    ],
    "remove": [
        "custom"
    ],
    "runs": [
        "custom"
    ],
    "scaffold": [
        "custom"
    ],
    "test": [
        "custom"
    ],
    "update": [
        "custom"
    ],
    "validate": [
        "custom"
    ]
}

# Subcommand for flow runs
runs_app = typer.Typer(help="Manage agent flow run history")


# Placeholder for permissions subcommand (coming soon)
permissions_app = typer.Typer(help="Manage agent flow permissions (coming soon)")


@permissions_app.callback(invoke_without_command=True)
def permissions_placeholder(ctx: typer.Context):
    """Manage agent flow permissions (grant, revoke, list)."""
    if ctx.invoked_subcommand is None:
        typer.echo("Agent flow permissions management is coming soon.")
        typer.echo("\nFor now, use the Power Platform admin center to manage flow permissions.")
        raise typer.Exit(0)


app.add_typer(permissions_app, name="permissions")
app.add_typer(runs_app, name="runs")

# Subcommand for scaffold templates
scaffold_app = typer.Typer(help="Manage agent flow scaffold templates")
app.add_typer(scaffold_app, name="scaffold")


def get_templates_dir() -> Path:
    """Get the templates directory path."""
    return Path(__file__).resolve().parent.parent / "templates"


def list_available_scaffolds(truncate: bool = False) -> list:
    """List available scaffold templates.

    Args:
        truncate: If True, truncate long values for table display
    """
    templates_dir = get_templates_dir()
    if not templates_dir.exists():
        return []

    scaffolds = []
    for f in templates_dir.glob("*.yaml"):
        if f.name.startswith("_"):
            continue
        # Read template to get description
        try:
            with open(f, "r") as file:
                content = yaml_lib.safe_load(file)
                desc = content.get("description", "").replace("{{DESCRIPTION}}", "No description")
        except Exception:
            desc = "Unable to read template"

        if truncate and len(desc) > 60:
            desc = desc[:60] + "..."

        scaffolds.append({
            "name": f.stem,
            "file": f.name,
            "description": desc,
        })
    return scaffolds


@scaffold_app.command("list")
@command
def scaffold_list(
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display output as a formatted table",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
        help="Maximum number of results to return",
    ),
    filter: Optional[list[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter results using field:op:value syntax",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include in output",
    ),
):
    """
    List available scaffold templates.

    Shows all scaffold templates that can be used with 'agent-flow create --scaffold'.

    Examples:
        copilot agent-flow scaffold list
        copilot agent-flow scaffold list --table
    """
    scaffolds = list_available_scaffolds(truncate=table)

    if not scaffolds:
        print_error("No scaffold templates found")
        raise typer.Exit(1)

    # Apply filters
    if filter:
        from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
        try:
            validate_filters(filter)
            scaffolds = apply_filters(scaffolds, filter)
        except FilterValidationError as e:
            print_error(str(e))
            raise typer.Exit(1)

    # Apply limit
    scaffolds = scaffolds[:limit]

    # Apply properties filter
    if properties:
        property_list = [p.strip() for p in properties.split(",")]
        scaffolds = [{k: v for k, v in item.items() if k in property_list} for item in scaffolds]

    if table:
        print_table(
            scaffolds,
            columns=["name", "description"],
            headers=["Template Name", "Description"],
        )
    else:
        print_json(scaffolds)


@scaffold_app.command("get")
def scaffold_get(
    template_name: str = typer.Argument(..., help="Template name (without .yaml extension)"),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display output as a formatted table",
    ),
):
    """
    Get details for a specific scaffold template.

    Shows the full metadata and content of a scaffold template by name.

    Examples:
        copilot agent-flow scaffold get basic
        copilot agent-flow scaffold get http-action --table
    """
    try:
        templates_dir = get_templates_dir()
        template_path = templates_dir / f"{template_name}.yaml"

        if not template_path.exists():
            print_error(f"Template '{template_name}' not found in {templates_dir}")
            raise typer.Exit(1)

        with open(template_path, "r") as f:
            content = yaml_lib.safe_load(f)

        result = {
            "name": template_name,
            "file": template_path.name,
            "description": content.get("description", "").replace("{{DESCRIPTION}}", "No description"),
            "content": content,
        }

        if table:
            display = {k: v for k, v in result.items() if k != "content"}
            print_table(
                [display],
                columns=["name", "file", "description"],
                headers=["Name", "File", "Description"],
            )
        else:
            print_json(result)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@runs_app.command("list")
def runs_list(
    workflow_id: str = typer.Argument(
        ...,
        help="The agent flow's unique identifier (GUID)",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display output as a formatted table",
    ),
    top: int = typer.Option(
        50,
        "--top",
        "-n",
        help="Maximum number of runs to return (default: 50)",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
        help="Maximum number of results to return",
    ),
    filter: Optional[list[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter results using field:op:value syntax",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include in output",
    ),
):
    """
    List flow run history for an agent flow.

    Shows past executions of the flow including status, start time,
    and duration.

    Examples:
        copilot agent-flow runs list <flow-id>
        copilot agent-flow runs list <flow-id> --table
        copilot agent-flow runs list <flow-id> -t -n 10
    """
    try:
        client = get_client()
        run_list = client.list_flow_runs(workflow_id, top=top)
        if not run_list:
            if table:
                typer.echo("No flow runs found.")
            else:
                print_json([])
            return

        formatted = [format_run_for_display(r) for r in run_list]

        # Apply filters
        if filter:
            from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
            try:
                validate_filters(filter)
                formatted = apply_filters(formatted, filter)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Apply limit
        formatted = formatted[:limit]

        # Apply properties filter
        if properties:
            property_list = [p.strip() for p in properties.split(",")]
            formatted = [{k: v for k, v in item.items() if k in property_list} for item in formatted]

        if table:
            print_table(
                formatted,
                columns=["id", "status", "startTime", "duration"],
                headers=["Run ID", "Status", "Start Time", "Duration"],
            )
        else:
            print_json(formatted)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@runs_app.command("get")
def runs_get(
    workflow_id: str = typer.Argument(
        ...,
        help="The agent flow's unique identifier (GUID)",
    ),
    run_id: str = typer.Argument(
        ...,
        help="The run's unique identifier",
    ),
):
    """
    Get details for a specific flow run.

    Shows detailed information about a specific run including
    action results, timing, and any errors.

    Examples:
        copilot agent-flow runs get <flow-id> <run-id>
    """
    try:
        client = get_client()
        run_data = client.get_flow_run(workflow_id, run_id, expand_actions=True)
        _display_run_details(run_data)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@runs_app.command("cancel")
def runs_cancel(
    workflow_id: str = typer.Argument(
        ...,
        help="The agent flow's unique identifier (GUID)",
    ),
    run_id: str = typer.Argument(
        ...,
        help="The run's unique identifier",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompt (for non-interactive use)",
    ),
):
    """
    Cancel a running flow run.

    Sends a cancel request to the Power Automate Flow Management API.
    A 4xx response from the API typically means the run already finished
    or does not exist.

    Examples:
        copilot agent-flow runs cancel <flow-id> <run-id>
        copilot agent-flow runs cancel <flow-id> <run-id> --yes
    """
    try:
        if not yes:
            confirm = typer.confirm(
                f"Cancel flow run {run_id} (flow {workflow_id})?",
                default=False,
            )
            if not confirm:
                typer.echo("Cancel aborted.")
                raise typer.Exit(0)

        client = get_client()
        result = client.cancel_flow_run(workflow_id, run_id)
        status_code = result.get("status_code")
        print_success(f"Cancelled flow run {run_id} (HTTP {status_code})")
    except typer.Exit:
        raise
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


def extract_triggers_from_clientdata(clientdata: str) -> list[dict]:
    """Extract trigger information from clientdata JSON.

    Returns a list of trigger dicts with name, type, and kind.
    """
    if not clientdata:
        return []

    try:
        definition = json.loads(clientdata)
        props = definition.get("properties", {})
        flow_def = props.get("definition", {})
        triggers = flow_def.get("triggers", {})

        result = []
        for trigger_name, trigger_data in triggers.items():
            trigger_type = trigger_data.get("type", "Unknown")
            trigger_kind = trigger_data.get("kind", "")
            result.append({
                "name": trigger_name,
                "type": trigger_type,
                "kind": trigger_kind,
            })
        return result
    except (json.JSONDecodeError, TypeError):
        return []


def format_triggers_for_display(triggers: list[dict]) -> str:
    """Format triggers list as a concise string for table display."""
    if not triggers:
        return ""

    # Show type/kind for each trigger
    parts = []
    for t in triggers:
        kind = t.get("kind")
        trigger_type = t.get("type", "Unknown")
        if kind:
            parts.append(kind)
        else:
            parts.append(trigger_type)
    return ", ".join(parts)


def format_agent_flow_for_display(flow: dict, include_triggers: bool = False, truncate: bool = False) -> dict:
    """Format an agent flow for display.

    Args:
        flow: The flow dict from the API
        include_triggers: If True, include trigger information
        truncate: If True, truncate long values for table display
    """
    description = flow.get("description") or ""
    if truncate and len(description) > 60:
        description = description[:57] + "..."

    # Get owner name from expanded owninguser
    owner = flow.get("owninguser", {})
    owner_name = owner.get("fullname", "") if owner else ""

    # Determine status based on statecode
    # statecode: 0=Draft, 1=Activated, 2=Suspended
    statecode = flow.get("statecode")
    if statecode == 0:
        status = "Draft"
    elif statecode == 1:
        status = "Published"
    elif statecode == 2:
        status = "Suspended"
    else:
        # Fallback to formatted value if available
        status = flow.get("statecode@OData.Community.Display.V1.FormattedValue", "Unknown")

    result = {
        "name": flow.get("name"),
        "id": flow.get("workflowid"),
        "owner": owner_name,
        "description": description,
        "status": status,
    }

    # Extract triggers if clientdata is available and requested
    if include_triggers:
        clientdata = flow.get("clientdata")
        triggers = extract_triggers_from_clientdata(clientdata)
        result["triggers"] = format_triggers_for_display(triggers)

    return result


@app.command("list")
def agent_flow_list(
    filter: Optional[list[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., name:ilike:%flow%, status:eq:Draft)",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
        help="Maximum number of flows to return",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display output as a formatted table instead of JSON",
    ),
    output: Optional[str] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output format: json (default) or table",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include in output",
    ),
):
    """
    List Copilot Studio agent flows in the environment.

    Agent flows are Power Automate flows that have the "When an agent calls
    the flow" trigger, making them usable as tools in Copilot Studio agents.

    Note: This lists all agent flows in the environment, regardless of
    whether they are currently attached to any agent. Use 'copilot agent
    tool list' to see flows attached to a specific agent.

    Examples:
        copilot agent-flow list
        copilot agent-flow list --table
        copilot agent-flow list --filter "name:ilike:%MyAgentPrefix%"
        copilot agent-flow list --limit 50
        copilot agent-flow list --properties "name,id,status,triggers"
    """
    from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError

    try:
        client = get_client()
        flows = client.list_agent_flows(include_clientdata=True)

        if not flows:
            print_json([])
            return

        # Apply filters using standard field:op:value syntax
        if filter:
            try:
                validate_filters(filter)
                flows = apply_filters(flows, filter)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        if not flows:
            print_json([])
            return

        # Apply limit
        flows = flows[:limit]

        use_table = table or output == "table"
        formatted = [format_agent_flow_for_display(f, include_triggers=True, truncate=use_table) for f in flows]

        # Apply properties filter if specified
        if properties:
            property_list = [p.strip() for p in properties.split(",")]
            formatted = [
                {k: v for k, v in item.items() if k in property_list}
                for item in formatted
            ]

        if use_table:
            if properties:
                property_list = [p.strip() for p in properties.split(",")]
                print_table(formatted, columns=property_list, headers=property_list)
            else:
                print_table(
                    formatted,
                    columns=["name", "triggers", "owner", "status", "id"],
                    headers=["Name", "Triggers", "Owner", "Status", "ID"],
                )
        else:
            print_json(formatted)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("create")
def agent_flow_create(
    name: str = typer.Option(
        ...,
        "--name",
        "-n",
        help="Display name for the agent flow",
    ),
    description: Optional[str] = typer.Option(
        None,
        "--description",
        "-d",
        help="Description for the agent flow",
    ),
    file: Optional[str] = typer.Option(
        None,
        "--file",
        "-f",
        help="YAML or JSON file containing flow definition to import",
    ),
    include_connections: bool = typer.Option(
        False,
        "--include-connections",
        "-c",
        help="Include connection references from the file (if using --file)",
    ),
    skip_validation: bool = typer.Option(
        False,
        "--skip-validation",
        help="Skip YAML validation (not recommended)",
    ),
    scaffold: Optional[str] = typer.Option(
        None,
        "--scaffold",
        "-s",
        help="Use a scaffold template (see 'scaffold list' for options)",
    ),
    from_flow: Optional[str] = typer.Option(
        None,
        "--from",
        help="Clone definition from existing flow ID (GUID)",
    ),
    output_file: Optional[str] = typer.Option(
        None,
        "--output",
        "-o",
        help="Write to local file instead of creating in Dataverse",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-F",
        help="Overwrite existing file when using --output",
    ),
):
    """
    Create a new Copilot Studio agent flow.

    Creates a new agent flow that can be used as a tool in Copilot Studio agents.
    The flow is created in Draft state and has the "When an agent calls the flow"
    trigger.

    You can create an empty flow with just a name, or import a flow definition
    from a YAML/JSON file, scaffold template, or existing flow.

    Sources for flow definition:
    1. --file: Import from YAML/JSON file (full export or definition-only)
    2. --scaffold: Use a built-in scaffold template (try-catch-finally, etc.)
    3. --from: Clone from an existing flow by ID

    Use --output to write to a local file instead of creating in Dataverse.

    Examples:
        # Create an empty agent flow
        copilot agent-flow create --name "My Agent Flow"
        copilot agent-flow create -n "My Flow" -d "Description here"

        # Create from a flow definition file
        copilot agent-flow create --name "My Flow" --file flow.yaml
        copilot agent-flow create -n "My Flow" -f flow.yaml --include-connections

        # Create from a scaffold template
        copilot agent-flow create -n "My Flow" --scaffold try-catch-finally
        copilot agent-flow create -n "My Flow" -s try-catch-finally -o ./flows/my_flow.yaml

        # Clone from an existing flow
        copilot agent-flow create -n "My Flow Copy" --from <existing-flow-id>
    """
    try:
        definition = None
        connection_refs = None

        # Check for mutually exclusive options
        sources_provided = sum([bool(scaffold), bool(from_flow), bool(file)])
        if sources_provided > 1:
            print_error("Cannot use multiple definition sources. Choose one of: --scaffold, --from, or --file")
            raise typer.Exit(1)

        # If scaffold provided, load template
        if scaffold:
            templates_dir = get_templates_dir()
            template_path = templates_dir / f"{scaffold}.yaml"

            if not template_path.exists():
                available = [s["name"] for s in list_available_scaffolds()]
                if available:
                    print_error(f"Scaffold '{scaffold}' not found. Available: {', '.join(available)}")
                else:
                    print_error(f"Scaffold '{scaffold}' not found. No scaffolds available.")
                raise typer.Exit(1)

            try:
                with open(template_path, "r") as f:
                    template_content = f.read()
                    # Replace placeholders
                    template_content = template_content.replace("{{NAME}}", name)
                    template_content = template_content.replace("{{DESCRIPTION}}", description or "")
                    data = yaml_lib.safe_load(template_content)
                    definition = data.get("definition", {})
                    connection_refs = data.get("connectionReferences", {})
                    typer.echo(f"Using scaffold template: {scaffold}", err=True)
            except Exception as e:
                print_error(f"Error loading scaffold: {e}")
                raise typer.Exit(1)

        # If --from provided, export and clone the flow definition
        if from_flow:
            try:
                client = get_client()
                typer.echo(f"Cloning definition from flow: {from_flow}", err=True)
                flow_data = client.get_agent_flow(from_flow, expand_definition=True)

                # Parse the clientdata to get definition
                clientdata = flow_data.get("clientdata", "{}")
                if isinstance(clientdata, str):
                    parsed = json.loads(clientdata)
                else:
                    parsed = clientdata

                definition = parsed.get("properties", {}).get("definition", {})

                if not definition:
                    print_error("Could not extract definition from source flow")
                    raise typer.Exit(1)

                typer.echo("Flow definition cloned successfully", err=True)
            except Exception as e:
                print_error(f"Error cloning flow: {e}")
                raise typer.Exit(1)

        # If file provided, parse it
        if file:
            try:
                with open(file, "r") as f:
                    content = f.read()
            except FileNotFoundError:
                print_error(f"File not found: {file}")
                raise typer.Exit(1)

            # Parse as YAML (which also handles JSON)
            try:
                data = yaml_lib.safe_load(content)
            except yaml_lib.YAMLError as e:
                print_error(f"Error parsing file: {e}")
                raise typer.Exit(1)

            if not isinstance(data, dict):
                print_error("File must contain a YAML/JSON object")
                raise typer.Exit(1)

            # Determine format
            if "definition" in data:
                # Full export format
                definition = data.get("definition", {})
                if include_connections:
                    connection_refs = data.get("connectionReferences", {})
                typer.echo("Detected full export format", err=True)
            elif "$schema" in data or "actions" in data or "triggers" in data:
                # Definition-only format — extract connectionReferences before
                # assigning the rest as the definition so it doesn't pollute the
                # definition payload sent to the API.
                if include_connections and "connectionReferences" in data:
                    connection_refs = data.pop("connectionReferences")
                elif "connectionReferences" in data:
                    # Even without --include-connections, strip connectionReferences
                    # from the definition — it belongs as a sibling under
                    # clientdata.properties, not inside the definition.
                    data.pop("connectionReferences")
                # Ensure required schema fields exist — the Power Platform API
                # rejects definitions missing $schema / contentVersion.
                if "$schema" not in data:
                    data["$schema"] = "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#"
                if "contentVersion" not in data:
                    data["contentVersion"] = "1.0.0.0"
                if "parameters" not in data:
                    data["parameters"] = {
                        "$authentication": {"defaultValue": {}, "type": "SecureObject"},
                        "$connections": {"defaultValue": {}, "type": "Object"},
                    }
                if "outputs" not in data:
                    data["outputs"] = {}
                definition = data
                typer.echo("Detected definition-only format", err=True)
            else:
                print_error(
                    "Unable to determine file format. Expected either full export "
                    "format (with 'definition' key) or definition-only format (with "
                    "'$schema', 'actions', or 'triggers' keys)."
                )
                raise typer.Exit(1)

            # Run validation
            if not skip_validation and definition:
                typer.echo("Validating flow definition...", err=True)
                validator = FlowYAMLValidator()
                validation_result = validator.validate(data)

                has_errors = len(validation_result.errors) > 0
                has_warnings = len(validation_result.warnings) > 0

                if has_errors:
                    typer.echo("\n=== Validation Errors ===", err=True)
                    for error in validation_result.errors:
                        typer.echo(f"  {safe_symbol('cross')} [{error.rule}] {error.path}", err=True)
                        typer.echo(f"    {error.message}", err=True)
                        if error.suggestion:
                            typer.echo(f"    → {error.suggestion}", err=True)
                    typer.echo("\nValidation failed. Fix the issues or use --skip-validation.", err=True)
                    raise typer.Exit(1)

                if has_warnings:
                    typer.echo("\n=== Validation Warnings ===", err=True)
                    for warning in validation_result.warnings:
                        typer.echo(f"  {safe_symbol('warning')} [{warning.rule}] {warning.path}", err=True)
                        typer.echo(f"    {warning.message}", err=True)
                        if warning.suggestion:
                            typer.echo(f"    → {warning.suggestion}", err=True)

                if not has_errors and not has_warnings:
                    typer.echo("Validation passed.", err=True)
                elif has_warnings:
                    typer.echo("\nValidation passed with warnings.", err=True)

        # If --output specified, write to local file instead of Dataverse
        if output_file:
            output_path = Path(output_file)

            # Check for existing file
            if output_path.exists() and not force:
                print_error(f"File already exists: {output_file}. Use --force to overwrite.")
                raise typer.Exit(1)

            # Ensure parent directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Build output structure
            flow_output = {
                "name": name,
                "description": description or "",
                "definition": definition or {},
                "connectionReferences": connection_refs or {},
            }

            with open(output_path, "w") as f:
                yaml_lib.dump(flow_output, f, default_flow_style=False, sort_keys=False)

            print_success(f"Flow scaffold written to: {output_file}")
            print_json({"file": str(output_path.resolve()), "name": name})
            return  # Don't create in Dataverse

        # Create the flow in Dataverse
        client = get_client()
        result = client.create_agent_flow(
            name=name,
            definition=definition,
            connection_references=connection_refs,
            description=description,
        )

        print_success(f"Agent flow '{name}' created successfully")
        print_json({
            "workflowid": result.get("workflowid"),
            "name": name,
            "status": "Draft",
        })

    except typer.Exit:
        raise
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("get")
def agent_flow_get(
    workflow_id: str = typer.Argument(
        ...,
        help="The agent flow's unique identifier (GUID)",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display output as a formatted table instead of JSON",
    ),
):
    """
    Get details for a specific agent flow.

    Shows flow metadata including triggers. For HTTP triggers, the callback
    URL is included to allow direct invocation.

    Examples:
        copilot agent-flow get <flow-id>
        copilot agent-flow get <flow-id> --table
    """
    try:
        client = get_client()

        # Get flow with clientdata to extract trigger info
        flow = client.get(
            f"workflows({workflow_id})/Microsoft.Dynamics.CRM.RetrieveUnpublished()"
            f"?$select=workflowid,name,description,statecode,statuscode,type,"
            f"parentworkflowid,createdon,modifiedon,clientdata"
            f"&$expand=owninguser($select=systemuserid,fullname)"
        )

        # Extract trigger information
        triggers = extract_triggers_from_clientdata(flow.get("clientdata"))

        # Get callback URL for HTTP triggers
        for trigger in triggers:
            if trigger.get("kind") == "Http" or trigger.get("type") == "Request":
                try:
                    callback_info = client.get_flow_callback_url(workflow_id)
                    callback_url = callback_info.get("response", {}).get("value")
                    if not callback_url:
                        callback_url = callback_info.get("value")
                    trigger["callbackUrl"] = callback_url
                except Exception:
                    trigger["callbackUrl"] = "(failed to retrieve)"

        if table:
            formatted = format_agent_flow_for_display(flow, include_triggers=True, truncate=True)
            print_table(
                [formatted],
                columns=["name", "triggers", "owner", "status", "id"],
                headers=["Name", "Triggers", "Owner", "Status", "ID"],
            )
        else:
            # Add trigger details to JSON output
            output = {
                "workflowid": flow.get("workflowid"),
                "name": flow.get("name"),
                "description": flow.get("description"),
                "statecode": flow.get("statecode"),
                "status": "Published" if flow.get("statecode") == 1 else "Draft",
                "owner": flow.get("owninguser", {}).get("fullname", ""),
                "triggers": triggers,
                "createdon": flow.get("createdon"),
                "modifiedon": flow.get("modifiedon"),
            }
            print_json(output)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("update")
def agent_flow_update(
    workflow_id: str = typer.Argument(
        ...,
        help="The agent flow's unique identifier (GUID)",
    ),
    name: Optional[str] = typer.Option(
        None,
        "--name",
        "-n",
        help="New name for the agent flow",
    ),
    description: Optional[str] = typer.Option(
        None,
        "--description",
        "-d",
        help="New description for the agent flow",
    ),
):
    """
    Update an agent flow's name or description.

    At least one of --name or --description must be provided.

    IMPORTANT: This command only works for PUBLISHED (activated) flows.
    Draft flows (statecode=0, type=1) cannot be updated via the public API.
    To rename a draft flow, use the Copilot Studio UI at:
    https://copilotstudio.microsoft.com

    Examples:
        copilot agent-flow update <flow-id> --name "My Agent Flow"
        copilot agent-flow update <flow-id> --description "Handles customer queries"
        copilot agent-flow update <flow-id> -n "New Name" -d "New description"
    """
    if not name and not description:
        typer.echo("Error: At least one of --name or --description must be provided", err=True)
        raise typer.Exit(1)

    try:
        client = get_client()
        client.update_agent_flow(workflow_id, name=name, description=description)
        typer.echo(f"Agent flow {workflow_id} updated successfully.")
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("export")
def agent_flow_export(
    workflow_id: str = typer.Argument(
        ...,
        help="The agent flow's unique identifier (GUID)",
    ),
    yaml_output: bool = typer.Option(
        False,
        "--yaml",
        "-Y",
        help="Output the flow definition as YAML (default is JSON)",
    ),
    output: Optional[str] = typer.Option(
        None,
        "--output",
        "-o",
        help="Write output to file instead of stdout",
    ),
    definition_only: bool = typer.Option(
        False,
        "--definition-only",
        "-d",
        help="Output only the flow definition (excludes metadata and connection references)",
    ),
    raw: bool = typer.Option(
        False,
        "--raw",
        "-r",
        help="Output the raw clientdata string without parsing",
    ),
    draft: bool = typer.Option(
        False,
        "--draft",
        help="Export the draft version instead of published (for solution-aware flows with drafts)",
    ),
):
    """
    Export an agent flow's definition as YAML or JSON.

    Retrieves the flow's definition including triggers, actions, and
    connection references. The output can be used for documentation,
    backup, or as a template for creating similar flows.

    By default, outputs the published version of the flow. Use --draft
    to get the draft version (for solution-aware flows with versioning).

    Use --definition-only to output just the flow definition.
    Use --yaml for human-readable YAML format.

    Examples:
        copilot agent-flow export <flow-id>
        copilot agent-flow export <flow-id> --yaml
        copilot agent-flow export <flow-id> --draft --yaml
        copilot agent-flow export <flow-id> --yaml --output flow.yaml
        copilot agent-flow export <flow-id> --definition-only --yaml
        copilot agent-flow export <flow-id> --raw
    """
    try:
        client = get_client()
        flow_data = client.export_agent_flow(workflow_id, draft=draft)

        # Show which version was retrieved
        version = flow_data.get("version", "unknown")
        if draft and version != "draft":
            typer.echo(f"Note: Retrieved version is '{version}' (draft may not exist separately)", err=True)

        # Handle raw output
        if raw:
            content = flow_data.get("raw_clientdata", "")
            if output:
                with open(output, "w") as f:
                    f.write(content)
                print_success(f"Raw clientdata written to {output}")
            else:
                typer.echo(content)
            return

        # Determine what to output
        if definition_only:
            output_data = flow_data.get("definition", {})
        else:
            # Remove raw_clientdata from output (it's redundant and large)
            output_data = {
                "name": flow_data.get("name"),
                "workflowid": flow_data.get("workflowid"),
                "version": flow_data.get("version"),
                "description": flow_data.get("description"),
                "definition": flow_data.get("definition"),
                "connectionReferences": flow_data.get("connectionReferences"),
            }

        # Format output
        if yaml_output:
            content = yaml_lib.dump(
                output_data,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
                width=120,
            )
        else:
            content = json.dumps(output_data, indent=2)

        # Write or print
        if output:
            with open(output, "w") as f:
                f.write(content)
            ext = "YAML" if yaml_output else "JSON"
            print_success(f"Flow definition ({ext}) written to {output}")
        else:
            typer.echo(content)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("import")
def agent_flow_import(
    workflow_id: str = typer.Argument(
        ...,
        help="The agent flow's unique identifier (GUID)",
    ),
    file: str = typer.Option(
        ...,
        "--file",
        "-f",
        help="Path to YAML or JSON file containing the flow definition",
    ),
    include_connections: bool = typer.Option(
        False,
        "--include-connections",
        "-c",
        help="Also update connection references from the file (default: preserve existing)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Parse and validate the file without updating the flow",
    ),
    skip_validation: bool = typer.Option(
        False,
        "--skip-validation",
        help="Skip YAML validation (not recommended)",
    ),
    warnings_as_errors: bool = typer.Option(
        False,
        "--warnings-as-errors",
        "-W",
        help="Treat validation warnings as errors",
    ),
):
    """
    Import/update an agent flow's definition from a YAML or JSON file.

    Reads a flow definition from a file and updates the specified agent flow.
    The file can be in either YAML or JSON format (auto-detected).

    VALIDATION:
    By default, the YAML is validated before import to catch common errors:
    - Invalid parameters (e.g., 'fields' parameter that doesn't exist in the API)
    - Connection reference format issues (connectionName vs connectionReferenceName)
    - Missing required fields
    - Expression syntax errors

    Use --skip-validation to bypass validation (not recommended).
    Use --warnings-as-errors to treat warnings as errors.
    Use --dry-run to validate without making changes.

    Accepts two input formats:
    1. Full export format (from 'agent-flow export'): Contains name, workflowid,
       definition, and connectionReferences fields
    2. Definition-only format (from 'agent-flow export --definition-only'):
       Contains just the flow definition

    By default, only the flow definition is updated and existing connection
    references are preserved. Use --include-connections to also update
    connection references from the file.

    Examples:
        copilot agent-flow import <flow-id> --file flow.yaml
        copilot agent-flow import <flow-id> -f flow.json
        copilot agent-flow import <flow-id> -f flow.yaml --include-connections
        copilot agent-flow import <flow-id> -f flow.yaml --dry-run
        copilot agent-flow import <flow-id> -f flow.yaml --warnings-as-errors
    """
    try:
        # Read and parse the file
        with open(file, "r") as f:
            content = f.read()

        # Try to parse as YAML first (which also handles JSON)
        try:
            data = yaml_lib.safe_load(content)
        except yaml_lib.YAMLError as e:
            typer.echo(f"Error parsing file: {e}", err=True)
            raise typer.Exit(1)

        if not isinstance(data, dict):
            typer.echo("Error: File must contain a YAML/JSON object", err=True)
            raise typer.Exit(1)

        # Determine if this is full export format or definition-only
        # Full export has: name, workflowid, definition, connectionReferences
        # Definition-only has: $schema, actions, triggers, etc.
        if "definition" in data:
            # Full export format
            definition = data.get("definition", {})
            connection_refs = data.get("connectionReferences", {}) if include_connections else None
            typer.echo("Detected full export format", err=True)
        elif "$schema" in data or "actions" in data or "triggers" in data:
            # Definition-only format — extract connectionReferences before
            # assigning the rest as the definition so it doesn't pollute the
            # definition payload sent to the API.
            if include_connections and "connectionReferences" in data:
                connection_refs = data.pop("connectionReferences")
            elif "connectionReferences" in data:
                # Even without --include-connections, strip connectionReferences
                # from the definition — it belongs as a sibling under
                # clientdata.properties, not inside the definition.
                data.pop("connectionReferences")
                connection_refs = None
            else:
                connection_refs = None
            # Ensure required schema fields exist — the Power Platform API
            # rejects definitions missing $schema / contentVersion.
            if "$schema" not in data:
                data["$schema"] = "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#"
            if "contentVersion" not in data:
                data["contentVersion"] = "1.0.0.0"
            if "parameters" not in data:
                data["parameters"] = {
                    "$authentication": {"defaultValue": {}, "type": "SecureObject"},
                    "$connections": {"defaultValue": {}, "type": "Object"},
                }
            if "outputs" not in data:
                data["outputs"] = {}
            definition = data
            typer.echo("Detected definition-only format", err=True)
        else:
            typer.echo(
                "Error: Unable to determine file format. Expected either full export "
                "format (with 'definition' key) or definition-only format (with "
                "'$schema', 'actions', or 'triggers' keys).",
                err=True
            )
            raise typer.Exit(1)

        # Validate definition has required fields
        if not definition.get("$schema") and not definition.get("actions") and not definition.get("triggers"):
            typer.echo(
                "Warning: Definition appears to be empty or missing key fields "
                "(no $schema, actions, or triggers found)",
                err=True
            )

        # Run YAML validation
        if not skip_validation:
            typer.echo("Validating flow definition...", err=True)
            validator = FlowYAMLValidator()
            validation_result = validator.validate(data)

            # Display validation results
            has_errors = len(validation_result.errors) > 0
            has_warnings = len(validation_result.warnings) > 0

            if has_errors:
                typer.echo("\n=== Validation Errors ===", err=True)
                for error in validation_result.errors:
                    typer.echo(f"  {safe_symbol('cross')} [{error.rule}] {error.path}", err=True)
                    typer.echo(f"    {error.message}", err=True)
                    if error.suggestion:
                        typer.echo(f"    → {error.suggestion}", err=True)

            if has_warnings:
                typer.echo("\n=== Validation Warnings ===", err=True)
                for warning in validation_result.warnings:
                    typer.echo(f"  {safe_symbol('warning')} [{warning.rule}] {warning.path}", err=True)
                    typer.echo(f"    {warning.message}", err=True)
                    if warning.suggestion:
                        typer.echo(f"    → {warning.suggestion}", err=True)

            # Determine if we should proceed
            if has_errors:
                typer.echo("\nValidation failed with errors. Fix the issues above and try again.", err=True)
                typer.echo("Use --skip-validation to bypass validation (not recommended).", err=True)
                raise typer.Exit(1)

            if has_warnings and warnings_as_errors:
                typer.echo("\nValidation failed due to --warnings-as-errors flag.", err=True)
                raise typer.Exit(1)

            if not has_errors and not has_warnings:
                typer.echo("Validation passed.", err=True)
            elif has_warnings and not warnings_as_errors:
                typer.echo("\nValidation passed with warnings.", err=True)

        if dry_run:
            typer.echo("\n=== Dry Run - No changes made ===", err=True)
            typer.echo(f"Flow ID: {workflow_id}", err=True)
            typer.echo(f"Definition keys: {list(definition.keys())}", err=True)
            if connection_refs:
                typer.echo(f"Connection references: {list(connection_refs.keys())}", err=True)
            else:
                typer.echo("Connection references: (preserving existing)", err=True)
            typer.echo("\nValidation passed. Run without --dry-run to apply changes.", err=True)
            return

        # Perform the import
        client = get_client()
        result = client.import_agent_flow(
            workflow_id=workflow_id,
            definition=definition,
            connection_references=connection_refs,
        )

        print_success(f"Flow {workflow_id} updated successfully")
        if connection_refs:
            typer.echo("Connection references were also updated.", err=True)
        else:
            typer.echo("Connection references were preserved (use --include-connections to update them).", err=True)

    except FileNotFoundError:
        typer.echo(f"Error: File not found: {file}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("validate")
def agent_flow_validate(
    file: Optional[str] = typer.Argument(
        None,
        help="Path to YAML or JSON file containing the flow definition",
    ),
    warnings_as_errors: bool = typer.Option(
        False,
        "--warnings-as-errors",
        "-W",
        help="Treat validation warnings as errors",
    ),
    list_rules: bool = typer.Option(
        False,
        "--list-rules",
        help="List all available validation rules",
    ),
):
    """
    Validate an agent flow YAML/JSON file without importing.

    Checks the flow definition for common errors:
    - Invalid parameters that don't exist in the API
    - Connection reference format issues
    - Missing required fields
    - Expression syntax errors

    Exit codes:
      0 - Validation passed (may include warnings)
      1 - Validation failed with errors

    Examples:
        copilot agent-flow validate flow.yaml
        copilot agent-flow validate flow.yaml --warnings-as-errors
        copilot agent-flow validate --list-rules
    """
    # List rules mode
    if list_rules:
        validator = FlowYAMLValidator()
        typer.echo("Available validation rules:\n")
        for name, description in validator.get_rule_descriptions().items():
            typer.echo(f"  {name}")
            typer.echo(f"    {description}\n")
        return

    # Require file when not listing rules
    if not file:
        typer.echo("Error: FILE argument is required when not using --list-rules", err=True)
        raise typer.Exit(1)

    try:
        # Read and parse the file
        with open(file, "r") as f:
            content = f.read()

        try:
            data = yaml_lib.safe_load(content)
        except yaml_lib.YAMLError as e:
            typer.echo(f"Error parsing file: {e}", err=True)
            raise typer.Exit(1)

        if not isinstance(data, dict):
            typer.echo("Error: File must contain a YAML/JSON object", err=True)
            raise typer.Exit(1)

        # Run validation
        typer.echo(f"Validating {file}...", err=True)
        validator = FlowYAMLValidator()
        validation_result = validator.validate(data)

        # Display validation results
        has_errors = len(validation_result.errors) > 0
        has_warnings = len(validation_result.warnings) > 0

        if has_errors:
            typer.echo("\n=== Validation Errors ===", err=True)
            for error in validation_result.errors:
                typer.echo(f"  {safe_symbol('cross')} [{error.rule}] {error.path}", err=True)
                typer.echo(f"    {error.message}", err=True)
                if error.suggestion:
                    typer.echo(f"    → {error.suggestion}", err=True)

        if has_warnings:
            typer.echo("\n=== Validation Warnings ===", err=True)
            for warning in validation_result.warnings:
                typer.echo(f"  {safe_symbol('warning')} [{warning.rule}] {warning.path}", err=True)
                typer.echo(f"    {warning.message}", err=True)
                if warning.suggestion:
                    typer.echo(f"    → {warning.suggestion}", err=True)

        # Summary
        typer.echo(f"\n=== Summary ===", err=True)
        typer.echo(f"  Errors:   {len(validation_result.errors)}", err=True)
        typer.echo(f"  Warnings: {len(validation_result.warnings)}", err=True)

        # Determine exit code
        if has_errors:
            typer.echo("\nValidation FAILED.", err=True)
            raise typer.Exit(1)

        if has_warnings and warnings_as_errors:
            typer.echo("\nValidation FAILED (--warnings-as-errors).", err=True)
            raise typer.Exit(1)

        typer.echo("\nValidation PASSED.", err=True)

    except FileNotFoundError:
        typer.echo(f"Error: File not found: {file}", err=True)
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


def format_trigger_history_for_display(history: dict) -> dict:
    """Format a trigger history entry for display."""
    props = history.get("properties", {})

    # Parse startTime to a readable format
    start_time = props.get("startTime", "")
    if start_time:
        # Truncate to just date and time
        start_time = start_time[:19].replace("T", " ")

    return {
        "id": history.get("name", ""),
        "status": props.get("status", ""),
        "startTime": start_time,
        "code": props.get("code", ""),
    }


def format_run_for_display(run: dict) -> dict:
    """Format a flow run entry for display."""
    props = run.get("properties", {})

    start_time = props.get("startTime", "")
    if start_time:
        start_time = start_time[:19].replace("T", " ")

    end_time = props.get("endTime", "")
    if end_time:
        end_time = end_time[:19].replace("T", " ")

    # Calculate duration if both times available
    duration = ""
    if props.get("startTime") and props.get("endTime"):
        try:
            from datetime import datetime
            start = datetime.fromisoformat(props["startTime"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(props["endTime"].replace("Z", "+00:00"))
            delta = end - start
            duration = f"{delta.total_seconds():.1f}s"
        except Exception:
            pass

    return {
        "id": run.get("name", ""),
        "status": props.get("status", ""),
        "startTime": start_time,
        "endTime": end_time,
        "duration": duration,
    }


def format_action_result(action_name: str, action_data: dict) -> dict:
    """Format an action result for display."""
    status = action_data.get("status", "Unknown")
    start_time = action_data.get("startTime", "")
    end_time = action_data.get("endTime", "")

    # Calculate duration
    duration = ""
    if start_time and end_time:
        try:
            from datetime import datetime
            start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            end = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            delta = end - start
            duration = f"{delta.total_seconds():.2f}s"
        except Exception:
            pass

    return {
        "name": action_name,
        "status": status,
        "duration": duration,
        "code": action_data.get("code", ""),
        "error": action_data.get("error"),
        "inputsLink": action_data.get("inputsLink"),
        "outputsLink": action_data.get("outputsLink"),
    }


@app.command("test")
def agent_flow_test(
    workflow_id: str = typer.Argument(
        ...,
        help="The agent flow's unique identifier (GUID)",
    ),
    history: bool = typer.Option(
        False,
        "--history",
        "-h",
        help="List trigger execution history",
    ),
    trigger: Optional[str] = typer.Option(
        None,
        "--trigger",
        "-T",
        help="Trigger type: 'manual' (new invocation) or 'run_history' (resubmit existing)",
    ),
    trigger_id: Optional[str] = typer.Option(
        None,
        "--trigger-id",
        "-i",
        help="For run_history: specific trigger history ID (omit for most recent)",
    ),
    body: Optional[str] = typer.Option(
        None,
        "--body",
        "-b",
        help="For manual trigger: JSON body",
    ),
    body_file: Optional[str] = typer.Option(
        None,
        "--body-file",
        help="For manual trigger: file containing JSON body",
    ),
    wait: bool = typer.Option(
        False,
        "--wait",
        "-w",
        help="Wait for run completion and show results",
    ),
    timeout: int = typer.Option(
        300,
        "--timeout",
        help="Timeout in seconds for --wait (default: 300)",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Deprecated for this command; JSON is always returned",
    ),
):
    """
    Test an agent flow by resubmitting a trigger or invoking manually.

    TRIGGER TYPES:
      --trigger manual       Invoke with custom JSON body (requires --body or --body-file)
      --trigger run_history  Resubmit from trigger history (optional --trigger-id)

    OTHER MODES:
      --history              List previous trigger executions
      (no --trigger)         Defaults to run_history with most recent trigger

    FLAGS:
      --wait                 Poll until run completes, then show action results
      --timeout              Max wait time in seconds (default: 300)
      --table                Deprecated; JSON is always returned

    Use 'copilot agent-flow runs list' to view run history.
    Use 'copilot agent-flow runs get' to view specific run details.

    Examples:
        copilot agent-flow test <flow-id>
        copilot agent-flow test <flow-id> --history --table
        copilot agent-flow test <flow-id> --trigger run_history --wait
        copilot agent-flow test <flow-id> --trigger run_history --trigger-id <id> --wait
        copilot agent-flow test <flow-id> --trigger manual --body '{"key": "value"}'
        copilot agent-flow test <flow-id> --trigger manual --body-file input.json --wait
    """
    try:
        client = get_client()

        # Mode: List trigger history
        if history:
            histories = client.get_flow_trigger_histories(workflow_id)
            if not histories:
                _print_flow_test_result([])
                return

            formatted = [format_trigger_history_for_display(h) for h in histories]
            _print_flow_test_result(formatted)
            return

        # Validate trigger type
        trigger_type = trigger.lower() if trigger else "run_history"
        if trigger_type not in ("manual", "run_history"):
            typer.echo(f"Error: --trigger must be 'manual' or 'run_history', got '{trigger}'", err=True)
            raise typer.Exit(1)

        # Mode: Manual trigger
        if trigger_type == "manual":
            if not body and not body_file:
                typer.echo("Error: --trigger manual requires --body or --body-file", err=True)
                raise typer.Exit(1)

            # Parse body
            if body_file:
                try:
                    with open(body_file, "r") as f:
                        body_data = json.load(f)
                except FileNotFoundError:
                    typer.echo(f"Error: File not found: {body_file}", err=True)
                    raise typer.Exit(1)
                except json.JSONDecodeError as e:
                    typer.echo(f"Error: Invalid JSON in file: {e}", err=True)
                    raise typer.Exit(1)
            else:
                try:
                    body_data = json.loads(body)
                except json.JSONDecodeError as e:
                    typer.echo(f"Error: Invalid JSON body: {e}", err=True)
                    raise typer.Exit(1)

            # Get callback URL and invoke
            callback_info = client.get_flow_callback_url(workflow_id)
            # API returns callback URL in response.value
            callback_url = callback_info.get("response", {}).get("value")
            if not callback_url:
                # Fallback: try top-level value
                callback_url = callback_info.get("value")
            if not callback_url:
                typer.echo("Error: Failed to get callback URL", err=True)
                typer.echo(f"Response: {callback_info}", err=True)
                raise typer.Exit(1)

            result = client.invoke_flow_manual(callback_url, body_data)

            if wait:
                # Need to find the run that was just created
                time.sleep(2)  # Brief pause for run to register
                run_list = client.list_flow_runs(workflow_id, top=1)
                if run_list:
                    latest_run_id = run_list[0].get("name")
                    run_result = _wait_for_run(client, workflow_id, latest_run_id, timeout)
                    _print_flow_test_result(run_result)
                else:
                    _print_flow_test_status("RunNotFound", "Could not find the triggered run")
            else:
                _print_flow_test_result(result)
            return

        # Mode: run_history (resubmit existing trigger)
        # Get most recent trigger history if --trigger-id not specified
        history_id = trigger_id
        if not history_id:
            histories = client.get_flow_trigger_histories(workflow_id)
            if not histories:
                _print_flow_test_status(
                    "NoTriggerHistory",
                    "No trigger history found. Use --trigger manual to invoke with a custom body.",
                )
                raise typer.Exit(1)
            history_id = histories[0].get("name")

        # Resubmit the trigger
        result = client.resubmit_flow_trigger(workflow_id, history_id)

        if wait:
            # Wait briefly for run to register, then find it
            time.sleep(2)
            run_list = client.list_flow_runs(workflow_id, top=1)
            if run_list:
                latest_run_id = run_list[0].get("name")
                run_result = _wait_for_run(client, workflow_id, latest_run_id, timeout)
                _print_flow_test_result(run_result)
            else:
                _print_flow_test_status("RunNotFound", "Could not find the triggered run")
        else:
            _print_flow_test_result(result)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("remove")
def agent_flow_remove(
    workflow_id: str = typer.Argument(
        ...,
        help="The agent flow's unique identifier (GUID)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip confirmation prompt and delete immediately",
    ),
):
    """
    Remove (delete) an agent flow.

    Deletes both draft and published agent flows. For published flows, the
    flow is automatically deactivated before deletion.

    This operation removes both the draft (definition) and published (activation)
    versions of the flow if they exist.

    WARNING: This action is irreversible. The flow and all its run history
    will be permanently deleted.

    Examples:
        copilot agent-flow remove <flow-id>
        copilot agent-flow remove <flow-id> --force
    """
    try:
        client = get_client()

        # Get flow info first to show what will be deleted
        try:
            flow = client.get(
                f"workflows({workflow_id})/Microsoft.Dynamics.CRM.RetrieveUnpublished()"
                f"?$select=workflowid,name,type,statecode"
            )
        except Exception:
            print_error(f"Agent flow {workflow_id} not found")
            raise typer.Exit(1)

        flow_name = flow.get("name", workflow_id)
        statecode = flow.get("statecode")
        status = "Published" if statecode == 1 else "Draft"

        # Confirm deletion unless --force flag is provided
        if not force:
            typer.echo(f"Flow: {flow_name}")
            typer.echo(f"ID: {workflow_id}")
            typer.echo(f"Status: {status}")
            typer.echo()
            confirm = typer.confirm(
                "Are you sure you want to delete this agent flow? This action cannot be undone",
                default=False,
            )
            if not confirm:
                typer.echo("Deletion cancelled.")
                raise typer.Exit(0)

        # Perform the deletion
        typer.echo(f"Deleting agent flow '{flow_name}'...", err=True)
        result = client.delete_agent_flow(workflow_id)

        print_success(f"Agent flow '{flow_name}' deleted successfully")
        if result.get("was_published"):
            typer.echo("Note: The flow was deactivated before deletion.", err=True)

    except typer.Exit:
        raise
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("enable")
def agent_flow_enable(
    workflow_id: str = typer.Argument(
        ...,
        help="The agent flow's unique identifier (GUID)",
    ),
):
    """
    Enable (activate) an agent flow.

    Changes a draft flow to activated state so it can receive triggers
    and execute. Flows created via the API start in Draft state and must
    be enabled before they can be used.

    If the flow is already activated, this command does nothing.

    Examples:
        copilot agent-flow enable <flow-id>
    """
    try:
        client = get_client()
        result = client.enable_agent_flow(workflow_id)

        flow_name = result.get("name", workflow_id)
        if result.get("was_draft"):
            print_success(f"Agent flow '{flow_name}' enabled successfully")
        else:
            typer.echo(f"Agent flow '{flow_name}' was already enabled")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("disable")
def agent_flow_disable(
    workflow_id: str = typer.Argument(
        ...,
        help="The agent flow's unique identifier (GUID)",
    ),
):
    """
    Disable (deactivate) an agent flow.

    Changes an activated flow back to draft state. The flow will no longer
    receive triggers or execute until re-enabled.

    If the flow is already in draft state, this command does nothing.

    Examples:
        copilot agent-flow disable <flow-id>
    """
    try:
        client = get_client()
        result = client.disable_agent_flow(workflow_id)

        flow_name = result.get("name", workflow_id)
        if result.get("was_activated"):
            print_success(f"Agent flow '{flow_name}' disabled successfully")
        else:
            typer.echo(f"Agent flow '{flow_name}' was already in draft state")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


def _extract_response_body(client, run_data: dict):
    """Extract the HTTP response body from a flow run's Response action.

    Agent flows that end with a "Respond to the agent" (Response) action
    have their output available via the action's outputsLink SAS URL.

    Returns:
        The parsed JSON body from the Response action, or None if not found.
    """
    import httpx

    props = run_data.get("properties", {})
    actions = props.get("actions", {})

    # Look for the Response action by name pattern.
    # Flow definitions use names like Respond_Success, Respond_To_Parent,
    # Respond_Not_Found, Response, etc. Only consider the one that actually
    # executed successfully (flows may have multiple Response actions for
    # different branches).
    for action_name, action_data in actions.items():
        name_lower = action_name.lower()
        if (name_lower.startswith("respond") or name_lower.startswith("response")) and action_data.get("status") == "Succeeded":
            outputs_link = action_data.get("outputsLink", {})
            uri = outputs_link.get("uri")
            if uri:
                try:
                    resp = httpx.get(uri, timeout=30.0)
                    resp.raise_for_status()
                    output_data = resp.json()
                    # The output contains statusCode and body
                    body = output_data.get("body")
                    if body is not None:
                        return body
                    return output_data
                except Exception as e:
                    typer.echo(f"Warning: Failed to fetch response body: {e}", err=True)
                    return None

    return None


def _print_flow_test_result(result: dict):
    """Print the machine-readable agent-flow test result."""
    print_json(result)


def _print_flow_test_status(status: str, message: str):
    """Print a machine-readable agent-flow test status message."""
    _print_flow_test_result({"status": status, "message": message})


def _wait_for_run(client, workflow_id: str, run_id: str, timeout: int) -> dict:
    """Wait for a flow run to complete and display results.

    Returns:
        dict with run_id, status, duration, and body (response body from
        the flow's Response action, if present) for easy parsing.
    """
    start_time = time.time()
    poll_interval = 3  # seconds
    final_status = "Unknown"
    final_duration = ""

    while time.time() - start_time < timeout:
        run_data = client.get_flow_run(workflow_id, run_id, expand_actions=True)
        props = run_data.get("properties", {})
        status = props.get("status", "")

        if status in ("Succeeded", "Failed", "Cancelled", "TimedOut"):
            final_status = status
            # Calculate duration
            if props.get("startTime") and props.get("endTime"):
                try:
                    from datetime import datetime
                    start = datetime.fromisoformat(props["startTime"].replace("Z", "+00:00"))
                    end = datetime.fromisoformat(props["endTime"].replace("Z", "+00:00"))
                    delta = end - start
                    final_duration = f"{delta.total_seconds():.2f}s"
                except Exception:
                    pass

            result = {"run_id": run_id, "status": final_status, "duration": final_duration}

            # Extract response body from Response action if present
            response_body = _extract_response_body(client, run_data)
            if response_body is not None:
                result["body"] = response_body

            return result

        time.sleep(poll_interval)

    return {"run_id": run_id, "status": "Timeout", "duration": f"{timeout}s"}


def _display_run_details(run_data: dict, full_data_to_stderr: bool = False):
    """Display detailed run results including action outputs.

    Args:
        run_data: The full run data dict from the API.
        full_data_to_stderr: If True, send the full JSON dump to stderr instead
            of stdout. Used by ``agent-flow test --wait`` to keep stdout clean
            for the structured result object.
    """
    props = run_data.get("properties", {})

    # Basic run info
    run_info = {
        "id": run_data.get("name", ""),
        "status": props.get("status", ""),
        "startTime": props.get("startTime", ""),
        "endTime": props.get("endTime", ""),
    }

    # Calculate duration
    if props.get("startTime") and props.get("endTime"):
        try:
            from datetime import datetime
            start = datetime.fromisoformat(props["startTime"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(props["endTime"].replace("Z", "+00:00"))
            delta = end - start
            run_info["duration"] = f"{delta.total_seconds():.2f}s"
        except Exception:
            pass

    typer.echo("\n=== Run Summary ===", err=True)
    for key, value in run_info.items():
        typer.echo(f"  {key}: {value}", err=True)

    # Error details if failed
    error = props.get("error")
    if error:
        typer.echo("\n=== Error Details ===", err=True)
        print_error(json.dumps(error, indent=2))

    # Action results
    actions = props.get("actions", {})
    if actions:
        typer.echo("\n=== Action Results ===", err=True)

        # Sort actions by start time if available
        action_list = []
        for name, data in actions.items():
            action_list.append((name, data))

        # Sort by startTime
        action_list.sort(key=lambda x: x[1].get("startTime", ""))

        for name, data in action_list:
            status = data.get("status", "Unknown")
            duration = ""
            if data.get("startTime") and data.get("endTime"):
                try:
                    from datetime import datetime
                    start = datetime.fromisoformat(data["startTime"].replace("Z", "+00:00"))
                    end = datetime.fromisoformat(data["endTime"].replace("Z", "+00:00"))
                    delta = end - start
                    duration = f" ({delta.total_seconds():.2f}s)"
                except Exception:
                    pass

            status_icon = safe_symbol("check") if status == "Succeeded" else safe_symbol("cross") if status == "Failed" else safe_symbol("circle")
            typer.echo(f"  {status_icon} {name}: {status}{duration}", err=True)

            # Show error details for failed actions
            if status == "Failed":
                action_error = data.get("error")
                if action_error:
                    typer.echo(f"      Error: {json.dumps(action_error, indent=6)}", err=True)

                # Show inputs/outputs links for debugging
                if data.get("inputsLink"):
                    typer.echo(f"      Inputs: {data['inputsLink'].get('uri', 'N/A')}", err=True)
                if data.get("outputsLink"):
                    typer.echo(f"      Outputs: {data['outputsLink'].get('uri', 'N/A')}", err=True)

    # Full JSON output
    typer.echo("\n=== Full Run Data ===", err=True)
    if full_data_to_stderr:
        typer.echo(json.dumps(run_data, indent=2, default=str), err=True)
    else:
        print_json(run_data)


@app.command("actions")
def agent_flow_actions(
    workflow_id: str = typer.Argument(
        ...,
        help="The agent flow's unique identifier (GUID)",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display output as a formatted table",
    ),
):
    """
    List all actions in an agent flow.

    Shows all actions defined in the flow with their types.
    For HTTP actions, the target URI is shown.

    Note: Trigger information is now shown in 'agent-flow list' and
    'agent-flow get' commands.

    Examples:
        copilot agent-flow actions <flow-id>
        copilot agent-flow actions <flow-id> --table
    """
    try:
        client = get_client()

        # Get flow definition
        flow = client.get(
            f"workflows({workflow_id})/Microsoft.Dynamics.CRM.RetrieveUnpublished()"
            f"?$select=workflowid,name,clientdata"
        )

        client_data = flow.get("clientdata")
        if not client_data:
            print_error("Flow has no definition")
            raise typer.Exit(1)

        # Parse clientdata JSON
        try:
            definition = json.loads(client_data)
        except json.JSONDecodeError:
            print_error("Failed to parse flow definition")
            raise typer.Exit(1)

        props = definition.get("properties", {})
        flow_def = props.get("definition", {})

        results = []

        # Process actions only (triggers moved to list/get commands)
        actions = flow_def.get("actions", {})
        for action_name, action_data in actions.items():
            action_type = action_data.get("type", "Unknown")

            item = {
                "name": action_name,
                "type": action_type,
                "url": None,
            }

            # For HTTP actions, show the URI if available
            if action_type == "Http":
                inputs = action_data.get("inputs", {})
                uri = inputs.get("uri", "")
                if uri:
                    item["url"] = uri

            results.append(item)

        if not results:
            typer.echo("No actions found in this flow.")
            return

        if table:
            # For table, show condensed view
            table_data = []
            for r in results:
                row = {
                    "name": r["name"],
                    "type": r["type"],
                }
                if r["url"]:
                    row["url"] = r["url"][:60] + "..." if len(r["url"]) > 60 else r["url"]
                else:
                    row["url"] = ""
                table_data.append(row)

            print_table(
                table_data,
                columns=["name", "type", "url"],
                headers=["Name", "Type", "URL"],
            )
        else:
            print_json(results)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)
