"""Display formatters for FreshBooks data objects."""
from typing import Dict


def format_invoice_for_display(invoice: Dict) -> Dict:
    """Format an invoice for display in tables and JSON output."""
    amount_obj = invoice.get("amount", {})
    amount = amount_obj.get("amount", "0.00") if isinstance(amount_obj, dict) else "0.00"

    outstanding_obj = invoice.get("outstanding", {})
    outstanding = outstanding_obj.get("amount", "0.00") if isinstance(outstanding_obj, dict) else "0.00"

    client = (
        invoice.get("current_organization", "") or
        invoice.get("fname", "") + " " + invoice.get("lname", "") or
        str(invoice.get("customerid", ""))
    ).strip()

    return {
        "id": invoice.get("id", invoice.get("invoiceid", "")),
        "number": invoice.get("invoice_number", ""),
        "client": client,
        "status": invoice.get("status", invoice.get("v3_status", "")),
        "amount": f"${amount}",
        "outstanding": f"${outstanding}",
        "created": invoice.get("create_date", ""),
        "due_date": invoice.get("due_date", ""),
    }


def format_client_for_display(client: Dict) -> Dict:
    """Format a client/customer for display in tables and JSON output."""
    fname = client.get("fname", "")
    lname = client.get("lname", "")
    name = f"{fname} {lname}".strip()

    return {
        "id": client.get("id", client.get("userid", "")),
        "organization": client.get("organization", ""),
        "name": name,
        "email": client.get("email", ""),
    }
