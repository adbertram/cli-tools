"""Message commands for Bricklink CLI (browser-based)."""
COMMAND_CREDENTIALS = {
    "get": [
        "browser_session"
    ],
    "list": [
        "browser_session"
    ],
    "mark-read": [
        "browser_session"
    ],
    "mark-unread": [
        "browser_session"
    ],
    "reply": [
        "browser_session"
    ],
    "send": [
        "browser_session"
    ]
}

import typer
from typing import Optional, List
from datetime import datetime, timedelta, timezone
import re as _re

from ..display import print_detail, print_list
from cli_tools_shared.filters import apply_filters, apply_properties_filter, apply_limit
from cli_tools_shared.output import print_json, print_success, handle_error
from . import run_browser

app = typer.Typer(help="Manage messages (browser)", no_args_is_help=True)


# ==================== Default Table Columns ====================

MSG_LIST_COLUMNS = ["message_id", "subject", "username", "date", "is_unread"]
MSG_LIST_HEADERS = ["ID", "Subject", "User", "Date", "Unread"]


# ==================== Helpers ====================


def _parse_msg_date(date_str: str) -> datetime:
    """Parse a message date string, converting local time to UTC for consistent comparison."""
    if not date_str:
        return datetime.min
    s = _re.sub(r'\s+[A-Z]{2,4}$', '', date_str.strip())
    for fmt in ["%b %d, %Y %I:%M:%S %p", "%b %d, %Y %I:%M %p", "%b %d, %Y %H:%M:%S", "%b %d, %Y %H:%M", "%b %d, %Y"]:
        try:
            naive_local = datetime.strptime(s, fmt)
            # Assume system local timezone, convert to naive UTC
            aware_local = naive_local.astimezone()
            return aware_local.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            continue
    return datetime.min


def _extract_order_id(subject: str) -> Optional[str]:
    """Extract an order ID from a message subject.

    Handles: "Order #30380055", "Re: Order # 30380055", "Order 30672405",
    "Regarding BrickLink Order #30697215 (view order)"
    """
    m = _re.search(r'Order\s*#?\s*(\d+)', subject, _re.IGNORECASE)
    return m.group(1) if m else None



def _get_api_client():
    """Try to get a BricklinkClient, return None if OAuth not configured."""
    try:
        from ..client import get_client
        return get_client()
    except Exception:
        return None


def _normalize_api_message(api_msg: dict, order_id: str) -> dict:
    """Normalize a Bricklink API message dict to match the browser-scraped format.

    API fields: subject, body, from, to, dateSent
    Browser fields: message_id, subject, from_username, to_username, sent_date, body, order_id, source
    """
    return {
        "subject": api_msg.get("subject", ""),
        "body": api_msg.get("body", ""),
        "from_username": api_msg.get("from", ""),
        "to_username": api_msg.get("to", ""),
        "sent_date": api_msg.get("dateSent", ""),
        "order_id": str(order_id),
        "source": "api",
    }



def _build_conversation(browser, subject: str, source_id: str, source_detail: dict, cache: Optional[dict] = None, max_search_messages: int = 50) -> list:
    """Find all messages matching a subject by scanning browser inbox/outbox.

    Strategy:
      1. Scan inbox until we find the thread root (non-"Re:" subject match) → root_date.
      2. Scan outbox bounded by root_date.

    Args:
        browser: BricklinkBrowser instance.
        subject: Subject of the source message.
        source_id: Message ID of the source message (already fetched).
        source_detail: Full detail dict of the source message (to avoid re-fetch).
        cache: Optional shared cache dict for page listings, message details, and API
               results. Enables efficient reuse across multiple _build_conversation calls.
        max_search_messages: Maximum number of messages to scan across inbox and outbox
                             before failing. Default 50.

    Returns:
        List of message detail dicts sorted oldest-first.

    Raises:
        RuntimeError: If max_search_messages is reached without completing the search.
    """
    from ..browser import normalize_subject
    base = normalize_subject(subject)
    if not base:
        return [{k: v for k, v in source_detail.items() if k != "message_history"}] if source_detail else []

    if cache is None:
        cache = {}

    def _cached_list(page_num, folder):
        key = ("list", folder, page_num)
        if key not in cache:
            cache[key] = browser.list_messages(page_num=page_num, folder=folder)
        return cache[key]

    def _cached_detail(mid, folder):
        key = ("detail", mid)
        if key not in cache:
            cache[key] = browser.get_message(mid, folder=folder)
        return cache[key]

    def _cached_api_messages(oid):
        if "client" not in cache:
            cache["client"] = _get_api_client()
        client = cache["client"]
        if not client:
            return None
        key = ("api", oid)
        if key not in cache:
            try:
                cache[key] = client.get_order_messages(oid)
            except Exception:
                cache[key] = None
        return cache[key]

    # Pre-cache source detail
    cache[("detail", source_id)] = source_detail

    seen = set()
    conversation = []
    root_date = None
    order_id = _extract_order_id(subject)
    messages_scanned = 0

    # 1. Root date detection: API for order-linked threads, inbox non-"Re:" fallback
    if order_id:
        api_msgs = _cached_api_messages(order_id)
        if api_msgs:
            oldest_date_str = min(m.get("dateSent", "") for m in api_msgs)
            if oldest_date_str:
                dt = datetime.fromisoformat(oldest_date_str.replace("Z", "+00:00"))
                root_date = dt.astimezone(timezone.utc).replace(tzinfo=None)

    def _scan_folder(folder):
        """Scan a folder for messages matching the conversation subject/order."""
        nonlocal messages_scanned, root_date
        pg = 1
        while True:
            msgs = _cached_list(pg, folder)
            if not msgs:
                break
            for c in msgs:
                messages_scanned += 1
                if messages_scanned > max_search_messages:
                    raise RuntimeError(
                        f"Scanned {max_search_messages} messages without completing conversation search "
                        f"for subject '{subject}'. Increase --max-search-messages to scan more."
                    )
                mid = c["message_id"]
                if mid in seen:
                    continue
                raw_subject = c.get("subject", "")
                matched = normalize_subject(raw_subject) == base
                if not matched and order_id and root_date and _extract_order_id(raw_subject) == order_id:
                    msg_date = _parse_msg_date(c.get("date", ""))
                    matched = msg_date.date() >= (root_date - timedelta(days=1)).date()
                if matched:
                    seen.add(mid)
                    detail = _cached_detail(mid, folder)
                    entry = {k: v for k, v in detail.items() if k != "message_history"}
                    entry["source"] = "browser"
                    conversation.append(entry)
                    # Detect root date from first non-reply in inbox
                    if not root_date and folder == "i" and not raw_subject.strip().lower().startswith("re:"):
                        root_date = _parse_msg_date(detail.get("sent_date", c.get("date", "")))
            if root_date:
                page_oldest = _parse_msg_date(msgs[-1].get("date", ""))
                if page_oldest <= root_date - timedelta(days=1):
                    break
            pg += 1

    # 2. Inbox: match by subject, OR by order_id for messages >= root_date
    _scan_folder("i")
    # 3. Outbox: match by subject, OR by order_id for messages after root_date
    _scan_folder("o")

    # 4. Include source message if not already present
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
    order_id: Optional[str] = typer.Option(None, "--order-id", help="Get messages for a specific order (API-based, no browser needed)"),
    page: int = typer.Option(1, "--page", "-pg", help="Page number"),
    include_history: bool = typer.Option(False, "--include-history", help="Include message history thread for each message"),
    max_search_messages: int = typer.Option(50, "--max-search-messages", help="Max messages to scan when building history (default 50)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Max results"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Fields to include"),
):
    """
    List messages (browser-based, or API-based with --order-id).

    Examples:
        bricklink messages list
        bricklink messages list --folder outbox
        bricklink messages list --page 2 --table
        bricklink messages list --filter "is_unread:eq:true"
        bricklink messages list --include-history
        bricklink messages list --order-id 31235160
    """
    # API-based path: fetch messages for a specific order
    if order_id:
        try:
            client = _get_api_client()
            if not client:
                raise RuntimeError("OAuth credentials not configured — cannot use --order-id")
            raw_msgs = client.get_order_messages(order_id)
            data = [_normalize_api_message(m, order_id) for m in raw_msgs]

            if filter:
                data = apply_filters(data, filter)
            data = apply_limit(data, limit)
            if properties:
                data = apply_properties_filter(data, properties)

            print_list(data, table, properties, MSG_LIST_COLUMNS, MSG_LIST_HEADERS)
        except Exception as e:
            raise typer.Exit(handle_error(e))
        return

    folder_code = "o" if folder == "outbox" else "i"
    try:
        from ..browser import normalize_subject

        def _load_messages(browser):
            raw = browser.list_messages(page_num=page, folder=folder_code)
            data = raw if isinstance(raw, list) else []

            if filter:
                data = apply_filters(data, filter)
            data = apply_limit(data, limit)

            if include_history:
                shared_cache = {}  # shared across all _build_conversation calls
                conv_cache = {}  # normalized_subject -> conversation list
                for msg in data:
                    subject = msg.get("subject", "")
                    base = normalize_subject(subject)
                    if not base:
                        continue
                    if base not in conv_cache:
                        mid = msg["message_id"]
                        detail = browser.get_message(mid, folder=folder_code)
                        detail["source"] = "browser"
                        shared_cache[("detail", mid)] = detail
                        conv_cache[base] = _build_conversation(
                            browser, subject, mid, detail, cache=shared_cache,
                            max_search_messages=max_search_messages,
                        )
                    msg["message_history"] = conv_cache[base]

            if properties:
                data = apply_properties_filter(data, properties)
            return data

        data = run_browser(_load_messages)

        print_list(data, table, properties, MSG_LIST_COLUMNS, MSG_LIST_HEADERS)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def messages_get(
    message_id: str = typer.Argument(..., help="Message ID"),
    folder: str = typer.Option("i", "--folder", help="i=inbox, o=outbox"),
    include_history: bool = typer.Option(False, "--include-history", help="Include message history thread"),
    max_search_messages: int = typer.Option(50, "--max-search-messages", help="Max messages to scan when building history (default 50)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get message details by ID (browser-based).

    Examples:
        bricklink messages get 12345678
        bricklink messages get 12345678 --table
        bricklink messages get 12345678 --folder o
        bricklink messages get 12345678 --include-history
    """
    try:
        def _load_message(browser):
            data = browser.get_message(message_id, folder=folder)
            data["source"] = "browser"

            if include_history:
                subject = data.get("subject", "")
                if subject:
                    conversation = _build_conversation(
                        browser, subject, message_id, data,
                        max_search_messages=max_search_messages,
                    )
                    data["message_history"] = conversation
            return data

        data = run_browser(_load_message)
        print_detail(data, table)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("send")
def messages_send(
    arg1: Optional[str] = typer.Argument(None, help="Order ID (when sending to an order) or message body (when using --member)"),
    arg2: Optional[str] = typer.Argument(None, help="Message body (when order ID is provided as first argument)"),
    member: Optional[str] = typer.Option(None, "--member", "-m", help="Bricklink username to send message to (uses contact form)"),
    subject: Optional[str] = typer.Option(None, "--subject", "-s", help="Message subject"),
    high_priority: bool = typer.Option(False, "--priority", help="Send as high priority"),
    send_copy: bool = typer.Option(False, "--copy", help="Send a copy to yourself"),
):
    """
    Send a message to a member or linked to an order (browser-based).

    When sending to an order:  bricklink messages send ORDER_ID BODY
    When sending to a member:  bricklink messages send --member USERNAME BODY

    Examples:
        bricklink messages send 12345678 "Your order has been shipped!"
        bricklink messages send --member sydneybrickemp "Hello!" --subject "Re: Your message"
        bricklink messages send 12345678 "Hello" --subject "Question about order"
    """
    # Resolve positional arguments:
    # - Two args: arg1=order_id, arg2=body (classic usage)
    # - One arg + --member: arg1=body (member contact)
    # - One arg, no --member: arg1=order_id, missing body
    if arg1 and arg2:
        order_id = arg1
        body = arg2
    elif arg1 and member:
        order_id = None
        body = arg1
    elif arg1 and not member:
        raise typer.BadParameter("Missing message body. Usage: bricklink messages send ORDER_ID BODY")
    else:
        raise typer.BadParameter("Missing arguments. Provide ORDER_ID BODY, or --member USERNAME BODY.")

    try:
        if member and not order_id:
            result = run_browser(
                lambda browser: browser.contact_member(
                    username=member,
                    body=body,
                    subject=subject,
                    high_priority=high_priority,
                    send_copy=send_copy,
                )
            )
        else:
            result = run_browser(
                lambda browser: browser.send_message(
                    order_id=order_id,
                    body=body,
                    subject=subject,
                    high_priority=high_priority,
                    send_copy=send_copy,
                )
            )

        if result.get("success"):
            target = f"member {member}" if member and not order_id else f"order {order_id}"
            print_success(f"Message sent for {target}")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("reply")
def messages_reply(
    message_id: str = typer.Argument(..., help="Message ID to reply to"),
    body: str = typer.Argument(..., help="Reply body"),
    subject: Optional[str] = typer.Option(None, "--subject", "-s", help="Override subject"),
    high_priority: bool = typer.Option(False, "--priority", help="Send as high priority"),
    send_copy: bool = typer.Option(False, "--copy", help="Send a copy to yourself"),
):
    """
    Reply to a message (browser-based).

    Examples:
        bricklink messages reply 12345678 "Thank you for your message!"
        bricklink messages reply 12345678 "Here is the tracking info" --copy
    """
    try:
        result = run_browser(
            lambda browser: browser.reply_to_message(
                message_id=message_id,
                body=body,
                subject=subject,
                high_priority=high_priority,
                send_copy=send_copy,
            )
        )

        if result.get("success"):
            print_success(f"Reply sent for message {message_id}")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("mark-read")
def messages_mark_read(
    message_id: str = typer.Argument(..., help="Message ID"),
):
    """
    Mark a message as read (browser-based).

    Examples:
        bricklink messages mark-read 12345678
    """
    try:
        result = run_browser(lambda browser: browser.mark_as_read(message_id))

        if result.get("success"):
            print_success(f"Message {message_id} marked as read")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("mark-unread")
def messages_mark_unread(
    message_id: str = typer.Argument(..., help="Message ID"),
):
    """
    Mark a message as unread (browser-based).

    Examples:
        bricklink messages mark-unread 12345678
    """
    try:
        result = run_browser(lambda browser: browser.mark_as_unread(message_id))

        if result.get("success"):
            print_success(f"Message {message_id} marked as unread")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))
