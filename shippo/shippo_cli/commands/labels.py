"""Label (transaction) commands for Shippo CLI."""
COMMAND_CREDENTIALS = {
    "create": [
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
    "print": [
        "api_key"
    ],
    "void": [
        "api_key"
    ]
}

import typer
from typing import Optional, List
import requests
from pathlib import Path

from pydantic import BaseModel

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, print_success, print_info, handle_error
from cli_tools_shared.filters import apply_filters
from ..parsers import format_local_time


app = typer.Typer(help="Manage Shippo shipping labels", no_args_is_help=True)


def model_to_dict(item):
    """Convert model or dict to dict for field extraction."""
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


def extract_field(item, field: str):
    """Extract a field value, supporting dot-notation for nested fields."""
    data = model_to_dict(item)
    parts = field.split(".")
    value = data
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def extract_fields(items: list, fields: list) -> list:
    """Extract specified fields from items, supporting dot-notation."""
    result = []
    for item in items:
        extracted = {}
        for field in fields:
            value = extract_field(item, field)
            extracted[field] = value
        result.append(extracted)
    return result


@app.command("list")
def labels_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of labels to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List purchased labels (transactions).

    Examples:
        shippo labels list
        shippo labels list --table
        shippo labels list --filter "status:success"
        shippo labels list --filter "tracking_status:delivered"
        shippo labels list --properties "object_id,tracking_number,status,label_url"
    """
    try:
        client = get_client()
        transactions = client.list_transactions(limit=limit, filters=filter)

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            transactions = extract_fields(transactions, fields)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(transactions, fields, fields)
            else:
                rows = []
                for t in transactions:
                    d = model_to_dict(t)
                    rows.append({
                        "object_id": d.get("object_id", "")[:16],
                        "tracking_number": d.get("tracking_number", "") or "",
                        "status": d.get("status", ""),
                        "carrier": d.get("rate", {}).get("provider", "") if d.get("rate") else "",
                        "created": format_local_time(d.get("object_created", "") or ""),
                    })
                print_table(
                    rows,
                    ["object_id", "tracking_number", "status", "carrier", "created"],
                    ["ID", "Tracking #", "Status", "Carrier", "Created"],
                )
        else:
            print_json(transactions)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def labels_get(
    transaction_id: str = typer.Argument(..., help="The transaction/label object ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    Get details for a specific label (transaction).

    Examples:
        shippo labels get TRANSACTION_ID
        shippo labels get TRANSACTION_ID --table
    """
    try:
        client = get_client()
        transaction = client.get_transaction(transaction_id)

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            transaction = extract_fields([transaction], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([transaction], fields, fields)
            else:
                item_dict = model_to_dict(transaction)
                rows = [{"field": k, "value": str(v)[:80]} for k, v in item_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(transaction)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def labels_create(
    rate_id: str = typer.Argument(..., help="The rate object ID to purchase"),
    label_format: str = typer.Option("PDF_4x6", "--format", "-F", help="Label format: PDF_4x6, PDF, PNG, ZPLII (default: PDF_4x6)"),
    metadata: Optional[str] = typer.Option(None, "--metadata", "-m", help="Optional metadata string"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Purchase a shipping label from a rate.

    First create a shipment to get rates, then use a rate ID to purchase a label.

    Examples:
        shippo labels create RATE_ID
        shippo labels create RATE_ID --format ZPLII
        shippo labels create RATE_ID --metadata "Order #12345"
    """
    try:
        client = get_client()
        # Map common format names to exact enum values
        format_map = {
            "PDF": "PDF",
            "PDF_4X6": "PDF_4x6",
            "PDF_4x6": "PDF_4x6",
            "PDF_4X8": "PDF_4x8",
            "PDF_4x8": "PDF_4x8",
            "PNG": "PNG",
            "ZPLII": "ZPLII",
            "ZPL": "ZPLII",
        }
        actual_format = format_map.get(label_format.upper().replace("X", "x").replace("4X", "4x"), label_format)

        transaction = client.create_transaction(
            rate_id=rate_id,
            label_file_type=actual_format,
            metadata=metadata,
        )

        if table:
            item_dict = model_to_dict(transaction)
            rows = [{"field": k, "value": str(v)[:80]} for k, v in item_dict.items() if v is not None]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(transaction)

        # Show helpful message
        if transaction.label_url:
            print_info(f"Label URL: {transaction.label_url}")
        if transaction.tracking_number:
            print_info(f"Tracking #: {transaction.tracking_number}")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("download")
def labels_download(
    transaction_id: str = typer.Argument(..., help="The transaction/label object ID"),
    output: Optional[str] = typer.Option(None, "-o", "--output", help="Output file path (default: label_<tracking>.pdf)"),
):
    """
    Download a label file.

    Examples:
        shippo labels download TRANSACTION_ID
        shippo labels download TRANSACTION_ID -o my_label.pdf
    """
    try:
        client = get_client()
        transaction = client.get_transaction(transaction_id)

        if not transaction.label_url:
            from cli_tools_shared.output import print_error
            print_error("No label URL available for this transaction")
            raise typer.Exit(1)

        # Download the label
        response = requests.get(transaction.label_url)
        response.raise_for_status()

        # Determine output filename
        if output:
            filepath = Path(output)
        else:
            tracking = transaction.tracking_number or transaction_id[:8]
            ext = "pdf"
            if transaction.label_file_type:
                if "PNG" in transaction.label_file_type.upper():
                    ext = "png"
                elif "ZPL" in transaction.label_file_type.upper():
                    ext = "zpl"
            filepath = Path(f"label_{tracking}.{ext}")

        # Write the file
        filepath.write_bytes(response.content)
        print_success(f"Label downloaded to: {filepath}")

    except requests.RequestException as e:
        from cli_tools_shared.output import print_error
        print_error(f"Failed to download label: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("print")
def labels_print(
    label_id: str = typer.Argument(..., help="Transaction ID or tracking number"),
    printer_name: str = typer.Option("Zebra_LP2844", "--printer", "-p", help="Printer name to use"),
    printer_timeout: int = typer.Option(90, "--timeout", "-T", help="Seconds to wait for print job to complete"),
):
    """
    Download and print a shipping label.

    Downloads the label PDF and sends it to the specified printer.

    Examples:
        # Print by transaction ID
        shippo labels print d3f43baa320949e99402777b28a8d888

        # Print by tracking number
        shippo labels print 9200190396055700531869

        # Print to a different printer
        shippo labels print d3f43baa320949e99402777b28a8d888 -p my_printer

        # Custom timeout
        shippo labels print d3f43baa320949e99402777b28a8d888 -T 60
    """
    import os
    import re
    import subprocess
    import tempfile
    import time

    try:
        client = get_client()

        # Try to get by transaction ID first, then by tracking number
        transaction = None
        try:
            transaction = client.get_transaction(label_id)
        except Exception:
            # Not a valid transaction ID, try searching by tracking number
            pass

        if not transaction:
            # Search in recent transactions for matching tracking number
            transactions = client.list_transactions(limit=100)
            for t in transactions:
                if t.tracking_number == label_id:
                    transaction = t
                    break

        if not transaction:
            print_info(f"No label found with ID or tracking number: {label_id}")
            raise typer.Exit(1)

        if not transaction.label_url:
            print_info("No label URL available for this transaction")
            raise typer.Exit(1)

        # Download the label
        print_info(f"Downloading label for tracking: {transaction.tracking_number or 'N/A'}")
        response = requests.get(transaction.label_url)
        response.raise_for_status()

        # Determine file type from URL or content
        label_url = transaction.label_url.lower()
        is_zpl = 'zpl' in label_url or response.content[:20].startswith(b'^XA')
        suffix = ".zpl" if is_zpl else ".pdf"

        # Save to temp file
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
            tmp_file.write(response.content)
            tmp_path = tmp_file.name

        try:
            if is_zpl:
                # ZPL format: send raw to Zebra printer using lp -o raw
                print_cmd = ["lp", "-d", printer_name, "-o", "raw", tmp_path]
            else:
                # PDF format: simple print (label should already be 4x6 from API)
                print_cmd = ["lp", "-d", printer_name, tmp_path]
            proc = subprocess.run(print_cmd, capture_output=True, text=True)

            if proc.returncode != 0:
                print_info(f"Print failed: {proc.stderr.strip() or 'Print command failed'}")
                raise typer.Exit(1)

            # Extract job ID from output
            # lp: "request id is Zebra_LP2844-2153 (1 file(s))"
            match = re.search(r"request id is (\S+)", proc.stdout)
            job_id = match.group(1) if match else None

            if not job_id:
                print_success(f"Label sent to {printer_name} (could not track job)")
                print_json({
                    "tracking_number": transaction.tracking_number,
                    "transaction_id": transaction.object_id,
                    "printed": True,
                    "printer": printer_name,
                })
                return

            # Wait for job to complete, with one retry if job was silently aborted
            retries_left = 1
            while True:
                start = time.time()
                job_disappeared = False
                while time.time() - start < printer_timeout:
                    status_proc = subprocess.run(
                        ["lpstat", "-o", printer_name],
                        capture_output=True, text=True
                    )

                    if job_id not in status_proc.stdout:
                        job_disappeared = True
                        break

                    # Also check if job already moved to completed queue
                    # (CUPS can keep it in active queue briefly after completion)
                    completed_check = subprocess.run(
                        ["lpstat", "-W", "completed", "-o", printer_name],
                        capture_output=True, text=True
                    )
                    if job_id in completed_check.stdout:
                        print_success(f"Label printed to {printer_name}")
                        print_json({
                            "tracking_number": transaction.tracking_number,
                            "transaction_id": transaction.object_id,
                            "printed": True,
                            "printer": printer_name,
                            "job_id": job_id,
                        })
                        return

                    time.sleep(1)

                if not job_disappeared:
                    # Timeout
                    print_info(f"Print timed out: job {job_id} still queued after {printer_timeout}s")
                    print_json({
                        "tracking_number": transaction.tracking_number,
                        "transaction_id": transaction.object_id,
                        "printed": False,
                        "printer": printer_name,
                        "job_id": job_id,
                        "error": f"Timed out after {printer_timeout}s",
                    })
                    raise typer.Exit(1)

                # Job is gone from active queue - check if printer is disabled
                printer_status = subprocess.run(
                    ["lpstat", "-p", printer_name],
                    capture_output=True, text=True
                )

                if "disabled" in printer_status.stdout.lower():
                    print_info(f"Print failed: Printer {printer_name} is disabled or offline")
                    print_json({
                        "tracking_number": transaction.tracking_number,
                        "transaction_id": transaction.object_id,
                        "printed": False,
                        "printer": printer_name,
                        "job_id": job_id,
                        "error": "Printer is disabled or offline",
                    })
                    raise typer.Exit(1)

                # Verify job actually completed (not silently aborted by CUPS)
                time.sleep(0.3)
                completed_proc = subprocess.run(
                    ["lpstat", "-W", "completed", "-o", printer_name],
                    capture_output=True, text=True
                )

                if job_id in completed_proc.stdout:
                    # Job confirmed in completed list - genuine success
                    print_success(f"Label printed to {printer_name}")
                    print_json({
                        "tracking_number": transaction.tracking_number,
                        "transaction_id": transaction.object_id,
                        "printed": True,
                        "printer": printer_name,
                        "job_id": job_id,
                    })
                    return

                # Job not in completed list - it was silently aborted
                if retries_left > 0:
                    retries_left -= 1
                    print_info(f"Job {job_id} was silently aborted by CUPS, retrying print...")
                    retry_proc = subprocess.run(print_cmd, capture_output=True, text=True)
                    if retry_proc.returncode != 0:
                        print_info(f"Print retry failed: {retry_proc.stderr.strip() or 'Print command failed'}")
                        raise typer.Exit(1)
                    retry_match = re.search(r"request id is (\S+)", retry_proc.stdout)
                    job_id = retry_match.group(1) if retry_match else None
                    if not job_id:
                        print_info("Print retry submitted but could not track job")
                        raise typer.Exit(1)
                    continue
                else:
                    # Retry also failed to show in completed list
                    print_info(f"Print failed: job {job_id} was not completed by CUPS (silently aborted)")
                    print_json({
                        "tracking_number": transaction.tracking_number,
                        "transaction_id": transaction.object_id,
                        "printed": False,
                        "printer": printer_name,
                        "job_id": job_id,
                        "error": "Job silently aborted by CUPS after retry",
                    })
                    raise typer.Exit(1)

        finally:
            # Small delay before cleanup to avoid race with CUPS still reading the file
            time.sleep(0.5)
            # Clean up temp file
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    except requests.RequestException as e:
        print_info(f"Failed to download label: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("void")
def labels_void(
    transaction_id: str = typer.Argument(..., help="The transaction/label object ID to void"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Void (refund) a shipping label.

    Note: Refunds are not instant. The status will be QUEUED until processed.

    Examples:
        shippo labels void TRANSACTION_ID
        shippo labels void TRANSACTION_ID --table
    """
    try:
        client = get_client()
        refund = client.create_refund(transaction_id)

        if table:
            item_dict = model_to_dict(refund)
            rows = [{"field": k, "value": str(v)} for k, v in item_dict.items() if v is not None]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(refund)

        print_info(f"Refund status: {refund.status}")

    except Exception as e:
        raise typer.Exit(handle_error(e))
