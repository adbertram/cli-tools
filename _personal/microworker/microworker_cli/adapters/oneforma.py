"""Adapter for `oneforma tasks list` records.

Raw keys (oneforma_cli/parsers.py `normalize_job_row`): `id`, `url`, `title`,
`project_id`, `project_name`, `job_type`, `project_category`, `rate`,
`rate_min`, `rate_max`, `rate_unit`, `rate_currency_symbol`, `deadline`,
`days_left`, `publish_date`, `applicant_count`, `apply_status`,
`target_countries`, `locale`, `platform`, `invited`.

Mapping notes (OneForma has no analog for some contract fields):
  - `pay_amount`: OneForma returns `rate` as a decimal string ("100.0000")
    that is a rate per `rate_unit` ("Per Hour", "Per Task"), not a fixed task
    payout. The number is reported as-is; `rate_unit` stays in `raw` so the
    unit is never silently dropped.
  - `pay_currency`: the API exposes only a symbol (`rate_currency_symbol`),
    never an ISO code. "$" maps to USD, matching the microworkers adapter;
    any other symbol stays `None` rather than being guessed.
  - `est_minutes`: OneForma publishes no per-task duration — an hourly rate
    is not a duration — so this is always `None`.
  - `slots_open`: OneForma exposes `applicant_count` (people who applied),
    which is not a remaining-slot count, so this stays `None` rather than
    reporting applicants as openings.
  - `expires_at`: `deadline` is the site's hiring deadline for the job post,
    the one real expiry timestamp it publishes.
"""

from __future__ import annotations

from cli_tools_shared.exceptions import ClientError

from .ids import task_id

SITE = "oneforma"
RAW_KEYS = ("id", "url", "title", "rate", "rate_currency_symbol", "deadline")
# Only a bare US-dollar symbol is understood; anything else stays unknown.
CURRENCY_BY_SYMBOL = {"$": "USD"}


def to_task(raw: dict) -> dict:
    missing = [key for key in RAW_KEYS if key not in raw]
    if missing:
        raise ClientError(
            f"{SITE} record is missing keys: {', '.join(missing)}")
    pay_amount = parse_rate(raw["rate"])
    return {
        "site": SITE,
        "task_id": task_id(SITE, raw["id"], field="id",
                           locator=f"title={raw['title']!r}"),
        "title": raw["title"],
        "url": raw["url"],
        "pay_amount": pay_amount,
        "pay_currency": parse_currency(raw["rate_currency_symbol"])
        if pay_amount is not None else None,
        "est_minutes": None,
        "slots_open": None,
        "expires_at": raw["deadline"],
        "raw": raw,
    }


def parse_rate(rate) -> float | None:
    """OneForma sends the rate as a decimal string; anything else is unknown."""
    if isinstance(rate, (int, float)) and not isinstance(rate, bool):
        return float(rate)
    if not isinstance(rate, str) or not rate.strip():
        return None
    try:
        return float(rate)
    except ValueError:
        return None


def parse_currency(symbol) -> str | None:
    if not isinstance(symbol, str):
        return None
    return CURRENCY_BY_SYMBOL.get(symbol.strip())
