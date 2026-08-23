"""Executions commands - query workflow execution history and events."""
import json
import typer
from datetime import timezone
from typing import Optional, List

from cli_tools_shared.output import print_json, print_table, print_error, print_info, handle_error
from cli_tools_shared.filters import apply_filters, apply_properties_filter, apply_limit
from ..parsers import format_local_time
from ..n8n_api import get_n8n_api_client
from ..server import run_on_server
from .logs import _parse_datetime, _default_from, _default_to, _shell_quote, _event_detail


def _local_to_utc_str(dt) -> str:
    """Convert a naive local datetime to a UTC string for comparison with API timestamps."""
    local_dt = dt.astimezone()  # attach local timezone
    utc_dt = local_dt.astimezone(timezone.utc)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S")


def _fetch_executions_in_range(client, status, workflow_id, include_data, start_utc, end_utc):
    """Paginate /executions and keep executions whose startedAt falls in [start_utc, end_utc].

    Date filtering must use startedAt: a running execution has no stoppedAt yet.
    Pages arrive newest-first, so pagination stops once an execution older than
    start_utc is seen.
    """
    results = []
    cursor = None
    page_size = 250  # max allowed by API

    while True:
        params = {"limit": page_size}
        if status:
            params["status"] = status
        if workflow_id:
            params["workflowId"] = workflow_id
        if include_data:
            params["includeData"] = "true"
        if cursor:
            params["cursor"] = cursor

        response = client._request("GET", "/executions", params=params)
        data = response.get("data", [])

        reached_older = False
        for ex in data:
            started = ex.get("startedAt")
            if not started:
                continue
            # API returns UTC timestamps like "2026-02-13T14:37:08.123Z"
            ex_utc = started.replace("Z", "")[:19]
            if ex_utc < start_utc:
                reached_older = True
                break
            if ex_utc <= end_utc:
                results.append(ex)

        next_cursor = response.get("nextCursor")
        if reached_older or not next_cursor:
            break
        cursor = next_cursor

    return results

app = typer.Typer(help="Query workflow executions and events", no_args_is_help=True)

COMMAND_CREDENTIALS = {
    "events": [
        "api_key"
    ],
    "get": [
        "api_key"
    ],
    "list": [
        "api_key"
    ]
}


@app.command("list")
def executions_list(
    from_dt: str = typer.Option(None, "--from", help="Start datetime (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS). Default: start of today"),
    to_dt: str = typer.Option(None, "--to", help="End datetime. Default: now"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status (error, success, running, canceled, waiting)"),
    workflow_id: Optional[str] = typer.Option(None, "--workflow-id", "-w", help="Filter by workflow ID"),
    include_data: bool = typer.Option(False, "--include-data", "-d", help="Include full execution data (large output)"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Query execution history by timeframe via the n8n API.

    Paginates through all executions and filters by startedAt client-side
    (the API has no date filter parameter; running executions have no
    stoppedAt). The n8n public API omits currently-running executions
    unless status=running is requested, so when no --status is given the
    command also fetches running executions and merges them in.

    Examples:
        n8n executions list --from 2026-02-12 --status error
        n8n executions list --from "2026-02-12T08:00" --to "2026-02-12T09:00" --table
        n8n executions list --workflow-id 17VB4GJjjp0ijgjJ
    """
    try:
        from_dt = from_dt or _default_from()
        to_dt = to_dt or _default_to()
        start = _parse_datetime(from_dt)
        end = _parse_datetime(to_dt)

        client = get_n8n_api_client()

        # Convert local time boundaries to UTC for comparison with API timestamps
        start_utc = _local_to_utc_str(start)
        end_utc = _local_to_utc_str(end)

        print_info(f"Fetching executions from {from_dt} to {to_dt}...")

        all_executions = _fetch_executions_in_range(
            client, status, workflow_id, include_data, start_utc, end_utc
        )

        # The n8n public API excludes currently-active executions from
        # GET /executions unless status=running is requested (the public-api
        # executions handler passes excludedExecutionsIds for every other
        # request). Without this merge, in-flight executions are silently
        # missing from the default list.
        if not status:
            running = _fetch_executions_in_range(
                client, "running", workflow_id, include_data, start_utc, end_utc
            )
            seen_ids = {ex["id"] for ex in all_executions}
            all_executions.extend(ex for ex in running if ex["id"] not in seen_ids)
            all_executions.sort(key=lambda ex: ex["startedAt"], reverse=True)

        if filter:
            all_executions = apply_filters(all_executions, filter)

        all_executions = apply_limit(all_executions, limit)

        if properties:
            all_executions = apply_properties_filter(all_executions, properties)

        # Unless --include-data, reduce to key fields for clean output
        list_fields = ["id", "status", "mode", "workflowId", "startedAt", "stoppedAt"]
        if not include_data and not properties:
            all_executions = [{k: ex.get(k) for k in list_fields} for ex in all_executions]

        print_info(f"Found {len(all_executions)} executions")

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(all_executions, fields, fields)
            else:
                rows = []
                for ex in all_executions:
                    rows.append({
                        "id": ex.get("id"),
                        "status": ex.get("status"),
                        "mode": ex.get("mode"),
                        "workflowId": ex.get("workflowId"),
                        "startedAt": format_local_time(ex.get("startedAt", "")),
                        "stoppedAt": format_local_time(ex.get("stoppedAt") or ""),
                    })
                print_table(
                    rows,
                    list_fields,
                    ["ID", "Status", "Mode", "Workflow", "Started", "Stopped"],
                )
        else:
            print_json(all_executions)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def executions_get(
    execution_id: str = typer.Argument(..., help="Execution ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    include_data: bool = typer.Option(False, "--include-data", "-d", help="Include full execution data"),
):
    """
    Get details for a specific execution by ID.

    Example:
        n8n executions get 12345
        n8n executions get 12345 --table
        n8n executions get 12345 --include-data
    """
    try:
        api = get_n8n_api_client()
        result = api.get_execution(int(execution_id), include_data=include_data)

        if not result:
            print_error(f"Execution '{execution_id}' not found")
            raise typer.Exit(1)

        if table:
            rows = [{"field": k, "value": str(v)} for k, v in result.items()]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(result)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("events")
def executions_events(
    from_dt: str = typer.Option(None, "--from", help="Start datetime (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS). Default: start of today"),
    to_dt: str = typer.Option(None, "--to", help="End datetime. Default: now"),
    event_type: Optional[str] = typer.Option(None, "--type", help="Filter by type: audit, workflow, node"),
    event_name: Optional[str] = typer.Option(None, "--name", "-n", help="Filter by event name (substring match, e.g. 'login', 'failed')"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results to return"),
    table: bool = typer.Option(False, "--table", help="Display as table"),
    data_dir: str = typer.Option("/var/root/.n8n", "--data-dir", help="n8n data directory on server"),
):
    """
    Query event log files (EventBus) by timeframe via SSH.

    Parses n8nEventLog*.log JSON files for audit events, workflow events, and node events.

    Examples:
        n8n executions events --from 2026-02-12 --type audit --table
        n8n executions events --from "2026-02-12T08:00" --name failed
        n8n executions events --type workflow --table
    """
    try:
        from_dt = from_dt or _default_from()
        to_dt = to_dt or _default_to()

        type_filter = ""
        if event_type:
            type_map = {
                "audit": "EventMessageAudit",
                "workflow": "EventMessageWorkflow",
                "node": "EventMessageNode",
            }
            mapped = type_map.get(event_type.lower())
            if not mapped:
                raise typer.BadParameter(f"Invalid event type: '{event_type}'. Use: audit, workflow, node")
            type_filter = mapped

        name_filter = event_name or ""

        script = f'''
import sys, json, glob
from_dt = "{from_dt}"
to_dt = "{to_dt}"
type_filter = "{type_filter}"
name_filter = "{name_filter}"
limit = {limit}

results = []
files = sorted(glob.glob("{data_dir}/n8nEventLog*.log"))
for fpath in files:
    with open(fpath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = e.get("ts", "")
            ts_cmp = ts[:19]
            if ts_cmp < from_dt[:19]:
                continue
            if ts_cmp > to_dt[:19]:
                continue
            if type_filter and type_filter not in e.get("__type", ""):
                continue
            if name_filter and name_filter.lower() not in e.get("eventName", "").lower():
                continue
            results.append(e)
            if len(results) >= limit:
                break
    if len(results) >= limit:
        break

print(json.dumps(results))
'''
        print_info(f"Querying event logs from {from_dt} to {to_dt}...")

        cmd = f"sudo python3 -c {_shell_quote(script)}"
        output = run_on_server(cmd, timeout=60)
        events = json.loads(output)

        print_info(f"Found {len(events)} events")

        if table:
            rows = []
            for ev in events:
                rows.append({
                    "ts": format_local_time(ev.get("ts", "")),
                    "eventName": ev.get("eventName", ""),
                    "type": ev.get("__type", "").replace("$$EventMessage", ""),
                    "detail": _event_detail(ev),
                })
            print_table(
                rows,
                ["ts", "type", "eventName", "detail"],
                ["Timestamp", "Type", "Event", "Detail"],
            )
        else:
            print_json(events)

    except Exception as e:
        raise typer.Exit(handle_error(e))
