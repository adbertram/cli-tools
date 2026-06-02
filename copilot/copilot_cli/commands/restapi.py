"""REST API commands for listing custom connectors available as agent tools."""
import typer
from typing import Optional

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error


app = typer.Typer(help="Manage REST API tools (custom connectors)")


def format_restapi_for_display(connector: dict, truncate: bool = False) -> dict:
    """Format a REST API connector for display.

    Args:
        connector: The connector dict from the API
        truncate: If True, truncate long values for table display
    """
    name = connector.get("displayname") or connector.get("name", "")
    connector_id = connector.get("connectorid", "")

    # Get description
    description = connector.get("description") or ""
    if truncate and len(description) > 60:
        description = description[:57] + "..."

    # Get state
    state_code = connector.get("statecode", 0)
    state = "Active" if state_code == 0 else "Inactive"

    # Get owner
    owner = connector.get("_ownerid_value@OData.Community.Display.V1.FormattedValue", "")

    # Get created/modified dates
    created = connector.get("createdon", "")
    if created:
        created = created.split("T")[0]

    modified = connector.get("modifiedon", "")
    if modified:
        modified = modified.split("T")[0]

    # Check if managed
    is_managed = connector.get("ismanaged", False)

    return {
        "name": name,
        "id": connector_id,
        "state": state,
        "owner": owner,
        "description": description,
        "created": created,
        "modified": modified,
        "managed": is_managed,
    }


@app.command("list")
def restapi_list(
    filter: Optional[list[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., name:ilike:%podio%)",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
        help="Maximum number of REST API tools to return",
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
    List all REST API tools (custom connectors) available for agents.

    REST API tools are custom connectors defined with OpenAPI specifications
    that can be attached to Copilot Studio agents as tools. They allow agents
    to call external REST APIs.

    Examples:
        copilot restapi list
        copilot restapi list --table
        copilot restapi list --filter "name:ilike:%podio%" --table
        copilot restapi list --limit 50
    """
    from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
    from cli_tools_shared.output import print_error

    try:
        client = get_client()
        use_table = table or output == "table"
        connectors = client.list_rest_apis()

        if not connectors:
            if use_table:
                print_table([], columns=["name", "id"], headers=["Name", "ID"])
            else:
                print_json([])
            return

        # Apply filters using standard field:op:value syntax
        if filter:
            try:
                validate_filters(filter)
                connectors = apply_filters(connectors, filter)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        if not connectors:
            if use_table:
                print_table([], columns=["name", "id"], headers=["Name", "ID"])
            else:
                print_json([])
            return

        # Apply limit
        connectors = connectors[:limit]

        formatted = [format_restapi_for_display(c, truncate=use_table) for c in connectors]

        # Sort by name
        formatted.sort(key=lambda x: x["name"].lower())

        # Apply properties filter
        if properties:
            property_list = [p.strip() for p in properties.split(",")]
            formatted = [{k: v for k, v in item.items() if k in property_list} for item in formatted]

        if use_table:
            if properties:
                property_list = [p.strip() for p in properties.split(",")]
                print_table(formatted, columns=property_list, headers=property_list)
            else:
                print_table(
                    formatted,
                    columns=["name", "state", "owner", "description", "id"],
                    headers=["Name", "State", "Owner", "Description", "ID"],
                )
        else:
            print_json(formatted)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("get")
def restapi_get(
    connector_id: str = typer.Argument(
        ...,
        help="The REST API connector's unique identifier (GUID)",
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
    Get details for a specific REST API tool.

    Examples:
        copilot restapi get abcdef01-2345-6789-abcd-ef0123456789
        copilot restapi get abcdef01-2345-6789-abcd-ef0123456789 --table
    """
    try:
        client = get_client()
        connector = client.get_rest_api(connector_id)

        use_table = table or output == "table"
        if use_table:
            formatted = format_restapi_for_display(connector, truncate=True)
            print_table(
                [formatted],
                columns=["name", "state", "owner", "description", "id"],
                headers=["Name", "State", "Owner", "Description", "ID"],
            )
        else:
            formatted = format_restapi_for_display(connector, truncate=False)
            print_json(formatted)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)
