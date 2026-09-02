"""`merge <run_id>`: every site envelope of a run -> the SQLite task store.

All-or-nothing, in this order: the run directory must hold an envelope for every
site in config.json and no envelope for anything else, every envelope must
validate, every `ok` task must map through its site adapter and validate against
the task contract, and the run's mapped tasks must be unique by
`(site, task_id)`. Only then does anything reach the database, and it lands in
one transaction (see `db.write_run`). A single bad envelope or task fails the
whole merge and leaves the store exactly as it was.

THE ENVELOPE SET IS CHECKED IN BOTH DIRECTIONS. Requiring an envelope per
configured site catches a worker that never ran. Rejecting an envelope for a
site config.json does not define catches the opposite mistake -- a stray or
misnamed `<site>.json`, e.g. `microworkers2.json` -- which would otherwise be
skipped in silence: its tasks would never merge, it would get no `run_sites`
row, and the run would exit 0 as though it had been complete.

DUPLICATE KEYS ARE REJECTED, NOT COLLAPSED. `db.write_run` writes the run's
tasks with `executemany` over an upsert, so two records mapping to the same
`(site, task_id)` inside ONE run would simply overwrite each other and the merge
would report more tasks than rows with no indication which record won. Within a
run that is not a re-sighting, it is a contradiction: two records from the same
listing claiming the same identity (a site printing `100` and `"100"` for the
same campaign, say). It is raised here, before the transaction opens, because
this is where the envelope path and the record indexes are still known.

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
    run = paths.run_dir(run_id)
    missing = [name for name in site_configs
               if not paths.envelope_path(run_id, name).is_file()]
    if missing:
        raise ClientError(
            f"run {run_id} under {run} has no envelope for: {', '.join(missing)}")
    _reject_unconfigured_envelopes(run, site_configs)

    site_summaries = {}
    tasks = []
    origins: dict[tuple[str, str], str] = {}
    for name in site_configs:
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
        }
        if data["status"] != envelope.OK:
            continue
        adapter = adapters.adapter_for(name)
        for index, raw in enumerate(data["tasks"]):
            task = adapter(raw)
            schema.validate_task(task, label=f"{path} tasks[{index}]")
            _claim_key(origins, task, path, index)
            tasks.append(task)

    # The merge wallclock stamps the run row only. Every task's first/last seen
    # timestamps are its own site envelope's `fetched_at`, which `db.write_run`
    # reads out of `site_summaries`.
    counts = db.write_run(run_id, envelope.utc_now(), site_summaries, tasks)
    return {
        "run_id": run_id,
        "db_path": str(paths.db_path()),
        "sites": {name: summary["status"] for name, summary in site_summaries.items()},
        **counts,
    }


def _reject_unconfigured_envelopes(run, site_configs) -> None:
    """Every `*.json` in the run directory must be a configured site."""
    extra = sorted(path.stem for path in run.glob("*.json")
                   if path.stem not in site_configs)
    if extra:
        raise ClientError(
            f"run directory {run} holds envelopes for sites config.json does not "
            f"define: {', '.join(extra)}; config.json defines: "
            f"{', '.join(site_configs)}")


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
