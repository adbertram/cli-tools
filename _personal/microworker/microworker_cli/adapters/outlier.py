"""Adapter for `outlier tasks list` records.

Raw keys (outlier_cli/parsers.py `normalize_task_rows`): `id`, `url`, `type`,
`assignment_type`, `node_type`, `project_id`, `review_level`,
`onboarding_flow_id`, `name`, `display_name`, `description`,
`qualification_id`, `qualification_type`, `qualification_status`,
`qualification_list_status`, `qualification_estimated_time`, `is_assessment`,
`is_pay_multiplier`, `created_at`, `updated_at`.

PROVENANCE. Those field names come from Outlier's own deployed frontend bundle
(`96381-*.js`, which ships verbatim `/internal/v2/tasks/peek_queue` response
fixtures, plus the accessor code in `375458-*.js` that reads
`assignments[0].{type,projectId,qualificationList,...}`), not from a live
queued assignment: the account's queue is empty and gated behind Outlier's KYC
/ pay-setup step, which `outlier queue status` reports as
`empty_queue_reason: "KYCInfoCollection"`. Nothing here is guessed, but nothing
here has been seen on a live assignment either. If the live shape turns out to
differ, the `RAW_KEYS` check below raises a `ClientError` at merge time and the
run fails loudly rather than storing a mismapped task.

Mapping notes (Outlier has no analog for several contract fields):
  - `title`: `display_name` is the label the site itself renders. `name` and
    `description` carry the same string in every observed fixture; picking the
    display field keeps the ledger showing what a worker would see on the site.
  - `pay_amount`/`pay_currency`: an Outlier assignment carries no price at all.
    Pay lives on a separate `/internal/scaler/pay_rate_card/...` endpoint keyed
    by project, not on the assignment record this adapter maps, so both stay
    `None` — the site published nothing, rather than publishing something this
    adapter could not read.
  - `est_minutes`: `qualification_estimated_time` is deliberately NOT mapped
    here. Outlier never renders a unit alongside it anywhere in its bundle, so
    calling it minutes would be an invention; an unlabelled number is not a
    duration.
  - `slots_open`: Outlier assigns work to one expert at a time and publishes no
    multi-worker slot pool (unlike microworkers), so there is no "slots"
    concept on this site — not an unobserved value.
  - `expires_at`: assignments carry no expiry field.
  - `unparsed_payment` (the `mapped.py` seam) is always False, and that is a
    fact about Outlier rather than a default: the site publishes no payment
    value on an assignment for this adapter to fail at parsing.
"""

from __future__ import annotations

from cli_tools_shared.exceptions import ClientError

from .ids import task_id
from .mapped import MappedTask

SITE = "outlier"
RAW_KEYS = ("id", "url", "display_name", "description")


def to_task(raw: dict) -> MappedTask:
    missing = [key for key in RAW_KEYS if key not in raw]
    if missing:
        raise ClientError(
            f"{SITE} record is missing keys: {', '.join(missing)}")
    task = {
        "site": SITE,
        "task_id": task_id(SITE, raw["id"], field="id",
                           locator=f"url={raw['url']!r}"),
        "title": raw["display_name"],
        "description": raw["description"],
        "url": raw["url"],
        "pay_amount": None,
        "pay_currency": None,
        "est_minutes": None,
        "slots_open": None,
        "expires_at": None,
        "raw": raw,
    }
    return MappedTask(task=task, unparsed_payment=False)
