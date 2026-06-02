"""Messages commands for Brickowl CLI.

Browser automation for listing, viewing, replying, sending,
and managing message read status on Brick Owl.
Mirrors bricklink messages CLI interface.
"""
COMMAND_CREDENTIALS = {
    "list": ["browser_session"],
    "get": ["browser_session"],
    "send": ["browser_session"],
    "reply": ["browser_session"],
    "mark-read": ["browser_session"],
    "mark-unread": ["browser_session"],
}

import re as _re
from datetime import datetime, timezone
from typing import Optional, List

import typer

from ..models import Message
from cli_tools_shared.output import print_json, print_table, print_success, handle_error
from cli_tools_shared.filters import apply_filters, apply_properties_filter, apply_limit

app = typer.Typer(help="Manage Brick Owl messages", no_args_is_help=True)


# ==================== Default Table Columns ====================

MSG_LIST_COLUMNS = ["message_id", "subject", "username", "date", "is_unread"]
MSG_LIST_HEADERS = ["ID", "Subject", "User", "Date", "Unread"]


# ==================== Helpers ====================


def _parse_msg_date(date_str: str) -> datetime:
    """Parse a message date string, converting local time to UTC for consistent comparison."""
    if not date_str:
        return datetime.min
    s = _re.sub(r'\s+[A-Z]{2,4}$', '', date_str.strip())
    for fmt in [
        "%b %d, %Y %I:%M:%S %p",
        "%b %d, %Y %I:%M %p",
        "%b %d, %Y %H:%M:%S",
        "%b %d, %Y %H:%M",
        "%b %d, %Y",
        "%d %b %Y %H:%M",
    ]:
        try:
            naive_local = datetime.strptime(s, fmt)
            aware_local = naive_local.astimezone()
            return aware_local.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            continue
    return datetime.min


def _extract_order_id(subject: str) -> Optional[str]:
    """Extract an order ID from a message subject."""
    m = _re.search(r'#\s*(\d+)', subject)
    return m.group(1) if m else None


def _normalize_list_msg(msg: dict, folder: str) -> dict:
    """Normalize a browser list message to match bricklink output fields."""
    out = dict(msg)
    # is_unread from icon-envelope presence (set by browser scraper).
    # Falls back to status text for backward compatibility.
    if "is_unread" not in out:
        status = out.get("status", "")
        out["is_unread"] = "unread" in status.lower() if status else False
    # Compute username: the other party (not us)
    if folder == "sent":
        out["username"] = out.get("to", "")
    else:
        out["username"] = out.get("from", "")
    # Extract order_id if not present
    if not out.get("order_id"):
        subj = out.get("subject", "")
        out["order_id"] = _extract_order_id(subj)
    return out


def _build_conversation(browser, subject: str, source_id: str, source_detail: dict, cache: Optional[dict] = None) -> list:
    """Find all messages matching a subject by scanning browser message list.

    Strategy:
      1. Fetch all messages (both sent and received) in one call.
      2. Match by normalized subject OR by order_id.
      3. Fetch details for each match, using cache for efficiency.

    Args:
        browser: BrickOwlBrowser instance.
        subject: Subject of the source message.
        source_id: Message ID of the source message (already fetched).
        source_detail: Full detail dict of the source message (to avoid re-fetch).
        cache: Optional shared cache dict for message listings and details.

    Returns:
        List of message detail dicts sorted oldest-first.
    """
    from ..browser import BrickOwlBrowser
    base = BrickOwlBrowser.normalize_subject(subject)
    if not base:
        return [{k: v for k, v in source_detail.items() if k != "message_history"}] if source_detail else []

    if cache is None:
        cache = {}

    # Cache the full "all" listing
    if "all_messages" not in cache:
        cache["all_messages"] = browser.list_messages(folder="all")

    def _cached_detail(mid):
        key = ("detail", mid)
        if key not in cache:
            cache[key] = browser.get_message(mid)
        return cache[key]

    # Pre-cache source detail
    cache[("detail", source_id)] = source_detail

    order_id = _extract_order_id(subject)
    seen = set()
    conversation = []

    for msg in cache["all_messages"]:
        mid = msg["message_id"]
        if mid in seen:
            continue
        raw_subject = msg.get("subject", "")
        matched = False
        if BrickOwlBrowser.normalize_subject(raw_subject) == base:
            matched = True
        elif order_id and _extract_order_id(raw_subject) == order_id:
            matched = True
        if matched:
            seen.add(mid)
            detail = _cached_detail(mid)
            entry = {k: v for k, v in detail.items() if k != "message_history"}
            entry["source"] = "browser"
            conversation.append(entry)

    # Include source message if not already present
    if source_id not in seen:
        seen.add(source_id)
        stripped = {k: v for k, v in source_detail.items() if k != "message_history"}
        if "source" not in stripped:
            stripped["source"] = "browser"
        conversation.append(stripped)

    conversation.sort(key=lambda m: _parse_msg_date(m.get("sent_date", m.get("date", ""))))
    return conversation


# ==================== Commands ====================


@app.command("list")
def messages_list(
    folder: str = typer.Option("inbox", "--folder", help="Message folder: inbox or outbox"),
    page: int = typer.Option(1, "--page", "-pg", help="Page number"),
    include_history: bool = typer.Option(False, "--include-history", help="Include message history thread for each message"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Max results"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Fields to include"),
):
    """
    List messages (browser-based).

    Examples:
        brickowl messages list
        brickowl messages list --folder outbox
        brickowl messages list --page 2 --table
        brickowl messages list --filter "is_unread:eq:true"
        brickowl messages list --include-history
    """
    folder_map = {"inbox": "received", "outbox": "sent"}
    browser_folder = folder_map.get(folder, "received")
    try:
        from ..browser import get_browser, BrickOwlBrowser
        browser = get_browser()

        try:
            raw = browser.list_messages(folder=browser_folder)
            data = raw if isinstance(raw, list) else []

            # Normalize each message
            data = [_normalize_list_msg(msg, browser_folder) for msg in data]

            # Client-side pagination (page size 25)
            page_size = 25
            start = (page - 1) * page_size
            end = start + page_size
            data = data[start:end]

            if filter:
                data = apply_filters(data, filter)
            data = apply_limit(data, limit)

            if include_history:
                shared_cache = {}
                conv_cache = {}
                for msg in data:
                    subject = msg.get("subject", "")
                    base = BrickOwlBrowser.normalize_subject(subject)
                    if not base:
                        continue
                    if base not in conv_cache:
                        mid = msg["message_id"]
                        detail = browser.get_message(mid)
                        detail["source"] = "browser"
                        shared_cache[("detail", mid)] = detail
                        conv_cache[base] = _build_conversation(
                            browser, subject, mid, detail, cache=shared_cache,
                        )
                    msg["message_history"] = conv_cache[base]

            if properties:
                data = apply_properties_filter(data, properties)
        finally:
            browser.close()

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(data, fields, fields)
            else:
                print_table(data, MSG_LIST_COLUMNS, MSG_LIST_HEADERS)
        else:
            print_json(data)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def messages_get(
    message_id: str = typer.Argument(..., help="Message ID"),
    folder: str = typer.Option("inbox", "--folder", help="Message folder (accepted for parity, ignored)"),
    include_history: bool = typer.Option(False, "--include-history", help="Include message history thread"),
    download_attachments: bool = typer.Option(False, "--download-attachments", help="Download attachments to local files"),
    output_dir: Optional[str] = typer.Option(None, "--output-dir", "-o", help="Directory for downloaded attachments (default: cwd)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get message details by ID (browser-based).

    Examples:
        brickowl messages get 12345678
        brickowl messages get 12345678 --table
        brickowl messages get 12345678 --include-history
    """
    try:
        from ..browser import get_browser
        browser = get_browser()

        try:
            data = browser.get_message(message_id)
            data["source"] = "browser"

            if include_history:
                subject = data.get("subject", "")
                if subject:
                    conversation = _build_conversation(
                        browser, subject, message_id, data,
                    )
                    data["message_history"] = conversation

            if download_attachments and data.get("attachments"):
                data["attachments"] = browser.download_attachments(
                    data["attachments"], output_dir=output_dir
                )
        finally:
            browser.close()

        msg = Message(**data)

        if table:
            msg_dict = msg.to_dict()
            rows = [{"field": k, "value": str(v)} for k, v in msg_dict.items() if v is not None]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(msg)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("send")
def messages_send(
    order_id: str = typer.Argument(..., help="Order ID to send message for"),
    body: str = typer.Argument(..., help="Message body"),
    subject: Optional[str] = typer.Option(None, "--subject", "-s", help="Message subject"),
    high_priority: bool = typer.Option(False, "--priority", help="Send as high priority (accepted for parity)"),
    send_copy: bool = typer.Option(False, "--copy", help="Send a copy to yourself (accepted for parity)"),
):
    """
    Send a message linked to an order (browser-based).

    Looks up the buyer username from the order, then sends a message.

    Examples:
        brickowl messages send 12345678 "Your order has been shipped!"
        brickowl messages send 12345678 "Hello" --subject "Question about order"
    """
    try:
        from ..browser import get_browser
        browser = get_browser()

        try:
            # Look up buyer user ID from order
            user_id = None
            try:
                from ..client import get_client
                client = get_client()
                order = client.get_order(order_id)
                user_id = getattr(order, "customer_user_id", None)
            except Exception:
                pass

            if not user_id:
                order_info = browser.get_order_info(order_id)
                user_id = order_info.get("customer_user_id")

            if not user_id:
                raise RuntimeError(f"Could not determine buyer user ID for order {order_id}")

            msg_subject = subject or f"Order #{order_id}"
            result = browser.send_order_message(order_id, user_id, subject=msg_subject, body=body)
        finally:
            browser.close()

        if result.get("success"):
            print_success(f"Message sent for order {order_id}")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("reply")
def messages_reply(
    message_id: str = typer.Argument(..., help="Message ID to reply to"),
    body: str = typer.Argument(..., help="Reply body"),
    subject: Optional[str] = typer.Option(None, "--subject", "-s", help="Override subject (accepted for parity)"),
    high_priority: bool = typer.Option(False, "--priority", help="Send as high priority (accepted for parity)"),
    send_copy: bool = typer.Option(False, "--copy", help="Send a copy to yourself (accepted for parity)"),
):
    """
    Reply to a message (browser-based).

    Examples:
        brickowl messages reply 12345678 "Thank you for your message!"
        brickowl messages reply 12345678 "Here is the tracking info" --copy
    """
    try:
        from ..browser import get_browser
        browser = get_browser()

        try:
            result = browser.reply_to_message(message_id, body)
        finally:
            browser.close()

        if result.get("success"):
            print_success(f"Reply sent for message {message_id}")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("mark-read")
def messages_mark_read(
    message_id: str = typer.Argument(..., help="The message ID"),
):
    """
    Mark a message as read (browser-based).

    Examples:
        brickowl messages mark-read MSG_ID
    """
    try:
        from ..browser import get_browser
        browser = get_browser()

        try:
            result = browser.mark_as_read(message_id)
        finally:
            browser.close()

        if result.get("success"):
            print_success(f"Message {message_id} marked as read")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("mark-unread")
def messages_mark_unread(
    message_id: str = typer.Argument(..., help="The message ID"),
):
    """
    Mark a message as unread (browser-based).

    Examples:
        brickowl messages mark-unread MSG_ID
    """
    try:
        from ..browser import get_browser
        browser = get_browser()

        try:
            result = browser.mark_as_unread(message_id)
        finally:
            browser.close()

        if result.get("success"):
            print_success(f"Message {message_id} marked as unread")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))
