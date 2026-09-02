"""Adapter for `humanrail tasks list` records.

Raw keys (humanrail_cli/parsers.py `normalize_task_row`): `id`, `url`,
`type`, `payout_sats`, `risk_tier`, `skills_required`, `estimated_minutes`,
`sla_deadline`, `sla_seconds`.

Mapping notes (HumanRail has no analog for some contract fields):
  - `pay_amount`/`pay_currency`: HumanRail pays in satoshis, not a fiat
    currency. `payout_sats` is reported as-is with currency `"SATS"` rather
    than invented through an unknown BTC/USD conversion rate.
  - `slots_open`: HumanRail tasks are single-worker claims (no multi-worker
    slot pool like microworkers), so this is always `None` — there is no
    "slots" concept on this site, not an unobserved value.
  - `expires_at`: HumanRail has no listing-expiry field; `sla_deadline` (the
    deadline to complete the task once claimed) is the closest real
    timestamp the site exposes, so it is used here rather than leaving a
    real signal unused.
"""

from __future__ import annotations

from cli_tools_shared.exceptions import ClientError

from .ids import task_id

SITE = "humanrail"
RAW_KEYS = ("id", "url", "type", "payout_sats", "estimated_minutes", "sla_deadline")


def to_task(raw: dict) -> dict:
    missing = [key for key in RAW_KEYS if key not in raw]
    if missing:
        raise ClientError(
            f"{SITE} record is missing keys: {', '.join(missing)}")
    return {
        "site": SITE,
        "task_id": task_id(SITE, raw["id"], field="id",
                           locator=f"url={raw['url']!r}"),
        "title": title_for(raw.get("type")),
        "url": raw["url"],
        "pay_amount": raw["payout_sats"],
        "pay_currency": "SATS" if raw["payout_sats"] is not None else None,
        "est_minutes": raw["estimated_minutes"],
        "slots_open": None,
        "expires_at": raw["sla_deadline"],
        "raw": raw,
    }


def title_for(task_type) -> str | None:
    """Match HumanRail's own display formatting for a task `type` value
    (e.g. "contract_review" -> "Contract Review"), validated against the
    site's live frontend bundle (`O1`/`uk` components) 2026-09-02."""
    if not isinstance(task_type, str) or not task_type:
        return None
    return " ".join(word.capitalize() for word in task_type.split("_"))
