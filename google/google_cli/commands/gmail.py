"""Gmail commands."""
COMMAND_CREDENTIALS = {
    "list": ["custom"],
    "get": ["custom"],
    "read": ["custom"],
    "search": ["custom"],
    "send": ["custom"],
    "archive": ["custom"],
    "download-attachment": ["custom"],
    "draft": ["custom"],
    "send-draft": ["custom"],
    "reply": ["custom"],
    "reply-all": ["custom"],
    "labels": ["custom"],
    "filters": ["custom"],
}

import typer
import base64
import mimetypes
import os
import re
import sys
import unicodedata
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import Optional, List
from pathlib import Path
from googleapiclient.errors import HttpError
from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error, print_success, print_error, print_info
from cli_tools_shared.filters import apply_filters
from ..filter_translator import translate_gmail_filters


def _resolve_wsl_path(file_path: Path) -> Path:
    """Convert WSL paths to Windows paths when running on Windows.

    When a WSL path like /mnt/c/Users/... is passed to the CLI running under
    Windows Python, pathlib creates a WindowsPath that resolves to \\mnt\\c\\...
    which doesn't exist. This converts /mnt/<drive>/... to <drive>:\\... so the
    file can be found.
    """
    if sys.platform != 'win32':
        return file_path

    # Get the original POSIX-style string representation
    # On Windows, Path('/mnt/c/foo') becomes \mnt\c\foo, so we need to check
    # the parts tuple which preserves the structure
    parts = file_path.parts

    # Check for WSL mount pattern: (\, mnt, <drive_letter>, ...)
    # On Windows, Path('/mnt/c/foo').parts == ('\\', 'mnt', 'c', 'foo')
    if (len(parts) >= 3
            and parts[0] == '\\'
            and parts[1] == 'mnt'
            and len(parts[2]) == 1
            and parts[2].isalpha()):
        drive = parts[2].upper()
        rest = parts[3:]
        windows_path = Path(f"{drive}:\\") / Path(*rest) if rest else Path(f"{drive}:\\")
        return windows_path

    return file_path


app = typer.Typer(help="Access Gmail messages")
labels_app = typer.Typer(help="Manage message labels")
app.add_typer(labels_app, name="labels")
filters_app = typer.Typer(help="Manage Gmail filters")
app.add_typer(filters_app, name="filters")

GMAIL_MESSAGE_PROPERTIES = {
    'id',
    'from',
    'to',
    'subject',
    'date',
    'threadId',
    'labelIds',
    'attachments',
}


def resolve_gmail_message_properties(properties: Optional[List[str]], include_body: bool = False) -> List[str]:
    if not properties:
        return ['id', 'from', 'subject', 'date']

    supported_properties = set(GMAIL_MESSAGE_PROPERTIES)
    if include_body:
        supported_properties.add('body')

    parsed_properties = [
        item.strip()
        for value in properties
        for item in value.split(',')
        if item.strip()
    ]
    invalid_properties = [
        item for item in parsed_properties if item not in supported_properties
    ]
    if invalid_properties:
        supported = ', '.join(sorted(supported_properties))
        raise ValueError(
            f"Unsupported Gmail message properties: {', '.join(invalid_properties)}. "
            f"Supported properties: {supported}"
        )

    return parsed_properties


def normalize_filename(name: str) -> str:
    """Normalize a filename for comparison.

    Handles Unicode normalization and common quote character variants
    to enable matching even when characters look similar but differ.
    """
    # First, apply NFC normalization to handle composed/decomposed forms
    normalized = unicodedata.normalize('NFC', name)

    # Map common visually-similar quote characters to ASCII equivalents
    # This handles cases where filenames contain typographic quotes
    quote_map = {
        '\u2018': "'",  # LEFT SINGLE QUOTATION MARK
        '\u2019': "'",  # RIGHT SINGLE QUOTATION MARK
        '\u201a': "'",  # SINGLE LOW-9 QUOTATION MARK
        '\u201b': "'",  # SINGLE HIGH-REVERSED-9 QUOTATION MARK
        '\u2032': "'",  # PRIME
        '\u2035': "'",  # REVERSED PRIME
        '\u0060': "'",  # GRAVE ACCENT
        '\u00b4': "'",  # ACUTE ACCENT
        '\u201c': '"',  # LEFT DOUBLE QUOTATION MARK
        '\u201d': '"',  # RIGHT DOUBLE QUOTATION MARK
        '\u201e': '"',  # DOUBLE LOW-9 QUOTATION MARK
        '\u201f': '"',  # DOUBLE HIGH-REVERSED-9 QUOTATION MARK
        '\u2033': '"',  # DOUBLE PRIME
        '\u2036': '"',  # REVERSED DOUBLE PRIME
        '\u00ab': '"',  # LEFT-POINTING DOUBLE ANGLE QUOTATION MARK
        '\u00bb': '"',  # RIGHT-POINTING DOUBLE ANGLE QUOTATION MARK
    }

    for unicode_char, ascii_char in quote_map.items():
        normalized = normalized.replace(unicode_char, ascii_char)

    return normalized


def strip_html(html: str) -> str:
    """Convert HTML to plain text.

    Removes style/script tags and content, strips HTML tags,
    decodes common entities, and normalizes whitespace.
    """
    import html as html_module

    # Remove style and script tags with their content
    text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)

    # Remove all other HTML tags
    text = re.sub(r'<[^>]+>', '', text)

    # Decode HTML entities
    text = html_module.unescape(text)

    # Normalize whitespace (collapse multiple spaces/newlines)
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def extract_attachments(payload: dict) -> list:
    """Extract attachment metadata from a Gmail message payload.

    Returns a list of attachment info dicts with filename, mimeType, size, and attachmentId.
    """
    attachments = []
    parts = payload.get('parts', [])

    def process_part(part):
        """Process a single part, checking for attachments."""
        filename = part.get('filename', '')
        body = part.get('body', {})
        attachment_id = body.get('attachmentId')

        # A part is an attachment if it has a filename and an attachmentId
        if filename and attachment_id:
            attachments.append({
                'filename': filename,
                'mimeType': part.get('mimeType', 'application/octet-stream'),
                'size': body.get('size', 0),
                'attachmentId': attachment_id,
            })

        # Check nested parts (for multipart messages)
        nested_parts = part.get('parts', [])
        for nested in nested_parts:
            process_part(nested)

    for part in parts:
        process_part(part)

    return attachments


def decode_body_from_payload(payload: dict) -> str:
    """Extract and decode the body from a Gmail message payload.

    Handles both simple messages and arbitrarily nested multipart messages.
    Prefers text/plain, falls back to text/html (stripped of tags).
    """

    # Recursively collect text/plain and text/html data from all nesting levels
    def _find_body_parts(part: dict, plain_parts: list, html_parts: list):
        mime_type = part.get('mimeType', '')
        data = part.get('body', {}).get('data', '')

        if mime_type == 'text/plain' and data:
            plain_parts.append(data)
        elif mime_type == 'text/html' and data:
            html_parts.append(data)

        # Recurse into nested parts (handles any depth of multipart nesting)
        for nested in part.get('parts', []):
            _find_body_parts(nested, plain_parts, html_parts)

    plain_parts: list = []
    html_parts: list = []
    _find_body_parts(payload, plain_parts, html_parts)

    # Prefer plain text over HTML
    data = (plain_parts[0] if plain_parts else
            html_parts[0] if html_parts else None)

    if data:
        try:
            decoded = base64.urlsafe_b64decode(data).decode('utf-8')
            # Strip HTML tags when falling back to HTML body
            if not plain_parts and html_parts:
                decoded = strip_html(decoded)
            return decoded
        except Exception:
            return ''

    return ''

@app.command("list")
def gmail_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of messages to list"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    label: Optional[str] = typer.Option(None, "--label", help="Filter by label (e.g., INBOX, SENT)"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Properties to include in output: id, from, to, subject, date, threadId, labelIds, attachments, body with --include-body"),
    include_body: bool = typer.Option(False, "--include-body", help="Include decoded message body text in each result"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """List Gmail messages."""
    try:
        props_to_include = resolve_gmail_message_properties(properties, include_body=include_body)
        client = get_client(profile=profile)
        service = client.get_gmail_service()

        query_params = {
            'userId': 'me',
            'maxResults': limit,
        }

        if label:
            query_params['labelIds'] = [label]

        # Build query string from filters (supports both standard and native formats)
        if filter:
            query_params['q'] = translate_gmail_filters(filter)

        results = service.users().messages().list(**query_params).execute()
        messages = results.get('messages', [])

        if not messages:
            print_json([])
            return

        # Get details for each message
        detailed_messages = []
        for msg in messages:
            msg_detail = service.users().messages().get(
                userId='me',
                id=msg['id'],
                format='full'
            ).execute()

            payload = msg_detail.get('payload', {})
            headers = {h['name']: h['value'] for h in payload.get('headers', [])}

            # Extract attachments
            attachments = extract_attachments(payload)

            full_msg = {
                'id': msg_detail['id'],
                'from': headers.get('From', ''),
                'to': headers.get('To', ''),
                'subject': headers.get('Subject', ''),
                'date': headers.get('Date', ''),
                'threadId': msg_detail.get('threadId', ''),
                'labelIds': msg_detail.get('labelIds', []),
            }

            # Add attachments if present
            if attachments:
                full_msg['attachments'] = attachments

            if include_body:
                full_msg['body'] = decode_body_from_payload(payload)

            # Filter to requested properties
            if properties:
                allowed_properties = set(props_to_include)
                if include_body:
                    allowed_properties.add('body')
                full_msg = {k: v for k, v in full_msg.items() if k in allowed_properties}

            detailed_messages.append(full_msg)

        if table:
            table_cols = [p for p in ['subject', 'from', 'date'] if p in props_to_include or not properties]
            if include_body:
                table_cols.append('body')
            table_headers = [p.title() for p in table_cols]
            print_table(detailed_messages, table_cols, table_headers)
        else:
            print_json(detailed_messages)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))

@app.command("get")
def gmail_get(
    message_id: str = typer.Argument(..., help="Message ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    raw: bool = typer.Option(False, "--raw", "-r", help="Return raw API response without processing"),
    include_body: bool = typer.Option(False, "--include-body", help="Include decoded message body text in the result"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Get a specific message."""
    try:
        client = get_client(profile=profile)
        service = client.get_gmail_service()

        message = service.users().messages().get(
            userId='me',
            id=message_id,
            format='full'
        ).execute()

        if raw:
            print_json(message)
            return

        payload = message.get('payload', {})
        headers = {h['name']: h['value'] for h in payload.get('headers', [])}

        # Decode the body
        body = decode_body_from_payload(payload)

        # Extract attachments
        attachments = extract_attachments(payload)

        if table:
            data = [{
                'id': message['id'],
                'from': headers.get('From', ''),
                'subject': headers.get('Subject', ''),
                'date': headers.get('Date', ''),
            }]
            table_cols = ['subject', 'from', 'date']
            table_headers = ['Subject', 'From', 'Date']
            if include_body:
                data[0]['body'] = body
                table_cols.append('body')
                table_headers.append('Body')
            print_table(data, table_cols, table_headers)
        else:
            result = {
                'id': message['id'],
                'threadId': message.get('threadId', ''),
                'labelIds': message.get('labelIds', []),
                'from': headers.get('From', ''),
                'to': headers.get('To', ''),
                'cc': headers.get('Cc', ''),
                'subject': headers.get('Subject', ''),
                'date': headers.get('Date', ''),
                'body': body,
            }
            # Remove empty cc field
            if not result['cc']:
                del result['cc']
            # Add attachments if present
            if attachments:
                result['attachments'] = attachments
            print_json(result)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))

@app.command("read")
def gmail_read(
    message_id: str = typer.Argument(..., help="Message ID"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Read message content (text only)."""
    try:
        client = get_client(profile=profile)
        service = client.get_gmail_service()

        message = service.users().messages().get(
            userId='me',
            id=message_id,
            format='full'
        ).execute()

        payload = message.get('payload', {})
        headers = {h['name']: h['value'] for h in payload.get('headers', [])}

        # Reuse shared decoder which handles nested parts and HTML fallback
        body = decode_body_from_payload(payload)

        result = {
            'id': message['id'],
            'from': headers.get('From', ''),
            'to': headers.get('To', ''),
            'subject': headers.get('Subject', ''),
            'date': headers.get('Date', ''),
            'body': body
        }

        print_json(result)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))

@app.command("search")
def gmail_search(
    query: str = typer.Argument(..., help="Search query (Gmail search syntax)"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Properties to include in output: id, from, to, subject, date, threadId, labelIds, attachments"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Search Gmail messages."""
    try:
        props_to_include = resolve_gmail_message_properties(properties)
        client = get_client(profile=profile)
        service = client.get_gmail_service()

        results = service.users().messages().list(
            userId='me',
            q=query,
            maxResults=limit
        ).execute()

        messages = results.get('messages', [])

        if not messages:
            print_json([])
            return

        # Get details for each message
        detailed_messages = []
        for msg in messages:
            msg_detail = service.users().messages().get(
                userId='me',
                id=msg['id'],
                format='full'
            ).execute()

            payload = msg_detail.get('payload', {})
            headers = {h['name']: h['value'] for h in payload.get('headers', [])}

            # Extract attachments
            attachments = extract_attachments(payload)

            full_msg = {
                'id': msg_detail['id'],
                'from': headers.get('From', ''),
                'to': headers.get('To', ''),
                'subject': headers.get('Subject', ''),
                'date': headers.get('Date', ''),
                'threadId': msg_detail.get('threadId', ''),
                'labelIds': msg_detail.get('labelIds', []),
            }

            # Add attachments if present
            if attachments:
                full_msg['attachments'] = attachments

            # Filter to requested properties
            if properties:
                full_msg = {k: v for k, v in full_msg.items() if k in props_to_include}

            detailed_messages.append(full_msg)

        if table:
            table_cols = [p for p in ['subject', 'from', 'date'] if p in props_to_include or not properties]
            table_headers = [p.title() for p in table_cols]
            print_table(detailed_messages, table_cols, table_headers)
        else:
            print_json(detailed_messages)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("send")
def gmail_send(
    to: str = typer.Option(..., "--to", help="Recipient email address"),
    subject: str = typer.Option(..., "--subject", "-s", help="Email subject"),
    body: str = typer.Option(..., "--body", "-b", help="Email body (plain text)"),
    cc: Optional[str] = typer.Option(None, "--cc", help="CC recipients (comma-separated)"),
    bcc: Optional[str] = typer.Option(None, "--bcc", help="BCC recipients (comma-separated)"),
    attach: Optional[List[Path]] = typer.Option(None, "--attach", "-a", help="File(s) to attach (can be used multiple times)"),
    confirm: bool = typer.Option(False, "--confirm", help="Actually send the email. Without this flag, only previews the message."),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Send an email message with optional attachments.

    By default, shows a preview of the message without sending.
    Use --confirm to actually send the email.
    """
    try:
        client = get_client(profile=profile)
        service = client.get_gmail_service()

        # Validate attachments exist
        attachments = []
        if attach:
            for file_path in attach:
                file_path = _resolve_wsl_path(file_path)
                if not file_path.exists():
                    print_error(f"Attachment not found: {file_path}")
                    raise typer.Exit(1)
                if not file_path.is_file():
                    print_error(f"Not a file: {file_path}")
                    raise typer.Exit(1)
                attachments.append(file_path)

        # Create the email message
        if attachments:
            # Use multipart for emails with attachments
            message = MIMEMultipart()
            message['to'] = to
            message['subject'] = subject
            if cc:
                message['cc'] = cc
            if bcc:
                message['bcc'] = bcc

            # Attach the body
            message.attach(MIMEText(body, 'plain'))

            # Attach files
            for file_path in attachments:
                # Guess the MIME type
                mime_type, _ = mimetypes.guess_type(str(file_path))
                if mime_type is None:
                    mime_type = 'application/octet-stream'

                main_type, sub_type = mime_type.split('/', 1)

                with open(file_path, 'rb') as f:
                    file_data = f.read()

                attachment = MIMEBase(main_type, sub_type)
                attachment.set_payload(file_data)
                encoders.encode_base64(attachment)
                attachment.add_header(
                    'Content-Disposition',
                    'attachment',
                    filename=file_path.name
                )
                message.attach(attachment)
        else:
            # Simple text message without attachments
            message = MIMEText(body)
            message['to'] = to
            message['subject'] = subject
            if cc:
                message['cc'] = cc
            if bcc:
                message['bcc'] = bcc

        # Encode the message
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')

        attachment_info = [str(a) for a in attachments] if attachments else []

        # If --confirm not provided, show preview only
        if not confirm:
            preview = {
                'to': to,
                'subject': subject,
                'body': body,
                'status': 'preview (not sent)'
            }
            if cc:
                preview['cc'] = cc
            if bcc:
                preview['bcc'] = bcc
            if attachment_info:
                preview['attachments'] = attachment_info

            print_json(preview)
            print_info("Use --confirm to actually send this email. The --confirm flag must be approved by a human, not AI.")
            return

        # Send the message
        sent_message = service.users().messages().send(
            userId='me',
            body={'raw': raw_message}
        ).execute()

        print_success(f"Email sent successfully. Message ID: {sent_message['id']}")
        print_json({
            'id': sent_message['id'],
            'to': to,
            'subject': subject,
            'attachments': attachment_info,
            'status': 'sent'
        })

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("archive")
def gmail_archive(
    message_ids: List[str] = typer.Argument(..., help="Message ID(s) to archive"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Archive messages by removing them from inbox."""
    try:
        client = get_client(profile=profile)
        service = client.get_gmail_service()

        archived_count = 0
        for message_id in message_ids:
            service.users().messages().modify(
                userId='me',
                id=message_id,
                body={'removeLabelIds': ['INBOX']}
            ).execute()
            archived_count += 1

        print_success(f"Archived {archived_count} message(s)")

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("download-attachment")
def gmail_download_attachment(
    message_id: str = typer.Argument(..., help="Message ID containing the attachment"),
    filename: Optional[str] = typer.Option(None, "--filename", "-f", help="Attachment filename to download"),
    attachment_id: Optional[str] = typer.Option(None, "--attachment-id", "-a", help="Attachment ID to download"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output path (defaults to current directory with original filename)"),
    all_attachments: bool = typer.Option(False, "--all", help="Download all attachments from the message"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Download attachment(s) from a message.

    Specify either --filename, --attachment-id, or --all to select which attachment(s) to download.
    """
    if not filename and not attachment_id and not all_attachments:
        print_error("Must specify --filename, --attachment-id, or --all")
        raise typer.Exit(1)

    try:
        client = get_client(profile=profile)
        service = client.get_gmail_service()

        # Get the message to find attachment metadata
        message = service.users().messages().get(
            userId='me',
            id=message_id,
            format='full'
        ).execute()

        payload = message.get('payload', {})
        attachments = extract_attachments(payload)

        if not attachments:
            print_error("No attachments found in this message")
            raise typer.Exit(1)

        # Determine which attachments to download
        to_download = []

        if all_attachments:
            to_download = attachments
        elif attachment_id:
            for att in attachments:
                if att['attachmentId'] == attachment_id:
                    to_download.append(att)
                    break
            if not to_download:
                print_error(f"Attachment ID not found: {attachment_id}")
                raise typer.Exit(1)
        elif filename:
            # Normalize the user-provided filename for comparison
            normalized_target = normalize_filename(filename)
            for att in attachments:
                # Compare normalized versions to handle Unicode variants
                if normalize_filename(att['filename']) == normalized_target:
                    to_download.append(att)
                    break
            if not to_download:
                print_error(f"Attachment not found: {filename}")
                print_info(f"Available attachments: {', '.join(a['filename'] for a in attachments)}")
                raise typer.Exit(1)

        # Download each attachment
        downloaded = []
        for att in to_download:
            # Fetch the attachment data
            attachment_data = service.users().messages().attachments().get(
                userId='me',
                messageId=message_id,
                id=att['attachmentId']
            ).execute()

            # Decode the data
            data = base64.urlsafe_b64decode(attachment_data['data'])

            # Determine output path
            if output and not all_attachments:
                # Single file with explicit output path
                out_path = output
            elif output and all_attachments:
                # Multiple files to a directory
                out_path = output / att['filename']
                output.mkdir(parents=True, exist_ok=True)
            else:
                # Default to current directory
                out_path = Path(att['filename'])

            # Write the file
            with open(out_path, 'wb') as f:
                f.write(data)

            downloaded.append({
                'filename': att['filename'],
                'path': str(out_path),
                'size': len(data),
            })

        print_success(f"Downloaded {len(downloaded)} attachment(s)")
        print_json(downloaded)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("draft")
def gmail_draft(
    to: str = typer.Option(..., "--to", help="Recipient email address"),
    subject: str = typer.Option(..., "--subject", "-s", help="Email subject"),
    body: str = typer.Option(..., "--body", "-b", help="Email body (plain text)"),
    cc: Optional[str] = typer.Option(None, "--cc", help="CC recipients (comma-separated)"),
    bcc: Optional[str] = typer.Option(None, "--bcc", help="BCC recipients (comma-separated)"),
    attach: Optional[List[Path]] = typer.Option(None, "--attach", "-a", help="File(s) to attach (can be used multiple times)"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Create an email draft with optional attachments."""
    try:
        client = get_client(profile=profile)
        service = client.get_gmail_service()

        # Validate attachments exist
        attachments = []
        if attach:
            for file_path in attach:
                file_path = _resolve_wsl_path(file_path)
                if not file_path.exists():
                    print_error(f"Attachment not found: {file_path}")
                    raise typer.Exit(1)
                if not file_path.is_file():
                    print_error(f"Not a file: {file_path}")
                    raise typer.Exit(1)
                attachments.append(file_path)

        # Create the email message
        if attachments:
            # Use multipart for emails with attachments
            message = MIMEMultipart()
            message['to'] = to
            message['subject'] = subject
            if cc:
                message['cc'] = cc
            if bcc:
                message['bcc'] = bcc

            # Attach the body
            message.attach(MIMEText(body, 'plain'))

            # Attach files
            for file_path in attachments:
                # Guess the MIME type
                mime_type, _ = mimetypes.guess_type(str(file_path))
                if mime_type is None:
                    mime_type = 'application/octet-stream'

                main_type, sub_type = mime_type.split('/', 1)

                with open(file_path, 'rb') as f:
                    file_data = f.read()

                attachment = MIMEBase(main_type, sub_type)
                attachment.set_payload(file_data)
                encoders.encode_base64(attachment)
                attachment.add_header(
                    'Content-Disposition',
                    'attachment',
                    filename=file_path.name
                )
                message.attach(attachment)
        else:
            # Simple text message without attachments
            message = MIMEText(body)
            message['to'] = to
            message['subject'] = subject
            if cc:
                message['cc'] = cc
            if bcc:
                message['bcc'] = bcc

        # Encode the message
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')

        # Create the draft
        draft = service.users().drafts().create(
            userId='me',
            body={'message': {'raw': raw_message}}
        ).execute()

        attachment_info = [str(a) for a in attachments] if attachments else []
        print_success(f"Draft created successfully. Draft ID: {draft['id']}")
        print_json({
            'id': draft['id'],
            'message_id': draft['message']['id'],
            'to': to,
            'subject': subject,
            'attachments': attachment_info,
            'status': 'draft'
        })

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("send-draft")
def gmail_send_draft(
    draft_id: str = typer.Argument(..., help="Gmail draft ID (returned by `gmail draft`)"),
    confirm: bool = typer.Option(False, "--confirm", help="Actually send the draft. Without this flag, only previews the draft."),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Send an existing Gmail draft.

    By default, prints the draft metadata without sending.
    Use --confirm to actually send the draft.
    """
    try:
        client = get_client(profile=profile)
        service = client.get_gmail_service()

        draft = service.users().drafts().get(
            userId='me',
            id=draft_id,
            format='metadata',
        ).execute()

        headers = {h['name'].lower(): h['value'] for h in draft['message'].get('payload', {}).get('headers', [])}

        if not confirm:
            preview = {
                'draft_id': draft_id,
                'to': headers.get('to', ''),
                'subject': headers.get('subject', ''),
                'status': 'preview (not sent)',
            }
            if 'cc' in headers:
                preview['cc'] = headers['cc']
            if 'bcc' in headers:
                preview['bcc'] = headers['bcc']
            print_json(preview)
            print_info("Use --confirm to actually send this draft. The --confirm flag must be approved by a human, not AI.")
            return

        sent = service.users().drafts().send(
            userId='me',
            body={'id': draft_id},
        ).execute()

        print_success(f"Draft sent successfully. Message ID: {sent['id']}")
        print_json({
            'id': sent['id'],
            'thread_id': sent.get('threadId', ''),
            'draft_id': draft_id,
            'to': headers.get('to', ''),
            'subject': headers.get('subject', ''),
            'status': 'sent',
        })

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


def extract_email(header_value: str) -> str:
    """Extract email address from 'Name <email>' format."""
    match = re.search(r'<([^>]+)>', header_value)
    return match.group(1) if match else header_value.strip()


def get_current_user_email(service) -> str:
    """Get the authenticated user's email address."""
    profile = service.users().getProfile(userId='me').execute()
    return profile['emailAddress']


@app.command("reply")
def gmail_reply(
    message_id: str = typer.Argument(..., help="Message ID to reply to"),
    body: str = typer.Option(..., "--body", "-b", help="Reply body (plain text)"),
    cc: Optional[str] = typer.Option(None, "--cc", help="Additional CC recipients (comma-separated)"),
    bcc: Optional[str] = typer.Option(None, "--bcc", help="BCC recipients (comma-separated)"),
    attach: Optional[List[Path]] = typer.Option(None, "--attach", "-a", help="File(s) to attach (can be used multiple times)"),
    confirm: bool = typer.Option(False, "--confirm", help="Actually send the reply. Without this flag, only previews the message."),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Reply to a message (sender only).

    By default, shows a preview of the reply without sending.
    Use --confirm to actually send the reply.
    """
    try:
        client = get_client(profile=profile)
        service = client.get_gmail_service()

        # Fetch original message to get headers for reply
        original = service.users().messages().get(
            userId='me',
            id=message_id,
            format='metadata',
            metadataHeaders=['From', 'To', 'Cc', 'Subject', 'Message-ID', 'References']
        ).execute()

        headers = {h['name']: h['value'] for h in original.get('payload', {}).get('headers', [])}
        thread_id = original.get('threadId')

        # Build reply headers
        reply_to = headers.get('From', '')
        original_subject = headers.get('Subject', '')
        reply_subject = original_subject if original_subject.lower().startswith('re:') else f"Re: {original_subject}"
        original_message_id = headers.get('Message-ID', '')
        original_references = headers.get('References', '')

        # Build References header for threading
        if original_references:
            references = f"{original_references} {original_message_id}"
        else:
            references = original_message_id

        # Validate attachments exist
        attachments = []
        if attach:
            for file_path in attach:
                file_path = _resolve_wsl_path(file_path)
                if not file_path.exists():
                    print_error(f"Attachment not found: {file_path}")
                    raise typer.Exit(1)
                if not file_path.is_file():
                    print_error(f"Not a file: {file_path}")
                    raise typer.Exit(1)
                attachments.append(file_path)

        # Create the email message
        if attachments:
            message = MIMEMultipart()
            message['to'] = reply_to
            message['subject'] = reply_subject
            if original_message_id:
                message['In-Reply-To'] = original_message_id
            if references:
                message['References'] = references
            if cc:
                message['cc'] = cc
            if bcc:
                message['bcc'] = bcc

            message.attach(MIMEText(body, 'plain'))

            for file_path in attachments:
                mime_type, _ = mimetypes.guess_type(str(file_path))
                if mime_type is None:
                    mime_type = 'application/octet-stream'

                main_type, sub_type = mime_type.split('/', 1)

                with open(file_path, 'rb') as f:
                    file_data = f.read()

                attachment = MIMEBase(main_type, sub_type)
                attachment.set_payload(file_data)
                encoders.encode_base64(attachment)
                attachment.add_header(
                    'Content-Disposition',
                    'attachment',
                    filename=file_path.name
                )
                message.attach(attachment)
        else:
            message = MIMEText(body)
            message['to'] = reply_to
            message['subject'] = reply_subject
            if original_message_id:
                message['In-Reply-To'] = original_message_id
            if references:
                message['References'] = references
            if cc:
                message['cc'] = cc
            if bcc:
                message['bcc'] = bcc

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        attachment_info = [str(a) for a in attachments] if attachments else []

        # Preview mode if --confirm not provided
        if not confirm:
            preview = {
                'to': reply_to,
                'subject': reply_subject,
                'body': body,
                'in_reply_to': message_id,
                'thread_id': thread_id,
                'status': 'preview (not sent)'
            }
            if cc:
                preview['cc'] = cc
            if bcc:
                preview['bcc'] = bcc
            if attachment_info:
                preview['attachments'] = attachment_info

            print_json(preview)
            print_info("Use --confirm to actually send this reply. The --confirm flag must be approved by a human, not AI.")
            return

        # Send the reply in the same thread
        sent_message = service.users().messages().send(
            userId='me',
            body={'raw': raw_message, 'threadId': thread_id}
        ).execute()

        print_success(f"Reply sent successfully. Message ID: {sent_message['id']}")
        print_json({
            'id': sent_message['id'],
            'to': reply_to,
            'subject': reply_subject,
            'thread_id': thread_id,
            'attachments': attachment_info,
            'status': 'sent'
        })

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("reply-all")
def gmail_reply_all(
    message_id: str = typer.Argument(..., help="Message ID to reply to"),
    body: str = typer.Option(..., "--body", "-b", help="Reply body (plain text)"),
    cc: Optional[str] = typer.Option(None, "--cc", help="Additional CC recipients (comma-separated)"),
    bcc: Optional[str] = typer.Option(None, "--bcc", help="BCC recipients (comma-separated)"),
    attach: Optional[List[Path]] = typer.Option(None, "--attach", "-a", help="File(s) to attach (can be used multiple times)"),
    confirm: bool = typer.Option(False, "--confirm", help="Actually send the reply. Without this flag, only previews the message."),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Reply to all recipients of a message.

    By default, shows a preview of the reply without sending.
    Use --confirm to actually send the reply.
    """
    try:
        client = get_client(profile=profile)
        service = client.get_gmail_service()

        # Get current user's email to exclude from recipients
        current_user_email = get_current_user_email(service).lower()

        # Fetch original message to get headers for reply
        original = service.users().messages().get(
            userId='me',
            id=message_id,
            format='metadata',
            metadataHeaders=['From', 'To', 'Cc', 'Subject', 'Message-ID', 'References']
        ).execute()

        headers = {h['name']: h['value'] for h in original.get('payload', {}).get('headers', [])}
        thread_id = original.get('threadId')

        # Build reply headers
        original_from = headers.get('From', '')
        original_to = headers.get('To', '')
        original_cc = headers.get('Cc', '')
        original_subject = headers.get('Subject', '')
        reply_subject = original_subject if original_subject.lower().startswith('re:') else f"Re: {original_subject}"
        original_message_id = headers.get('Message-ID', '')
        original_references = headers.get('References', '')

        # Build To: original sender + original To recipients (minus self)
        to_recipients = []
        to_recipients.append(original_from)

        if original_to:
            for addr in original_to.split(','):
                addr = addr.strip()
                if addr and extract_email(addr).lower() != current_user_email:
                    to_recipients.append(addr)

        reply_to = ', '.join(to_recipients)

        # Build Cc: original Cc recipients (minus self) + any additional --cc
        cc_recipients = []
        if original_cc:
            for addr in original_cc.split(','):
                addr = addr.strip()
                if addr and extract_email(addr).lower() != current_user_email:
                    cc_recipients.append(addr)

        if cc:
            for addr in cc.split(','):
                addr = addr.strip()
                if addr:
                    cc_recipients.append(addr)

        reply_cc = ', '.join(cc_recipients) if cc_recipients else None

        # Build References header for threading
        if original_references:
            references = f"{original_references} {original_message_id}"
        else:
            references = original_message_id

        # Validate attachments exist
        attachments = []
        if attach:
            for file_path in attach:
                file_path = _resolve_wsl_path(file_path)
                if not file_path.exists():
                    print_error(f"Attachment not found: {file_path}")
                    raise typer.Exit(1)
                if not file_path.is_file():
                    print_error(f"Not a file: {file_path}")
                    raise typer.Exit(1)
                attachments.append(file_path)

        # Create the email message
        if attachments:
            message = MIMEMultipart()
            message['to'] = reply_to
            message['subject'] = reply_subject
            if original_message_id:
                message['In-Reply-To'] = original_message_id
            if references:
                message['References'] = references
            if reply_cc:
                message['cc'] = reply_cc
            if bcc:
                message['bcc'] = bcc

            message.attach(MIMEText(body, 'plain'))

            for file_path in attachments:
                mime_type, _ = mimetypes.guess_type(str(file_path))
                if mime_type is None:
                    mime_type = 'application/octet-stream'

                main_type, sub_type = mime_type.split('/', 1)

                with open(file_path, 'rb') as f:
                    file_data = f.read()

                attachment = MIMEBase(main_type, sub_type)
                attachment.set_payload(file_data)
                encoders.encode_base64(attachment)
                attachment.add_header(
                    'Content-Disposition',
                    'attachment',
                    filename=file_path.name
                )
                message.attach(attachment)
        else:
            message = MIMEText(body)
            message['to'] = reply_to
            message['subject'] = reply_subject
            if original_message_id:
                message['In-Reply-To'] = original_message_id
            if references:
                message['References'] = references
            if reply_cc:
                message['cc'] = reply_cc
            if bcc:
                message['bcc'] = bcc

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        attachment_info = [str(a) for a in attachments] if attachments else []

        # Preview mode if --confirm not provided
        if not confirm:
            preview = {
                'to': reply_to,
                'subject': reply_subject,
                'body': body,
                'in_reply_to': message_id,
                'thread_id': thread_id,
                'status': 'preview (not sent)'
            }
            if reply_cc:
                preview['cc'] = reply_cc
            if bcc:
                preview['bcc'] = bcc
            if attachment_info:
                preview['attachments'] = attachment_info

            print_json(preview)
            print_info("Use --confirm to actually send this reply. The --confirm flag must be approved by a human, not AI.")
            return

        # Send the reply in the same thread
        sent_message = service.users().messages().send(
            userId='me',
            body={'raw': raw_message, 'threadId': thread_id}
        ).execute()

        print_success(f"Reply sent successfully. Message ID: {sent_message['id']}")
        print_json({
            'id': sent_message['id'],
            'to': reply_to,
            'cc': reply_cc,
            'subject': reply_subject,
            'thread_id': thread_id,
            'attachments': attachment_info,
            'status': 'sent'
        })

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@labels_app.command("list")
def labels_list(
    message_id: str = typer.Argument(..., help="Message ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of labels to list"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Properties to include in output"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """List labels on a message."""
    try:
        client = get_client(profile=profile)
        service = client.get_gmail_service()

        message = service.users().messages().get(
            userId='me',
            id=message_id,
            format='minimal'
        ).execute()

        label_ids = message.get('labelIds', [])

        # Get label details for human-readable names
        labels_response = service.users().labels().list(userId='me').execute()
        all_labels = {l['id']: l['name'] for l in labels_response.get('labels', [])}

        labels = [{'id': lid, 'name': all_labels.get(lid, lid)} for lid in label_ids]

        if filter:
            labels = apply_filters(labels, filter)
        labels = labels[:limit]
        if properties:
            labels = [{k: v for k, v in label_item.items() if k in properties} for label_item in labels]

        if table:
            table_cols = properties[:3] if properties else ["id", "name"]
            print_table(labels, table_cols, table_cols)
        else:
            print_json({
                'message_id': message_id,
                'labels': labels
            })

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@labels_app.command("get")
def labels_get(
    label_id: str = typer.Argument(..., help="Label ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Get label details by ID."""
    try:
        client = get_client(profile=profile)
        service = client.get_gmail_service()

        label = service.users().labels().get(
            userId='me',
            id=label_id
        ).execute()

        if table:
            data = [{
                'id': label.get('id'),
                'name': label.get('name'),
                'type': label.get('type'),
            }]
            print_table(data, ['name', 'id', 'type'], ['Name', 'ID', 'Type'])
        else:
            print_json(label)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@labels_app.command("add")
def labels_add(
    message_id: str = typer.Argument(..., help="Message ID"),
    label: List[str] = typer.Option(..., "--label", "-l", help="Label ID(s) to add"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Add labels to a message."""
    try:
        client = get_client(profile=profile)
        service = client.get_gmail_service()

        service.users().messages().modify(
            userId='me',
            id=message_id,
            body={'addLabelIds': label}
        ).execute()

        print_success(f"Added {len(label)} label(s) to message {message_id}")
        print_json({'message_id': message_id, 'added_labels': label})

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@labels_app.command("remove")
def labels_remove(
    message_id: str = typer.Argument(..., help="Message ID"),
    label: List[str] = typer.Option(..., "--label", "-l", help="Label ID(s) to remove"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Remove labels from a message."""
    try:
        client = get_client(profile=profile)
        service = client.get_gmail_service()

        service.users().messages().modify(
            userId='me',
            id=message_id,
            body={'removeLabelIds': label}
        ).execute()

        print_success(f"Removed {len(label)} label(s) from message {message_id}")
        print_json({'message_id': message_id, 'removed_labels': label})

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


def normalize_gmail_filter(raw: dict) -> dict:
    """Flatten a Gmail API filter resource into a single-level record."""
    criteria = raw.get('criteria', {})
    action = raw.get('action', {})
    return {
        'id': raw['id'],
        'from': criteria.get('from'),
        'to': criteria.get('to'),
        'subject': criteria.get('subject'),
        'query': criteria.get('query'),
        'negated_query': criteria.get('negatedQuery'),
        'has_attachment': criteria.get('hasAttachment'),
        'exclude_chats': criteria.get('excludeChats'),
        'size': criteria.get('size'),
        'size_comparison': criteria.get('sizeComparison'),
        'add_label_ids': action.get('addLabelIds'),
        'remove_label_ids': action.get('removeLabelIds'),
        'forward': action.get('forward'),
    }


@filters_app.command("list")
def filters_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of filters to list"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., from:contains:newsletter)"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Properties to include in output"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """List Gmail filters."""
    try:
        client = get_client(profile=profile)
        service = client.get_gmail_service()

        response = service.users().settings().filters().list(userId='me').execute()
        filters = [normalize_gmail_filter(raw) for raw in response.get('filter', [])]

        if filter:
            filters = apply_filters(filters, filter)
        filters = filters[:limit]
        if properties:
            filters = [{k: v for k, v in record.items() if k in properties} for record in filters]

        if table:
            table_cols = properties[:4] if properties else ["id", "from", "subject", "add_label_ids"]
            print_table(filters, table_cols, table_cols)
        else:
            print_json(filters)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@filters_app.command("get")
def filters_get(
    filter_id: str = typer.Argument(..., help="Filter ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Get a Gmail filter by ID."""
    try:
        client = get_client(profile=profile)
        service = client.get_gmail_service()

        raw = service.users().settings().filters().get(
            userId='me',
            id=filter_id
        ).execute()

        if table:
            record = normalize_gmail_filter(raw)
            cols = ["id", "from", "to", "subject", "query", "add_label_ids", "remove_label_ids", "forward"]
            print_table([record], cols, cols)
        else:
            print_json(raw)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@filters_app.command("create")
def filters_create(
    from_: Optional[str] = typer.Option(None, "--from", help="Match sender address/pattern"),
    to: Optional[str] = typer.Option(None, "--to", help="Match recipient address/pattern"),
    subject: Optional[str] = typer.Option(None, "--subject", help="Match subject text"),
    query: Optional[str] = typer.Option(None, "--query", help="Gmail search query the message must match"),
    negated_query: Optional[str] = typer.Option(None, "--negated-query", help="Gmail search query the message must NOT match"),
    has_attachment: bool = typer.Option(False, "--has-attachment", help="Match only messages with attachments"),
    exclude_chats: bool = typer.Option(False, "--exclude-chats", help="Exclude chat messages"),
    size: Optional[int] = typer.Option(None, "--size", help="Message size in bytes (use with --size-comparison)"),
    size_comparison: Optional[str] = typer.Option(None, "--size-comparison", help="Size comparison: larger or smaller"),
    add_label: Optional[List[str]] = typer.Option(None, "--add-label", help="Label ID to add (repeatable)"),
    remove_label: Optional[List[str]] = typer.Option(None, "--remove-label", help="Label ID to remove, e.g. INBOX, UNREAD, SPAM (repeatable)"),
    forward: Optional[str] = typer.Option(None, "--forward", help="Forward matching messages to this verified address"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Create a Gmail filter.

    Requires at least one matching criterion and at least one action.
    Common actions: --add-label <LABEL_ID>, --remove-label INBOX (archive),
    --remove-label UNREAD (mark read), --add-label TRASH (delete).
    """
    try:
        criteria = {
            'from': from_,
            'to': to,
            'subject': subject,
            'query': query,
            'negatedQuery': negated_query,
            'hasAttachment': has_attachment or None,
            'excludeChats': exclude_chats or None,
            'size': size,
            'sizeComparison': size_comparison,
        }
        criteria = {k: v for k, v in criteria.items() if v is not None}

        action = {
            'addLabelIds': add_label or None,
            'removeLabelIds': remove_label or None,
            'forward': forward,
        }
        action = {k: v for k, v in action.items() if v is not None}

        if not criteria:
            print_error("At least one criterion is required (--from, --to, --subject, --query, --negated-query, --has-attachment, --size)")
            raise typer.Exit(1)
        if not action:
            print_error("At least one action is required (--add-label, --remove-label, --forward)")
            raise typer.Exit(1)

        client = get_client(profile=profile)
        service = client.get_gmail_service()

        created = service.users().settings().filters().create(
            userId='me',
            body={'criteria': criteria, 'action': action}
        ).execute()

        print_json(created)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@filters_app.command("delete")
def filters_delete(
    filter_id: str = typer.Argument(..., help="Filter ID"),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Skip confirmation prompt"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Delete a Gmail filter."""
    try:
        if not confirm:
            typer.confirm(f"Are you sure you want to delete filter '{filter_id}'?", abort=True)

        client = get_client(profile=profile)
        service = client.get_gmail_service()

        service.users().settings().filters().delete(
            userId='me',
            id=filter_id
        ).execute()

        print_json({'filter_id': filter_id, 'deleted': True})

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))
