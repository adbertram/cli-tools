"""Tweet commands for X CLI.

Commands for posting, deleting, and retrieving tweets.
"""
import typer
from typing import Optional, List

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, print_success, handle_error
from cli_tools_shared.filters import apply_filters, apply_limit


app = typer.Typer(help="Manage tweets", no_args_is_help=True)


@app.command("list")
def tweet_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of tweets to return (5-100)"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display (supports dot-notation)"),
):
    """
    List tweets from the authenticated user's timeline.

    The X API does not support server-side filtering, so --filter applies client-side filtering
    after fetching tweets from the API.

    Examples:
        x tweet list
        x tweet list --table
        x tweet list --limit 10
        x tweet list --filter "text:contains:hello"
        x tweet list --properties "id,text,created_at" --table
    """
    try:
        client = get_client()
        tweets = client.list_tweets(limit=limit)

        # Convert models to dicts for filtering
        tweet_dicts = [tweet.model_dump() if hasattr(tweet, 'model_dump') else tweet.__dict__ for tweet in tweets]

        # Apply client-side filters if provided
        if filter:
            tweet_dicts = apply_filters(tweet_dicts, filter)

        tweet_dicts = apply_limit(tweet_dicts, limit)

        # Apply properties field selection if provided
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            tweet_dicts = [
                {field: tweet.get(field) for field in fields}
                for tweet in tweet_dicts
            ]

        if table:
            if properties:
                # Use custom fields from --properties
                fields = [f.strip() for f in properties.split(",")]
                print_table(tweet_dicts, fields, fields)
            else:
                # Default table columns for tweets
                print_table(
                    tweet_dicts,
                    ["id", "text", "created_at"],
                    ["ID", "Text", "Created At"],
                )
        else:
            print_json(tweet_dicts)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("post")
def tweet_post(
    text: str = typer.Argument(..., help="The text content of the tweet (max 280 chars)"),
    reply_to: Optional[str] = typer.Option(None, "--reply-to", "-r", help="Tweet ID to reply to"),
    quote: Optional[str] = typer.Option(None, "--quote", "-q", help="Tweet ID to quote"),
):
    """
    Post a new tweet to X.

    Examples:
        x tweet post "Hello World!"
        x tweet post "This is a reply" --reply-to 1234567890
        x tweet post "Check this out" --quote 1234567890
    """
    try:
        client = get_client()
        tweet = client.post_tweet(text=text, reply_to=reply_to, quote_tweet_id=quote)
        print_success(f"Tweet posted successfully!")
        print_json(tweet)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def tweet_delete(
    tweet_id: str = typer.Argument(..., help="The ID of the tweet to delete"),
):
    """
    Delete a tweet.

    Examples:
        x tweet delete 1234567890
    """
    try:
        client = get_client()
        success = client.delete_tweet(tweet_id)

        if success:
            print_success(f"Tweet {tweet_id} deleted successfully!")
        else:
            raise typer.Exit(1)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def tweet_get(
    tweet_id: str = typer.Argument(..., help="The ID of the tweet to retrieve"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get a tweet by ID.

    Examples:
        x tweet get 1234567890
        x tweet get 1234567890 --table
    """
    try:
        client = get_client()
        tweet = client.get_tweet(tweet_id)

        if table:
            from cli_tools_shared.output import print_table
            # Convert tweet model to dict for table display
            tweet_dict = tweet.model_dump() if hasattr(tweet, 'model_dump') else tweet.__dict__
            rows = [{"field": k, "value": str(v)} for k, v in tweet_dict.items() if v is not None]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(tweet)

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "delete": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "post": [
        "custom"
    ]
}
