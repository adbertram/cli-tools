"""Program, contract, promotion, deal, and tracking-link commands."""
from typing import List, Optional

import typer

from cli_tools_shared.output import handle_error

from ..client import get_client
from ._common import output_download, output_item, output_list, read_json_body


COMMAND_CREDENTIALS = {"list": ["custom"], "get": ["custom"], "logo": ["custom"], "contracts": ["custom"], "promotions": ["custom"], "deals": ["custom"], "tracking-link": ["custom"]}

app = typer.Typer(help="Manage Impact programs and program assets", no_args_is_help=True)
contracts_app = typer.Typer(help="Manage contracts", no_args_is_help=True)
promotions_app = typer.Typer(help="Manage promotions", no_args_is_help=True)
deals_app = typer.Typer(help="Manage deals", no_args_is_help=True)


@app.command("list")
def campaigns_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000, help="Maximum records to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="API equality filter field:eq:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List programs."""
    try:
        output_list(get_client().list_campaigns(limit=limit, filters=filter), table, properties, ["id", "name"], ["Id", "Name"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def campaigns_get(campaign_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Get one program."""
    try:
        output_item(get_client().get_campaign(campaign_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("logo")
def campaigns_logo(campaign_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Download a program logo."""
    try:
        output_download(get_client().get_campaign_logo(campaign_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("tracking-link")
def campaigns_tracking_link(
    program_id: str,
    json_file: Optional[str] = typer.Option(None, "--json-file", help="JSON request body file; stdin when omitted"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Create a program tracking link."""
    try:
        output_item(get_client().create_tracking_link(program_id, read_json_body(json_file)), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@contracts_app.command("list")
def contracts_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000, help="Maximum records to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="API equality filter field:eq:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List contracts."""
    try:
        output_list(get_client().list_contracts(limit=limit, filters=filter), table, properties, ["id", "name"], ["Id", "Name"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@contracts_app.command("get")
def contracts_get(contract_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Get one contract."""
    try:
        output_item(get_client().get_contract(contract_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@contracts_app.command("active")
def contracts_active(campaign_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Download a program's active contract."""
    try:
        output_download(get_client().download_active_contract(campaign_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@contracts_app.command("public-terms")
def contracts_public_terms(campaign_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Download public terms for a program."""
    try:
        output_download(get_client().download_public_terms(campaign_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@promotions_app.command("list")
def promotions_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000, help="Maximum records to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="API equality filter field:eq:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List promotions."""
    try:
        output_list(get_client().list_promotions(limit=limit, filters=filter), table, properties, ["id", "name"], ["Id", "Name"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@promotions_app.command("get")
def promotions_get(promotion_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Get one promotion."""
    try:
        output_item(get_client().get_promotion(promotion_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@deals_app.command("list")
def deals_list(
    campaign_id: str,
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000, help="Maximum records to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="API equality filter field:eq:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List deals for a program."""
    try:
        output_list(get_client().list_deals(campaign_id, limit=limit, filters=filter), table, properties, ["id", "name"], ["Id", "Name"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@deals_app.command("get")
def deals_get(campaign_id: str, deal_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Get one program deal."""
    try:
        output_item(get_client().get_deal(campaign_id, deal_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


app.add_typer(contracts_app, name="contracts")
app.add_typer(promotions_app, name="promotions")
app.add_typer(deals_app, name="deals")
