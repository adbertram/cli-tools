"""Rebuild an invoice's ``lines`` array with changed unit prices.

The FreshBooks Accounting API replaces the whole ``lines`` array on a PUT:
"the request payload must contain all the lines of the invoice that you wish
to remain" (https://www.freshbooks.com/api/invoices). Changing one price
therefore means resending every line, so each fetched line is reduced to its
writable fields (type, expenseid, qty, unit_cost, description, name,
modern_project_id, modern_time_entries, taxName1/2, taxAmount1/2). Computed
fields (amount, updated) and server bookkeeping are dropped.
"""
from decimal import Decimal, InvalidOperation
from typing import Dict, List

from cli_tools_shared.exceptions import ClientError

_COPIED_FIELDS = ("name", "description", "qty", "type", "expenseid")


def parse_line_amounts(specs: List[str]) -> Dict[str, str]:
    """Parse repeated ``LINEID=AMOUNT`` specs into ``{lineid: amount}``.

    Raises ClientError for a malformed spec, a duplicate lineid, or an amount
    that is not a finite number greater than zero.
    """
    amounts: Dict[str, str] = {}
    for spec in specs:
        lineid, sep, raw_amount = spec.partition("=")
        lineid, raw_amount = lineid.strip(), raw_amount.strip()
        if not sep or not lineid or not raw_amount:
            raise ClientError(f"Invalid --line-amount '{spec}': expected LINEID=AMOUNT")
        if lineid in amounts:
            raise ClientError(f"Duplicate --line-amount for line {lineid}")
        try:
            value = Decimal(raw_amount)
        except InvalidOperation:
            raise ClientError(
                f"Invalid amount '{raw_amount}' for line {lineid}: must be a number"
            )
        if not value.is_finite() or value <= 0:
            raise ClientError(
                f"Invalid amount '{raw_amount}' for line {lineid}: must be greater than zero"
            )
        amounts[lineid] = raw_amount
    return amounts


def rebuild_lines(existing: List[Dict], amounts: Dict[str, str]) -> List[Dict]:
    """Return the full PUT ``lines`` list with ``unit_cost`` changed per ``amounts``.

    Lines not named in ``amounts`` keep every writable field unchanged. Raises
    ClientError when an amount names a lineid the invoice does not have.
    """
    known = {str(line["lineid"]) for line in existing}
    unknown = sorted(set(amounts) - known)
    if unknown:
        raise ClientError(
            f"Unknown line ID(s): {', '.join(unknown)}. "
            f"Invoice has lines: {', '.join(sorted(known, key=int))}"
        )

    rebuilt = []
    for line in existing:
        out: Dict = {"lineid": line["lineid"]}
        for field in _COPIED_FIELDS:
            if field in line:
                out[field] = line[field]
        unit_cost = dict(line["unit_cost"])
        if str(line["lineid"]) in amounts:
            unit_cost["amount"] = amounts[str(line["lineid"])]
        out["unit_cost"] = unit_cost
        for n in ("1", "2"):
            if line.get(f"taxName{n}"):
                out[f"taxName{n}"] = line[f"taxName{n}"]
                out[f"taxAmount{n}"] = line[f"taxAmount{n}"]
        if line.get("modern_project_id"):
            out["modern_project_id"] = line["modern_project_id"]
        if line.get("modern_time_entries"):
            out["modern_time_entries"] = line["modern_time_entries"]
        rebuilt.append(out)
    return rebuilt
