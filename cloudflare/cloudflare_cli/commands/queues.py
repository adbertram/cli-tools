"""Account-level Cloudflare Queues operations."""
COMMAND_CREDENTIALS = {"list": ["api_key"], "get": ["api_key"], "create": ["api_key"], "consumers": ["api_key"]}

from typing import Optional

import typer

from ..client import DEFAULT_LIST_LIMIT, QueueJurisdiction, get_client
from ..presentation import print_records as _output
from cli_tools_shared.output import command


app = typer.Typer(help="Manage Cloudflare Queues", no_args_is_help=True)
QUEUE_COLUMNS = ("queue_id", "queue_name")


def _account_id(client, account):
    return client.resolve_account_id(account) if account else client.default_account_id()


@app.command("list")
@command
def list_queues(
    account: Optional[str] = typer.Argument(None, help="Account name or ID; defaults to the single visible account"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(DEFAULT_LIST_LIMIT, "--limit", "-l", min=0, help="Maximum matching queues; 0 returns all"),
    filter_str: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Client-side filter: field:op:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated output fields"),
):
    """List queues across pages; filters precede the result limit.

    Examples:
        cloudflare queues list --limit 0
        cloudflare queues list --filter "queue_name:eq:issue-manager" --table
    """
    client = get_client()
    _output(client.list_queues(_account_id(client, account), limit, filter_str), table, properties, QUEUE_COLUMNS)


@app.command("get")
@command
def get_queue(
    queue_id: str = typer.Argument(..., help="Queue ID from queues list or create"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID; defaults to the single visible account"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated output fields"),
):
    """Get a queue by ID.

    Examples:
        cloudflare queues get QUEUE_ID ACCOUNT_ID
    """
    client = get_client()
    _output(client.get_queue(_account_id(client, account), queue_id), table, properties, QUEUE_COLUMNS)


@app.command("create")
@command
def create_queue(
    queue_name: str = typer.Argument(..., help="Name for the new queue"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID; defaults to the single visible account"),
    jurisdiction: Optional[QueueJurisdiction] = typer.Option(None, "--jurisdiction", help="Optional queue jurisdiction"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Create a queue with one POST attempt. Inspect queues list before retrying failures.

    Examples:
        cloudflare queues create issue-manager ACCOUNT_ID
        cloudflare queues create regional-work ACCOUNT_ID --jurisdiction eu
    """
    client = get_client()
    _output(client.create_queue(_account_id(client, account), queue_name, jurisdiction.value if jurisdiction else None), table, default_columns=QUEUE_COLUMNS)


consumers_app = typer.Typer(help="Inspect consumers and enable HTTP pull", no_args_is_help=True)
CONSUMER_COLUMNS = ("consumer_id", "type")


@consumers_app.command("list")
@command
def list_consumers(
    queue_id: str = typer.Argument(..., help="Queue ID"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID; defaults to the single visible account"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(DEFAULT_LIST_LIMIT, "--limit", "-l", min=0, help="Maximum matching consumers; 0 returns all"),
    filter_str: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Client-side filter: field:op:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated output fields"),
):
    """List the consumers configured for a queue.

    Examples:
        cloudflare queues consumers list QUEUE_ID ACCOUNT_ID --limit 0
    """
    client = get_client()
    _output(client.list_queue_consumers(_account_id(client, account), queue_id, limit, filter_str), table, properties, CONSUMER_COLUMNS)


@consumers_app.command("get")
@command
def get_consumer(
    queue_id: str = typer.Argument(..., help="Queue ID"),
    consumer_id: str = typer.Argument(..., help="Consumer ID from consumers list"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID; defaults to the single visible account"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated output fields"),
):
    """Get one configured consumer by ID.

    Examples:
        cloudflare queues consumers get QUEUE_ID CONSUMER_ID ACCOUNT_ID
    """
    client = get_client()
    _output(client.get_queue_consumer(_account_id(client, account), queue_id, consumer_id), table, properties, CONSUMER_COLUMNS)


@consumers_app.command("create")
@command
def create_consumer(
    queue_id: str = typer.Argument(..., help="Queue ID"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID; defaults to the single visible account"),
    batch_size: Optional[int] = typer.Option(None, "--batch-size", help="Maximum messages per batch; service validates allowed range"),
    max_retries: Optional[int] = typer.Option(None, "--max-retries", help="Maximum delivery retries; service validates allowed range"),
    retry_delay: Optional[int] = typer.Option(None, "--retry-delay", help="Seconds before a retry becomes available"),
    visibility_timeout_ms: Optional[int] = typer.Option(None, "--visibility-timeout-ms", help="Milliseconds a pulled message is exclusively leased"),
    dead_letter_queue: Optional[str] = typer.Option(None, "--dead-letter-queue", help="Optional dead-letter queue name"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Create an HTTP-pull consumer once; omitted settings use Cloudflare defaults.

    Examples:
        cloudflare queues consumers create QUEUE_ID ACCOUNT_ID --batch-size 1 --visibility-timeout-ms 30000
    """
    client = get_client()
    result = client.create_queue_http_consumer(
        _account_id(client, account), queue_id, batch_size=batch_size,
        max_retries=max_retries, retry_delay=retry_delay,
        visibility_timeout_ms=visibility_timeout_ms, dead_letter_queue=dead_letter_queue,
    )
    _output(result, table, default_columns=CONSUMER_COLUMNS)


app.add_typer(consumers_app, name="consumers")
