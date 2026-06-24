"""User license commands for checking Microsoft 365 license assignments via MS Graph API."""
import typer
import httpx
from typing import Optional

from ..client import get_access_token, ClientError
from cli_tools_shared.output import print_json, print_table, handle_error, command


app = typer.Typer(help="Check user license assignments via Microsoft Graph")

COMMAND_CREDENTIALS = {
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ]
}


def _fetch_user_licenses(user_principal_name: str) -> list[dict]:
    """Fetch and format license assignments for a user."""
    graph_token = get_access_token("https://graph.microsoft.com")

    with httpx.Client(timeout=30.0) as client:
        response = client.get(
            f"https://graph.microsoft.com/v1.0/users/{user_principal_name}/licenseDetails",
            headers={"Authorization": f"Bearer {graph_token}"},
        )
        if response.status_code != 200:
            raise ClientError(
                f"Failed to get licenses for '{user_principal_name}': "
                f"{response.status_code} {response.text[:300]}"
            )

        license_details = response.json().get("value", [])

    formatted = []
    for lic in license_details:
        service_plans = [
            {
                "name": sp.get("servicePlanName", ""),
                "status": sp.get("provisioningStatus", ""),
            }
            for sp in lic.get("servicePlans", [])
        ]
        service_plans.sort(key=lambda x: x["name"])

        formatted.append({
            "sku": lic.get("skuPartNumber", ""),
            "sku_id": lic.get("skuId", ""),
            "service_plans": service_plans,
        })

    formatted.sort(key=lambda x: x["sku"])
    return formatted


def _emit_user_licenses(
    formatted: list[dict],
    table: bool,
    output: Optional[str],
    properties: Optional[str],
    filter: Optional[list[str]],
    limit: int,
) -> None:
    if filter:
        from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
        try:
            validate_filters(filter)
            formatted = apply_filters(formatted, filter)
        except FilterValidationError as e:
            from cli_tools_shared.output import print_error
            print_error(str(e))
            raise typer.Exit(1)

    formatted = formatted[:limit]

    if properties:
        property_list = [p.strip() for p in properties.split(",")]
        formatted = [
            {k: v for k, v in item.items() if k in property_list}
            for item in formatted
        ]

    use_table = table or output == "table"
    if use_table:
        rows = []
        for lic in formatted:
            sku = lic.get("sku", "")
            for sp in lic.get("service_plans", []):
                rows.append({
                    "sku": sku,
                    "service_plan": sp["name"],
                    "status": sp["status"],
                })
        if not rows:
            rows = [{"sku": "(none)", "service_plan": "", "status": ""}]
        print_table(
            rows,
            columns=["sku", "service_plan", "status"],
            headers=["SKU", "Service Plan", "Status"],
        )
    else:
        print_json(formatted)


def _list_options(
    user_principal_name: str,
    table: bool,
    output: Optional[str],
    properties: Optional[str],
    filter: Optional[list[str]],
    limit: int,
) -> None:
    try:
        formatted = _fetch_user_licenses(user_principal_name)
        _emit_user_licenses(formatted, table, output, properties, filter, limit)
    except typer.Exit:
        raise
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("list")
@command
def list_licenses(
    user_principal_name: str = typer.Argument(
        ...,
        help="User principal name (e.g., user@domain.com)",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display flat table of all service plans"),
    filter: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of license SKUs to return"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output format: json (default) or table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List license assignments for a user."""
    _list_options(user_principal_name, table, output, properties, filter, limit)


@app.command("get")
@command
def get_licenses(
    user_principal_name: str = typer.Argument(..., help="User principal name (e.g., user@domain.com)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display flat table of all service plans"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output format: json (default) or table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get license assignments for a user."""
    _list_options(user_principal_name, table, output, properties, None, 100)
