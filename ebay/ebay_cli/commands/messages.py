"""Messages commands for eBay CLI.

Uses the eBay Trading API to query and manage buyer messages about listings.
"""
COMMAND_CREDENTIALS = {
    "list": ["oauth_authorization_code"],
    "get": ["oauth_authorization_code"],
    "reply": ["oauth_authorization_code"],
}

import sys
import typer
import xml.etree.ElementTree as ET
from typing import Optional, List
from pathlib import Path

from ..client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, handle_error, print_success, print_error, print_info
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError
from ..parsers import format_local_time
from ..properties import validate_and_filter_properties, PropertyValidationError

app = typer.Typer(help="Manage eBay seller messages")

# eBay XML namespace for Trading API parsing
NS = {"ebay": "urn:ebay:apis:eBLBaseComponents"}


# =============================================================================
# Helper Functions: XML Parsing
# =============================================================================


def _find_element(parent: Optional[ET.Element], path: str) -> Optional[ET.Element]:
    """Find child element, trying with namespace first then without."""
    if parent is None:
        return None
    el = parent.find(f"ebay:{path}", NS)
    if el is not None:
        return el
    return parent.find(path)


def _get_text(element: Optional[ET.Element], path: str, default: str = "") -> str:
    """Get text from an element, handling namespace and None."""
    if element is None:
        return default
    el = _find_element(element, path)
    return el.text if el is not None and el.text else default


def _parse_member_messages_xml(xml_content: str) -> tuple[list[dict], int]:
    """Parse GetMemberMessages XML response into list of messages."""
    try:
        root = ET.fromstring(xml_content)

        # Check for errors
        ack = _get_text(root, "Ack")
        if ack == "Failure":
            errors = _find_element(root, "Errors")
            if errors is not None:
                error_msg = _get_text(errors, "LongMessage") or _get_text(errors, "ShortMessage")
                raise ClientError(f"eBay API error: {error_msg}")
            raise ClientError("eBay API returned failure status")

        # Get pagination info
        pagination_result = _find_element(root, "PaginationResult")
        total_entries = int(_get_text(pagination_result, "TotalNumberOfEntries", "0"))

        # Parse messages
        messages = []
        member_messages_array = _find_element(root, "MemberMessages")
        if member_messages_array is not None:
            for msg_container in member_messages_array.findall("ebay:MemberMessage", NS):
                # Get basic message info
                message = {
                    "message_id": _get_text(msg_container, "MessageID"),
                    "sender_id": _get_text(msg_container, "Sender"),
                    "recipient_id": _get_text(msg_container, "RecipientID"),
                    "subject": _get_text(msg_container, "Subject"),
                    "question_body": _get_text(msg_container, "Body"),
                    "created_date": _get_text(msg_container, "CreationDate"),
                    "last_modified_date": _get_text(msg_container, "ReceiveDate"),
                    "message_status": _get_text(msg_container, "MessageStatus"),
                    "message_type": _get_text(msg_container, "MessageType"),
                }

                # Get item info if present
                item = _find_element(msg_container, "Item")
                if item is not None:
                    message["item_id"] = _get_text(item, "ItemID")
                    message["item_title"] = _get_text(item, "Title")

                # Get responses if present
                responses = []
                responses_array = _find_element(msg_container, "ResponseDetails")
                if responses_array is not None:
                    for response_container in responses_array.findall("ebay:MessageResponse", NS):
                        response = {
                            "response_body": _get_text(response_container, "ResponseText"),
                            "response_date": _get_text(response_container, "ResponseDate"),
                        }
                        responses.append(response)

                message["responses"] = responses

                messages.append(message)

        return messages, total_entries

    except ET.ParseError as e:
        raise ClientError(f"Failed to parse XML response: {e}")


def _parse_my_messages_xml(xml_content: str) -> list[dict]:
    """Parse GetMyMessages XML response into list of messages."""
    try:
        root = ET.fromstring(xml_content)

        # Check for errors
        ack = _get_text(root, "Ack")
        if ack == "Failure":
            errors = _find_element(root, "Errors")
            if errors is not None:
                error_msg = _get_text(errors, "LongMessage") or _get_text(errors, "ShortMessage")
                raise ClientError(f"eBay API error: {error_msg}")
            raise ClientError("eBay API returned failure status")

        # Parse messages
        messages = []
        messages_array = _find_element(root, "Messages")
        if messages_array is not None:
            for msg_container in messages_array.findall("ebay:Message", NS):
                message = {
                    "message_id": _get_text(msg_container, "MessageID"),
                    "external_message_id": _get_text(msg_container, "ExternalMessageID"),
                    "sender": _get_text(msg_container, "Sender"),
                    "recipient_user_id": _get_text(msg_container, "RecipientUserID"),
                    "subject": _get_text(msg_container, "Subject"),
                    "body": _get_text(msg_container, "Text"),
                    "created_date": _get_text(msg_container, "ReceiveDate"),
                    "flagged": _get_text(msg_container, "Flagged"),
                    "read": _get_text(msg_container, "Read"),
                    "folder_id": _get_text(msg_container, "Folder", "FolderID"),
                }

                # Get item info if present
                item_id = _get_text(msg_container, "ItemID")
                if item_id:
                    message["item_id"] = item_id

                messages.append(message)

        return messages

    except ET.ParseError as e:
        raise ClientError(f"Failed to parse XML response: {e}")


# =============================================================================
# Commands
# =============================================================================


@app.command("list")
def messages_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of messages to return (max 200)"),
    offset: int = typer.Option(0, "--offset", "-o", help="Offset for pagination"),
    start_date: Optional[str] = typer.Option(
        None,
        "--start-date",
        help="Filter messages created after this date (ISO format: 2025-01-01)"
    ),
    end_date: Optional[str] = typer.Option(
        None,
        "--end-date",
        help="Filter messages created before this date (ISO format: 2025-01-31)"
    ),
    filters: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter (field:op:value). Operators: eq, ne, gt, gte, lt, lte, in, nin, like, ilike, null, notnull"
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include in output"
    ),
):
    """
    List all eBay messages (inbox + buyer questions).

    Examples:
        ebay messages list
        ebay messages list --table
        ebay messages list --start-date 2025-01-01 --end-date 2025-01-31
        ebay messages list --limit 50 --offset 100
        ebay messages list --filter "sender:ilike:%john%"
    """
    try:
        client = get_client()

        # Convert dates to ISO format with time if needed
        from datetime import datetime, timedelta

        start_time = None
        end_time = None

        if start_date:
            # Add time component if not present
            if "T" not in start_date:
                start_time = f"{start_date}T00:00:00.000Z"
            else:
                start_time = start_date
        if end_date:
            # Add time component if not present
            if "T" not in end_date:
                end_time = f"{end_date}T23:59:59.999Z"
            else:
                end_time = end_date

        # If no date range provided, default to last 30 days
        if not start_time and not end_time:
            now = datetime.utcnow()
            start_time = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            end_time = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        all_messages = []

        # 1. Get inbox messages (GetMyMessages)
        try:
            headers_xml = client.get_my_messages_headers(
                folder_id="0",
                start_time=start_time,
                end_time=end_time,
            )

            # Parse headers to extract message IDs
            import xml.etree.ElementTree as ET
            root = ET.fromstring(headers_xml)

            # Check for errors
            ack = _get_text(root, "Ack")
            if ack != "Failure":
                # Extract message IDs from headers
                message_ids = []
                messages_container = _find_element(root, "Messages")
                if messages_container is not None:
                    for msg in messages_container.findall("ebay:Message", NS):
                        msg_id = _get_text(msg, "MessageID")
                        if msg_id:
                            message_ids.append(msg_id)

                # Fetch messages in batches of 10
                for i in range(0, len(message_ids), 10):
                    batch_ids = message_ids[i:i+10]
                    xml_response = client.get_my_messages(
                        message_ids=batch_ids,
                        entries_per_page=10,
                        page_number=1,
                    )
                    inbox_messages = _parse_my_messages_xml(xml_response)

                    # Normalize message format
                    for msg in inbox_messages:
                        msg["source"] = "inbox"
                        msg["message_type"] = "General"

                    all_messages.extend(inbox_messages)

        except ET.ParseError as e:
            print_error(f"Warning: Failed to parse inbox messages: {e}", file=sys.stderr)
        except ClientError as e:
            print_error(f"Warning: Failed to retrieve inbox messages: {e}", file=sys.stderr)

        # 2. Get buyer question messages (GetMemberMessages)
        try:
            xml_response = client.get_member_messages(
                item_id=None,
                sender_id=None,
                message_status=None,
                start_creation_time=start_time,
                end_creation_time=end_time,
                entries_per_page=200,
                page_number=1,
            )

            # Parse XML response
            member_messages, _ = _parse_member_messages_xml(xml_response)

            # Normalize message format
            for msg in member_messages:
                msg["source"] = "buyer_question"
                # Rename fields to match inbox format for consistency
                if "sender_id" in msg and "sender" not in msg:
                    msg["sender"] = msg["sender_id"]
                if "question_body" in msg and "body" not in msg:
                    msg["body"] = msg["question_body"]

            all_messages.extend(member_messages)

        except ClientError as e:
            print_error(f"Warning: Failed to retrieve buyer question messages: {e}", file=sys.stderr)

        # Sort all messages by created_date (newest first)
        all_messages.sort(key=lambda x: x.get("created_date", ""), reverse=True)

        # Validate and apply client-side filters if provided
        if filters:
            try:
                validated_filters = validate_filters(filters)
                all_messages = apply_filters(all_messages, validated_filters)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Apply offset and limit
        total_entries = len(all_messages)
        messages = all_messages[offset:offset+limit]

        # Handle properties filtering
        if properties:
            try:
                messages = validate_and_filter_properties(messages, properties)
            except PropertyValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Display output
        if table:
            # Unified table format
            table_data = []
            for msg in messages:
                subject = msg.get("subject", "")
                if len(subject) > 40:
                    subject = subject[:37] + "..."

                body_or_question = msg.get("body", "") or msg.get("question_body", "")
                if len(body_or_question) > 60:
                    body_or_question = body_or_question[:57] + "..."

                table_data.append({
                    "message_id": msg.get("message_id", ""),
                    "sender": msg.get("sender", ""),
                    "subject": subject,
                    "source": msg.get("source", ""),
                    "created": format_local_time(msg.get("created_date", "")),
                    "preview": body_or_question,
                })

            print_table(
                table_data,
                ["message_id", "sender", "subject", "source", "created", "preview"],
                ["Message ID", "Sender", "Subject", "Source", "Created", "Preview"]
            )
            print(f"\nTotal messages: {total_entries}", file=sys.stderr)
        else:
            # JSON output
            output = {
                "messages": messages,
                "total": total_entries,
                "limit": limit,
                "offset": offset,
            }
            print_json(output)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def messages_get(
    message_id: str = typer.Argument(..., help="Message ID or comma-separated list of IDs (max 10)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get specific message(s) by ID.

    Examples:
        ebay messages get 123456
        ebay messages get 123456,789012
        ebay messages get 123456 --table
    """
    try:
        client = get_client()

        # Parse message IDs
        message_ids = [mid.strip() for mid in message_id.split(",")]
        if len(message_ids) > 10:
            print_error("Maximum 10 message IDs allowed")
            raise typer.Exit(1)

        # Get messages from API
        xml_response = client.get_my_messages(message_ids=message_ids)

        # Parse XML response
        messages = _parse_my_messages_xml(xml_response)

        # Display output
        if table:
            for msg in messages:
                msg["created_date"] = format_local_time(msg.get("created_date", ""))
            print_table(
                messages,
                ["message_id", "sender", "subject", "created_date", "read", "flagged"],
                ["Message ID", "Sender", "Subject", "Created", "Read", "Flagged"]
            )
        else:
            print_json({"messages": messages})

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("reply")
def messages_reply(
    message_id: str = typer.Argument(..., help="Message ID to reply to"),
    body: Optional[str] = typer.Option(None, "--body", "-b", help="Reply body text (max 2000 chars)"),
    body_file: Optional[str] = typer.Option(None, "--body-file", help="Path to file containing body text, or '-' for stdin"),
    public: bool = typer.Option(False, "--public", help="Display reply publicly on listing"),
    email_copy: bool = typer.Option(False, "--email-copy", help="Send email copy to seller"),
):
    """
    Reply to a buyer question.

    Examples:
        ebay messages reply 123456 --body "Thank you for your question..."
        ebay messages reply 123456 --body-file response.txt
        echo "Thanks!" | ebay messages reply 123456 --body-file -
        ebay messages reply 123456 --body "Yes" --public --email-copy
    """
    try:
        client = get_client()

        # Validate that exactly one of body or body_file is provided
        if not body and not body_file:
            print_error("Must provide either --body or --body-file")
            raise typer.Exit(1)
        if body and body_file:
            print_error("Cannot use both --body and --body-file")
            raise typer.Exit(1)

        # Get body text
        reply_body = ""
        if body:
            reply_body = body
        elif body_file:
            if body_file == "-":
                # Read from stdin
                reply_body = sys.stdin.read()
            else:
                # Read from file
                file_path = Path(body_file)
                if not file_path.exists():
                    print_error(f"File not found: {body_file}")
                    raise typer.Exit(1)
                reply_body = file_path.read_text()

        # Validate body length
        if len(reply_body) > 2000:
            print_error(f"Message body exceeds 2000 characters (current: {len(reply_body)})")
            raise typer.Exit(1)

        # Get the original message to extract recipient_id and item_id
        print_info(f"Fetching message {message_id}...")
        xml_response = client.get_my_messages(message_ids=[message_id])
        messages = _parse_my_messages_xml(xml_response)

        if not messages:
            print_error(f"Message {message_id} not found")
            raise typer.Exit(1)

        original_message = messages[0]
        recipient_id = original_message.get("sender")
        item_id = original_message.get("item_id")

        if not recipient_id:
            print_error("Could not determine recipient from original message")
            raise typer.Exit(1)

        # Send reply
        print_info("Sending reply...")
        xml_response = client.add_member_message_reply(
            parent_message_id=message_id,
            recipient_id=recipient_id,
            body=reply_body,
            item_id=item_id,
            display_to_public=public,
            email_copy_to_sender=email_copy,
        )

        # Check for errors in response
        root = ET.fromstring(xml_response)
        ack = _get_text(root, "Ack")
        if ack == "Failure":
            errors = _find_element(root, "Errors")
            if errors is not None:
                error_msg = _get_text(errors, "LongMessage") or _get_text(errors, "ShortMessage")
                print_error(f"eBay API error: {error_msg}")

                # Check for rate limiting
                if "rate limit" in error_msg.lower():
                    print_info("Rate limit: AddMemberMessageRTQ allows 75 calls per 60 seconds")
                    print_info("Consider waiting 100 seconds before retrying")

                raise typer.Exit(1)
            print_error("Reply failed")
            raise typer.Exit(1)

        print_success(f"Reply sent to message {message_id}")

        # Show rate limit info
        print_info("Note: AddMemberMessageRTQ rate limit is 75 calls per 60 seconds")

    except Exception as e:
        raise typer.Exit(handle_error(e))
