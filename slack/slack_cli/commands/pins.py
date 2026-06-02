"""Pinned items management commands for Slack CLI."""

COMMAND_CREDENTIALS = {
    "list": ["custom"],
    "get": ["custom"],
}

import typer
from typing import Optional, List
from ..client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, handle_error
from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError, apply_properties_filter

app = typer.Typer(help="Manage Slack pinned items")


@app.command("list")
def list_pins(
    channel_id: str = typer.Argument(..., help="Channel ID to list pinned items for"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of pinned items"),
    filter_: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List pinned items in a channel.

    Example:
        slack pins list C1234567890
        slack pins list C1234567890 --table
    """
    try:
        client = get_client()
        response = client.list_pins(channel_id)
        items = response.get("items", [])

        # Apply client-side filters
        if filter_:
            try:
                validate_filters(filter_)
            except FilterValidationError as e:
                raise typer.BadParameter(str(e))
            items = apply_filters(items, filter_)

        # Apply limit
        items = items[:limit]

        if properties:
            items = apply_properties_filter(items, properties)

        if table:
            from datetime import datetime

            table_data = []
            for item in items:
                item_type = item.get("type", "")

                # Extract relevant info based on type
                if item_type == "message":
                    message = item.get("message", {})
                    table_data.append({
                        "type": item_type,
                        "ts": message.get("ts", ""),
                        "text": (message.get("text", "")[:60] + "...") if len(message.get("text", "")) > 60 else message.get("text", ""),
                        "user": message.get("user", ""),
                        "pinned": datetime.fromtimestamp(item.get("created", 0)).strftime("%Y-%m-%d %H:%M")
                        if item.get("created")
                        else "",
                        "pinned_by": item.get("created_by", ""),
                    })
                elif item_type == "file":
                    file_obj = item.get("file", {})
                    table_data.append({
                        "type": item_type,
                        "ts": file_obj.get("id", ""),
                        "text": file_obj.get("name", file_obj.get("title", "")),
                        "user": file_obj.get("user", ""),
                        "pinned": datetime.fromtimestamp(item.get("created", 0)).strftime("%Y-%m-%d %H:%M")
                        if item.get("created")
                        else "",
                        "pinned_by": item.get("created_by", ""),
                    })
                else:
                    table_data.append({
                        "type": item_type,
                        "ts": "",
                        "text": "",
                        "user": "",
                        "pinned": datetime.fromtimestamp(item.get("created", 0)).strftime("%Y-%m-%d %H:%M")
                        if item.get("created")
                        else "",
                        "pinned_by": item.get("created_by", ""),
                    })

            print_table(
                table_data,
                ["type", "ts", "text", "user", "pinned", "pinned_by"],
                ["Type", "TS/ID", "Content", "User", "Pinned At", "Pinned By"],
            )
        else:
            print_json({"items": items, "count": len(items)})

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def get_pin(
    channel_id: str = typer.Argument(..., help="Channel ID where pin exists"),
    pin_ts: str = typer.Argument(..., help="Timestamp of the pinned message or file ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get a specific pinned item by timestamp or file ID.

    Example:
        slack pins get C1234567890 1234567890.123456
        slack pins get C1234567890 1234567890.123456 --table
    """
    try:
        client = get_client()
        response = client.list_pins(channel_id)
        items = response.get("items", [])

        # Find the specific pinned item
        pin = None
        for item in items:
            item_type = item.get("type", "")
            if item_type == "message":
                message = item.get("message", {})
                if message.get("ts") == pin_ts:
                    pin = item
                    break
            elif item_type == "file":
                file_obj = item.get("file", {})
                if file_obj.get("id") == pin_ts:
                    pin = item
                    break

        if not pin:
            typer.echo(f"Pinned item {pin_ts} not found in channel {channel_id}", err=True)
            raise typer.Exit(1)

        if table:
            from datetime import datetime

            item_type = pin.get("type", "")

            if item_type == "message":
                message = pin.get("message", {})
                table_data = [{
                    "type": item_type,
                    "channel": pin.get("channel", ""),
                    "ts": message.get("ts", ""),
                    "text": message.get("text", ""),
                    "user": message.get("user", ""),
                    "permalink": message.get("permalink", ""),
                    "pinned": datetime.fromtimestamp(pin.get("created", 0)).strftime("%Y-%m-%d %H:%M")
                    if pin.get("created")
                    else "",
                    "pinned_by": pin.get("created_by", ""),
                }]
                print_table(
                    table_data,
                    ["type", "channel", "ts", "text", "user", "permalink", "pinned", "pinned_by"],
                    ["Type", "Channel", "TS", "Text", "User", "Permalink", "Pinned At", "Pinned By"],
                )
            elif item_type == "file":
                file_obj = pin.get("file", {})
                table_data = [{
                    "type": item_type,
                    "file_id": file_obj.get("id", ""),
                    "name": file_obj.get("name", ""),
                    "title": file_obj.get("title", ""),
                    "user": file_obj.get("user", ""),
                    "url": file_obj.get("url_private", ""),
                    "pinned": datetime.fromtimestamp(pin.get("created", 0)).strftime("%Y-%m-%d %H:%M")
                    if pin.get("created")
                    else "",
                    "pinned_by": pin.get("created_by", ""),
                }]
                print_table(
                    table_data,
                    ["type", "file_id", "name", "title", "user", "pinned", "pinned_by"],
                    ["Type", "File ID", "Name", "Title", "User", "Pinned At", "Pinned By"],
                )
            else:
                print_json(pin)
        else:
            print_json(pin)

    except Exception as e:
        raise typer.Exit(handle_error(e))
