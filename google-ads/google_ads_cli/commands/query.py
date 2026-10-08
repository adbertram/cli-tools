"""Run Google Ads Query Language queries."""
COMMAND_CREDENTIALS = {"search": ["oauth_authorization_code"]}

from typing import Optional
import typer
from cli_tools_shared.activity_log import get_activity_logger
from cli_tools_shared.output import command
from cli_tools_shared.exceptions import ClientError
from ..client import get_client
from ..output import print_responses
from ..config import get_config
from ..schema import DEFAULT_API_VERSION

app = typer.Typer(help='Run Google Ads Query Language queries.', no_args_is_help=True)
logger = get_activity_logger("google-ads")


@app.command("search")
@command
def search(query: str = typer.Argument(..., help="Complete GAQL query; use GAQL WHERE and LIMIT for server filtering"),
           customer_id: Optional[str] = typer.Option(None, "--customer-id", help="Ads account digits; or configured CUSTOMER_ID"),
           stream: bool = typer.Option(False, "--stream", help="Stream complete response batches as JSONL"),
           all_pages: bool = typer.Option(False, "--all-pages", help="Fetch all pages, preserving every page envelope"),
           page_token: Optional[str] = typer.Option(None, "--page-token", help="Page token returned by a prior search"),
           api_version: str = typer.Option(DEFAULT_API_VERSION, "--api-version", help="SDK API version"),
           timeout: float = typer.Option(60.0, "--timeout", min=0.001, help="Per-RPC timeout in seconds")):
    """Search all GAQL-supported resources, metrics, segments and fields."""
    if stream and (page_token or all_pages):
        raise ClientError("--stream cannot be combined with --page-token or --all-pages.")
    account = customer_id or get_config()._get("CUSTOMER_ID")
    if not account:
        raise ClientError("Missing customer ID. Pass --customer-id.")
    request = {"customer_id": account.replace("-", ""), "query": query}
    if page_token:
        request["page_token"] = page_token
    result = get_client(api_version).call("GoogleAdsService", "search_stream" if stream else "search", request,
                                         all_pages=all_pages, timeout=timeout)
    print_responses(result, stream=stream)


