"""Notification commands for Slack CLI."""

COMMAND_CREDENTIALS = {
    "counts": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "summary": [
        "custom"
    ]
}

import typer
from typing import Optional, List, Dict
from datetime import datetime
from ..client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, print_success, print_warning, handle_error
from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError, apply_properties_filter

app = typer.Typer(help="Manage Slack notifications")

# Cache for user ID to name mapping
_user_cache: Dict[str, str] = {}
# Cache for channel ID to name mapping
_channel_cache: Dict[str, str] = {}


def _get_user_name(client, user_id: str) -> str:
    """Get user display name from user ID, with caching."""
    if not user_id:
        return "unknown"

    if user_id in _user_cache:
        return _user_cache[user_id]

    try:
        response = client.get_user_info(user_id)
        user = response.get("user", {})
        name = (
            user.get("profile", {}).get("display_name") or
            user.get("real_name") or
            user.get("name") or
            user_id
        )
        _user_cache[user_id] = name
        return name
    except Exception:
        _user_cache[user_id] = user_id
        return user_id


def _get_channel_name(client, channel_id: str) -> str:
    """Get channel name from channel ID, with caching."""
    if not channel_id:
        return "unknown"

    if channel_id in _channel_cache:
        return _channel_cache[channel_id]

    try:
        response = client.get_channel_info(channel_id)
        channel = response.get("channel", {})
        # For DMs, get the user name
        if channel.get("is_im"):
            user_id = channel.get("user", "")
            name = f"DM: {_get_user_name(client, user_id)}"
        elif channel.get("is_mpim"):
            name = f"Group: {channel.get('name', channel_id)}"
        else:
            name = f"#{channel.get('name', channel_id)}"
        _channel_cache[channel_id] = name
        return name
    except Exception:
        _channel_cache[channel_id] = channel_id
        return channel_id


def _get_channel_unread_info(client, channel_id: str) -> dict:
    """Get channel info including unread count."""
    try:
        response = client.get_channel_info(channel_id)
        return response.get("channel", {})
    except Exception:
        return {}


def _collect_from_client_counts(client) -> Dict:
    """
    Use the fast client.counts API to get all notification counts.

    Returns a dict with:
    - dms: list of DM notifications
    - channels: list of channel notifications
    - threads: list of thread notifications
    - saved: list of saved for later items
    - badge_counts: dict with the actual badge numbers
    - supported: bool indicating if API is supported
    - reason: reason why not supported (if applicable)
    """
    result = {
        "dms": [],
        "channels": [],
        "threads": [],
        "saved": [],
        "badge_counts": {},
        "supported": False,
        "reason": None,
    }

    try:
        counts = client.get_client_counts()
        result["supported"] = True

        # Get the actual badge counts (this is what Slack uses for the badge!)
        badges = counts.get("channel_badges", {})
        saved_info = counts.get("saved", {})

        result["badge_counts"] = {
            "channels": badges.get("channels", 0),
            "dms": badges.get("dms", 0),
            "app_dms": badges.get("app_dms", 0),
            "thread_mentions": badges.get("thread_mentions", 0),
            "thread_unreads": badges.get("thread_unreads", 0),
            "saved": saved_info.get("uncompleted_count", 0),
        }

        # Process DMs (ims) - only those with mentions (badge contributors)
        for im in counts.get("ims", []):
            if im.get("mention_count", 0) > 0:
                channel_id = im.get("id", "")
                result["dms"].append({
                    "type": "dm",
                    "channel_id": channel_id,
                    "channel_name": _get_channel_name(client, channel_id),
                    "mention_count": im.get("mention_count", 0),
                    "has_unreads": im.get("has_unreads", False),
                })

        # Process group DMs (mpims)
        for mpim in counts.get("mpims", []):
            if mpim.get("mention_count", 0) > 0:
                channel_id = mpim.get("id", "")
                result["dms"].append({
                    "type": "group_dm",
                    "channel_id": channel_id,
                    "channel_name": _get_channel_name(client, channel_id),
                    "mention_count": mpim.get("mention_count", 0),
                    "has_unreads": mpim.get("has_unreads", False),
                })

        # Process channels (only those with mentions)
        for ch in counts.get("channels", []):
            if ch.get("mention_count", 0) > 0:
                channel_id = ch.get("id", "")
                result["channels"].append({
                    "type": "channel_mention",
                    "channel_id": channel_id,
                    "channel_name": _get_channel_name(client, channel_id),
                    "mention_count": ch.get("mention_count", 0),
                    "has_unreads": ch.get("has_unreads", False),
                })

        # Process threads
        threads_info = counts.get("threads", {})
        if threads_info.get("has_unreads") or threads_info.get("mention_count", 0) > 0:
            unread_by_channel = threads_info.get("unread_count_by_channel", {})
            for channel_id, unread_count in unread_by_channel.items():
                result["threads"].append({
                    "type": "thread",
                    "channel_id": channel_id,
                    "channel_name": _get_channel_name(client, channel_id),
                    "unread_count": unread_count,
                    "mention_count": threads_info.get("mention_count_by_channel", {}).get(channel_id, 0),
                })

        # Add saved for later count
        if saved_info.get("uncompleted_count", 0) > 0:
            result["saved"].append({
                "type": "saved",
                "count": saved_info.get("uncompleted_count", 0),
                "overdue": saved_info.get("uncompleted_overdue_count", 0),
            })

    except ClientError as e:
        error_str = str(e)
        if "not_allowed_token_type" in error_str:
            result["reason"] = "token type not supported for this API"
        elif "No suitable token" in error_str:
            result["reason"] = "no session token (xoxc) available"
        else:
            result["reason"] = error_str

    return result


def _collect_unread_dms_slow(client, limit: int = 50) -> List[Dict]:
    """Collect unread DMs using the slower individual API calls."""
    notifications = []
    try:
        response = client.list_dms(limit=limit)
        channels = response.get("channels", [])

        for ch in channels:
            channel_info = _get_channel_unread_info(client, ch.get("id"))
            if channel_info:
                unread_count = channel_info.get("unread_count", 0)
                if unread_count > 0:
                    user_id = ch.get("user", "")
                    user_name = _get_user_name(client, user_id) if user_id else "unknown"
                    notifications.append({
                        "type": "dm",
                        "channel_id": ch.get("id"),
                        "channel_name": f"DM: {user_name}",
                        "user_id": user_id,
                        "user_name": user_name,
                        "mention_count": unread_count,
                        "has_unreads": True,
                    })
    except Exception as e:
        print_warning(f"Failed to fetch DMs: {e}")

    return notifications


def _collect_mentions(client, count: int = 20) -> List[Dict]:
    """Collect recent mentions using search."""
    notifications = []
    try:
        current_user_id = client.get_current_user_id()
        response = client.search_messages(query=f"<@{current_user_id}>", count=count, page=1)
        matches = response.get("messages", {}).get("matches", [])

        for msg in matches:
            channel = msg.get("channel", {})
            notifications.append({
                "type": "mention",
                "channel_id": channel.get("id", ""),
                "channel_name": f"#{channel.get('name', 'unknown')}",
                "user_name": msg.get("username", "unknown"),
                "text": msg.get("text", "")[:80] + ("..." if len(msg.get("text", "")) > 80 else ""),
                "ts": msg.get("ts", ""),
                "permalink": msg.get("permalink", ""),
            })
    except Exception as e:
        print_warning(f"Failed to fetch mentions: {e}")

    return notifications


@app.command("get")
def notification_get(
    channel_id: str = typer.Argument(..., help="Channel ID to get notification info for"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get notification details for a specific channel.

    Example:
        slack notifications get C1234567890
        slack notifications get C1234567890 --table
    """
    try:
        client = get_client()
        channel_info = client.get_channel_info(channel_id)
        channel = channel_info.get("channel", {})
        result = {
            "channel_id": channel.get("id"),
            "name": channel.get("name"),
            "unread_count": channel.get("unread_count", 0),
            "unread_count_display": channel.get("unread_count_display", 0),
            "has_unreads": channel.get("has_unreads", False),
            "mention_count": channel.get("mention_count", 0),
        }
        if table:
            print_table([result],
                ["channel_id", "name", "unread_count", "mention_count", "has_unreads"],
                ["Channel", "Name", "Unread", "Mentions", "Has Unreads"])
        else:
            print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("counts")
def notification_counts(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Show notification counts using Slack's internal API (fast).

    This uses the client.counts API which gives accurate badge counts for:
    - Unread DMs and group DMs
    - Channel mentions (@you)
    - Unread thread replies

    Requires xoxc (session) token. Falls back to slower method for other token types.

    Example:
        slack notifications counts --table
    """
    try:
        client = get_client()
        all_notifications = []

        counts_result = _collect_from_client_counts(client)

        if counts_result["supported"]:
            all_notifications.extend(counts_result["dms"])
            all_notifications.extend(counts_result["channels"])
            all_notifications.extend(counts_result["threads"])
        else:
            print_warning(f"client.counts not supported, using slower method")
            all_notifications.extend(_collect_unread_dms_slow(client, limit=50))

        # Calculate totals
        dm_count = sum(1 for n in all_notifications if n.get("type") in ("dm", "group_dm"))
        channel_mention_count = sum(1 for n in all_notifications if n.get("type") == "channel_mention")
        thread_count = sum(1 for n in all_notifications if n.get("type") == "thread")
        total_mentions = sum(n.get("mention_count", 0) for n in all_notifications)

        if table:
            table_data = []
            for notif in all_notifications:
                notif_type = notif.get("type", "")
                type_display = {
                    "dm": "DM",
                    "group_dm": "GROUP DM",
                    "channel_mention": "MENTION",
                    "thread": "THREAD",
                }.get(notif_type, notif_type.upper())

                table_data.append({
                    "type": type_display,
                    "source": notif.get("channel_name", ""),
                    "mentions": notif.get("mention_count", 0) or "",
                })

            columns = ["type", "source", "mentions"]
            headers = ["Type", "Source", "Mentions"]

            if table_data:
                print_table(table_data, columns, headers)
            else:
                typer.echo("No notifications found.")

            typer.echo("")
            typer.echo(f"Summary: {dm_count} DMs, {channel_mention_count} channel mentions, {thread_count} threads")
            typer.echo(f"Total badge-contributing items: {len(all_notifications)}")
        else:
            print_json({
                "notifications": all_notifications,
                "summary": {
                    "dms": dm_count,
                    "channel_mentions": channel_mention_count,
                    "threads": thread_count,
                    "total_items": len(all_notifications),
                    "total_mentions": total_mentions,
                },
            })

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("list")
def list_notifications(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    include_dms: bool = typer.Option(True, "--dms/--no-dms", help="Include unread DMs"),
    include_threads: bool = typer.Option(True, "--threads/--no-threads", help="Include unread threads"),
    include_mentions: bool = typer.Option(True, "--mentions/--no-mentions", help="Include channel mentions"),
    include_saved: bool = typer.Option(True, "--saved/--no-saved", help="Include saved for later"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of notifications"),
    filter_: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List all notifications that contribute to your Slack badge.

    Uses the fast client.counts API when available (xoxc tokens).
    Shows:
    - Unread DMs and group DMs
    - Channel mentions (@you)
    - Unread thread replies
    - Saved for later items

    Example:
        slack notifications list --table
        slack notifications list --no-threads --table
    """
    try:
        client = get_client()
        all_notifications = []
        total_badge = 0

        counts_result = _collect_from_client_counts(client)

        if counts_result["supported"]:
            if include_dms:
                all_notifications.extend(counts_result["dms"])
            if include_mentions:
                all_notifications.extend(counts_result["channels"])
            if include_threads:
                all_notifications.extend(counts_result["threads"])
            if include_saved:
                all_notifications.extend(counts_result["saved"])

            # Use the actual badge counts
            badges = counts_result["badge_counts"]
            total_badge += (
                badges.get("dms", 0) + badges.get("app_dms", 0) +
                badges.get("channels", 0) +
                badges.get("thread_mentions", 0) + badges.get("thread_unreads", 0) +
                badges.get("saved", 0)
            )
        else:
            reason = counts_result.get("reason", "session token (xoxc) required")
            print_warning(f"{reason}")
            if include_dms:
                dms = _collect_unread_dms_slow(client, limit=50)
                all_notifications.extend(dms)
                total_badge += len(dms)

        # Apply filters
        if filter_:
            try:
                validate_filters(filter_)
                all_notifications = apply_filters(all_notifications, filter_)
            except FilterValidationError as e:
                typer.echo(f"Invalid filter: {e}", err=True)
                raise typer.Exit(1)

        # Apply limit
        all_notifications = all_notifications[:limit]

        # Apply properties filter
        if properties:
            all_notifications = apply_properties_filter(all_notifications, properties)

        # Calculate display totals
        dm_count = sum(1 for n in all_notifications if n.get("type") in ("dm", "group_dm"))
        channel_mention_count = sum(1 for n in all_notifications if n.get("type") == "channel_mention")
        thread_count = sum(1 for n in all_notifications if n.get("type") == "thread")
        saved_count = sum(n.get("count", 0) for n in all_notifications if n.get("type") == "saved")

        if table:
            table_data = []
            for notif in all_notifications:
                notif_type = notif.get("type", "")
                type_display = {
                    "dm": "DM",
                    "group_dm": "GROUP DM",
                    "channel_mention": "MENTION",
                    "thread": "THREAD",
                    "saved": "SAVED",
                }.get(notif_type, notif_type.upper())

                if notif_type == "saved":
                    source = f"Saved for later ({notif.get('overdue', 0)} overdue)"
                    count = notif.get("count", 0)
                else:
                    source = notif.get("channel_name", "")
                    count = notif.get("mention_count", 0) or notif.get("unread_count", 0) or ""

                table_data.append({
                    "type": type_display,
                    "source": source,
                    "count": count,
                })

            columns = ["type", "source", "count"]
            headers = ["Type", "Source", "Count"]

            if table_data:
                print_table(table_data, columns, headers)
            else:
                typer.echo("No notifications found.")

            typer.echo("")
            typer.echo(f"Summary: {dm_count} DMs, {channel_mention_count} mentions, {thread_count} threads, {saved_count} saved")
            typer.echo(f"Badge count: {total_badge}")
        else:
            print_json({
                "notifications": all_notifications,
                "summary": {
                    "dms": dm_count,
                    "channel_mentions": channel_mention_count,
                    "threads": thread_count,
                    "saved": saved_count,
                    "badge_count": total_badge,
                },
            })

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("summary")
def notification_summary():
    """
    Show a quick summary of notification counts.

    Uses the fast client.counts API when available. Shows the actual
    badge counts that Slack uses for the app icon badge.

    Example:
        slack notifications summary
    """
    try:
        client = get_client()
        counts_result = _collect_from_client_counts(client)

        if counts_result["supported"]:
            badges = counts_result["badge_counts"]
            dm_badge = badges.get("dms", 0) + badges.get("app_dms", 0)
            channel_badge = badges.get("channels", 0)
            thread_badge = badges.get("thread_mentions", 0) + badges.get("thread_unreads", 0)
            saved_badge = badges.get("saved", 0)
            total = dm_badge + channel_badge + thread_badge + saved_badge

            typer.echo(f"  {dm_badge} DMs")
            typer.echo(f"  {channel_badge} channel mentions")
            typer.echo(f"  {thread_badge} thread replies")
            typer.echo(f"  {saved_badge} saved for later")
            typer.echo(f"  {total} total (badge count)")
        else:
            # Fall back to slower method
            dms = _collect_unread_dms_slow(client, limit=100)
            dm_count = len(dms)

            reason = counts_result.get("reason", "session token (xoxc) required")
            typer.echo(f"(limited - {reason})")
            typer.echo(f"  {dm_count} unread DMs")

    except Exception as e:
        raise typer.Exit(handle_error(e))
