"""Groups commands for Facebook CLI."""
COMMAND_CREDENTIALS = {
    "get": [
        "browser_session"
    ],
    "list": [
        "browser_session"
    ],
    "posts": [
        "browser_session"
    ]
}

import typer
from typing import Optional, List

from cli_tools_shared.output import print_json, handle_error

from .._helpers import client_session, output_list, output_single

app = typer.Typer(help="Manage Facebook Groups", no_args_is_help=True)

POST_COLUMNS = ["post_id", "author", "text", "timestamp"]
POST_HEADERS = ["Post ID", "Author", "Text", "Timestamp"]

GROUP_COLUMNS = ["group_id", "name", "member_count", "url"]
GROUP_HEADERS = ["Group ID", "Name", "Members", "URL"]

# --- Posts sub-app ---
posts_app = typer.Typer(help="Manage posts in Facebook Groups", no_args_is_help=True)
app.add_typer(posts_app, name="posts")


@posts_app.command("list")
def posts_list(
    group_id: str = typer.Argument(..., help="Group ID or name/slug"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(20, "--limit", "-l", min=1, max=50, help="Maximum number of results"),
    full_threads: bool = typer.Option(False, "--full-threads", help="Fetch full thread metadata for each returned post"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List posts from a Facebook Group.

    Examples:
        facebook groups posts list 123456789
        facebook groups posts list my-group-name --table --limit 10
        facebook groups posts list 2318028917 --limit 25 --full-threads
        facebook groups posts list 123456789 --filter "author:contains:John"
    """
    try:
        with client_session() as client:
            posts = client.list_group_posts(group_id, limit=limit, full_threads=full_threads)
            items = [post.model_dump() for post in posts]

            output_list(
                items, table=table, filter=filter, properties=properties,
                limit=limit, default_columns=POST_COLUMNS,
                default_headers=POST_HEADERS, noun="post",
            )
    except Exception as e:
        raise typer.Exit(handle_error(e))


@posts_app.command("get")
def posts_get(
    post_url: str = typer.Argument(..., help="Post permalink URL or 'group_id/posts/post_id'"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get a specific post from a Facebook Group.

    Accepts a full post URL or a path like 'group_id/posts/post_id'.

    Examples:
        facebook groups posts get https://www.facebook.com/groups/123/posts/456
        facebook groups posts get 123/posts/456
        facebook groups posts get 123/posts/456 --table
    """
    try:
        with client_session() as client:
            post = client.get_group_post(post_url)
            output_single(post.model_dump(), table=table, properties=properties)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@posts_app.command("create")
def posts_create(
    group_id: str = typer.Argument(..., help="Group ID"),
    text: str = typer.Option(..., "--text", "-m", help="Post content text"),
):
    """Create a new post in a Facebook Group.

    Examples:
        facebook groups posts create 123456789 --text "Hello everyone!"
        facebook groups posts create 123456789 -m "Looking for advice on shipping"
    """
    try:
        with client_session() as client:
            result = client.create_group_post(group_id, text)
            print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@posts_app.command("comment")
def posts_comment(
    post_url: str = typer.Argument(..., help="Post URL or 'group_id/posts/post_id'"),
    text: str = typer.Option(..., "--text", "-m", help="Comment text"),
):
    """Comment on a Facebook Group post.

    Examples:
        facebook groups posts comment https://www.facebook.com/groups/123/posts/456 --text "Great post!"
        facebook groups posts comment 123/posts/456 -m "Thanks for sharing"
    """
    try:
        with client_session() as client:
            result = client.comment_on_post(post_url, text)
            print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@posts_app.command("reply")
def posts_reply(
    post_url: str = typer.Argument(..., help="Post URL or 'group_id/posts/post_id'"),
    text: str = typer.Option(..., "--text", "-m", help="Reply text"),
    comment_index: int = typer.Option(..., "--comment-index", "-c", help="1-based index of the comment to reply to"),
):
    """Reply to a comment on a Facebook Group post.

    Examples:
        facebook groups posts reply https://www.facebook.com/groups/123/posts/456 --comment-index 1 --text "Good point!"
        facebook groups posts reply 123/posts/456 -c 2 -m "I agree"
    """
    try:
        with client_session() as client:
            result = client.reply_to_comment(post_url, comment_index, text)
            print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))


# --- Groups commands ---
@app.command("list")
def groups_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(20, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List Facebook Groups the logged-in user has joined.

    Examples:
        facebook groups list
        facebook groups list --table --limit 50
        facebook groups list --filter "name:contains:Python"
    """
    try:
        with client_session() as client:
            groups = client.list_joined_groups(limit=limit)
            items = [g.model_dump() for g in groups]

            output_list(
                items, table=table, filter=filter, properties=properties,
                limit=limit, default_columns=GROUP_COLUMNS,
                default_headers=GROUP_HEADERS, noun="group",
            )
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def groups_get(
    group_id: str = typer.Argument(..., help="Group ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get a specific Facebook Group by ID.

    Examples:
        facebook groups get 123456789
        facebook groups get 123456789 --table
    """
    try:
        with client_session() as client:
            group = client.get_group(group_id)
            output_single(group.model_dump(), table=table, properties=properties)
    except Exception as e:
        raise typer.Exit(handle_error(e))
