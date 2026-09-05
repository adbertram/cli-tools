"""Adapter for `microworkers tasks list` records.

Raw keys (microworkers_cli/parsers.py `normalize_task_row`): `id` (= url),
`campaign_id`, `title`, `provider`, `url`, `payment` (raw string),
`success_rate_required`, `ttr_days`, `ttf_minutes`, `positions_done`,
`positions_total`.

`payment` is a display string, so it is the one field here that can be present,
non-empty, and still unreadable. `to_task` returns that fact alongside the task
(see `mapped.py`) instead of leaving an unreadable price indistinguishable from
an unpriced one.
"""

from __future__ import annotations

import re

from cli_tools_shared.exceptions import ClientError

from .ids import task_id
from .mapped import MappedTask, is_unparsed_payment

SITE = "microworkers"
RAW_KEYS = ("campaign_id", "title", "url", "payment", "ttf_minutes",
            "positions_done", "positions_total")
# Only a bare US-dollar amount is understood; anything else stays unknown.
PAYMENT_RE = re.compile(r"^\$(\d+\.\d{2})$")


def to_task(raw: dict) -> MappedTask:
    missing = [key for key in RAW_KEYS if key not in raw]
    if missing:
        raise ClientError(
            f"{SITE} record is missing keys: {', '.join(missing)}")
    pay_amount, pay_currency = parse_payment(raw["payment"])
    task = {
        "site": SITE,
        "task_id": task_id(SITE, raw["campaign_id"], field="campaign_id",
                           locator=f"url={raw['url']!r}"),
        "title": raw["title"],
        "description": raw.get("description"),
        "url": raw["url"],
        "pay_amount": pay_amount,
        "pay_currency": pay_currency,
        "est_minutes": raw["ttf_minutes"],
        "slots_open": slots_open(raw["positions_done"], raw["positions_total"]),
        "expires_at": None,
        "raw": raw,
    }
    return MappedTask(
        task=task,
        unparsed_payment=is_unparsed_payment(raw["payment"], pay_amount))


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


def detail_description(detail: dict) -> str | None:
    """Description text for a task DETAIL record (`microworkers tasks get`).

    The jobs listing carries no description; the detail page's
    `instructions_and_proof` and `work_summary` paragraph lists are the
    site's own text about the job. Instructions come first -- that is the
    actual description -- followed by the summary. Paragraphs are joined with
    newlines; when the site published neither, this is None: no text is
    invented.
    """
    paragraphs: list[str] = []
    for key in ("instructions_and_proof", "work_summary"):
        value = detail.get(key) or []
        if not isinstance(value, list):
            continue
        paragraphs.extend(
            str(item).strip() for item in value if str(item).strip())
    if not paragraphs:
        return None
    return "\n".join(paragraphs)
