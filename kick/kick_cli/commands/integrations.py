"""Integrations commands for Kick CLI."""
import typer
from typing import Optional, List

from cli_tools_shared.filters import apply_filters
from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error

app = typer.Typer(help="Manage Kick integrations (linked financial accounts)")


def get_integration_name(integ: dict) -> str:
    """Get the display name for an integration."""
    # Try bankName first (Plaid connections), then fall back to provider-specific names
    return integ.get("bankName") or integ.get("connectionProvider") or ""


def get_integration_provider(integ: dict) -> str:
    """Get the provider name for an integration."""
    return integ.get("connectionProvider") or ""


@app.command("list")
def integrations_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of integrations to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of properties to display"),
    provider: Optional[str] = typer.Option(None, "--provider", help="Filter by provider (e.g., Plaid, Stripe)"),
):
    """
    List all integrations.

    Integrations represent linked financial accounts such as banks (via Plaid),
    PayPal, Stripe, and other payment processors.

    Examples:
        kick integrations list
        kick integrations list --table
        kick integrations list --provider Plaid --table
    """
    try:
        client = get_client()
        integrations = client.list_integrations()

        # Filter by provider if specified
        if provider:
            integrations = [i for i in integrations if get_integration_provider(i).lower() == provider.lower()]

        # Apply client-side filtering
        if filter:
            integrations = apply_filters(integrations, filter)

        # Apply limit
        integrations = integrations[:limit]

        if table:
            table_data = []
            for integ in integrations:
                # Get financial account info from accounts
                accounts = integ.get("accounts", [])
                financial_account_ids = [str(a.get("financialAccountId", "")) for a in accounts]
                entity_names = []
                for a in accounts:
                    fa = a.get("financialAccount", {})
                    entity = fa.get("entity", {})
                    if entity.get("name"):
                        entity_names.append(entity.get("name"))

                # Determine source type
                source = integ.get("_source", "")
                if source == "integration_connection":
                    source_label = "Direct"
                elif integ.get("connectionProvider") == "Plaid":
                    source_label = "Plaid"
                else:
                    source_label = integ.get("connectionProvider", "")

                table_data.append({
                    "id": integ.get("id", ""),
                    "name": get_integration_name(integ),
                    "source": source_label,
                    "status": "error" if integ.get("error") else "ok",
                    "accounts": len(accounts),
                    "entities": ", ".join(sorted(set(entity_names))) if entity_names else "",
                    "created": integ.get("createdAt", "")[:10] if integ.get("createdAt") else "",
                })

            print_table(
                table_data,
                ["id", "name", "source", "status", "accounts", "entities", "created"],
                ["ID", "Name", "Source", "Status", "Accounts", "Entities", "Created"],
            )
            from cli_tools_shared.output import print_info
            print_info(f"Found {len(integrations)} integrations")
        else:
            print_json(integrations)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def integrations_get(
    integration_id: str = typer.Argument(..., help="The integration ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get details for a specific integration.

    Examples:
        kick integrations get 8531
        kick integrations get 8531 --table
    """
    try:
        client = get_client()
        integ = client.get_integration(integration_id)

        if table:
            # Show integration summary
            accounts = integ.get("accounts", [])

            summary = [{
                "id": integ.get("id", ""),
                "name": get_integration_name(integ),
                "provider": get_integration_provider(integ),
                "external_id": integ.get("connectionExternalId", ""),
                "created": integ.get("createdAt", "")[:10] if integ.get("createdAt") else "",
                "error": integ.get("error") or "",
            }]

            print_table(
                summary,
                ["id", "name", "provider", "external_id", "created", "error"],
                ["ID", "Name", "Provider", "External ID", "Created", "Error"],
            )

            # Show linked financial accounts
            if accounts:
                from cli_tools_shared.output import print_info
                typer.echo("")  # Blank line
                print_info(f"Linked Financial Accounts ({len(accounts)}):")

                account_data = []
                for a in accounts:
                    fa = a.get("financialAccount", {})
                    entity = fa.get("entity", {})
                    balance = fa.get("balance")
                    # Format balance - divide by 100 if it looks like cents
                    if balance is not None:
                        balance_str = f"${balance:,.2f}"
                    else:
                        balance_str = ""

                    account_data.append({
                        "financial_account_id": fa.get("id", ""),
                        "name": fa.get("name", ""),
                        "type": fa.get("financialType", ""),
                        "entity": entity.get("name", ""),
                        "balance": balance_str,
                        "synced": a.get("transactionsSyncedAt", "")[:10] if a.get("transactionsSyncedAt") else "",
                    })

                print_table(
                    account_data,
                    ["financial_account_id", "name", "type", "entity", "balance", "synced"],
                    ["Financial Acct ID", "Name", "Type", "Entity", "Balance", "Last Synced"],
                )
        else:
            print_json(integ)

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ]
}
