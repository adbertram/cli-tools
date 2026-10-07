"""Enterprise Admin API operations for workspace Custom Agents."""

from pathlib import Path
from typing import List, Optional

import typer
from cli_tools_shared.config import read_cli_tool_secret
from cli_tools_shared.filters import apply_filters, apply_properties_filter

from ..client import ClientError, NotionClient
from ..output import command, print_json, print_table
from .agents import _body


app = typer.Typer(help="Enterprise workspace agent administration")
VERSION = "2026-06-01"


def _request(method: str, endpoint: str, body: Optional[dict] = None, params: Optional[dict] = None) -> dict:
    token = read_cli_tool_secret("notion-admin-token")
    if not token:
        raise ClientError("Missing Enterprise organization token. Store it with cli-tools secret manager as notion-admin-token")
    return NotionClient(token=token)._make_request(
        method, endpoint, data=body, params=params, version=VERSION,
        base_url="https://api.notion.com/admin/v1", token=token,
    )


def _print(result: dict, table: bool) -> None:
    print_table([result], list(result), list(result)) if table else print_json(result)


def _records(endpoint: str, params: dict, limit: Optional[int], filters: Optional[List[str]], properties: Optional[str], table: bool) -> None:
    if limit is not None and limit < 0:
        raise ClientError("--limit must be non-negative")
    records = []
    cursor = None
    while True:
        page = _request("GET", endpoint, params={**params, **({"cursor": cursor} if cursor else {})})
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
    columns = [x.strip() for x in properties.split(",")] if properties else ["id", "name", "status", "type"]
    print_table(records, columns, columns) if table else print_json(records)


@app.command("list")
@command
def agents_list(space_id: str, name: Optional[str] = typer.Option(None, "--name"), query_file: Optional[Path] = typer.Option(None, "--query-file", help="JSON object of documented Admin API query parameters"), filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value"), limit: Optional[int] = typer.Option(None, "--limit", "-l"), properties: Optional[str] = typer.Option(None, "--properties", "-p"), table: bool = typer.Option(False, "--table", "-t")):
    """List all agents in an Enterprise workspace, including administrative metadata."""
    params = _body(query_file)
    if name:
        params["name"] = name
    _records(f"/spaces/{space_id}/agents", params, limit, filter, properties, table)


@app.command("get")
@command
def agents_get(space_id: str, agent_id: str, table: bool = typer.Option(False, "--table", "-t")):
    """Find one workspace agent by ID through the Admin API listing."""
    records = []
    cursor = None
    while True:
        page = _request("GET", f"/spaces/{space_id}/agents", params={"cursor": cursor} if cursor else None)
        records.extend(page.get("results", []))
        match = next((item for item in records if item.get("id") == agent_id), None)
        if match:
            _print(match, table)
            return
        cursor = page.get("next_cursor")
        if not page.get("has_more") or not cursor:
            raise ClientError(f"Agent not found in workspace: {agent_id}")


@app.command("usage")
@command
def agent_usage(space_id: str, agent_id: str, start_cursor: Optional[str] = typer.Option(None, "--start-cursor"), table: bool = typer.Option(False, "--table", "-t")):
    """Get credit usage for one workspace agent."""
    _print(_request("GET", f"/spaces/{space_id}/agents/{agent_id}/credit_usage", params={"start_cursor": start_cursor} if start_cursor else None), table)


@app.command("usage-list")
@command
def agent_usage_list(space_id: str, query_file: Optional[Path] = typer.Option(None, "--query-file", help="JSON object of documented Admin API query parameters"), filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value"), limit: Optional[int] = typer.Option(None, "--limit", "-l"), properties: Optional[str] = typer.Option(None, "--properties", "-p"), table: bool = typer.Option(False, "--table", "-t")):
    """List credit usage for workspace agents."""
    _records(f"/spaces/{space_id}/agents/credit_usage", _body(query_file), limit, filter, properties, table)


@app.command("credit-limit")
@command
def agent_credit_limit(space_id: str, agent_id: str, limit: Optional[int] = typer.Option(None, "--limit", help="Non-negative limit; omit to clear"), table: bool = typer.Option(False, "--table", "-t")):
    """Set or clear an agent's Enterprise credit limit."""
    if limit is not None and limit < 0:
        raise ClientError("--limit must be non-negative")
    _print(_request("PUT", f"/spaces/{space_id}/agents/{agent_id}/credit_limit", {"credit_limit": limit}), table)


@app.command("permissions")
@command
def agent_permissions(space_id: str, agent_id: str, cursor: Optional[str] = typer.Option(None, "--cursor"), table: bool = typer.Option(False, "--table", "-t")):
    """Get Custom Agent sharing permissions."""
    _print(_request("GET", f"/spaces/{space_id}/agents/{agent_id}/permissions", params={"cursor": cursor} if cursor else None), table)


@app.command("update-permissions")
@command
def agent_update_permissions(space_id: str, agent_id: str, body_file: Path = typer.Option(..., "--body-file", help="JSON with set and/or remove grants"), table: bool = typer.Option(False, "--table", "-t")):
    """Grant, change, or revoke Custom Agent sharing permissions."""
    body = _body(body_file)
    if not any(key in body for key in ("set", "remove")):
        raise ClientError("body must contain set and/or remove")
    _print(_request("PATCH", f"/spaces/{space_id}/agents/{agent_id}/permissions", body), table)


@app.command("status")
@command
def agent_status(space_id: str, agent_id: str, status: str = typer.Argument(..., help="active or disabled"), table: bool = typer.Option(False, "--table", "-t")):
    """Disable or re-enable a workspace agent."""
    if status not in {"active", "disabled"}:
        raise ClientError("status must be active or disabled")
    _print(_request("PATCH", f"/spaces/{space_id}/agents/{agent_id}/status", {"admin_status": status}), table)


@app.command("delete")
@command
def agent_delete(space_id: str, agent_id: str, yes: bool = typer.Option(False, "--yes"), table: bool = typer.Option(False, "--table", "-t")):
    """Delete a workspace Custom Agent."""
    if not yes:
        raise ClientError("Refusing to delete agent without --yes")
    _print(_request("DELETE", f"/spaces/{space_id}/agents/{agent_id}"), table)


@app.command("creation-policy")
@command
def agent_creation_policy(space_id: str, policy: str = typer.Argument(..., help="all_workspace_members, workspace_owners_only, or disabled"), disable_existing_agents: bool = typer.Option(False, "--disable-existing-agents"), table: bool = typer.Option(False, "--table", "-t")):
    """Set who may create agents in an Enterprise workspace."""
    if policy not in {"all_workspace_members", "workspace_owners_only", "disabled"}:
        raise ClientError("Invalid creation policy")
    if disable_existing_agents and policy != "disabled":
        raise ClientError("--disable-existing-agents requires disabled policy")
    _print(_request("PATCH", f"/spaces/{space_id}/agents/creation_policy", {"policy": policy, "disable_existing_agents": disable_existing_agents}), table)


@app.command("workspace-credit-limit")
@command
def workspace_credit_limit(space_id: str, limit: Optional[int] = typer.Option(None, "--limit", help="Non-negative default limit; omit to clear"), table: bool = typer.Option(False, "--table", "-t")):
    """Set or clear the default credit limit for future workspace agents."""
    if limit is not None and limit < 0:
        raise ClientError("--limit must be non-negative")
    _print(_request("PATCH", f"/spaces/{space_id}/credit_limit", {"default_agent_credit_limit": limit}), table)


COMMAND_CREDENTIALS = {name: ["no_auth"] for name in ("list", "get", "usage", "usage-list", "credit-limit", "permissions", "update-permissions", "status", "delete", "creation-policy", "workspace-credit-limit")}
