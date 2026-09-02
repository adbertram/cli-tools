"""`merge <run_id>`: every site envelope of a run -> one `merged.json`.

All-or-nothing: every site in config.json must have an envelope, every
envelope must validate, every `ok` task must map through its adapter and
validate, and the merged document must validate before it is written.
"""

from __future__ import annotations

import json

from cli_tools_shared.exceptions import ClientError

from . import adapters, envelope, paths, schema, sites


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

    merged = {
        "run_id": run_id,
        "merged_at": envelope.utc_now(),
        "sites": site_summaries,
        "tasks": tasks,
    }
    schema.validate_merged(merged)
    merged_path = paths.merged_path(run_id)
    merged_path.write_text(
        json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "run_id": run_id,
        "merged_path": str(merged_path),
        "sites": {name: summary["status"] for name, summary in site_summaries.items()},
        "task_count": len(tasks),
    }
