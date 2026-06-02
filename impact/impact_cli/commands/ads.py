"""Ad commands."""
from typing import List, Optional

import typer

from cli_tools_shared.output import handle_error

from ..client import get_client
from ._common import output_item, output_list


COMMAND_CREDENTIALS = {"list": ["custom"], "get": ["custom"], "code": ["custom"], "iframe-code": ["custom"], "tracking-link": ["custom"]}

app = typer.Typer(help="Manage ads and ad tracking assets", no_args_is_help=True)


@app.command("list")
def ads_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000, help="Maximum records to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="API equality filter field:eq:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List ads."""
    try:
        output_list(get_client().list_ads(limit=limit, filters=filter), table, properties, ["id", "name"], ["Id", "Name"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def ads_get(ad_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Get one ad."""
    try:
        output_item(get_client().get_ad(ad_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("code")
def ads_code(ad_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Retrieve ad code."""
    try:
        output_item(get_client().get_ad_code(ad_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("iframe-code")
def ads_iframe_code(ad_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Retrieve ad iframe code."""
    try:
        output_item(get_client().get_ad_iframe_code(ad_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("tracking-link")
def ads_tracking_link(ad_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Retrieve an ad tracking link."""
    try:
        output_item(get_client().get_ad_tracking_link(ad_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
