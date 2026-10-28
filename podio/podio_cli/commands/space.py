"""Space commands for Podio CLI."""

COMMAND_CREDENTIALS = {
    "find-by-url": [
        "oauth_authorization_code"
    ],
    "get": [
        "oauth_authorization_code"
    ],
    "list": [
        "oauth_authorization_code"
    ],
    "member": [
        "oauth_authorization_code"
    ]
}
import json
from enum import Enum
from urllib.parse import urlencode
import typer
from typing import List, Optional, Any

from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
from ..client import get_client
from ..config import get_config
from cli_tools_shared.output import command
from ..output import print_json, print_output, print_success, print_error, print_warning, handle_api_error, format_response
from pypodio2.transport import TransportException
from ..filter_map import FilterMap, apply_properties

app = typer.Typer(help="Manage Podio spaces")

member_app = typer.Typer(help="Manage Podio space members")
app.add_typer(member_app, name="member")


class MemberRole(str, Enum):
    regular = "regular"
    light = "light"
    admin = "admin"


@app.command("get")
@command
def get_space(
    space_id: Optional[int] = typer.Argument(None, help="Space ID to retrieve"),
    url: Optional[str] = typer.Option(None, "--url", "-u", help="Find space by Podio URL"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Get a Podio space by ID or URL.

    If neither space_id nor url is provided, uses PODIO_WORKSPACE_ID from environment.

    Examples:
        podio space get 12345
        podio space get --url https://podio.com/org/workspace
        podio space get  # Uses PODIO_WORKSPACE_ID
        podio space get --table
    """
    try:
        client = get_client()

        if url:
            # Look up by URL
            result = client.Space.find_by_url(space_url=url, id_only=False)
        elif space_id:
            # Look up by space ID
            result = client.Space.find(space_id=space_id)
        else:
            # Use workspace_id from config
            config = get_config()
            if config.workspace_id:
                result = client.Space.find(space_id=int(config.workspace_id))
            else:
                print_error("No space_id provided and WORKSPACE_ID not set in environment")
                raise typer.Exit(1)

        formatted = format_response(result)
        print_output(formatted, table=table)
    except TransportException as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("list")
@command
def list_spaces(
    org_id: Optional[int] = typer.Option(None, "--org-id", "-o", help="Organization ID to list spaces from (defaults to PODIO_ORGANIZATION_ID)"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum spaces to return"),
    filter: Optional[str] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of fields to include"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    List all spaces in an organization.

    If org_id is not provided, uses PODIO_ORGANIZATION_ID from environment.

    Examples:
        podio space list --org-id 3747840
        podio space list  # Uses PODIO_ORGANIZATION_ID
        podio space list --limit 10
        podio space list --filter "name:Progress"
        podio space list --properties "space_id,name"
        podio space list --table
    """
    try:
        # Use organization_id from config if org_id not provided
        if org_id is None:
            config = get_config()
            if config.organization_id:
                org_id = int(config.organization_id)
            else:
                print_error("No org_id provided and PODIO_ORGANIZATION_ID not set in environment")
                raise typer.Exit(1)

        client = get_client()
        result = client.Space.find_all_for_org(org_id=org_id)
        formatted = format_response(result)

        # Apply client-side filtering
        if filter and isinstance(formatted, list):
            formatted = apply_filters(formatted, filter)

        # Apply limit (client-side)
        if isinstance(formatted, list) and len(formatted) > limit:
            formatted = formatted[:limit]

        # Apply properties filter
        if properties:
            formatted = apply_properties(formatted, properties)

        print_output(formatted, table=table)
    except TransportException as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("find-by-url", hidden=True)
@command
def find_space_by_url_deprecated(
    url: str = typer.Argument(..., help="Podio space URL"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """[DEPRECATED] Use 'podio space get --url <url>' instead."""
    print_warning("'podio space find-by-url' is deprecated. Use 'podio space get --url <url>' instead.")
    return get_space(url=url, table=table)



@member_app.command("list")
@command
def list_members(
    space_id: int = typer.Argument(..., help="Space ID to list members of"),
    member_type: Optional[str] = typer.Option(None, "--member-type", help="Only this member type: employee, external, admin, regular, light, guest"),
    query: Optional[str] = typer.Option(None, "--query", "-q", help="Search term matched against members"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum members to return"),
    offset: int = typer.Option(0, "--offset", help="Position in the member list to start from"),
    filter: Optional[str] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., role:eq:admin, profile.name:contains:Adam)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of fields to include"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    List the members of a space (GET /space/{space_id}/member/v2/).

    Each member has profile, employee, role (light, regular, admin or blank), grants and is_partner.

    Examples:
        podio space member list 12345
        podio space member list 12345 --member-type admin
        podio space member list 12345 --query adam --limit 10
        podio space member list 12345 --filter "role:eq:admin"
        podio space member list 12345 --properties "profile,role"
        podio space member list 12345 --table
    """
    try:
        params = {"limit": limit, "offset": offset}
        if member_type:
            params["member_type"] = member_type
        if query:
            params["query"] = query

        client = get_client()
        result = client.transport.GET(url=f"/space/{space_id}/member/v2/?{urlencode(params)}")
        formatted = format_response(result)

        if filter and isinstance(formatted, list):
            formatted = apply_filters(formatted, [filter])
        if properties:
            formatted = apply_properties(formatted, properties)

        print_output(formatted, table=table)
    except TransportException as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@member_app.command("get")
@command
def get_member(
    space_id: int = typer.Argument(..., help="Space ID"),
    user_id: int = typer.Argument(..., help="User ID of the member"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Get the membership details of one user on a space (GET /space/{space_id}/member/{user_id}/v2).

    Examples:
        podio space member get 12345 77109345
        podio space member get 12345 77109345 --table
    """
    try:
        client = get_client()
        result = client.transport.GET(url=f"/space/{space_id}/member/{user_id}/v2")
        print_output(format_response(result), table=table)
    except TransportException as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@member_app.command("add")
@command
def add_members(
    space_id: int = typer.Argument(..., help="Space ID to add members to"),
    email: List[str] = typer.Option(..., "--email", "-e", help="Email address to invite (repeat for several)"),
    role: MemberRole = typer.Option(..., "--role", "-r", help="Role of the new members"),
    message: Optional[str] = typer.Option(None, "--message", "-m", help="Personalized message for the invitation"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Add users to a space by email (POST /space/{space_id}/member/).

    Sends invitations to the given addresses, new or existing Podio users.

    Podio only allows this through the API for API clients with a trust level of
    2 or higher. Without it Podio answers HTTP 403 and this command exits 1;
    add the members in the Podio web app instead.

    Examples:
        podio space member add 12345 --email a@example.com --role regular
        podio space member add 12345 -e a@example.com -e b@example.com --role light --message "Welcome"
    """
    try:
        body = {"role": role.value, "mails": email}
        if message:
            body["message"] = message

        client = get_client()
        result = client.transport.POST(
            url=f"/space/{space_id}/member/", body=json.dumps(body), type="application/json"
        )
        print_success(f"Added {len(email)} member(s) to space {space_id}")
        print_output(
            {"space_id": space_id, "role": role.value, "emails": email, "response": format_response(result)},
            table=table,
        )
    except TransportException as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)
