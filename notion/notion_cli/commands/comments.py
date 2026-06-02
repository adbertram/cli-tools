"""Comments commands for Notion CLI - manage page and block comments."""
import json
import typer
from typing import Optional, List

from ..client import DEFAULT_MAX_WORKERS, get_client
from ..output import _chunk_code_content, print_json, print_table, handle_error
from cli_tools_shared.filters import apply_filters

app = typer.Typer(help="Manage comments on pages and blocks")


def extract_comment_text(comment: dict) -> str:
    """Extract plain text from a comment's rich_text array."""
    rich_text = comment.get("rich_text", [])
    return "".join(rt.get("plain_text", "") for rt in rich_text)


def format_comment_for_display(comment: dict) -> dict:
    """
    Format a comment for display.

    Args:
        comment: Raw comment from Notion API

    Returns:
        Simplified record for display
    """
    parent = comment.get("parent", {})
    parent_type = parent.get("type", "")
    parent_id = parent.get(parent_type, "") if parent_type else ""

    # Determine comment type: page-level vs inline (block-level)
    comment_type = "page" if parent_type == "page_id" else "inline"

    return {
        "id": comment.get("id", ""),
        "comment_type": comment_type,
        "text": extract_comment_text(comment),
        "context": comment.get("context", ""),  # Added by list_comments_with_context
        "context_before": comment.get("context_before", ""),
        "context_after": comment.get("context_after", ""),
        "context_around": comment.get("context_around", ""),
        "selected_block": comment.get("context", ""),
        "selected_block_status": "available" if comment.get("context", "") else "not_available",
        "parent_type": parent_type,
        "parent_id": parent_id,
        "discussion_id": comment.get("discussion_id", ""),
        "created_time": comment.get("created_time", ""),
        "created_by": comment.get("created_by", {}).get("id", ""),
    }


def build_comment_rich_text(text: str) -> List[dict]:
    """Build a Notion rich_text payload for comment text."""
    return [
        {"type": "text", "text": {"content": chunk}}
        for chunk in _chunk_code_content(text)
    ]


@app.command("list")
def comments_list(
    page_id: Optional[str] = typer.Option(
        None,
        "--page-id",
        "-p",
        help="Page ID to get comments for",
    ),
    block_id: Optional[str] = typer.Option(
        None,
        "--block-id",
        "-b",
        help="Block ID to get comments for",
    ),
    discussion_id: Optional[str] = typer.Option(
        None,
        "--discussion-id",
        "-d",
        help="Discussion thread ID to get comments for",
    ),
    with_context: bool = typer.Option(
        False,
        "--with-context",
        "-c",
        help="Include parent block text as context (only with --page-id)",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display as formatted table",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
        help="Maximum number of comments to return",
    ),
    max_workers: int = typer.Option(
        DEFAULT_MAX_WORKERS,
        "--max-workers",
        help="Maximum concurrent block comment lookups when using --with-context",
    ),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., text:contains:bug, parent_type:eq:page_id)",
    ),
):
    """
    List comments on a page, block, or in a discussion thread.

    Examples:

        # List all comments on a page
        notion comments list --page-id abc123

        # List comments with context (what they're attached to)
        notion comments list --page-id abc123 --with-context

        # List comments on a specific block
        notion comments list --block-id def456

        # List comments in a discussion thread
        notion comments list --discussion-id ghi789
    """
    try:
        # Validate input
        provided = sum([bool(page_id), bool(block_id), bool(discussion_id)])
        if provided == 0:
            handle_error("One of --page-id, --block-id, or --discussion-id is required")
            raise typer.Exit(1)
        if provided > 1:
            handle_error("Only one of --page-id, --block-id, or --discussion-id should be provided")
            raise typer.Exit(1)

        if with_context and not page_id:
            handle_error("--with-context can only be used with --page-id")
            raise typer.Exit(1)

        client = get_client()

        api_limit = None if filter else limit

        if page_id:
            if with_context:
                comments = client.list_comments_with_context(
                    page_id,
                    max_workers=max_workers,
                    limit=api_limit,
                )
            else:
                comments = client.list_comments_all(block_id=page_id, limit=api_limit)
                for c in comments:
                    c["context"] = ""
        else:
            target_id = block_id
            comments = client.list_comments_all(
                block_id=target_id,
                discussion_id=discussion_id,
                limit=api_limit,
            )

        # Format for display
        formatted = [format_comment_for_display(c) for c in comments]

        # Apply client-side filtering
        if filter:
            formatted = apply_filters(formatted, filter)

        # Apply client-side limit
        formatted = formatted[:limit]

        if table:
            # Select columns based on whether context is included
            if with_context:
                columns = ["id", "comment_type", "context", "context_around", "text", "created_time"]
            else:
                columns = ["id", "comment_type", "text", "parent_type", "parent_id", "created_time"]
            print_table(formatted, columns=columns)
        else:
            print_json(formatted)

    except Exception as e:
        handle_error(str(e))
        raise typer.Exit(1)


@app.command("get")
def comment_get(
    comment_id: str = typer.Argument(
        ...,
        help="Comment ID to retrieve",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display as formatted table",
    ),
):
    """
    Get a specific comment by ID.

    Examples:

        notion comments get abc123-def456
    """
    try:
        client = get_client()
        comment = client.get_comment(comment_id)

        formatted = format_comment_for_display(comment)

        if table:
            print_table([formatted])
        else:
            print_json(formatted)

    except Exception as e:
        handle_error(str(e))
        raise typer.Exit(1)


@app.command("create")
def comment_create(
    text: str = typer.Argument(
        ...,
        help="Comment text content",
    ),
    page_id: Optional[str] = typer.Option(
        None,
        "--page-id",
        "-p",
        help="Page ID to add comment to",
    ),
    block_id: Optional[str] = typer.Option(
        None,
        "--block-id",
        "-b",
        help="Block ID to add comment to",
    ),
    discussion_id: Optional[str] = typer.Option(
        None,
        "--discussion-id",
        "-d",
        help="Discussion thread ID to reply to",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display result as formatted table",
    ),
):
    """
    Create a comment on a page, block, or in a discussion thread.

    Examples:

        # Add comment to a page
        notion comments create "This is my comment" --page-id abc123

        # Add comment to a specific block
        notion comments create "Comment on this block" --block-id def456

        # Reply to an existing discussion thread
        notion comments create "My reply" --discussion-id ghi789
    """
    try:
        # Validate exactly one target is provided
        provided = sum([bool(page_id), bool(block_id), bool(discussion_id)])
        if provided == 0:
            handle_error("One of --page-id, --block-id, or --discussion-id is required")
            raise typer.Exit(1)
        if provided > 1:
            handle_error("Only one of --page-id, --block-id, or --discussion-id can be provided")
            raise typer.Exit(1)

        rich_text = build_comment_rich_text(text)

        client = get_client()
        comment = client.create_comment(
            rich_text=rich_text,
            page_id=page_id,
            block_id=block_id,
            discussion_id=discussion_id,
        )

        formatted = format_comment_for_display(comment)

        if table:
            print_table([formatted])
        else:
            print_json(formatted)

    except Exception as e:
        handle_error(str(e))
        raise typer.Exit(1)


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
