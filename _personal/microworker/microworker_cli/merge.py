"""`merge <run_id>`: every site envelope of a run -> the SQLite task store.

All-or-nothing, in this order: the run directory must hold an envelope for every
ENABLED site in config.json (sites with `disabled: true` are skipped -- their
workers are not spawned, so no envelope exists or is expected) and no envelope
for anything else, every envelope must validate, every `ok` task must map
through its site adapter and validate against the task contract, and the run's
mapped tasks must be unique by `(site, task_id)`. Only then does anything reach
the database, and it lands in one transaction (see `db.write_run`). A single
bad envelope or task fails the whole merge and leaves the store exactly as it
was.

THE ENVELOPE SET IS CHECKED IN BOTH DIRECTIONS. Requiring an envelope per
enabled site catches a worker that never ran. Rejecting an envelope for a site
that is not an enabled config.json site catches the opposite mistake -- a stray
or misnamed `<site>.json`, e.g. `microworkers2.json` or a disabled site's
leftover envelope -- which would otherwise be skipped in silence: its tasks
would never merge, it would get no `run_sites` row, and the run would exit 0
as though it had been complete.

DUPLICATE KEYS ARE REJECTED, NOT COLLAPSED. `db.write_run` writes the run's
tasks with `executemany` over an upsert, so two records mapping to the same
`(site, task_id)` inside ONE run would simply overwrite each other and the merge
would report more tasks than rows with no indication which record won. Within a
run that is not a re-sighting, it is a contradiction: two records from the same
listing claiming the same identity (a site printing `100` and `"100"` for the
same campaign, say). It is raised here, before the transaction opens, because
this is where the envelope path and the record indexes are still known.

AN UNREADABLE PRICE IS COUNTED, NOT SWALLOWED. An adapter returns a
`MappedTask`, so each mapped record says whether the site published a payment
its adapter could not parse (see `adapters/mapped.py`). Those are summed per
site into `unparsed_payments`, which goes out in this function's summary and
onto the run's `run_sites` rows. Without that count, a site changing its price
format is indistinguishable from a site publishing no prices: both store
`pay_amount: null`, both exit 0, and `--filter pay_amount:gte:0` quietly stops
returning tasks that do have a price.

A task's seen timestamps come from its envelope's `fetched_at`, not from this
process's clock; only `runs.merged_at` is the merge wallclock. See `db.py`.

Nothing is written to disk as JSON. The per-run envelopes are the inputs; the
durable output is `data/tasks.db`, where each task is one row per
`(site, task_id)` that remembers when it was first and last seen.
"""

from __future__ import annotations

from cli_tools_shared.exceptions import ClientError

from . import adapters, db, envelope, paths, schema, sites


def merge(run_id: str) -> dict:
    site_configs = sites.load_sites()
    # Disabled sites are skipped deterministically: no envelope is expected of
    # them, none is accepted for them, and they get no run_sites row.
    active = {name: cfg for name, cfg in site_configs.items() if not cfg.disabled}
    run = paths.run_dir(run_id)
    missing = [name for name in active
               if not paths.envelope_path(run_id, name).is_file()]
    if missing:
        raise ClientError(
            f"run {run_id} under {run} has no envelope for: {', '.join(missing)}")
    _reject_unconfigured_envelopes(run, active)

    site_summaries = {}
    tasks = []
    origins: dict[tuple[str, str], str] = {}
    for name in active:
        path = paths.envelope_path(run_id, name)
        data = envelope.read(path)
        if data["site"] != name:
            raise ClientError(
                f"{path} claims site '{data['site']}' but is the envelope for '{name}'")
        site_summaries[name] = {
            "status": data["status"],
            "error": data["error"],
            "fetched_at": data["fetched_at"],
            "task_count": len(data["tasks"]),
            # A site with no `ok` envelope merged no tasks, so it published no
            # unreadable price in this run. That 0 is a fact, not a placeholder.
            "unparsed_payments": 0,
        }
        if data["status"] != envelope.OK:
            continue
        adapter = adapters.adapter_for(name)
        for index, raw in enumerate(data["tasks"]):
            mapped = adapter(raw)
            schema.validate_task(mapped.task, label=f"{path} tasks[{index}]")
            _claim_key(origins, mapped.task, path, index)
            tasks.append(mapped.task)
            if mapped.unparsed_payment:
                site_summaries[name]["unparsed_payments"] += 1

    # The merge wallclock stamps the run row only. Every task's first/last seen
    # timestamps are its own site envelope's `fetched_at`, which `db.write_run`
    # reads out of `site_summaries`.
    counts = db.write_run(run_id, envelope.utc_now(), site_summaries, tasks)
    return {
        "run_id": run_id,
        "db_path": str(paths.db_path()),
        "sites": {name: summary["status"] for name, summary in site_summaries.items()},
        # Keyed by every enabled site, like `sites`, so a healthy run reads
        # as an explicit 0 per site rather than as an absent key.
        "unparsed_payments": {name: summary["unparsed_payments"]
                              for name, summary in site_summaries.items()},
        **counts,
    }


def _reject_unconfigured_envelopes(run, active) -> None:
    """Every `*.json` in the run directory must be an enabled site."""
    extra = sorted(path.stem for path in run.glob("*.json")
                   if path.stem not in active)
    if extra:
        raise ClientError(
            f"run directory {run} holds envelopes for sites that are not "
            f"enabled in config.json: {', '.join(extra)}; enabled sites: "
            f"{', '.join(active)}")


def _claim_key(origins: dict[tuple[str, str], str], task: dict,
               path, index: int) -> None:
    """Record where this `(site, task_id)` came from, or name the collision."""
    key = (task["site"], task["task_id"])
    origin = f"{path} tasks[{index}]"
    if key in origins:
        raise ClientError(
            f"two records map to the same task (site={key[0]!r}, "
            f"task_id={key[1]!r}): {origins[key]} and {origin}")
    origins[key] = origin
