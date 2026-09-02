"""`merge <run_id>`: every site envelope of a run -> the SQLite task store.

All-or-nothing, in this order: every site in config.json must have an envelope,
every envelope must validate, and every `ok` task must map through its site
adapter and validate against the task contract. Only then does anything reach
the database, and it lands in one transaction (see `db.write_run`). A single bad
envelope or task fails the whole merge and leaves the store exactly as it was.

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

    site_summaries = {}
    tasks = []
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
            tasks.append(task)

    # One timestamp for the whole run: it stamps the run row and both the
    # first_seen_at and last_seen_at of every task the run touched.
    counts = db.write_run(run_id, envelope.utc_now(), site_summaries, tasks)
    return {
        "run_id": run_id,
        "db_path": str(paths.db_path()),
        "sites": {name: summary["status"] for name, summary in site_summaries.items()},
        **counts,
    }
