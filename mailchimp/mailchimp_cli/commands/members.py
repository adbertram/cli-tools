"""Members/Subscribers commands for Mailchimp CLI."""
import typer
import hashlib
from typing import List, Optional

from cli_tools_shared.filters import apply_filters, apply_limit, apply_properties_filter
from cli_tools_shared.output import print_json, print_table, handle_error, print_success, print_error, print_info

from ..client import get_client

app = typer.Typer(help="Manage list members/subscribers")


def email_to_hash(email: str) -> str:
    """Convert email to MD5 hash for API calls."""
    return hashlib.md5(email.lower().encode()).hexdigest()


@app.command("list")
def members_list(
    list_id: str = typer.Argument(..., help="The list/audience ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum number of members to return"),
    offset: int = typer.Option(0, "--offset", "-o", help="Offset for pagination"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status (subscribed, unsubscribed, cleaned, pending)"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List members of a specific audience/list.

    Examples:
        mailchimp members list LIST_ID
        mailchimp members list LIST_ID --table
        mailchimp members list LIST_ID --status subscribed
        mailchimp members list LIST_ID --count 50
    """
    try:
        client = get_client()

        kwargs = {}
        if status:
            kwargs["status"] = status

        result = client.list_members(list_id, count=limit, offset=offset, **kwargs)
        members = result.get("members", [])
        members = apply_filters(members, filter)
        members = apply_limit(members, limit)
        members = apply_properties_filter(members, properties)

        if table:
            columns = [field.strip() for field in properties.split(",")] if properties else ["email_address", "status", "merge_fields.FNAME", "timestamp_opt"]
            headers = [column.replace("_", " ").replace(".", " ").title() for column in columns]
            print_table(members, columns, headers)
        else:
            print_json(members)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def members_get(
    list_id: str = typer.Argument(..., help="The list/audience ID"),
    email: str = typer.Argument(..., help="Member email address"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
):
    """
    Get information about a specific list member.

    Examples:
        mailchimp members get LIST_ID user@example.com
        mailchimp members get LIST_ID user@example.com --table
    """
    try:
        client = get_client()
        subscriber_hash = email_to_hash(email)
        member = client.get_member(list_id, subscriber_hash)

        if table:
            merge_fields = member.get("merge_fields", {})
            summary = [{
                "email": member.get("email_address", ""),
                "status": member.get("status", ""),
                "name": f"{merge_fields.get('FNAME', '')} {merge_fields.get('LNAME', '')}".strip() or "N/A",
                "subscribed": member.get("timestamp_opt", "N/A"),
                "rating": member.get("member_rating", "N/A"),
            }]

            print_table(
                summary,
                ["email", "status", "name", "subscribed", "rating"],
                ["Email", "Status", "Name", "Subscribed Date", "Rating"],
            )
        else:
            print_json(member)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("add")
def members_add(
    list_id: str = typer.Argument(..., help="The list/audience ID"),
    email: str = typer.Option(..., "--email", "-e", help="Member email address"),
    status: str = typer.Option("subscribed", "--status", "-s", help="Subscription status (subscribed, pending)"),
    first_name: Optional[str] = typer.Option(None, "--first-name", "-f", help="First name"),
    last_name: Optional[str] = typer.Option(None, "--last-name", "-l", help="Last name"),
):
    """
    Add a new member to a list.

    Examples:
        mailchimp members add LIST_ID --email user@example.com
        mailchimp members add LIST_ID --email user@example.com --status pending
        mailchimp members add LIST_ID --email user@example.com \\
            --first-name John --last-name Doe
    """
    try:
        client = get_client()

        data = {
            "email_address": email,
            "status": status,
        }

        if first_name or last_name:
            data["merge_fields"] = {}
            if first_name:
                data["merge_fields"]["FNAME"] = first_name
            if last_name:
                data["merge_fields"]["LNAME"] = last_name

        result = client.add_member(list_id, data)
        print_success(f"Added member: {email}")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def members_update(
    list_id: str = typer.Argument(..., help="The list/audience ID"),
    email: str = typer.Argument(..., help="Member email address"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Subscription status"),
    first_name: Optional[str] = typer.Option(None, "--first-name", "-f", help="First name"),
    last_name: Optional[str] = typer.Option(None, "--last-name", "-l", help="Last name"),
):
    """
    Update a list member.

    Examples:
        mailchimp members update LIST_ID user@example.com --status unsubscribed
        mailchimp members update LIST_ID user@example.com --first-name Jane
    """
    try:
        client = get_client()
        subscriber_hash = email_to_hash(email)

        data = {}
        if status:
            data["status"] = status

        if first_name or last_name:
            data["merge_fields"] = {}
            if first_name:
                data["merge_fields"]["FNAME"] = first_name
            if last_name:
                data["merge_fields"]["LNAME"] = last_name

        if not data:
            print_error("No update fields provided")
            raise typer.Exit(1)

        result = client.update_member(list_id, subscriber_hash, data)
        print_success(f"Updated member: {email}")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("remove")
def members_remove(
    list_id: str = typer.Argument(..., help="The list/audience ID"),
    email: str = typer.Argument(..., help="Member email address"),
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """
    Remove a member from a list.

    Examples:
        mailchimp members remove LIST_ID user@example.com
        mailchimp members remove LIST_ID user@example.com --yes
    """
    try:
        if not confirm:
            confirm = typer.confirm(f"Are you sure you want to remove {email}?")
            if not confirm:
                print_info("Cancelled")
                raise typer.Exit(0)

        client = get_client()
        subscriber_hash = email_to_hash(email)
        client.delete_member(list_id, subscriber_hash)
        print_success(f"Removed member: {email}")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("search")
def members_search(
    query: str = typer.Argument(..., help="Email address to search for"),
    list_id: Optional[str] = typer.Option(None, "--list-id", "-l", help="Search within specific list"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Search for list members by email address.

    Examples:
        mailchimp members search user@example.com
        mailchimp members search user@example.com --list-id LIST_ID
        mailchimp members search user@example.com --table
    """
    try:
        client = get_client()
        result = client.search_members(query, list_id)

        exact_matches = result.get("exact_matches", {}).get("members", [])
        full_search = result.get("full_search", {}).get("members", [])
        all_results = exact_matches + full_search

        if table:
            table_data = []
            for member in all_results:
                merge_fields = member.get("merge_fields", {})
                table_data.append({
                    "email": member.get("email_address", ""),
                    "list_id": member.get("list_id", ""),
                    "status": member.get("status", ""),
                    "name": f"{merge_fields.get('FNAME', '')} {merge_fields.get('LNAME', '')}".strip() or "N/A",
                })

            print_table(
                table_data,
                ["email", "list_id", "status", "name"],
                ["Email", "List ID", "Status", "Name"],
            )
        else:
            print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "add": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "remove": [
        "custom"
    ],
    "search": [
        "custom"
    ],
    "update": [
        "custom"
    ]
}
