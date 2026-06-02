"""Power Automate flow commands for listing available cloud flows."""
import typer
from typing import Optional

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error


app = typer.Typer(help="Manage Power Automate cloud flows")

COMMAND_CREDENTIALS = {
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ]
}


# Flow category mappings
FLOW_CATEGORIES = {
    0: "Automated",
    1: "Scheduled",
    2: "Button",
    3: "Approval",
    5: "Instant",
    6: "Business Process",
}


def get_category_name(category: int) -> str:
    """Get human-readable category name."""
    return FLOW_CATEGORIES.get(category, f"Category {category}")


def format_flow_for_display(flow: dict, truncate: bool = False) -> dict:
    """Format a flow for display.

    Args:
        flow: The flow dict from the API
        truncate: If True, truncate long values for table display
    """
    description = flow.get("description") or ""
    if truncate and len(description) > 80:
        description = description[:77] + "..."

    category = flow.get("category", 0)

    return {
        "name": flow.get("name"),
        "id": flow.get("workflowid"),
        "category": get_category_name(category),
        "description": description,
        "status": flow.get("statecode@OData.Community.Display.V1.FormattedValue", "Active"),
    }


@app.command("list")
def flow_list(
    category: Optional[int] = typer.Option(
        None,
        "--category",
        "-c",
        help="Filter by category: 0=Automated, 5=Instant, 6=Business Process",
    ),
    filter: Optional[list[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., name:ilike:%flow%)",
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
    List Power Automate cloud flows in the environment.

    This command lists flows stored in Dataverse that can potentially
    be used as tools in Copilot Studio agents.

    Categories:
      - 0: Automated (automated/scheduled flows)
      - 5: Instant (button/HTTP triggered flows)
      - 6: Business Process flows

    Note: Flows that work best as agent tools are typically Instant (5)
    flows with HTTP request triggers.

    Examples:
        copilot powerautomate-flow list
        copilot powerautomate-flow list --table
        copilot powerautomate-flow list --category 5
        copilot powerautomate-flow list --category 5 --table
        copilot powerautomate-flow list --filter "name:ilike:%flow%"
        copilot powerautomate-flow list --limit 50
        copilot powerautomate-flow list --properties "name,id,category"
    """
    from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError

    try:
        client = get_client()
        flows = client.list_flows(category=category)

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
        formatted = [format_flow_for_display(f, truncate=use_table) for f in flows]

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
                    columns=["name", "category", "status", "id"],
                    headers=["Name", "Category", "Status", "ID"],
                )
        else:
            print_json(formatted)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("get")
def flow_get(
    workflow_id: str = typer.Argument(
        ...,
        help="The flow's unique identifier (GUID)",
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
):
    """
    Get details for a specific Power Automate cloud flow.

    Examples:
        copilot powerautomate-flow get <flow-id>
        copilot powerautomate-flow get <flow-id> --table
    """
    try:
        client = get_client()
        flow = client.get_flow(workflow_id)

        use_table = table or output == "table"
        if use_table:
            formatted = format_flow_for_display(flow, truncate=True)
            print_table(
                [formatted],
                columns=["name", "category", "status", "id"],
                headers=["Name", "Category", "Status", "ID"],
            )
        else:
            formatted = format_flow_for_display(flow, truncate=False)
            print_json(formatted)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)
