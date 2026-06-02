"""Comment commands for Podio CLI."""

COMMAND_CREDENTIALS = {
    "create": [
        "oauth_authorization_code"
    ],
    "delete": [
        "oauth_authorization_code"
    ],
    "get": [
        "oauth_authorization_code"
    ],
    "list": [
        "oauth_authorization_code"
    ],
    "update": [
        "oauth_authorization_code"
    ]
}
import json
import sys
from typing import Optional, Any
from pathlib import Path
import typer

from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
from ..client import get_client
from ..output import print_json, print_output, print_error, print_success, handle_api_error, format_response
from ..filter_map import FilterMap, apply_properties

app = typer.Typer(help="Manage Podio comments")


@app.command("create")
def create_comment(
    ref_type: str = typer.Argument(..., help="Object type (e.g., 'item', 'status')"),
    ref_id: int = typer.Argument(..., help="Object ID"),
    text: Optional[str] = typer.Option(None, "--text", help="Comment text"),
    json_file: Optional[Path] = typer.Option(
        None,
        "--json-file",
        help="Path to JSON file with comment data",
    ),
    silent: bool = typer.Option(False, "--silent", help="Suppress notifications"),
    no_hook: bool = typer.Option(False, "--no-hook", help="Skip webhook execution"),
    alert_invite: bool = typer.Option(False, "--alert-invite", help="Auto-invite mentioned users"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Add a comment to a Podio object (item, status, etc.).

    You can provide comment text directly with --text, or use a JSON file for more complex
    comments with attachments or embeds.

    Comment data format:
        {
            "value": "Comment text",
            "external_id": "Optional external ID",
            "file_ids": [123, 456],
            "embed_id": 789,
            "embed_url": "https://example.com"
        }

    Examples:
        podio comment create item 12345 --text "This is a comment"
        podio comment create item 12345 --json-file comment.json
        podio comment create item 12345 --text "Great work!" --silent
        podio comment create item 12345 --text "Comment" --table
    """
    try:
        client = get_client()

        # Build comment data
        if json_file:
            if not json_file.exists():
                print_error(f"File not found: {json_file}")
                raise typer.Exit(1)
            with open(json_file) as f:
                comment_data = json.load(f)
        elif text:
            comment_data = {"value": text}
        else:
            # Try reading from stdin
            if not sys.stdin.isatty():
                try:
                    stdin_data = sys.stdin.read().strip()
                    if stdin_data:
                        comment_data = {"value": stdin_data}
                    else:
                        print_error("No comment text provided. Use --text or --json-file")
                        raise typer.Exit(1)
                except Exception as e:
                    print_error(f"Error reading from stdin: {e}")
                    raise typer.Exit(1)
            else:
                print_error("No comment text provided. Use --text or --json-file")
                raise typer.Exit(1)

        result = client.Comment.create(
            ref_type=ref_type,
            ref_id=ref_id,
            attributes=comment_data,
            silent=silent,
            hook=not no_hook,
            alert_invite=alert_invite
        )
        formatted = format_response(result)
        print_success(f"Comment added to {ref_type} {ref_id}")
        print_output(formatted, table=table)
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("list")
def list_comments(
    ref_type: str = typer.Argument(..., help="Object type (e.g., 'item', 'status')"),
    ref_id: int = typer.Argument(..., help="Object ID"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum comments to return"),
    offset: int = typer.Option(0, "--offset", help="Offset for pagination"),
    filter: Optional[str] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of fields to include"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Get all comments on a Podio object.

    Examples:
        podio comment list item 12345
        podio comment list item 12345 --limit 50
        podio comment list item 12345 --filter "created_by.name:Example User"
        podio comment list item 12345 --properties "comment_id,value"
        podio comment list item 12345 --table
    """
    try:
        client = get_client()
        result = client.Comment.get_for_object(
            ref_type=ref_type,
            ref_id=ref_id,
            limit=limit,
            offset=offset
        )
        formatted = format_response(result)

        # Apply client-side filtering
        if filter and isinstance(formatted, list):
            formatted = apply_filters(formatted, filter)

        # Apply properties filter
        if properties:
            formatted = apply_properties(formatted, properties)

        print_output(formatted, table=table)
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("get")
def get_comment(
    comment_id: int = typer.Argument(..., help="Comment ID to retrieve"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Get a specific comment by ID.

    Examples:
        podio comment get 98765
        podio comment get 98765 --table
    """
    try:
        client = get_client()
        result = client.Comment.get(comment_id)
        formatted = format_response(result)
        print_output(formatted, table=table)
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("update")
def update_comment(
    comment_id: int = typer.Argument(..., help="Comment ID to update"),
    text: Optional[str] = typer.Option(None, "--text", help="Updated comment text"),
    json_file: Optional[Path] = typer.Option(
        None,
        "--json-file",
        help="Path to JSON file with updated comment data",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Update an existing comment.

    This should only be used to correct spelling and grammatical mistakes.

    Update data format:
        {
            "value": "Updated comment text",
            "external_id": "Optional external ID",
            "file_ids": [123, 456],
            "embed_id": 789,
            "embed_url": "https://example.com"
        }

    Examples:
        podio comment update 98765 --text "Corrected comment text"
        podio comment update 98765 --json-file updated-comment.json
        podio comment update 98765 --text "Corrected" --table
    """
    try:
        client = get_client()

        # Build update data
        if json_file:
            if not json_file.exists():
                print_error(f"File not found: {json_file}")
                raise typer.Exit(1)
            with open(json_file) as f:
                update_data = json.load(f)
        elif text:
            update_data = {"value": text}
        else:
            print_error("No update data provided. Use --text or --json-file")
            raise typer.Exit(1)

        result = client.Comment.update(
            comment_id=comment_id,
            attributes=update_data
        )
        formatted = format_response(result)
        print_success(f"Comment {comment_id} updated successfully")
        print_output(formatted, table=table)
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("delete")
def delete_comment(
    comment_id: int = typer.Argument(..., help="Comment ID to delete"),
    no_hook: bool = typer.Option(False, "--no-hook", help="Skip webhook execution"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Delete a comment.

    Examples:
        podio comment delete 98765
        podio comment delete 98765 --no-hook
        podio comment delete 98765 --table
    """
    try:
        client = get_client()
        client.Comment.delete(comment_id=comment_id, hook=not no_hook)
        print_success(f"Comment {comment_id} deleted successfully")
        print_output({"comment_id": comment_id, "deleted": True}, table=table)
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)
