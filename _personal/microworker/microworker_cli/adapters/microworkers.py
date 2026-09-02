"""Adapter for `microworkers tasks list` records.

Raw keys (microworkers_cli/parsers.py `normalize_task_row`): `id` (= url),
`campaign_id`, `title`, `provider`, `url`, `payment` (raw string),
`success_rate_required`, `ttr_days`, `ttf_minutes`, `positions_done`,
`positions_total`.
"""

from __future__ import annotations

import re

from cli_tools_shared.exceptions import ClientError

SITE = "microworkers"
RAW_KEYS = ("campaign_id", "title", "url", "payment", "ttf_minutes",
            "positions_done", "positions_total")
# Only a bare US-dollar amount is understood; anything else stays unknown.
PAYMENT_RE = re.compile(r"^\$(\d+\.\d{2})$")


def to_task(raw: dict) -> dict:
    missing = [key for key in RAW_KEYS if key not in raw]
    if missing:
        raise ClientError(
            f"{SITE} record is missing keys: {', '.join(missing)}")
    campaign_id = raw["campaign_id"]
    if campaign_id is None or str(campaign_id) == "":
        raise ClientError(
            f"{SITE} record has no campaign_id (url={raw['url']!r})")
    pay_amount, pay_currency = parse_payment(raw["payment"])
    return {
        "site": SITE,
        "task_id": str(campaign_id),
        "title": raw["title"],
        "url": raw["url"],
        "pay_amount": pay_amount,
        "pay_currency": pay_currency,
        "est_minutes": raw["ttf_minutes"],
        "slots_open": slots_open(raw["positions_done"], raw["positions_total"]),
        "expires_at": None,
        "raw": raw,
    }


def parse_payment(payment) -> tuple[float | None, str | None]:
    if not isinstance(payment, str):
        return None, None
    match = PAYMENT_RE.match(payment.strip())
    if match is None:
        return None, None
    return float(match.group(1)), "USD"


def slots_open(done, total) -> int | None:
    if isinstance(done, int) and isinstance(total, int):
        return total - done
    return None
