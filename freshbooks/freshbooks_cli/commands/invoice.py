"""Invoice commands for FreshBooks CLI."""
from datetime import date
from pathlib import Path
from typing import Optional, List

import typer

from cli_tools_shared.output import print_json, print_table, handle_error, print_success

from ..client import get_client
from ..config import get_config
from ..formatters import format_invoice_for_display
from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError

app = typer.Typer(help="Manage FreshBooks invoices")


@app.command("list")
def invoice_list(
    filter_: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter results (field:op:value, e.g., client:like:acme)",
    ),
    status: Optional[str] = typer.Option(
        None,
        "--status",
        "-s",
        help="Filter by status (draft, sent, viewed, paid, overdue)",
    ),
    unpaid: bool = typer.Option(
        False,
        "--unpaid",
        "-u",
        help="Filter to show only unpaid invoices (sent, viewed, overdue)",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
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

    Shows all invoices in your FreshBooks account with optional status filtering.

    Examples:
        freshbooks invoice list
        freshbooks invoice list --table
        freshbooks invoice list --status sent --table
        freshbooks invoice list --unpaid --table
        freshbooks invoice list --filter client:like:acme
        freshbooks invoice list --limit 10
        freshbooks invoice list --from 2024-01-01 --to 2024-12-31
    """
    try:
        # Validate filters first
        if filter_:
            try:
                validate_filters(filter_)
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
                typer.echo("Warning: --unpaid overrides --status")
            # For unpaid, fetch sent and viewed invoices
            # (overdue is not a real API status - it's a client-side calculation)
            status_filter = ["sent", "viewed"]
            filter_unpaid_client_side = True
        elif status == "overdue":
            # "overdue" is not a real FreshBooks API status
            # Fetch unpaid invoices (sent, viewed) and filter client-side
            status_filter = ["sent", "viewed"]
            filter_overdue_client_side = True
        else:
            status_filter = [status] if status else None
        invoices = client.get_invoices(
            status=status_filter,
            per_page=limit,
            date_from=date_from,
            date_to=date_to,
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

        # Apply filters if provided (client-side filtering)
        if filter_:
            formatted = apply_filters(formatted, filter_)

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

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("get")
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
        freshbooks invoice get 1234567
        freshbooks invoice get 1234567 --table
    """
    try:
        client = get_client()
        invoice = client.get_invoice(invoice_id)

        if not invoice:
            typer.echo(f"Invoice {invoice_id} not found.")
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

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("create")
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

    Payment terms are automatically added from DEFAULT_TERMS in .env
    unless --no-terms is specified or --terms provides custom terms.

    Examples:
        freshbooks invoice create -c 12345 -d "Consulting Services" -a 500.00
        freshbooks invoice create -c 12345 -d "Article Writing" -a 750.00 -n "Thank you!" -p "REF-001"
        freshbooks invoice create -c 12345 -d "Contract Work" -a 1000.00 -f ./contract.pdf
        freshbooks invoice create -c 12345 -d "Consulting" -a 500.00 --due-days 60
        freshbooks invoice create -c 12345 -d "Consulting" -a 500.00 --no-terms
        freshbooks invoice create -c 12345 -d "Line 1" -a 500 -d "Line 2" -a 1000
        freshbooks invoice create -c 12345 -d "Item A" -a 500 -q 2 -d "Item B" -a 300 -q 1
    """
    try:
        client = get_client()
        config = get_config()

        # Handle file attachment if provided
        attachments = None
        if attachment:
            typer.echo(f"Uploading attachment: {attachment}")
            upload_result = client.upload_attachment(attachment)
            attachments = [
                {
                    "jwt": upload_result["jwt"],
                    "media_type": upload_result["media_type"]
                }
            ]
            typer.echo("Attachment uploaded successfully.")

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
        invoice_terms = None
        if not no_terms:
            if terms:
                invoice_terms = terms
            elif config.default_terms:
                invoice_terms = config.default_terms

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

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("send")
def invoice_send(
    invoice_id: str = typer.Argument(
        ...,
        help="The invoice ID to send",
    ),
    email: Optional[str] = typer.Option(
        None,
        "--email",
        "-e",
        help="Override recipient email address",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-F",
        help="Skip confirmation prompt",
    ),
):
    """
    Send an invoice via email.

    Examples:
        freshbooks invoice send 1234567
        freshbooks invoice send 1234567 --email client@example.com
        freshbooks invoice send 1234567 -F
    """
    try:
        client = get_client()

        # Get invoice details first
        invoice = client.get_invoice(invoice_id)
        if not invoice:
            typer.echo(f"Invoice {invoice_id} not found.")
            raise typer.Exit(1)

        # Confirm before sending
        if not force:
            typer.echo(f"Invoice #{invoice.get('invoice_number')}")
            typer.echo(f"Amount: ${invoice.get('amount', {}).get('amount', '0.00')}")
            if not typer.confirm("Send this invoice?"):
                typer.echo("Aborted.")
                raise typer.Exit(0)

        recipients = [email] if email else None
        result = client.send_invoice(invoice_id, email_recipients=recipients)

        print_success(f"Invoice {invoice.get('invoice_number')} sent successfully!")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("delete")
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
        freshbooks invoice delete 1234567
        freshbooks invoice delete 1234567 -F
    """
    try:
        client = get_client()

        # Get invoice details first
        invoice = client.get_invoice(invoice_id)
        if not invoice:
            typer.echo(f"Invoice {invoice_id} not found.")
            raise typer.Exit(1)

        # Confirm before deleting
        if not force:
            typer.echo(f"Invoice #{invoice.get('invoice_number')}")
            typer.echo(f"Amount: ${invoice.get('amount', {}).get('amount', '0.00')}")
            if not typer.confirm("Delete this invoice?", default=False):
                typer.echo("Aborted.")
                raise typer.Exit(0)

        client.delete_invoice(invoice_id)
        print_success(f"Invoice {invoice.get('invoice_number')} deleted.")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("mark-paid")
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
        freshbooks invoice mark-paid 1234567 -a 500.00
        freshbooks invoice mark-paid 1234567 -a 500.00 -d 2024-01-15
    """
    try:
        from datetime import datetime

        client = get_client()

        payment_date = date or datetime.now().strftime("%Y-%m-%d")
        result = client.mark_invoice_paid(invoice_id, payment_date, amount)

        print_success(f"Invoice marked as paid. Payment ID: {result.get('id')}")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("update")
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
        help="Set payment terms from DEFAULT_TERMS in .env",
    ),
    po_number: Optional[str] = typer.Option(
        None,
        "--po-number",
        "-p",
        help="Update purchase order number/reference",
    ),
):
    """
    Update an existing invoice.

    Examples:
        freshbooks invoice update 1234567 -f ./contract.pdf
        freshbooks invoice update 1234567 -n "Updated notes"
        freshbooks invoice update 1234567 -f ./receipt.pdf -n "Added receipt"
        freshbooks invoice update 1234567 --terms-from-config
        freshbooks invoice update 1234567 -t "Net 30"
    """
    try:
        client = get_client()
        config = get_config()

        # Determine terms to use
        invoice_terms = None
        if terms_from_config:
            if not config.default_terms:
                typer.echo("Error: DEFAULT_TERMS not set in .env")
                raise typer.Exit(1)
            invoice_terms = config.default_terms
        elif terms:
            invoice_terms = terms

        # Check that at least one update option is provided
        if not any([attachment, notes, invoice_terms, po_number]):
            typer.echo("No updates specified. Use --help to see available options.")
            raise typer.Exit(1)

        # Handle file attachment if provided
        attachments = None
        if attachment:
            typer.echo(f"Uploading attachment: {attachment}")
            upload_result = client.upload_attachment(attachment)
            attachments = [
                {
                    "jwt": upload_result["jwt"],
                    "media_type": upload_result["media_type"]
                }
            ]
            typer.echo("Attachment uploaded successfully.")

        invoice = client.update_invoice(
            invoice_id=invoice_id,
            attachments=attachments,
            notes=notes,
            terms=invoice_terms,
            po_number=po_number
        )

        print_success(f"Invoice {invoice.get('invoice_number')} updated.")
        print_json(format_invoice_for_display(invoice))

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("download")
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
        freshbooks invoice download 1234567
        freshbooks invoice download 1234567 -o ~/Downloads/invoice.pdf
        freshbooks invoice download 1234567 --output ./my-invoice.pdf
    """
    try:
        client = get_client()

        # Get invoice details for the filename
        invoice = client.get_invoice(invoice_id)
        if not invoice:
            typer.echo(f"Invoice {invoice_id} not found.")
            raise typer.Exit(1)

        invoice_number = invoice.get("invoice_number", invoice_id)

        # Determine output path
        if output:
            output_path = Path(output).expanduser()
        else:
            output_path = Path(f"invoice_{invoice_number}.pdf")

        # Download the PDF
        typer.echo(f"Downloading invoice #{invoice_number}...")
        pdf_content = client.download_invoice_pdf(invoice_id)

        # Ensure parent directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Write the PDF
        with open(output_path, "wb") as f:
            f.write(pdf_content)

        print_success(f"Invoice saved to {output_path}")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


COMMAND_CREDENTIALS = {
    "create": [
        "oauth"
    ],
    "delete": [
        "oauth"
    ],
    "download": [
        "oauth"
    ],
    "get": [
        "oauth"
    ],
    "list": [
        "oauth"
    ],
    "mark-paid": [
        "oauth"
    ],
    "send": [
        "oauth"
    ],
    "update": [
        "oauth"
    ]
}
