"""Subagent activity commands for Claude Code Sessions CLI."""
import typer
from typing import Optional, List
from ..client import get_client, ClientError
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import print_json, print_table, handle_error

app = typer.Typer(help="Query subagent invocations", no_args_is_help=True)


@app.command("list")
def list_subagent_activity(
    project: str = typer.Option(..., "--project", "-p", help="Project name (required)"),
    session_id: Optional[str] = typer.Option(None, "--session-id", "-S", help="Filter to specific session"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Time filter: 5h, 1d, 7d"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    List all subagent invocations for a project.

    Example:
        claude-code-sessions subagent-activity list --project Agent-ATABlogger
        claude-code-sessions subagent-activity list --project Agent-ATABlogger --since 5h
        claude-code-sessions subagent-activity list --project Agent-ATABlogger --filter "type:eq:Explore"
        claude-code-sessions subagent-activity list --project Agent-ATABlogger --session-id abc123
    """
    try:
        client = get_client()
        subagents = client.list_subagent_activity(project=project, limit=limit, since=since)

        # Convert to dicts for filtering/output
        items = [s.model_dump() for s in subagents]

        # Apply session_id filter
        if session_id:
            items = [item for item in items if item.get('session_id') == session_id]

        # Apply client-side filters
        if filter:
            items = apply_filters(items, filter)

        # Apply property selection
        if properties:
            prop_list = [p.strip() for p in properties.split(",")]
            items = [{k: v for k, v in item.items() if k in prop_list} for item in items]

        if table:
            # Add derived columns for table display
            for item in items:
                item['error_count'] = len(item.get('errors', []))
                item['tool_count'] = len(item.get('tool_calls', []))
                # Format token counts
                input_tok = item.get('total_input_tokens', 0)
                output_tok = item.get('total_output_tokens', 0)
                cache_read = item.get('total_cache_read_tokens', 0)
                cache_create = item.get('total_cache_creation_tokens', 0)
                effective = item.get('effective_tokens', 0)
                item['in_tok'] = f"{input_tok:,}" if input_tok else ''
                item['out_tok'] = f"{output_tok:,}" if output_tok else ''
                item['cache_read'] = f"{cache_read:,}" if cache_read else ''
                item['cache_create'] = f"{cache_create:,}" if cache_create else ''
                item['effective'] = f"{effective:,}" if effective else ''
            columns = ["id", "type", "description", "message_count", "tool_count", "in_tok", "out_tok", "cache_read", "cache_create", "effective", "error_count"]
            headers = ["ID", "Type", "Description", "Msgs", "Tools", "In Tok", "Out Tok", "Cache Read", "Cache Create", "Effective", "Errors"]
            print_table(items, columns, headers, max_columns=0)
        else:
            print_json(items)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def get_subagent(
    subagent_id: str = typer.Argument(..., help="Subagent/tool call ID"),
    project: str = typer.Option(..., "--project", "-p", help="Project name (required)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get full details for a subagent invocation.

    Example:
        claude-code-sessions subagent-activity get tool-123 --project Agent-ATABlogger
    """
    try:
        client = get_client()
        subagent = client.get_subagent(subagent_id, project)

        if table:
            rows = [
                {"field": "ID", "value": subagent.get("id", "N/A")},
                {"field": "Type", "value": subagent.get("type", "N/A")},
                {"field": "Prompt", "value": (subagent.get("prompt", "N/A") or "N/A")[:100]},
                {"field": "Status", "value": subagent.get("status", "N/A")},
                {"field": "Messages", "value": str(len(subagent.get("messages", [])))},
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(subagent)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
