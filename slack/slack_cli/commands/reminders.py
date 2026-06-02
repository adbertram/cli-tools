"""Reminder commands for Slack CLI.

Combines traditional reminders (reminders.list) and saved items (saved.list)
into a unified view.
"""

COMMAND_CREDENTIALS = {
    "complete": [
        "custom"
    ],
    "delete": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "new": [
        "custom"
    ]
}

from datetime import datetime
from pathlib import Path
import typer
from typing import List, Optional

from ..client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, handle_error
from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError, apply_properties_filter

app = typer.Typer(help="Manage Slack reminders")


def _format_time(timestamp: Optional[int]) -> str:
    """Format Unix timestamp to readable datetime string."""
    if not timestamp:
        return "N/A"
    try:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError):
        return str(timestamp)


def _get_overdue_status(date_due: int) -> str:
    """Get human-readable overdue status."""
    if not date_due or date_due <= 1:
        return ""
    now = datetime.now().timestamp()
    diff_seconds = now - date_due
    if diff_seconds <= 0:
        return ""

    days = int(diff_seconds // 86400)
    if days > 0:
        return f"Overdue by {days} day{'s' if days != 1 else ''}"
    hours = int(diff_seconds // 3600)
    if hours > 0:
        return f"Overdue by {hours} hour{'s' if hours != 1 else ''}"
    minutes = int(diff_seconds // 60)
    return f"Overdue by {minutes} minute{'s' if minutes != 1 else ''}"


def _normalize_saved_item(item: dict) -> dict:
    """Normalize a saved.list item into the common format."""
    return {
        "id": item.get("id", ""),
        "source": "saved",
        "channel": item.get("item_id", ""),
        "state": item.get("state", ""),
        "due": item.get("date_due", 0),
        "created": item.get("date_created", 0),
        "text": item.get("text", ""),
        "ts": item.get("ts", ""),
        "_raw": item,
    }


def _normalize_reminder(item: dict) -> dict:
    """Normalize a reminders.list item into the common format."""
    complete_ts = item.get("complete_ts", 0)
    state = "completed" if complete_ts else "in_progress"
    return {
        "id": item.get("id", ""),
        "source": "reminder",
        "channel": item.get("channel", ""),
        "state": state,
        "due": item.get("time", 0),
        "created": item.get("created", 0),
        "text": item.get("text", ""),
        "ts": "",
        "_raw": item,
    }


def _resolve_channel_name(client, channel_id: str) -> str:
    """Resolve a channel ID to its display name."""
    if not channel_id or not channel_id.startswith("C"):
        return channel_id
    try:
        info = client.get_channel_info(channel_id)
        channel = info.get("channel", {})
        return channel.get("name", channel_id)
    except Exception:
        return channel_id


def _query_reminders_for_profile(profile_name: Optional[str], include_content: bool) -> dict:
    """Query both saved items and reminders for a single profile.

    Returns dict with keys: items, saved_items, raw_reminders, saved_counts, workspace.
    """
    client = get_client(profile=profile_name)
    workspace = profile_name or "default"

    saved_response = client.list_saved()
    saved_items = saved_response.get("saved_items", [])
    saved_counts = saved_response.get("counts", {})

    reminder_response = client.list_reminders()
    raw_reminders = reminder_response.get("reminders", [])

    items = [_normalize_saved_item(s) for s in saved_items]
    items += [_normalize_reminder(r) for r in raw_reminders]

    # Tag each item with the workspace/profile name
    # Resolve channel IDs to names
    channel_cache = {}
    for item in items:
        item["workspace"] = workspace
        ch_id = item.get("channel", "")
        if ch_id and ch_id not in channel_cache:
            channel_cache[ch_id] = _resolve_channel_name(client, ch_id)
        if ch_id:
            item["channel_name"] = channel_cache.get(ch_id, ch_id)

    # Optionally fetch message content for saved items
    if include_content:
        for item in items:
            if item["source"] == "saved" and not item.get("text"):
                try:
                    channel = item.get("channel")
                    ts = item.get("ts")
                    if channel and ts:
                        history = client.get_message_history(
                            channel, limit=1, oldest=ts, latest=ts, inclusive=True
                        )
                        messages = history.get("messages", [])
                        if messages:
                            item["text"] = messages[0].get("text", "")
                except Exception:
                    item["text"] = "(unable to fetch)"

    return {
        "items": items,
        "saved_items": saved_items,
        "raw_reminders": raw_reminders,
        "saved_counts": saved_counts,
        "workspace": workspace,
    }


@app.command("list")
def list_reminders(
    state: str = typer.Option(
        "in_progress",
        "--state",
        "-s",
        help="Filter by state: in_progress, archived, completed, all",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    include_content: bool = typer.Option(
        False, "--content", "-c", help="Fetch and include message content for saved items (slower)"
    ),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of items"),
    filter_: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Query a specific profile instead of the default"),
    all_profiles: bool = typer.Option(False, "--all-profiles", "-a", help="Query all configured profiles"),
):
    """
    List all reminders from both traditional reminders and saved items (Later).

    Queries both reminders.list and saved.list APIs, normalizes results
    into a unified list.

    Example:
        slack reminders list
        slack reminders list --state all
        slack reminders list --all-profiles
        slack reminders list --profile devolutions
        slack reminders list --state all --table
        slack reminders list --content --table
    """
    try:
        if all_profiles:
            from cli_tools_shared.profiles import list_profiles
            tool_dir = Path(__file__).resolve().parent.parent.parent
            profiles = list_profiles(tool_dir)
            profile_names = [p["name"] for p in profiles]
        elif profile:
            profile_names = [profile]
        else:
            profile_names = [None]  # None = default profile

        all_items = []
        total_saved = 0
        total_raw_reminders = 0
        total_saved_counts = {
            "uncompleted_count": 0,
            "completed_count": 0,
            "archived_count": 0,
            "total_count": 0,
        }

        for pname in profile_names:
            try:
                result = _query_reminders_for_profile(pname, include_content)
                all_items.extend(result["items"])
                total_saved += len(result["saved_items"])
                total_raw_reminders += len(result["raw_reminders"])
                sc = result["saved_counts"]
                for key in total_saved_counts:
                    total_saved_counts[key] += sc.get(key, 0)
            except ClientError as e:
                import sys
                ws = pname or "default"
                print(f"Skipping profile '{ws}': {e}", file=sys.stderr)
                continue

        items = all_items

        # Filter by state
        if state != "all":
            items = [item for item in items if item.get("state") == state]

        # Apply filters
        if filter_:
            try:
                validate_filters(filter_)
                items = apply_filters(items, filter_)
            except FilterValidationError as e:
                typer.echo(f"Invalid filter: {e}", err=True)
                raise typer.Exit(1)

        # Apply properties filter
        if properties:
            items = apply_properties_filter(items, properties)

        # Apply limit
        items = items[:limit]

        # Compute combined counts across all queried profiles
        reminder_in_progress = sum(1 for i in all_items if i["source"] == "reminder" and i.get("state") == "in_progress")
        reminder_completed = sum(1 for i in all_items if i["source"] == "reminder" and i.get("state") == "completed")
        total_in_progress = total_saved_counts.get("uncompleted_count", 0) + reminder_in_progress
        total_completed = total_saved_counts.get("completed_count", 0) + reminder_completed
        total_archived = total_saved_counts.get("archived_count", 0)
        total_count = total_saved_counts.get("total_count", 0) + total_raw_reminders

        show_workspace = all_profiles or (profile is not None)

        if table:
            table_data = []
            for item in items:
                due_val = item.get("due", 0)
                row = {
                    "id": item.get("id", ""),
                    "channel": item.get("channel_name", item.get("channel", "")),
                    "state": item.get("state", ""),
                    "due": _format_time(due_val) if due_val and due_val > 1 else "No due date",
                    "overdue": _get_overdue_status(due_val) if due_val else "",
                    "created": _format_time(item.get("created")),
                }
                if show_workspace:
                    row["workspace"] = item.get("workspace", "")
                if include_content:
                    text = item.get("text", "")
                    row["text"] = text[:50] + ("..." if len(text) > 50 else "")
                table_data.append(row)

            columns = ["id", "channel", "state", "due", "overdue", "created"]
            headers = ["ID", "Channel", "State", "Due", "Status", "Created"]
            if show_workspace:
                columns.insert(0, "workspace")
                headers.insert(0, "Workspace")
            if include_content:
                columns.append("text")
                headers.append("Text")

            print_table(table_data, columns, headers)

            from cli_tools_shared.output import print_info
            profiles_label = ", ".join(p or "default" for p in profile_names)
            print_info(f"\nShowing {len(items)} {state} items from [{profiles_label}] (saved: {total_saved}, reminders: {total_raw_reminders})")
            print_info(f"Total: {total_count} | In Progress: {total_in_progress} | Archived: {total_archived} | Completed: {total_completed}")
        else:
            result = {
                "ok": True,
                "items": items,
                "counts": {
                    "total_count": total_count,
                    "uncompleted_count": total_in_progress,
                    "archived_count": total_archived,
                    "completed_count": total_completed,
                    "saved_count": total_saved,
                    "reminder_count": total_raw_reminders,
                },
                "filter": state,
            }
            if show_workspace:
                result["profiles"] = [p or "default" for p in profile_names]
            print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def get_reminder(
    reminder_id: str = typer.Argument(..., help="Reminder ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get a specific reminder by ID.

    Example:
        slack reminders get Rm12345678
        slack reminders get Rm12345678 --table
    """
    try:
        client = get_client()
        response = client.list_reminders()
        reminders = response.get("reminders", [])
        reminder = next((r for r in reminders if r.get("id") == reminder_id), None)
        if not reminder:
            typer.echo(f"Reminder {reminder_id} not found", err=True)
            raise typer.Exit(1)
        if table:
            print_table([{
                "id": reminder.get("id"),
                "text": reminder.get("text", "")[:50],
                "time": _format_time(reminder.get("time")),
                "complete_ts": reminder.get("complete_ts", 0),
            }], ["id", "text", "time", "complete_ts"], ["ID", "Text", "Time", "Completed"])
        else:
            print_json(reminder)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("complete")
def complete_reminder(
    reminder_id: str = typer.Argument(..., help="The ID of the reminder to complete"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Mark a reminder as complete.

    Example:
        slack reminders complete Rm12345678
        slack reminders complete Rm12345678 --table
    """
    try:
        client = get_client()
        client.complete_reminder(reminder_id)

        result = {"ok": True, "reminder_id": reminder_id, "message": "Reminder marked as complete"}

        if table:
            print_table(
                [{"reminder_id": reminder_id, "status": "Completed"}],
                ["reminder_id", "status"],
                ["Reminder ID", "Status"],
            )
        else:
            print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


def _parse_friendly_time(time_str: str) -> Optional[int]:
    """
    Parse a friendly time string into seconds.

    Supports formats like:
        - "30 min", "30 minutes", "30m"
        - "2 hours", "2 hour", "2h"
        - "3 days", "3 day", "3d"
        - "1 week", "2 weeks", "1w"
        - Plain integers (treated as seconds)
        - Large integers (treated as Unix timestamps)

    Returns:
        Unix timestamp for the due time, or None if parsing fails
    """
    import re

    time_str = time_str.strip().lower()

    # Try plain integer first
    try:
        value = int(time_str)
        # If it's a large number, treat as Unix timestamp
        if value > 86400 * 365:  # More than 1 year in seconds
            return value
        # Otherwise treat as seconds from now
        return int(datetime.now().timestamp()) + value
    except ValueError:
        pass

    # Parse friendly formats
    patterns = [
        (r"^(\d+)\s*(?:m|min|mins|minute|minutes)$", 60),           # minutes
        (r"^(\d+)\s*(?:h|hr|hrs|hour|hours)$", 3600),               # hours
        (r"^(\d+)\s*(?:d|day|days)$", 86400),                       # days
        (r"^(\d+)\s*(?:w|wk|wks|week|weeks)$", 604800),             # weeks
    ]

    for pattern, multiplier in patterns:
        match = re.match(pattern, time_str)
        if match:
            value = int(match.group(1))
            return int(datetime.now().timestamp()) + (value * multiplier)

    return None


@app.command("new")
def new_reminder(
    channel: str = typer.Argument(..., help="The channel ID containing the message"),
    ts: str = typer.Argument(..., help="The message timestamp to save"),
    due: Optional[str] = typer.Option(
        None,
        "--due",
        "-d",
        help="When to be reminded: e.g., '30 min', '2 hours', '3 days', '1 week'",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Save a message for later with an optional reminder time.

    Uses Slack's 'Later' feature (saved.add API) to save messages.

    Example:
        slack reminders new C01234567 1734625200.123456
        slack reminders new C01234567 1734625200.123456 --due "30 min"
        slack reminders new C01234567 1734625200.123456 --due "2 hours"
        slack reminders new C01234567 1734625200.123456 --due "3 days"
        slack reminders new C01234567 1734625200.123456 --table
    """
    try:
        client = get_client()

        # Parse due time if provided
        date_due = None
        if due:
            date_due = _parse_friendly_time(due)
            if date_due is None:
                from cli_tools_shared.output import print_error
                print_error(f"Invalid due time: '{due}'. Use formats like '30 min', '2 hours', '3 days', '1 week'")
                raise typer.Exit(1)

        response = client.add_saved(channel, ts, date_due)
        item = response.get("item", {})

        if table:
            table_data = [
                {
                    "channel": item.get("item_id", ""),
                    "ts": item.get("ts", ""),
                    "due": _format_time(item.get("date_due")) if item.get("date_due", 0) > 0 else "No due date",
                    "state": item.get("state", ""),
                    "created": _format_time(item.get("date_created")),
                }
            ]
            print_table(
                table_data,
                ["channel", "ts", "due", "state", "created"],
                ["Channel", "Timestamp", "Due", "State", "Created"],
            )
        else:
            print_json(response)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def delete_reminder(
    reminder_id: str = typer.Argument(..., help="The ID of the reminder to delete"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Delete a reminder.

    Example:
        slack reminders delete Rm12345678
        slack reminders delete Rm12345678 --table
    """
    try:
        client = get_client()
        client.delete_reminder(reminder_id)

        result = {"ok": True, "reminder_id": reminder_id, "message": "Reminder deleted"}

        if table:
            print_table(
                [{"reminder_id": reminder_id, "status": "Deleted"}],
                ["reminder_id", "status"],
                ["Reminder ID", "Status"],
            )
        else:
            print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))

