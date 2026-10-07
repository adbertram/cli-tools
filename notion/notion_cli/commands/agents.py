"""Custom Agent and session operations from Notion's public Agent API."""

import json
from pathlib import Path
from typing import List, Optional

import typer
import requests
from cli_tools_shared.filters import apply_filters, apply_properties_filter

from ..client import ClientError, get_client
from ..output import command, print_json, print_table


API_VERSION = "2026-03-11"
app = typer.Typer(help="Discover and manage accessible Custom Agents")
sessions = typer.Typer(help="Run and inspect agent sessions")
app.add_typer(sessions, name="sessions")


def _body(path: Optional[Path]) -> dict:
    if path is None:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ClientError(f"Invalid JSON body file: {exc}") from exc
    if not isinstance(value, dict):
        raise ClientError("JSON body file must contain an object")
    return value


def _request(method: str, endpoint: str, body: Optional[dict] = None, params: Optional[dict] = None) -> dict:
    return get_client()._make_request(method, endpoint, data=body, params=params, version=API_VERSION)


def _emit(result: dict, table: bool, columns: Optional[List[str]] = None) -> None:
    if table:
        fields = columns or list(result)
        print_table([result], fields, fields)
    else:
        print_json(result)


def _list(endpoint: str, body: dict, limit: Optional[int], filters: Optional[List[str]], properties: Optional[str], table: bool, columns: List[str]) -> None:
    if limit is not None and limit < 0:
        raise ClientError("--limit must be non-negative")
    records = []
    cursor = None
    while True:
        request_body = {**body, **({"start_cursor": cursor} if cursor else {})}
        page = _request("POST", endpoint, request_body)
        if not isinstance(page, dict) or not isinstance(page.get("results"), list):
            raise ClientError("Notion returned an invalid paginated response")
        records.extend(page["results"])
        cursor = page.get("next_cursor")
        if not cursor or not page.get("has_more"):
            break
        if limit is not None and not filters and len(records) >= limit:
            break
    if filters:
        records = apply_filters(records, filters)
    if limit is not None:
        records = records[:limit]
    if properties:
        records = apply_properties_filter(records, properties)
        columns = [field.strip() for field in properties.split(",") if field.strip()]
    if table:
        print_table(records, columns, columns)
    else:
        print_json(records)


@app.command("list")
@command
def agents_list(
    query: Optional[str] = typer.Option(None, "--query", "-q", help="Search name and description"),
    body_file: Optional[Path] = typer.Option(None, "--body-file", help="Notion query body JSON, including native filters or sorts"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter returned fields: field:op:value"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum agents to return"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated output fields"),
    table: bool = typer.Option(False, "--table", "-t", help="Table output"),
):
    """Find accessible Custom Agents; query body supports Notion's full search schema."""
    body = _body(body_file)
    if query is not None:
        body["query"] = query
    _list("/agents/query", body, limit, filter, properties, table, ["id", "name", "status", "agent_type"])


@app.command("get")
@command
def agents_get(agent_id: str, verbose: bool = typer.Option(False, "--verbose"), table: bool = typer.Option(False, "--table", "-t")):
    """Retrieve Custom Agent metadata."""
    result = _request("GET", f"/agents/{agent_id}", params={"verbose": str(verbose).lower()})
    _emit(result, table, ["id", "name", "status", "agent_type"])


@app.command("insights")
@command
def agents_insights(agent_id: str, start_time: Optional[int] = typer.Option(None), end_time: Optional[int] = typer.Option(None), table: bool = typer.Option(False, "--table", "-t")):
    """Retrieve agent configuration and credit usage insights."""
    if (start_time is None) != (end_time is None):
        raise ClientError("--start-time and --end-time must be supplied together")
    params = {"start_time": start_time, "end_time": end_time} if start_time is not None else None
    result = _request("GET", f"/agents/{agent_id}/insights", params=params)
    _emit(result, table)


@app.command("status")
@command
def agents_status(agent_id: str, status: str = typer.Argument(..., help="active or disabled"), table: bool = typer.Option(False, "--table", "-t")):
    """Enable or disable a Custom Agent."""
    if status not in {"active", "disabled"}:
        raise ClientError("status must be active or disabled")
    result = _request("PATCH", f"/agents/{agent_id}/status", {"status": status})
    _emit(result, table)


@app.command("credit-limit")
@command
def agents_credit_limit(agent_id: str, limit: Optional[int] = typer.Option(None, "--limit", help="Non-negative credit limit; omit to clear"), table: bool = typer.Option(False, "--table", "-t")):
    """Set or clear an agent's credit limit."""
    if limit is not None and limit < 0:
        raise ClientError("--limit must be non-negative")
    result = _request("PATCH", f"/agents/{agent_id}/credit_limit", {"credit_limit": limit})
    _emit(result, table)


@app.command("delete")
@command
def agents_delete(agent_id: str, yes: bool = typer.Option(False, "--yes", help="Confirm soft deletion"), table: bool = typer.Option(False, "--table", "-t")):
    """Soft-delete a Custom Agent."""
    if not yes:
        raise ClientError("Refusing to delete agent without --yes")
    result = _request("DELETE", f"/agents/{agent_id}")
    _emit(result, table)


@app.command("batch")
@command
def agents_batch(body_file: Path = typer.Option(..., "--body-file", help="JSON body with operations array"), table: bool = typer.Option(False, "--table", "-t")):
    """Submit documented agent operations as an asynchronous batch."""
    body = _body(body_file)
    if not isinstance(body.get("operations"), list) or not body["operations"]:
        raise ClientError("body must contain a non-empty operations array")
    result = _request("POST", "/agents/batch", body)
    _emit(result, table)


@sessions.command("list")
@command
def sessions_list(body_file: Optional[Path] = typer.Option(None, "--body-file", help="Notion query body JSON"), filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value"), limit: Optional[int] = typer.Option(None, "--limit", "-l"), properties: Optional[str] = typer.Option(None, "--properties", "-p"), table: bool = typer.Option(False, "--table", "-t")):
    """Find accessible agent sessions."""
    _list("/sessions/query", _body(body_file), limit, filter, properties, table, ["id", "agent_id", "status", "title"])


@sessions.command("get")
@command
def sessions_get(session_id: str, table: bool = typer.Option(False, "--table", "-t")):
    """Retrieve a session and its required actions."""
    result = _request("GET", f"/sessions/{session_id}")
    _emit(result, table)


@sessions.command("send")
@command
def sessions_send(message: str, agent_id: Optional[str] = typer.Option(None, "--agent-id", help="Agent ID for a new session"), session_id: Optional[str] = typer.Option(None, "--session-id", help="Existing session ID"), body_file: Optional[Path] = typer.Option(None, "--body-file", help="Additional documented session fields as JSON"), table: bool = typer.Option(False, "--table", "-t")):
    """Start a session or send another message."""
    if not agent_id and not session_id:
        raise ClientError("--agent-id or --session-id is required")
    body = _body(body_file)
    body.update({"message": message})
    if agent_id:
        body["agent_id"] = agent_id
    if session_id:
        body["session_id"] = session_id
    result = _request("POST", "/sessions", body)
    _emit(result, table)


@sessions.command("submit")
@command
def sessions_submit(body_file: Path = typer.Option(..., "--body-file", help="JSON with session_id and actions"), table: bool = typer.Option(False, "--table", "-t")):
    """Submit approvals or rejections requested by a session."""
    body = _body(body_file)
    if not body.get("session_id") or not isinstance(body.get("actions"), list):
        raise ClientError("body must contain session_id and actions array")
    result = _request("POST", "/sessions", body)
    _emit(result, table)


@sessions.command("stream")
@command
def sessions_stream(body_file: Path = typer.Option(..., "--body-file", help="Session message or continue_from JSON body")):
    """Stream session events as server-sent events; continue_from replays an event."""
    body = _body(body_file)
    if not (
        body.get("message")
        or (body.get("session_id") and body.get("actions"))
        or (body.get("session_id") and body.get("continue_from"))
    ):
        raise ClientError("body must contain message, session_id and actions, or session_id and continue_from")
    client = get_client()
    try:
        with requests.post(
            f"{client.base_url}/sessions",
            headers={**client.headers, "Notion-Version": API_VERSION, "Accept": "text/event-stream"},
            json=body,
            stream=True,
            timeout=(10, None),
        ) as response:
            if not response.ok:
                raise ClientError(f"API request failed: {response.status_code} - {response.text}")
            for line in response.iter_lines(decode_unicode=True):
                typer.echo(line if isinstance(line, str) else line.decode("utf-8"))
    except requests.RequestException as exc:
        raise ClientError(f"Session stream failed: {exc}") from exc


@sessions.command("events")
@command
def sessions_events(session_id: str, body_file: Optional[Path] = typer.Option(None, "--body-file", help="Notion event query body JSON"), filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value"), limit: Optional[int] = typer.Option(None, "--limit", "-l"), properties: Optional[str] = typer.Option(None, "--properties", "-p"), table: bool = typer.Option(False, "--table", "-t")):
    """List session events, including agent messages and tool results."""
    _list(f"/sessions/{session_id}/events/query", _body(body_file), limit, filter, properties, table, ["id", "type", "created_at", "sequence"])


@sessions.command("cancel")
@command
def sessions_cancel(session_id: str, event_id: Optional[str] = typer.Option(None, "--event-id"), table: bool = typer.Option(False, "--table", "-t")):
    """Cancel an in-progress session turn."""
    result = _request("POST", f"/sessions/{session_id}/cancel", {"event_id": event_id} if event_id else {})
    _emit(result, table)


COMMAND_CREDENTIALS = {name: ["custom"] for name in ("list", "get", "insights", "status", "credit-limit", "delete", "batch", "sessions")}
