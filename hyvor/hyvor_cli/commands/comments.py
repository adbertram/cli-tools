"""Comments commands for Hyvor CLI."""
COMMAND_CREDENTIALS = {
    "delete": [
        "api_key"
    ],
    "get": [
        "api_key"
    ],
    "list": [
        "api_key"
    ],
    "publish": [
        "api_key"
    ],
    "reply": [
        "api_key"
    ],
    "spam": [
        "api_key"
    ],
    "update": [
        "api_key"
    ]
}

import typer
from typing import Optional, List

from pydantic import BaseModel

from cli_tools_shared.filters import apply_filters
from ..client import get_client
from ..config import get_config
from cli_tools_shared import FilterMap
from cli_tools_shared.output import print_json, print_table, handle_error, print_info
from ..parsers import format_local_time


app = typer.Typer(help="Manage hyvor comments", no_args_is_help=True)


def model_to_dict(item):
    """Convert model or dict to dict for field extraction."""
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


def extract_field(item, field: str):
    """Extract a field value, supporting dot-notation for nested fields."""
    data = model_to_dict(item)
    parts = field.split(".")
    value = data
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def extract_fields(items: list, fields: list) -> list:
    """Extract specified fields from items, supporting dot-notation."""
    result = []
    for item in items:
        extracted = {}
        for field in fields:
            value = extract_field(item, field)
            extracted[field] = value
        result.append(extracted)
    return result


@app.command("list")
def comments_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of comments to return"),
    offset: int = typer.Option(0, "--offset", "-o", help="Pagination offset"),
    comment_type: Optional[str] = typer.Option(None, "--type", "-s", help="Filter by type: published, pending, deleted, spam, flagged"),
    filter: Optional[str] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    client_filter: Optional[List[str]] = typer.Option(None, "--client-filter", "-F", help="Client-side filter (field:op:value)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include (supports dot-notation)"),
):
    """
    List comments.

    Examples:
        hyvor comments list
        hyvor comments list --table
        hyvor comments list --limit 10
        hyvor comments list --type pending
        hyvor comments list --type pending --filter unreplied
        hyvor comments list --filter unreplied
        hyvor comments list --properties "id,body_html,status"
    """
    try:
        client = get_client()
        config = get_config()

        if not config.website_id:
            raise ValueError("website_id not configured. Run 'hyvor auth login' first.")

        # Returns List[Comment] models
        comments = client.list_comments(
            website_id=config.website_id,
            limit=limit,
            offset=offset,
            comment_type=comment_type,
            comment_filter=filter,
            filters=client_filter,
        )

        # Apply client-side --client-filter (Hyvor API has no field-level filtering)
        if client_filter:
            comments_dicts = [model_to_dict(c) for c in comments]
            comments = apply_filters(comments_dicts, client_filter)

        # Apply properties field selection with dot-notation support
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            comments = extract_fields(comments, fields)

        if table:
            # Format timestamps for display
            table_data = []
            for c in comments:
                d = model_to_dict(c) if isinstance(c, BaseModel) else dict(c)
                if "created_at" in d and d["created_at"]:
                    d["created_at"] = format_local_time(d["created_at"])
                table_data.append(d)

            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(table_data, fields, fields)
            else:
                print_table(
                    table_data,
                    ["id", "body_html", "status", "created_at"],
                    ["ID", "Body", "Status", "Created"],
                )
        else:
            print_json(comments)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def comments_get(
    comment_id: int = typer.Argument(..., help="The comment ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include (supports dot-notation)"),
):
    """
    Get details for a specific comment.

    Examples:
        hyvor comments get 12345
        hyvor comments get 12345 --table
        hyvor comments get 12345 --properties "id,body_html,user.name"
    """
    try:
        client = get_client()
        config = get_config()

        if not config.website_id:
            raise ValueError("website_id not configured. Run 'hyvor auth login' first.")

        # Returns CommentDetail model
        comment = client.get_comment(
            website_id=config.website_id,
            comment_id=comment_id,
        )

        # Apply properties field selection with dot-notation support
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            comment = extract_fields([comment], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([comment], fields, fields)
            else:
                # Convert model to key-value table
                comment_dict = model_to_dict(comment)
                rows = [{"field": k, "value": str(v)} for k, v in comment_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(comment)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("reply")
def comments_reply(
    comment_id: int = typer.Argument(..., help="The comment ID to reply to"),
    body: str = typer.Argument(..., help="Reply body text"),
    table: bool = typer.Option(False, "--table", "-t", help="Display reply as table"),
):
    """
    Reply to a comment.

    Examples:
        hyvor comments reply 12345 "This is a reply"
        hyvor comments reply 12345 "Thanks for your comment!" --table
    """
    try:
        client = get_client()
        config = get_config()

        if not config.website_id:
            raise ValueError("website_id not configured. Run 'hyvor auth login' first.")

        # Returns CommentDetail model of the reply
        reply = client.reply_to_comment(
            website_id=config.website_id,
            comment_id=comment_id,
            body=body,
        )

        if table:
            # Convert model to key-value table
            reply_dict = model_to_dict(reply)
            rows = [{"field": k, "value": str(v)} for k, v in reply_dict.items() if v is not None]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(reply)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def comments_update(
    comment_id: int = typer.Argument(..., help="The comment ID to update"),
    body: Optional[str] = typer.Option(None, "--body", "-b", help="New comment body"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="New comment status (published, pending, spam, rejected, trash)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display updated comment as table"),
):
    """
    Update a comment's body or status.

    Examples:
        hyvor comments update 12345 --body "Updated comment text"
        hyvor comments update 12345 --status "spam"
        hyvor comments update 12345 --body "Updated" --status "published"
    """
    try:
        client = get_client()
        config = get_config()

        if not config.website_id:
            raise ValueError("website_id not configured. Run 'hyvor auth login' first.")

        if body is None and status is None:
            raise ValueError("Must provide either --body or --status to update")

        # Returns CommentDetail model
        updated = client.update_comment(
            website_id=config.website_id,
            comment_id=comment_id,
            body=body,
            status=status,
        )

        if table:
            # Convert model to key-value table
            comment_dict = model_to_dict(updated)
            rows = [{"field": k, "value": str(v)} for k, v in comment_dict.items() if v is not None]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(updated)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def comments_delete(
    comment_id: int = typer.Argument(..., help="The comment ID to delete"),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Skip confirmation prompt"),
):
    """
    Delete a comment.

    Examples:
        hyvor comments delete 12345 --confirm
        hyvor comments delete 12345
    """
    try:
        client = get_client()
        config = get_config()

        if not config.website_id:
            raise ValueError("website_id not configured. Run 'hyvor auth login' first.")

        if not confirm:
            if not typer.confirm(f"Delete comment {comment_id}? This cannot be undone."):
                print_info("Delete cancelled.")
                raise typer.Exit(0)

        client.delete_comment(
            website_id=config.website_id,
            comment_id=comment_id,
        )

        print_info(f"Comment {comment_id} deleted successfully.")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("spam")
def comments_spam(
    comment_id: int = typer.Argument(..., help="The comment ID to mark as spam"),
    table: bool = typer.Option(False, "--table", "-t", help="Display updated comment as table"),
):
    """
    Mark a comment as spam.

    This updates the comment's status to 'spam', which helps train Hyvor's
    spam detection system.

    Examples:
        hyvor comments spam 12345
        hyvor comments spam 12345 --table
    """
    try:
        client = get_client()
        config = get_config()

        if not config.website_id:
            raise ValueError("website_id not configured. Run 'hyvor auth login' first.")

        # Update comment status to spam
        updated = client.update_comment(
            website_id=config.website_id,
            comment_id=comment_id,
            status="spam",
        )

        if table:
            # Convert model to key-value table
            comment_dict = model_to_dict(updated)
            rows = [{"field": k, "value": str(v)} for k, v in comment_dict.items() if v is not None]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(updated)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("publish")
def comments_publish(
    comment_id: int = typer.Argument(..., help="The comment ID to publish"),
    table: bool = typer.Option(False, "--table", "-t", help="Display updated comment as table"),
):
    """
    Publish a pending comment.

    This updates the comment's status from 'pending' to 'published',
    making it visible on the website.

    Examples:
        hyvor comments publish 12345
        hyvor comments publish 12345 --table
    """
    try:
        client = get_client()
        config = get_config()

        if not config.website_id:
            raise ValueError("website_id not configured. Run 'hyvor auth login' first.")

        # Update comment status to published
        updated = client.update_comment(
            website_id=config.website_id,
            comment_id=comment_id,
            status="published",
        )

        if table:
            # Convert model to key-value table
            comment_dict = model_to_dict(updated)
            rows = [{"field": k, "value": str(v)} for k, v in comment_dict.items() if v is not None]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(updated)

    except Exception as e:
        raise typer.Exit(handle_error(e))
