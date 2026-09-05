"""Adapter for `trainee-digital tasks list` records.

Raw keys (trainee_digital_cli/parsers.py `normalize_order`): `id`, `title`,
`category`, `pay`, `unit`, `volume`, `deadline`, `posted`, plus the derived
`url` (the /orders listing page every order is listed on). Detail-only keys
(`totalPay`, `dataset`, `scope`, `guidelines`, `createdAt`) can appear on a
record but are not required.

Mapping notes (trainee.digital has no analog for some contract fields):
  - `pay_amount`: the feed publishes `pay` as a display string ("$0.40").
    A bare US-dollar prefix with an optional decimal amount is parsed
    ("$0.40" -> 0.4, "$2,200" -> 2200.0); any other shape stays `None` and is
    surfaced through the `mapped.py` seam as an unparsed published price.
  - `pay_currency`: only "$" is understood (USD, matching the microworkers and
    oneforma adapters); a parsed amount beside an unknown symbol keeps
    `pay_amount` and leaves `pay_currency` `None` rather than guessing.
  - `est_minutes`: the feed publishes no per-task duration, only a `volume`
    human string ("1,200 pages") and a `deadline` human string ("5 days"), so
    this is always `None`.
  - `slots_open`: never published on the order feed, so `None`.
  - `expires_at`: `deadline` is a relative human string ("5 days"), not a
    timestamp, so it stays `None` rather than being stored as an expiry it is
    not.
"""

from __future__ import annotations

import re

from cli_tools_shared.exceptions import ClientError

from .ids import task_id
from .mapped import MappedTask, is_unparsed_payment

SITE = "trainee-digital"
RAW_KEYS = ("id", "url", "title", "pay", "volume", "deadline")
# Only a bare US-dollar prefix is understood; anything else stays unknown.
PAY_RE = re.compile(r"^\$(?P<amount>[\d,]+(?:\.\d+)?)$")


def to_task(raw: dict) -> MappedTask:
    missing = [key for key in RAW_KEYS if key not in raw]
    if missing:
        raise ClientError(
            f"{SITE} record is missing keys: {', '.join(missing)}")
    pay_amount = parse_pay(raw["pay"])
    task = {
        "site": SITE,
        "task_id": task_id(SITE, raw["id"], field="id",
                           locator=f"title={raw['title']!r}"),
        "title": raw["title"],
        "description": raw.get("description"),
        "url": raw["url"],
        "pay_amount": pay_amount,
        "pay_currency": parse_currency(raw["pay"])
        if pay_amount is not None else None,
        "est_minutes": None,
        "slots_open": None,
        "expires_at": None,
        "raw": raw,
    }
    return MappedTask(
        task=task,
        unparsed_payment=is_unparsed_payment(raw["pay"], pay_amount))


def parse_pay(pay) -> float | None:
    """trainee.digital sends `pay` as a "$<amount>" display string.

    Thousand separators are tolerated ("$2,200" -> 2200.0); anything else is
    an unknown amount, not a guessed one.
    """
    if isinstance(pay, (int, float)) and not isinstance(pay, bool):
        return float(pay)
    if not isinstance(pay, str) or not pay.strip():
        return None
    match = PAY_RE.match(pay.strip())
    if match is None:
        return None
    try:
        return float(match.group("amount").replace(",", ""))
    except ValueError:
        return None


def parse_currency(pay) -> str | None:
    if not isinstance(pay, str) or not pay.strip():
        return None
    return "USD" if PAY_RE.match(pay.strip()) else None
