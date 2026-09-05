"""Adapter for `mercor tasks list` records.

Raw keys (mercor_cli/parsers.py `normalize_listing`): the full listing object
from `GET aws.api.mercor.com/work/listings-explore-page` -- `listingId`, `uid`,
`title`, `description`, `status`, `listingType`, `rateMin`, `rateMax`,
`payRateFrequency`, `commitment`, `workArrangement`, `location`,
`remainingSlots`, `referralAmount`, `hoursPerWeek`, `postedAt`, `createdAt`,
... -- plus the derived public keys `id` (= `listingId`), `title` and `url`.

PROVENANCE. The fixture (`tests/fixtures/mercor_tasks_list.json`) is a real
record captured live 2026-09-03 from Adam's authenticated Mercor worker
session: listing `list_AAABoGYcR_Q8k7gMhOdC84s-` "Certified Medical Coder
(ICD-10) ..." from the 402-listing `/listings-explore-page` response. Field
names come from that capture, not from guesswork.

Mapping notes (Mercor publishes no single price and no currency code):
  - `pay_amount`/`pay_currency`: a listing carries `rateMin`..`rateMax` (float
    or null) and `payRateFrequency` (`hourly`/`per-task`/`one-time`/`yearly`),
    but no ISO currency or symbol anywhere on the record (the site renders "$"
    in the UI only). When `rateMin == rateMax` the site published a single
    price point, and that number is reported as `pay_amount` with a null
    currency -- mirroring how the oneforma adapter reports its rate while its
    unit stays in `raw` (the frequency does too, via `raw`). A range
    (`rateMin < rateMax`) is not a single published price, so both stay `None`
    rather than reporting the lower bound as if it were the price. Nothing is
    ever guessed.
  - `est_minutes`: Mercor publishes no per-listing duration (the interview
    estimate lives in the description prose, not in a field), so always `None`.
  - `slots_open`: `remainingSlots` is the real remaining-open-slots count Mercor
    publishes (int or null) -- the one contract field Mercor fills directly.
  - `expires_at`: listings carry `postedAt`/`createdAt` and a `status`, never
    an expiry timestamp, so always `None`.
  - `unparsed_payment` (the `mapped.py` seam) is always False: Mercor's pay
    numbers are read and kept verbatim in `raw`, and a null `pay_amount` here
    is the adapter's deliberate contract mapping (range / no currency), not a
    parse failure the seam exists to surface.
"""

from __future__ import annotations

from typing import Any, Optional

from cli_tools_shared.exceptions import ClientError

from .ids import task_id
from .mapped import MappedTask

SITE = "mercor"
RAW_KEYS = ("listingId", "title", "url", "description")


def to_task(raw: dict) -> MappedTask:
    missing = [key for key in RAW_KEYS if key not in raw]
    if missing:
        raise ClientError(
            f"{SITE} record is missing keys: {', '.join(missing)}")
    task = {
        "site": SITE,
        "task_id": task_id(SITE, raw["listingId"], field="listingId",
                           locator=f"url={raw['url']!r}"),
        "title": raw["title"],
        "description": raw["description"],
        "url": raw["url"],
        "pay_amount": pay_amount(raw),
        "pay_currency": None,
        "est_minutes": None,
        "slots_open": slots_open(raw["remainingSlots"]),
        "expires_at": None,
        "raw": raw,
    }
    return MappedTask(task=task, unparsed_payment=False)


def pay_amount(raw: dict) -> Optional[float]:
    """The single published price point, or None for a range.

    `rateMin` and `rateMax` are floats or null. Only an exact price
    (`rateMin == rateMax`, non-null) maps to `pay_amount`; a range is no
    single published price. A `payRateFrequency` other than a fixed unit is
    not a reason to drop an exact number (the oneforma adapter reports its
    per-unit rate the same way); the frequency stays visible in `raw`.
    """
    rate_min = raw.get("rateMin")
    rate_max = raw.get("rateMax")
    if isinstance(rate_min, bool) or isinstance(rate_max, bool):
        return None
    if not isinstance(rate_min, (int, float)) or not isinstance(rate_max, (int, float)):
        return None
    if rate_min != rate_max:
        return None
    return float(rate_min)


def slots_open(remaining: Any) -> Optional[int]:
    """Mercor's remaining-slots count, when it published one."""
    if isinstance(remaining, bool) or not isinstance(remaining, int):
        return None
    return remaining
