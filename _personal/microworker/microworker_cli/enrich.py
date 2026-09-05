"""`enrich <site>`: pull task descriptions from the site's detail pages.

Some sites publish a description only on the task DETAIL page, never in the
listing rows discovery merges (`microworkers` is the live case: the /jobs.php
row carries title/payment/positions, while the detail page carries
`instructions_and_proof` and `work_summary`). Fetching every detail page for
every discovery run is not viable -- the live queue lists 2500+ rows -- so
enrichment is bounded by the LEDGER instead: the board shows ledger tasks,
and this command walks only the site's ledger rows whose `description` is
still null, one detail fetch each, and writes the site's own text back
through `db.update_task_description`.

Incremental by construction: a row enriched once is skipped forever, and a
later re-discovery cannot wipe the text because the merge upsert's
description guard keeps a stored description when a sighting carries none.
The detail->text extraction is per-site and lives with the site's adapter
(`adapters.detail_description_for`); a site without one is not enrichable and
this command refuses it rather than guessing.

Like `merge`, this runs on the machine that owns the ledger and has the site
CLIs installed -- the discovery machine. The site CLI is called exactly as
discovery calls it (`<cli> tasks get <url>`), so all browser automation stays
inside the site CLIs.
"""

from __future__ import annotations

import json
import time

from cli_tools_shared.exceptions import ClientError, ConfigError

from . import adapters, db, jsonio, runner, sites
from .discover import _ensure_authenticated
from .runner import RunnerError


def enrich(site_name: str, timeout: int, delay: float = 0.0) -> dict:
    site = sites.get_site(site_name)
    if site.disabled:
        raise ConfigError(
            f"site '{site_name}' is disabled in config.json (disabled: true)")
    extractor = adapters.detail_description_for(site_name)
    if extractor is None:
        raise ClientError(
            f"site '{site_name}' has no detail-page description extractor; "
            "enrichment is not defined for this site")
    if site.cli is None:
        raise ConfigError(
            f"site '{site_name}' has cli=null in config.json; nothing to run")
    auth_failure = _ensure_authenticated(site, timeout)
    if auth_failure is not None:
        status, error = auth_failure
        raise ClientError(f"`{site.cli}` is not authenticated: {error}")

    pending = [task for task in db.list_tasks()
               if task["site"] == site_name
               and task.get("description") is None
               and task.get("url")]
    summary = {
        "site": site_name,
        "checked": len(pending),
        "enriched": 0,
        "failed": 0,
        "skipped_no_description": 0,
        "failures": {},
    }
    for index, task in enumerate(pending):
        try:
            result = runner.run([site.cli, "tasks", "get", task["url"]], timeout)
        except RunnerError as exc:
            summary["failed"] += 1
            summary["failures"][task["task_id"]] = str(exc)
            continue
        if result.returncode != 0:
            summary["failed"] += 1
            summary["failures"][task["task_id"]] = (
                f"`{' '.join(result.argv)}` exited {result.returncode}: "
                f"{result.stderr.strip()}")
            continue
        try:
            payload = jsonio.loads(
                result.stdout, f"`{site.cli} tasks get` stdout")
        except (json.JSONDecodeError, jsonio.NonFiniteNumberError) as exc:
            summary["failed"] += 1
            summary["failures"][task["task_id"]] = str(exc)
            continue
        if not isinstance(payload, dict):
            summary["failed"] += 1
            summary["failures"][task["task_id"]] = (
                f"`{site.cli} tasks get` printed a JSON "
                f"{type(payload).__name__}, expected an object")
            continue
        description = extractor(payload)
        if description is None:
            # The site's detail page published no description text. The row is
            # marked with an empty string -- falsy to every reader, distinct
            # from NULL -- so the pending filter above never fetches it again.
            db.update_task_description(site_name, task["task_id"], "")
            summary["skipped_no_description"] += 1
            continue
        db.update_task_description(site_name, task["task_id"], description)
        summary["enriched"] += 1
        # Gentleness: the backfill walks every missing row in one process. A
        # burst of rapid detail fetches is what gets an account flagged (the
        # microworkers account earned a 1-day "Auto-refresh / Bot" ban on
        # 2026-09-04 from a rapid listing + relogin burst); spacing the
        # fetches keeps this within a human-looking cadence.
        if delay > 0 and index < len(pending) - 1:
            time.sleep(delay)
    return summary
