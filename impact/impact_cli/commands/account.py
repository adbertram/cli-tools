"""Account, user, invoice, tax, and withdrawal commands."""
from typing import List, Optional

import typer

from cli_tools_shared.output import handle_error

from ..client import get_client
from ._common import apply_cli_filters, output_download, output_item, output_list, read_json_body


COMMAND_CREDENTIALS = {
    "get": ["custom"],
    "list": ["custom"],
    "update": ["custom"],
    "users": ["custom"],
    "invoices": ["custom"],
    "tax-documents": ["custom"],
    "withdrawal-settings": ["custom"],
}

app = typer.Typer(help="Manage Impact account data", no_args_is_help=True)
users_app = typer.Typer(help="Manage account users", no_args_is_help=True)
invoices_app = typer.Typer(help="Manage invoices", no_args_is_help=True)
tax_documents_app = typer.Typer(help="Manage tax documents", no_args_is_help=True)
withdrawal_app = typer.Typer(help="Manage withdrawal settings", no_args_is_help=True)


@app.command("get")
def account_get(table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Get account/company information."""
    try:
        output_item(get_client().get_account(), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("update")
def account_update(
    json_file: Optional[str] = typer.Option(None, "--json-file", help="JSON request body file; stdin when omitted"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Update account/company information."""
    try:
        output_item(get_client().update_account(read_json_body(json_file)), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("list")
def account_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000, help="Maximum records to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:Example)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List the current account as a single account record."""
    try:
        output_list(apply_cli_filters([get_client().get_account()], filter), table, properties, ["id", "name"], ["Id", "Name"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@users_app.command("list")
def users_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000, help="Maximum records to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="API equality filter field:eq:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List account users."""
    try:
        output_list(get_client().list_users(limit=limit, filters=filter), table, properties, ["id", "name"], ["Id", "Name"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@users_app.command("get")
def users_get(user_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Get one account user."""
    try:
        output_item(get_client().get_user(user_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@invoices_app.command("list")
def invoices_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000, help="Maximum records to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="API equality filter field:eq:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List invoices."""
    try:
        output_list(get_client().list_invoices(limit=limit, filters=filter), table, properties, ["id", "name"], ["Id", "Name"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@invoices_app.command("get")
def invoices_get(invoice_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Get one invoice."""
    try:
        output_item(get_client().get_invoice(invoice_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@invoices_app.command("download")
def invoices_download(invoice_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Download invoice content."""
    try:
        output_download(get_client().download_invoice(invoice_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@tax_documents_app.command("list")
def tax_documents_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000, help="Maximum records to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="API equality filter field:eq:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List tax documents."""
    try:
        output_list(get_client().list_tax_documents(limit=limit, filters=filter), table, properties, ["id", "name"], ["Id", "Name"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@tax_documents_app.command("get")
def tax_documents_get(tax_document_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Get one tax document."""
    try:
        output_item(get_client().get_tax_document(tax_document_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@tax_documents_app.command("latest")
def tax_documents_latest(table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Get the latest saved tax document."""
    try:
        output_item(get_client().get_latest_tax_document(), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@tax_documents_app.command("create")
def tax_documents_create(
    json_file: Optional[str] = typer.Option(None, "--json-file", help="JSON request body file; stdin when omitted"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Create a tax document."""
    try:
        output_item(get_client().create_tax_document(read_json_body(json_file)), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@tax_documents_app.command("complete")
def tax_documents_complete(
    json_file: Optional[str] = typer.Option(None, "--json-file", help="JSON request body file; stdin when omitted"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Complete tax document submission."""
    try:
        output_item(get_client().complete_tax_document_submission(read_json_body(json_file)), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@withdrawal_app.command("get")
def withdrawal_get(table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Get withdrawal settings."""
    try:
        output_item(get_client().get_withdrawal_settings(), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@withdrawal_app.command("list")
def withdrawal_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000, help="Maximum records to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:Example)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List withdrawal settings as a single record."""
    try:
        output_list(apply_cli_filters([get_client().get_withdrawal_settings()], filter), table, properties, ["id", "name"], ["Id", "Name"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@withdrawal_app.command("update")
def withdrawal_update(
    json_file: Optional[str] = typer.Option(None, "--json-file", help="JSON request body file; stdin when omitted"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Update withdrawal settings."""
    try:
        output_item(get_client().update_withdrawal_settings(read_json_body(json_file)), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@withdrawal_app.command("required-fields")
def withdrawal_required_fields(
    bank_country: str = typer.Option(..., "--bank-country", help="Two-letter bank country code"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Retrieve required banking fields for a country."""
    try:
        output_item(get_client().get_required_banking_fields(bank_country), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


app.add_typer(users_app, name="users")
app.add_typer(invoices_app, name="invoices")
app.add_typer(tax_documents_app, name="tax-documents")
app.add_typer(withdrawal_app, name="withdrawal-settings")
