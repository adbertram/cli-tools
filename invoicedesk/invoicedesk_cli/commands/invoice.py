"""Invoice commands for InvoiceDesk CLI."""
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Optional, List

import typer
from cli_tools_shared.exceptions import ClientError

from cli_tools_shared.output import command, print_json, print_table, print_success

from ..client import get_client
from ..config import get_config
from ..filter_map import INVOICE_FILTER_FIELDS
from ..formatters import format_invoice_for_display
from ..invoice_lines import parse_line_amounts, rebuild_lines
from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError

app = typer.Typer(help="Manage InvoiceDesk invoices")


def _upload_attachment(client, path):
    if not path:
        return None
    typer.echo(f"Uploading attachment: {path}", err=True)
    result = client.upload_attachment(path)
    typer.echo("Attachment uploaded successfully.", err=True)
    return [{"jwt": result["jwt"], "media_type": result["media_type"]}]


@app.command("list")
@command
def invoice_list(
    filter_: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help=(
            "Filter results (field:op:value, e.g., client:contains:acme). "
            "Fields: id, number, client, status, amount, outstanding, created, "
            "due_date. Note that 'like' is SQL LIKE, so a substring search needs "
            "wildcards: client:like:%acme%"
        ),
    ),
    status: Optional[str] = typer.Option(
        None,
        "--status",
        "-s",
        help="Filter by status (draft, sent, viewed, partial, paid, overdue)",
    ),
    unpaid: bool = typer.Option(
        False,
        "--unpaid",
        "-u",
        help="Filter to show only active unpaid issued invoices, including partial payments",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
        min=1,
        help="Maximum number of invoices to return (default: 100)",
    ),
    date_from: Optional[str] = typer.Option(
        None,
        "--from",
        help="Filter invoices created on or after this date (YYYY-MM-DD)",
    ),
    date_to: Optional[str] = typer.Option(
        None,
        "--to",
        help="Filter invoices created on or before this date (YYYY-MM-DD)",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of properties to display (e.g., 'id,number,client')",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display output as a formatted table instead of JSON",
    ),
):
    """
    List all invoices.

    Shows all invoices in your InvoiceDesk account with optional status filtering.

    Filterable fields: id, number, client, status, amount, outstanding, created,
    due_date. Substring searches use 'contains', or 'like' with explicit SQL
    wildcards ('%acme%'). A bare 'like:acme' is an anchored, case-insensitive
    exact match.

    Examples:
        invoicedesk invoice list
        invoicedesk invoice list --table
        invoicedesk invoice list --status sent --table
        invoicedesk invoice list --unpaid --table
        invoicedesk invoice list --filter client:contains:acme
        invoicedesk invoice list --filter client:like:%acme%
        invoicedesk invoice list --limit 10
        invoicedesk invoice list --from 2024-01-01 --to 2024-12-31
    """
    # Validate filters first. Declaring the filterable fields turns a filter
    # on an unknown field into a loud error instead of an empty result that
    # reads as "no such invoice".
    if filter_:
        try:
            validate_filters(filter_, allowed_fields=INVOICE_FILTER_FIELDS)
        except FilterValidationError as e:
            typer.echo(f"Filter error: {e}", err=True)
            raise typer.Exit(1)

    client = get_client()

    # Track if we need client-side overdue filtering
    filter_overdue_client_side = False

    # Track if we need client-side unpaid filtering
    filter_unpaid_client_side = False

    # Determine status filter
    if unpaid:
        if status:
            typer.echo("Warning: --unpaid overrides --status", err=True)
        status_filter = ["sent", "viewed", "overdue", "partial", "partially paid", "disputed", "retry", "failed"]
        filter_unpaid_client_side = True
    elif status == "overdue":
        status_filter = ["sent", "viewed", "overdue", "partial", "partially paid", "disputed", "retry", "failed"]
        filter_overdue_client_side = True
    else:
        status_filter = [status] if status else None
    # InvoiceDesk has no server-side search for the display fields exposed by
    # --filter, and --unpaid/--status overdue are computed here too. Whenever
    # rows are dropped after the fetch, every page has to be considered
    # before --limit is applied; --limit caps the results returned, not the
    # rows searched.
    filters_client_side = bool(
        filter_ or filter_unpaid_client_side or filter_overdue_client_side
    )
    invoices = client.get_invoices(
        status=status_filter,
        date_from=date_from,
        date_to=date_to,
        max_records=None if filters_client_side else limit,
    )

    # Apply client-side unpaid filtering (outstanding > $0)
    if filter_unpaid_client_side:
        unpaid_invoices = []
        for inv in invoices:
            outstanding_obj = inv.get("outstanding", {})
            outstanding_amount = float(outstanding_obj.get("amount", "0.00") if isinstance(outstanding_obj, dict) else "0.00")
            if outstanding_amount > 0:
                unpaid_invoices.append(inv)
        invoices = unpaid_invoices

    # Apply client-side overdue filtering if requested
    if filter_overdue_client_side:
        today = date.today()
        overdue_invoices = []
        for inv in invoices:
            due_date_str = inv.get("due_date", "")
            outstanding_obj = inv.get("outstanding", {})
            outstanding_amount = float(outstanding_obj.get("amount", "0.00") if isinstance(outstanding_obj, dict) else "0.00")

            # Only include if due date is in the past and there's an outstanding balance
            if due_date_str and outstanding_amount > 0:
                try:
                    due_date_obj = date.fromisoformat(due_date_str)
                    if due_date_obj < today:
                        overdue_invoices.append(inv)
                except ValueError:
                    # Skip invoices with invalid due dates
                    pass
        invoices = overdue_invoices

    if not invoices:
        if table:
            print_table([], columns=["id", "number", "client", "status", "amount", "outstanding", "due_date"],
                        headers=["ID", "Number", "Client", "Status", "Amount", "Outstanding", "Due Date"])
        else:
            print_json([])
        return

    formatted = [format_invoice_for_display(inv) for inv in invoices]

    # The shared filter module is the single authority on whether a record
    # matches.
    if filter_:
        formatted = apply_filters(
            formatted, filter_, allowed_fields=INVOICE_FILTER_FIELDS
        )

    if filters_client_side:
        formatted = formatted[:limit]

    if not formatted:
        if table:
            print_table([], columns=["id", "number", "client", "status", "amount", "outstanding", "due_date"],
                        headers=["ID", "Number", "Client", "Status", "Amount", "Outstanding", "Due Date"])
        else:
            print_json([])
        return

    # Apply property selection
    if properties:
        prop_list = [p.strip() for p in properties.split(",")]
        formatted = [{k: v for k, v in inv.items() if k in prop_list} for inv in formatted]

    if table:
        if properties:
            prop_list = [p.strip() for p in properties.split(",")]
            print_table(formatted, columns=prop_list, headers=prop_list)
        else:
            print_table(
                formatted,
                columns=["id", "number", "client", "status", "amount", "outstanding", "due_date"],
                headers=["ID", "Number", "Client", "Status", "Amount", "Outstanding", "Due Date"],
            )
    else:
        print_json(formatted)


@app.command("get")
@command
def invoice_get(
    invoice_id: str = typer.Argument(
        ...,
        help="The invoice ID to retrieve",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display output as a formatted table instead of JSON",
    ),
):
    """
    Get details for a specific invoice.

    Examples:
        invoicedesk invoice get 1234567
        invoicedesk invoice get 1234567 --table
    """
    client = get_client()
    invoice = client.get_invoice(invoice_id)

    if not invoice:
        typer.echo(f"Invoice {invoice_id} not found.", err=True)
        raise typer.Exit(1)

    if table:
        formatted = format_invoice_for_display(invoice)
        print_table(
            [formatted],
            columns=["id", "number", "client", "status", "amount", "outstanding", "due_date"],
            headers=["ID", "Number", "Client", "Status", "Amount", "Outstanding", "Due Date"],
        )
    else:
        print_json(invoice)


@app.command("create")
@command
def invoice_create(
    customer_id: str = typer.Option(
        ...,
        "--customer-id",
        "-c",
        help="Customer ID to invoice",
    ),
    description: List[str] = typer.Option(
        ...,
        "--description",
        "-d",
        help="Line item description (repeat for multiple line items)",
    ),
    amount: List[str] = typer.Option(
        ...,
        "--amount",
        "-a",
        help="Line item amount, e.g. '500.00' (repeat for multiple line items)",
    ),
    quantity: Optional[List[str]] = typer.Option(
        None,
        "--quantity",
        "-q",
        help="Line item quantity (default: 1; repeat for multiple line items)",
    ),
    notes: Optional[str] = typer.Option(
        None,
        "--notes",
        "-n",
        help="Invoice notes",
    ),
    terms: Optional[str] = typer.Option(
        None,
        "--terms",
        "-t",
        help="Payment terms (overrides default from config)",
    ),
    po_number: Optional[str] = typer.Option(
        None,
        "--po-number",
        "-p",
        help="Purchase order number/reference",
    ),
    attachment: Optional[str] = typer.Option(
        None,
        "--attachment",
        "-f",
        help="Path to file to attach (PDF or image)",
    ),
    due_days: int = typer.Option(
        30,
        "--due-days",
        help="Number of days until invoice is due (default: 30)",
    ),
    no_terms: bool = typer.Option(
        False,
        "--no-terms",
        help="Skip adding default payment terms",
    ),
):
    """
    Create a new invoice.

    Supports multiple line items by repeating -d and -a flags. Each -d is
    paired with the corresponding -a by position. Use -q to set quantity
    per line item (defaults to 1).

    Payment terms are automatically added from InvoiceDesk Settings
    unless --no-terms is specified or --terms provides custom terms.

    Examples:
        invoicedesk invoice create -c 12345 -d "Consulting Services" -a 500.00
        invoicedesk invoice create -c 12345 -d "Article Writing" -a 750.00 -n "Thank you!" -p "REF-001"
        invoicedesk invoice create -c 12345 -d "Contract Work" -a 1000.00 -f ./contract.pdf
        invoicedesk invoice create -c 12345 -d "Consulting" -a 500.00 --due-days 60
        invoicedesk invoice create -c 12345 -d "Consulting" -a 500.00 --no-terms
        invoicedesk invoice create -c 12345 -d "Line 1" -a 500 -d "Line 2" -a 1000
        invoicedesk invoice create -c 12345 -d "Item A" -a 500 -q 2 -d "Item B" -a 300 -q 1
    """
    client = get_client()
    config = get_config()

    # Validate that descriptions and amounts pair up
    if len(description) != len(amount):
        typer.echo(
            f"Error: number of descriptions ({len(description)}) must match "
            f"number of amounts ({len(amount)}).",
            err=True,
        )
        raise typer.Exit(1)

    # Normalize quantities: default to "1" for any missing entries
    quantities = quantity if quantity else []
    if len(quantities) > len(description):
        typer.echo(
            f"Error: number of quantities ({len(quantities)}) exceeds "
            f"number of line items ({len(description)}).",
            err=True,
        )
        raise typer.Exit(1)

    # Determine payment terms: explicit > default > none
    invoice_terms = ""
    if not no_terms:
        if terms:
            invoice_terms = terms
        else:
            invoice_terms = config.default_terms

    from decimal import Decimal, InvalidOperation
    for value in [*amount, *(quantity or [])]:
        try:
            parsed = Decimal(value)
        except InvalidOperation:
            raise ClientError("Amounts and quantities must be positive decimal numbers")
        if not parsed.is_finite() or parsed <= 0:
            raise ClientError("Amounts and quantities must be positive decimal numbers")

    items = []
    for i, (desc, amt) in enumerate(zip(description, amount)):
        qty = quantities[i] if i < len(quantities) else "1"
        items.append(
            {
                "name": desc,
                "qty": qty,
                "type": 0,
                "unit_cost": {
                    "amount": amt,
                    "code": "USD"
                }
            }
        )

    attachments = _upload_attachment(client, attachment)

    invoice = client.create_invoice(
        customer_id=customer_id,
        items=items,
        notes=notes,
        terms=invoice_terms,
        po_number=po_number,
        attachments=attachments,
        due_offset_days=due_days
    )

    print_success(f"Invoice {invoice.get('invoice_number')} created (ID: {invoice.get('id')})")
    print_json(format_invoice_for_display(invoice))


@app.command("mark-sent")
@command
def invoice_mark_sent(
    invoice_id: str = typer.Argument(..., help="Invoice ID already delivered externally"),
    force: bool = typer.Option(False, "--force", "-F", help="Skip confirmation prompt"),
):
    """Record external invoice delivery. Download PDF first; caller sends it.

    Examples:
        invoicedesk invoice download 1234567 -o invoice.pdf
        invoicedesk invoice mark-sent 1234567 -F
    """
    client = get_client()
    invoice = client.get_invoice(invoice_id)
    if not force and not typer.confirm("Confirm invoice was delivered externally?", err=True):
        raise typer.Exit(0)
    client.mark_invoice_sent(invoice_id)
    print_success(f"Invoice {invoice.get('invoice_number')} marked sent.")


@app.command("delete")
@command
def invoice_delete(
    invoice_id: str = typer.Argument(
        ...,
        help="The invoice ID to delete",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-F",
        help="Skip confirmation prompt",
    ),
):
    """
    Delete/void an invoice.

    Examples:
        invoicedesk invoice delete 1234567
        invoicedesk invoice delete 1234567 -F
    """
    client = get_client()

    # Get invoice details first
    invoice = client.get_invoice(invoice_id)
    if not invoice:
        typer.echo(f"Invoice {invoice_id} not found.", err=True)
        raise typer.Exit(1)

    # Confirm before deleting
    if not force:
        typer.echo(f"Invoice #{invoice.get('invoice_number')}", err=True)
        typer.echo(f"Amount: ${invoice.get('amount', {}).get('amount', '0.00')}", err=True)
        if not typer.confirm("Delete this invoice?", default=False, err=True):
            typer.echo("Aborted.", err=True)
            raise typer.Exit(0)

    client.delete_invoice(invoice_id)
    print_success(f"Invoice {invoice.get('invoice_number')} deleted.")


@app.command("mark-paid")
@command
def invoice_mark_paid(
    invoice_id: str = typer.Argument(
        ...,
        help="The invoice ID to mark as paid",
    ),
    amount: str = typer.Option(
        ...,
        "--amount",
        "-a",
        help="Payment amount (e.g., '500.00')",
    ),
    date: Optional[str] = typer.Option(
        None,
        "--date",
        "-d",
        help="Payment date (YYYY-MM-DD, default: today)",
    ),
):
    """
    Mark an invoice as paid.

    Examples:
        invoicedesk invoice mark-paid 1234567 -a 500.00
        invoicedesk invoice mark-paid 1234567 -a 500.00 -d 2024-01-15
    """
    from datetime import datetime

    client = get_client()

    payment_date = date or datetime.now().strftime("%Y-%m-%d")
    result = client.mark_invoice_paid(invoice_id, payment_date, amount)

    print_success(f"Invoice marked as paid. Payment ID: {result.get('id')}")


@app.command("update")
@command
def invoice_update(
    invoice_id: str = typer.Argument(
        ...,
        help="The invoice ID to update",
    ),
    attachment: Optional[str] = typer.Option(
        None,
        "--attachment",
        "-f",
        help="Path to file to attach (PDF or image)",
    ),
    notes: Optional[str] = typer.Option(
        None,
        "--notes",
        "-n",
        help="Update invoice notes",
    ),
    terms: Optional[str] = typer.Option(
        None,
        "--terms",
        "-t",
        help="Update payment terms",
    ),
    terms_from_config: bool = typer.Option(
        False,
        "--terms-from-config",
        help="Set payment terms from InvoiceDesk Settings",
    ),
    po_number: Optional[str] = typer.Option(
        None,
        "--po-number",
        "-p",
        help="Update purchase order number/reference",
    ),
    line_amount: Optional[List[str]] = typer.Option(
        None,
        "--line-amount",
        "-l",
        help=(
            "Set an existing line's unit price as LINEID=AMOUNT, e.g. 2=750.00 "
            "(repeatable; quantity and all other lines are unchanged)"
        ),
    ),
):
    """
    Update an existing invoice.

    --line-amount LINEID=AMOUNT sets that line's unit_cost (quantity unchanged).
    Find line IDs with `invoicedesk invoice get <id>`. InvoiceDesk replaces the
    whole lines array on update, so the invoice is fetched and every line is
    resent; lines not named are preserved. An unknown line ID or a
    non-numeric/non-positive amount fails with a non-zero exit and nothing is
    sent. With --line-amount the output JSON also includes the invoice lines.

    Examples:
        invoicedesk invoice update 1234567 -f ./contract.pdf
        invoicedesk invoice update 1234567 -n "Updated notes"
        invoicedesk invoice update 1234567 -f ./receipt.pdf -n "Added receipt"
        invoicedesk invoice update 1234567 --terms-from-config
        invoicedesk invoice update 1234567 -t "Net 30"
        invoicedesk invoice update 1234567 --line-amount 1=750.00
        invoicedesk invoice update 1234567 -l 1=750 -l 2=800.50
    """
    client = get_client()
    config = get_config()

    # Validate before any network call.
    line_amounts = parse_line_amounts(line_amount) if line_amount else {}

    # Determine terms to use
    invoice_terms = None
    if terms_from_config:
        if not config.default_terms:
            typer.echo("Error: No payment instructions set in InvoiceDesk Settings", err=True)
            raise typer.Exit(1)
        invoice_terms = config.default_terms
    elif terms:
        invoice_terms = terms

    # Check that at least one update option is provided
    if not any([attachment, notes, invoice_terms, po_number, line_amounts]):
        typer.echo("No updates specified. Use --help to see available options.", err=True)
        raise typer.Exit(1)

    # Build and validate the new lines before uploading anything.
    lines = None
    if line_amounts:
        existing = client.get_invoice(invoice_id)
        if not existing:
            typer.echo(f"Invoice {invoice_id} not found.", err=True)
            raise typer.Exit(1)
        lines = rebuild_lines(existing.get("lines", []), line_amounts)

    attachments = _upload_attachment(client, attachment)

    invoice = client.update_invoice(
        invoice_id=invoice_id,
        attachments=attachments,
        notes=notes,
        terms=invoice_terms,
        po_number=po_number,
        lines=lines,
    )

    print_success(f"Invoice {invoice.get('invoice_number')} updated.")
    result = format_invoice_for_display(invoice)
    if line_amounts:
        # Re-read so the output shows the stored lines, not the request echo.
        result["lines"] = [
            {
                "lineid": line["lineid"],
                "name": line["name"],
                "qty": line["qty"],
                "unit_cost": line["unit_cost"],
                "amount": line["amount"],
            }
            for line in client.get_invoice(invoice_id).get("lines", [])
        ]
    print_json(result)


@app.command("download")
@command
def invoice_download(
    invoice_id: str = typer.Argument(
        ...,
        help="The invoice ID to download",
    ),
    output: Optional[str] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file path (default: invoice_{number}.pdf in current directory)",
    ),
):
    """
    Download an invoice as a PDF.

    Examples:
        invoicedesk invoice download 1234567
        invoicedesk invoice download 1234567 -o ~/Downloads/invoice.pdf
        invoicedesk invoice download 1234567 --output ./my-invoice.pdf
    """
    client = get_client()

    # Get invoice details for the filename
    invoice = client.get_invoice(invoice_id)
    if not invoice:
        typer.echo(f"Invoice {invoice_id} not found.", err=True)
        raise typer.Exit(1)

    invoice_number = invoice.get("invoice_number", invoice_id)

    # Imported invoice numbers are untrusted filename components.
    if output:
        output_path = Path(output).expanduser()
    else:
        number = str(invoice_number)
        if not number or number in {".", ".."} or any(c in number for c in "/\\") or any(ord(c) < 32 or ord(c) == 127 for c in number):
            raise ClientError("Unsafe invoice number for default PDF filename; use --output")
        output_path = Path(f"invoice_{number}.pdf")
    if output_path.is_symlink():
        raise ClientError("PDF destination cannot be a symbolic link")
    if not output and output_path.exists():
        raise ClientError("Default PDF destination already exists; choose an explicit --output path")

    # Download the PDF
    typer.echo(f"Downloading invoice #{invoice_number}...", err=True)
    pdf_content = client.download_invoice_pdf(invoice_id)

    # Ensure parent directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Publish only a completed PDF; explicit output paths authorize replacement.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output_path.parent, prefix=".invoice-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(pdf_content)
            stream.flush()
            os.fsync(stream.fileno())
        if output:
            os.replace(temporary, output_path)
        else:
            os.link(temporary, output_path)
    except OSError as exc:
        raise ClientError(f"Cannot save PDF: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    print_success(f"Invoice saved to {output_path}")


COMMAND_CREDENTIALS = {
    "create": [
        "api_key"
    ],
    "delete": [
        "api_key"
    ],
    "download": [
        "api_key"
    ],
    "get": [
        "api_key"
    ],
    "list": [
        "api_key"
    ],
    "mark-paid": [
        "api_key"
    ],
    "mark-sent": [
        "api_key"
    ],
    "update": [
        "api_key"
    ]
}
