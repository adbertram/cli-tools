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

from cli_tools_shared.output import print_json, command

from .._helpers import client_session, output_list, output_single

app = typer.Typer(help="Manage Facebook Groups", no_args_is_help=True)

POST_COLUMNS = ["post_id", "author", "text", "timestamp"]
POST_HEADERS = ["Post ID", "Author", "Text", "Timestamp"]

GROUP_COLUMNS = ["group_id", "name", "membership", "url"]
GROUP_HEADERS = ["Group ID", "Name", "Membership", "URL"]

# --- Posts sub-app ---
posts_app = typer.Typer(help="Manage posts in Facebook Groups", no_args_is_help=True)
app.add_typer(posts_app, name="posts")


@posts_app.command("list")
@command
def posts_list(
    group_id: str = typer.Argument(..., help="Group ID or name/slug"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(20, "--limit", "-l", min=1, max=50, help="Maximum number of results"),
    full_threads: bool = typer.Option(False, "--full-threads", help="Fetch full thread metadata for each returned post"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List posts from a Facebook Group.

    Fails with exit code 1 and an "UNREADABLE_GROUP:" stderr message when this
    session cannot see the group's posts (a private group you have not joined,
    or one whose join request is still pending), so an unreadable group is never
    reported as an empty one. Use 'facebook groups get <group_id>' to check
    posts_readable before crawling.

    Examples:
        facebook groups posts list 123456789
        facebook groups posts list my-group-name --table --limit 10
        facebook groups posts list 2318028917 --limit 25 --full-threads
        facebook groups posts list 123456789 --filter "author:contains:John"
    """
    with client_session() as client:
        posts = client.list_group_posts(group_id, limit=limit, full_threads=full_threads)
        items = [post.model_dump() for post in posts]

        output_list(
            items, table=table, filter=filter, properties=properties,
            limit=limit, default_columns=POST_COLUMNS,
            default_headers=POST_HEADERS, noun="post",
        )


@posts_app.command("get")
@command
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
    with client_session() as client:
        post = client.get_group_post(post_url)
        output_single(post.model_dump(), table=table, properties=properties)


@posts_app.command("create")
@command
def posts_create(
    group_id: str = typer.Argument(..., help="Group ID"),
    text: str = typer.Option(..., "--text", "-m", help="Post content text"),
):
    """Create a new post in a Facebook Group.

    Examples:
        facebook groups posts create 123456789 --text "Hello everyone!"
        facebook groups posts create 123456789 -m "Looking for advice on shipping"
    """
    with client_session() as client:
        result = client.create_group_post(group_id, text)
        print_json(result)


@posts_app.command("comment")
@command
def posts_comment(
    post_url: str = typer.Argument(..., help="Post URL or 'group_id/posts/post_id'"),
    text: str = typer.Option(..., "--text", "-m", help="Comment text"),
):
    """Comment on a Facebook Group post.

    Examples:
        facebook groups posts comment https://www.facebook.com/groups/123/posts/456 --text "Great post!"
        facebook groups posts comment 123/posts/456 -m "Thanks for sharing"
    """
    with client_session() as client:
        result = client.comment_on_post(post_url, text)
        print_json(result)


@posts_app.command("reply")
@command
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
    with client_session() as client:
        result = client.reply_to_comment(post_url, comment_index, text)
        print_json(result)


# --- Groups commands ---
@app.command("list")
@command
def groups_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(20, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List Facebook Groups the logged-in user has joined or requested to join.

    Every row carries group_id, name, url, and membership ("member" or
    "pending"); joined groups are listed before pending requests. Facebook does
    not render privacy or member counts on this page, so those stay null - use
    'facebook groups get <group_id>' for them.

    Examples:
        facebook groups list
        facebook groups list --table --limit 50
        facebook groups list --filter "membership:eq:member"
        facebook groups list --filter "name:contains:Python"
    """
    with client_session() as client:
        groups = client.list_joined_groups(limit=limit)
        items = [g.model_dump() for g in groups]

        output_list(
            items, table=table, filter=filter, properties=properties,
            limit=limit, default_columns=GROUP_COLUMNS,
            default_headers=GROUP_HEADERS, noun="group",
        )


@app.command("get")
@command
def groups_get(
    group_id: str = typer.Argument(..., help="Group ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get a specific Facebook Group by ID, slug, or URL.

    Reports the group's privacy ("public"/"private"), this session's membership
    ("member"/"pending"/"non_member"), and posts_readable - whether this session
    can actually read the group's posts. All three are read from the live group
    page and never inferred.

    Examples:
        facebook groups get 123456789
        facebook groups get 123456789 --table
        facebook groups get 123456789 --properties group_id,privacy,membership,posts_readable
    """
    with client_session() as client:
        group = client.get_group(group_id)
        output_single(group.model_dump(), table=table, properties=properties)
