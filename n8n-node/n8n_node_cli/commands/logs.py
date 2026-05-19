"""Logs commands - query n8n logs, events, and execution history for troubleshooting."""
import json
import subprocess
import typer
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List

from ..output import print_json, print_table, print_error, print_info, print_warning, handle_error
from ..filters import apply_filters, apply_limit
from ..n8n_api import get_n8n_api_client, N8nApiError

app = typer.Typer(help="Query n8n logs, events, and execution history", no_args_is_help=True)


# ---------------------------------------------------------------------------
# SSH helpers
# ---------------------------------------------------------------------------

def _get_ssh_host() -> str:
    """Get SSH host from n8n .env (N8N_SSH_HOST) or derive from N8N_BASE."""
    env_path = Path.home() / ".claude" / "skills" / "n8n" / ".env"
    env_vars = {}
    if env_path.exists():
        for line in env_path.read_text().strip().split("\n"):
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                env_vars[key.strip()] = value.strip()

    ssh_host = env_vars.get("N8N_SSH_HOST")
    if ssh_host:
        return ssh_host

    # Derive from N8N_BASE (e.g., http://100.117.198.37:5678/api/v1)
    base = env_vars.get("N8N_BASE", "")
    if base:
        from urllib.parse import urlparse
        parsed = urlparse(base)
        return parsed.hostname or "localhost"

    raise N8nApiError("Cannot determine SSH host. Set N8N_SSH_HOST in ~/.claude/skills/n8n/.env")


def _ssh_run(command: str, timeout: int = 30) -> str:
    """Run a command on the n8n server via SSH.

    Args:
        command: Shell command to execute remotely
        timeout: Timeout in seconds

    Returns:
        stdout from the remote command

    Raises:
        RuntimeError: If SSH command fails
    """
    host = _get_ssh_host()
    result = subprocess.run(
        ["ssh", host, command],
        capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(f"SSH command failed (exit {result.returncode}): {stderr}")
    return result.stdout


# ---------------------------------------------------------------------------
# Date parsing helpers
# ---------------------------------------------------------------------------

def _parse_datetime(value: str) -> datetime:
    """Parse a datetime string, supporting multiple formats.

    Supports:
        2026-02-12
        2026-02-12T08:00
        2026-02-12T08:00:00
        2026-02-12 08:00
        2026-02-12 08:00:00
    """
    formats = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise typer.BadParameter(f"Cannot parse datetime: '{value}'. Use YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS")


def _default_from() -> str:
    """Default --from: start of today."""
    return datetime.now().strftime("%Y-%m-%d")


def _default_to() -> str:
    """Default --to: now."""
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.command("executions")
def logs_executions(
    from_dt: str = typer.Option(None, "--from", "-f", help="Start datetime (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS). Default: start of today"),
    to_dt: str = typer.Option(None, "--to", "-t", help="End datetime. Default: now"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status (error, success, running, canceled, waiting)"),
    workflow_id: Optional[str] = typer.Option(None, "--workflow-id", "-w", help="Filter by workflow ID"),
    include_data: bool = typer.Option(False, "--include-data", "-d", help="Include full execution data (large output)"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results to return"),
    table: bool = typer.Option(False, "--table", help="Display as table"),
):
    """
    Query execution history by timeframe via the n8n API.

    Paginates through all executions and filters by date client-side
    (the API has no date filter parameter).

    Examples:
        n8n-node logs executions --from 2026-02-12 --status error
        n8n-node logs executions --from "2026-02-12T08:00" --to "2026-02-12T09:00" --table
        n8n-node logs executions --workflow-id 17VB4GJjjp0ijgjJ
    """
    try:
        from_dt = from_dt or _default_from()
        to_dt = to_dt or _default_to()
        start = _parse_datetime(from_dt)
        end = _parse_datetime(to_dt)

        client = get_n8n_api_client()
        all_executions = []
        cursor = None
        page_size = 250  # max allowed by API

        print_info(f"Fetching executions from {from_dt} to {to_dt}...")

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

            for ex in data:
                started = ex.get("startedAt", "")
                if not started:
                    continue
                # Parse ISO datetime, compare as strings (ISO sorts correctly)
                ex_start = started.replace("Z", "+00:00")
                # Simple string comparison works for ISO format
                start_str = start.strftime("%Y-%m-%dT%H:%M:%S")
                end_str = end.strftime("%Y-%m-%dT%H:%M:%S")
                # Normalize: take first 19 chars for comparison
                ex_start_trimmed = ex_start[:19]
                if ex_start_trimmed < start_str:
                    # Executions are ordered newest first - if we've gone past our range, stop
                    cursor = None
                    break
                if ex_start_trimmed <= end_str:
                    all_executions.append(ex)

            next_cursor = response.get("nextCursor")
            # Stop if: no more pages, or we've gone past our time range
            if not next_cursor or (data and data[-1].get("startedAt", "")[:19].replace("Z", "") < start.strftime("%Y-%m-%dT%H:%M:%S")):
                break
            cursor = next_cursor

        all_executions = apply_limit(all_executions, limit)

        print_info(f"Found {len(all_executions)} executions")

        if table:
            rows = []
            for ex in all_executions:
                rows.append({
                    "id": ex.get("id"),
                    "status": ex.get("status"),
                    "mode": ex.get("mode"),
                    "workflowId": ex.get("workflowId"),
                    "startedAt": ex.get("startedAt", "")[:19],
                    "stoppedAt": (ex.get("stoppedAt") or "")[:19],
                })
            print_table(
                rows,
                ["id", "status", "mode", "workflowId", "startedAt", "stoppedAt"],
                ["ID", "Status", "Mode", "Workflow", "Started", "Stopped"],
            )
        else:
            print_json(all_executions)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("events")
def logs_events(
    from_dt: str = typer.Option(None, "--from", "-f", help="Start datetime (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS). Default: start of today"),
    to_dt: str = typer.Option(None, "--to", "-t", help="End datetime. Default: now"),
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
        n8n-node logs events --from 2026-02-12 --type audit --table
        n8n-node logs events --from "2026-02-12T08:00" --name failed
        n8n-node logs events --type workflow --table
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

        # Build Python script to parse event logs on remote server
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
            # Normalize: compare first 19 chars
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
        output = _ssh_run(cmd, timeout=60)
        events = json.loads(output)

        print_info(f"Found {len(events)} events")

        if table:
            rows = []
            for ev in events:
                payload = ev.get("payload", {})
                rows.append({
                    "ts": ev.get("ts", "")[:19],
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


@app.command("app")
def logs_app(
    lines: int = typer.Option(50, "--lines", "-n", help="Number of lines to show"),
    log_file: str = typer.Option("/var/log/n8n.log", "--log-file", help="Log file path on server"),
):
    """
    View application logs from the n8n server via SSH.

    Examples:
        n8n-node logs app
        n8n-node logs app --lines 200
    """
    try:
        cmd = f"tail -{lines} {log_file}"
        output = _ssh_run(cmd, timeout=15)
        print(output, end="")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("errors")
def logs_errors(
    lines: int = typer.Option(50, "--lines", "-n", help="Number of lines to show"),
    log_file: str = typer.Option("/var/log/n8n.error.log", "--log-file", help="Error log file path on server"),
):
    """
    View error logs from the n8n server via SSH.

    Examples:
        n8n-node logs errors
        n8n-node logs errors --lines 100
    """
    try:
        cmd = f"tail -{lines} {log_file}"
        output = _ssh_run(cmd, timeout=15)
        if output.strip():
            print(output, end="")
        else:
            print_info("No errors in log")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("all")
def logs_all(
    from_dt: str = typer.Option(None, "--from", "-f", help="Start datetime. Default: start of today"),
    to_dt: str = typer.Option(None, "--to", "-t", help="End datetime. Default: now"),
    limit: int = typer.Option(50, "--limit", "-l", help="Max results per source"),
    data_dir: str = typer.Option("/var/root/.n8n", "--data-dir", help="n8n data directory on server"),
):
    """
    Combined troubleshooting dump: executions + events + app logs + error logs.

    Collects from all 4 data sources for the given timeframe and outputs
    a structured JSON report.

    Examples:
        n8n-node logs all --from 2026-02-12
        n8n-node logs all --from "2026-02-12T08:00" --to "2026-02-12T09:00"
    """
    try:
        from_dt = from_dt or _default_from()
        to_dt = to_dt or _default_to()
        start = _parse_datetime(from_dt)
        end = _parse_datetime(to_dt)

        report = {
            "timeframe": {"from": from_dt, "to": to_dt},
            "executions": [],
            "events": [],
            "app_log_tail": "",
            "error_log_tail": "",
        }

        # 1. Executions via API
        print_info("Collecting executions...")
        try:
            client = get_n8n_api_client()
            cursor = None
            start_str = start.strftime("%Y-%m-%dT%H:%M:%S")
            end_str = end.strftime("%Y-%m-%dT%H:%M:%S")

            while len(report["executions"]) < limit:
                params = {"limit": 250}
                if cursor:
                    params["cursor"] = cursor
                response = client._request("GET", "/executions", params=params)
                data = response.get("data", [])
                past_range = False

                for ex in data:
                    started = (ex.get("startedAt") or "")[:19].replace("Z", "")
                    if started < start_str:
                        past_range = True
                        break
                    if started <= end_str:
                        report["executions"].append(ex)
                        if len(report["executions"]) >= limit:
                            break

                next_cursor = response.get("nextCursor")
                if not next_cursor or past_range or len(report["executions"]) >= limit:
                    break
                cursor = next_cursor
        except Exception as e:
            report["executions_error"] = str(e)

        print_info(f"  {len(report['executions'])} executions found")

        # 2. Events via SSH
        print_info("Collecting events...")
        try:
            script = f'''
import sys, json, glob
results = []
for fpath in sorted(glob.glob("{data_dir}/n8nEventLog*.log")):
    with open(fpath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except: continue
            ts = e.get("ts","")[:19]
            if ts < "{from_dt[:19]}": continue
            if ts > "{to_dt[:19]}": continue
            results.append(e)
            if len(results) >= {limit}: break
    if len(results) >= {limit}: break
print(json.dumps(results))
'''
            cmd = f"sudo python3 -c {_shell_quote(script)}"
            output = _ssh_run(cmd, timeout=60)
            report["events"] = json.loads(output)
        except Exception as e:
            report["events_error"] = str(e)

        print_info(f"  {len(report['events'])} events found")

        # 3. App logs
        print_info("Collecting app logs...")
        try:
            report["app_log_tail"] = _ssh_run(f"tail -100 /var/log/n8n.log", timeout=15)
        except Exception as e:
            report["app_log_error"] = str(e)

        # 4. Error logs
        print_info("Collecting error logs...")
        try:
            report["error_log_tail"] = _ssh_run(f"tail -50 /var/log/n8n.error.log", timeout=15)
        except Exception as e:
            report["error_log_error"] = str(e)

        print_json(report)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("config")
def logs_config(
    plist_path: str = typer.Option(
        "/Library/LaunchDaemons/com.n8n.server.plist",
        "--plist", help="LaunchDaemon plist path on server"
    ),
):
    """
    Show current logging configuration from the n8n LaunchDaemon plist.

    Displays environment variables related to logging and their current values.

    Example:
        n8n-node logs config
    """
    try:
        print_info("Reading logging configuration from server...")
        plist_content = _ssh_run(f"sudo cat {plist_path}", timeout=15)

        # Parse relevant env vars from plist
        import plistlib
        plist = plistlib.loads(plist_content.encode())
        env_vars = plist.get("EnvironmentVariables", {})

        log_vars = {
            "N8N_LOG_LEVEL": {"current": env_vars.get("N8N_LOG_LEVEL", "(not set — default: info)"), "options": "silent, error, warn, info, debug"},
            "N8N_LOG_OUTPUT": {"current": env_vars.get("N8N_LOG_OUTPUT", "(not set — default: console)"), "options": "console, file, console,file"},
            "N8N_LOG_FORMAT": {"current": env_vars.get("N8N_LOG_FORMAT", "(not set — default: text)"), "options": "text, json"},
            "N8N_LOG_FILE_LOCATION": {"current": env_vars.get("N8N_LOG_FILE_LOCATION", "(not set — default: <n8n-dir>/logs/n8n.log)"), "options": "file path"},
            "N8N_LOG_FILE_SIZE_MAX": {"current": env_vars.get("N8N_LOG_FILE_SIZE_MAX", "(not set — default: 16 MB)"), "options": "number (MB)"},
            "N8N_LOG_FILE_COUNT_MAX": {"current": env_vars.get("N8N_LOG_FILE_COUNT_MAX", "(not set — default: 100)"), "options": "number"},
            "DB_LOGGING_ENABLED": {"current": env_vars.get("DB_LOGGING_ENABLED", "(not set — default: false)"), "options": "true, false"},
            "DB_LOGGING_OPTIONS": {"current": env_vars.get("DB_LOGGING_OPTIONS", "(not set — default: error)"), "options": "query, error, schema, warn, info, log, all"},
            "DB_LOGGING_MAX_EXECUTION_TIME": {"current": env_vars.get("DB_LOGGING_MAX_EXECUTION_TIME", "(not set — default: 1000 ms)"), "options": "number (ms)"},
        }

        rows = [{"variable": k, "current": v["current"], "options": v["options"]} for k, v in log_vars.items()]
        print_table(
            rows,
            ["variable", "current", "options"],
            ["Variable", "Current Value", "Options"],
        )

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("set-level")
def logs_set_level(
    level: str = typer.Argument(..., help="Log level: silent, error, warn, info, debug"),
    log_format: Optional[str] = typer.Option(None, "--format", help="Log format: text, json"),
    log_output: Optional[str] = typer.Option(None, "--output", help="Log output: console, file, console,file"),
    db_logging: Optional[bool] = typer.Option(None, "--db-logging", help="Enable/disable database query logging"),
    restart: bool = typer.Option(True, "--restart/--no-restart", help="Restart n8n after changing config"),
    plist_path: str = typer.Option(
        "/Library/LaunchDaemons/com.n8n.server.plist",
        "--plist", help="LaunchDaemon plist path on server"
    ),
):
    """
    Set n8n log level and optionally other logging settings.

    Modifies the LaunchDaemon plist on the server and restarts n8n.

    Examples:
        n8n-node logs set-level debug
        n8n-node logs set-level debug --format json --output console,file
        n8n-node logs set-level info --no-restart
        n8n-node logs set-level error --db-logging
    """
    valid_levels = {"silent", "error", "warn", "info", "debug"}
    if level not in valid_levels:
        print_error(f"Invalid level: '{level}'. Must be one of: {', '.join(sorted(valid_levels))}")
        raise typer.Exit(1)

    try:
        # Build the plist modification script
        changes = [f'"N8N_LOG_LEVEL": "{level}"']
        if log_format:
            if log_format not in ("text", "json"):
                print_error(f"Invalid format: '{log_format}'. Must be: text, json")
                raise typer.Exit(1)
            changes.append(f'"N8N_LOG_FORMAT": "{log_format}"')
        if log_output:
            changes.append(f'"N8N_LOG_OUTPUT": "{log_output}"')
        if db_logging is not None:
            changes.append(f'"DB_LOGGING_ENABLED": "{"true" if db_logging else "false"}"')
            if db_logging:
                changes.append('"DB_LOGGING_OPTIONS": "all"')

        # Use Python on the remote server to modify the plist
        script = f'''
import plistlib

with open("{plist_path}", "rb") as f:
    plist = plistlib.load(f)

env = plist.setdefault("EnvironmentVariables", {{}})
updates = {{{", ".join(changes)}}}
env.update(updates)

with open("{plist_path}", "wb") as f:
    plistlib.dump(plist, f)

for k, v in updates.items():
    print(f"  {{k}} = {{v}}")
'''
        print_info("Updating logging configuration...")
        cmd = f"sudo python3 -c {_shell_quote(script)}"
        output = _ssh_run(cmd, timeout=15)
        print(output, end="")

        if restart:
            print_info("Restarting n8n...")
            _ssh_run(f"sudo launchctl unload {plist_path}", timeout=15)
            _ssh_run(f"sudo launchctl load {plist_path}", timeout=15)
            print_info("n8n restarted with new logging configuration")
        else:
            print_warning("Config updated but n8n NOT restarted. Use: sudo launchctl unload/load to apply.")

    except Exception as e:
        raise typer.Exit(handle_error(e))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _shell_quote(s: str) -> str:
    """Quote a string for use in a shell command (single-quote wrapping)."""
    # Replace single quotes with '\'' (end quote, escaped quote, start quote)
    escaped = s.replace("'", "'\\''")
    return f"'{escaped}'"


def _event_detail(event: dict) -> str:
    """Extract a human-readable detail string from an event payload."""
    payload = event.get("payload", {})
    parts = []

    wf_name = payload.get("workflowName")
    if wf_name:
        parts.append(f"wf={wf_name}")

    exec_id = payload.get("executionId")
    if exec_id:
        parts.append(f"exec={exec_id}")

    node_name = payload.get("nodeName")
    if node_name:
        parts.append(f"node={node_name}")

    error = payload.get("errorMessage")
    if error:
        parts.append(f"error={error}")

    email = payload.get("_email")
    if email and not wf_name:
        parts.append(f"user={email}")

    cred_type = payload.get("credentialType")
    if cred_type:
        parts.append(f"cred={cred_type}")

    return " | ".join(parts) if parts else ""
