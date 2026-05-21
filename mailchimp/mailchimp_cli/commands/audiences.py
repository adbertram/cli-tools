"""Audiences/Lists commands for Mailchimp CLI."""
import typer
from typing import List, Optional

from cli_tools_shared.filters import apply_filters, apply_limit, apply_properties_filter
from cli_tools_shared.output import print_json, print_table, handle_error, print_success

from ..client import get_client

app = typer.Typer(help="Manage Mailchimp audiences/lists")


@app.command("list")
def audiences_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum number of audiences to return"),
    offset: int = typer.Option(0, "--offset", "-o", help="Offset for pagination"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List all audiences/lists in the account.

    Examples:
        mailchimp audiences list
        mailchimp audiences list --table
        mailchimp audiences list --count 20
    """
    try:
        client = get_client()
        result = client.list_audiences(count=limit, offset=offset)

        lists = result.get("lists", [])
        lists = apply_filters(lists, filter)
        lists = apply_limit(lists, limit)
        lists = apply_properties_filter(lists, properties)

        if table:
            columns = [field.strip() for field in properties.split(",")] if properties else ["id", "name", "stats.member_count", "stats.unsubscribe_count"]
            headers = [column.replace("_", " ").replace(".", " ").title() for column in columns]
            print_table(lists, columns, headers)
        else:
            print_json(lists)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def audiences_get(
    list_id: str = typer.Argument(..., help="The list/audience ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
):
    """
    Get details for a specific audience/list.

    Examples:
        mailchimp audiences get LIST_ID
        mailchimp audiences get LIST_ID --table
    """
    try:
        client = get_client()
        audience = client.get_audience(list_id)

        if table:
            stats = audience.get("stats", {})
            contact = audience.get("contact", {})
            summary = [{
                "id": audience.get("id", ""),
                "name": audience.get("name", ""),
                "members": stats.get("member_count", 0),
                "company": contact.get("company", ""),
                "created": audience.get("date_created", ""),
            }]

            print_table(
                summary,
                ["id", "name", "members", "company", "created"],
                ["ID", "Name", "Members", "Company", "Created"],
            )
        else:
            print_json(audience)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def audiences_create(
    name: str = typer.Option(..., "--name", "-n", help="List name"),
    company: str = typer.Option(..., "--company", "-c", help="Company name"),
    address1: str = typer.Option(..., "--address1", help="Address line 1"),
    city: str = typer.Option(..., "--city", help="City"),
    state: str = typer.Option(..., "--state", help="State/Province"),
    zip_code: str = typer.Option(..., "--zip", help="Postal code"),
    country: str = typer.Option(..., "--country", help="Country (2-letter code)"),
    from_email: str = typer.Option(..., "--from-email", help="From email address"),
    from_name: str = typer.Option(..., "--from-name", help="From name"),
    permission_reminder: str = typer.Option(
        "You are receiving this email because you signed up.",
        "--permission-reminder",
        help="Permission reminder text",
    ),
):
    """
    Create a new audience/list.

    Example:
        mailchimp audiences create --name "Newsletter" --company "ACME Inc" \\
            --address1 "123 Main St" --city "New York" --state "NY" \\
            --zip "10001" --country "US" --from-email "news@example.com" \\
            --from-name "ACME Newsletter"
    """
    try:
        client = get_client()

        data = {
            "name": name,
            "contact": {
                "company": company,
                "address1": address1,
                "city": city,
                "state": state,
                "zip": zip_code,
                "country": country,
            },
            "permission_reminder": permission_reminder,
            "campaign_defaults": {
                "from_email": from_email,
                "from_name": from_name,
                "subject": "",
                "language": "en",
            },
            "email_type_option": True,
        }

        result = client.create_audience(data)
        print_success(f"Created audience: {result.get('id')}")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "create": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ]
}
