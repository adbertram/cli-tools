"""Webform commands for Podio CLI."""

COMMAND_CREDENTIALS = {
    "attachments": [
        "oauth_authorization_code"
    ],
    "field": [
        "oauth_authorization_code"
    ],
    "get": [
        "oauth_authorization_code"
    ],
    "list": [
        "oauth_authorization_code"
    ],
    "submit": [
        "oauth_authorization_code"
    ]
}
import json
import re
import sys
from pathlib import Path
from typing import Optional, Any, List

import requests
import typer

from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
from ..client import get_client
from ..output import print_json, print_output, print_error, print_success, print_info, handle_api_error, format_response
from ..filter_map import FilterMap, apply_properties

app = typer.Typer(help="Manage Podio webforms")

# Subcommand group for field operations
field_app = typer.Typer(help="Manage webform fields")
app.add_typer(field_app, name="field")

# Subcommand group for attachment operations
attachments_app = typer.Typer(help="Manage webform file attachments")
app.add_typer(attachments_app, name="attachments")


@app.command("list")
def list_webforms(
    app_id: int = typer.Argument(..., help="Application ID to list webforms from"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum webforms to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of fields to include"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    List all webforms for an application.

    Returns all webforms (active and disabled) configured on the given app.

    Filter examples:
        --filter "status:active"
        --filter "name:contains:Contact"

    Examples:
        podio webform list 12345
        podio webform list 12345 --limit 10
        podio webform list 12345 --filter "status:active"
        podio webform list 12345 --properties "form_id,name,status"
        podio webform list 12345 --table
    """
    try:
        client = get_client()
        # Use raw transport since pypodio2 doesn't have Form area
        result = client.transport.GET(url=f"/form/app/{app_id}/")
        formatted = format_response(result)

        # Apply client-side filter if specified
        if filter:
            formatted = apply_filters(formatted, filter)

        # Apply limit (client-side)
        if isinstance(formatted, list) and len(formatted) > limit:
            formatted = formatted[:limit]

        # Apply properties filter
        if properties:
            formatted = apply_properties(formatted, properties)

        print_output(formatted, table=table)
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("get")
def get_webform(
    form_id: int = typer.Argument(..., help="Webform ID to retrieve"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Get a specific webform by ID.

    Returns full details including settings, fields, domains, and attachments configuration.

    Examples:
        podio webform get 12345
        podio webform get 12345 --table
    """
    try:
        client = get_client()
        # Use raw transport since pypodio2 doesn't have Form area
        result = client.transport.GET(url=f"/form/{form_id}")
        formatted = format_response(result)
        print_output(formatted, table=table)
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


def _extract_csrf_token(html: str) -> Optional[str]:
    """Extract CSRF token from webform HTML."""
    # Try meta tag first
    meta_match = re.search(r'<meta\s+name="csrf-token"\s+content="([^"]+)"', html)
    if meta_match:
        return meta_match.group(1)

    # Try bootstrap data JSON
    bootstrap_match = re.search(r'"csrfToken"\s*:\s*"([^"]+)"', html)
    if bootstrap_match:
        return bootstrap_match.group(1)

    return None


def _parse_webform_url(url: str) -> tuple[int, int]:
    """Parse webform URL to extract app_id and form_id.

    URL format: https://podio.com/webforms/{app_id}/{form_id}

    Returns:
        Tuple of (app_id, form_id)
    """
    match = re.search(r'/webforms/(\d+)/(\d+)', url)
    if not match:
        raise ValueError(f"Invalid webform URL format: {url}")
    return int(match.group(1)), int(match.group(2))


def _parse_form_id(form_id_or_url: str) -> int:
    """Parse form_id from either a numeric ID or a webform URL.

    Args:
        form_id_or_url: Either a numeric form_id or a webform URL

    Returns:
        The form_id as an integer

    Raises:
        typer.BadParameter: If input is neither a valid integer nor a valid webform URL
    """
    # First, try to parse as integer
    try:
        return int(form_id_or_url)
    except ValueError:
        pass

    # Try to parse as URL
    if '/webforms/' in form_id_or_url:
        try:
            _, form_id = _parse_webform_url(form_id_or_url)
            return form_id
        except ValueError:
            pass

    # Neither worked - provide helpful error
    raise typer.BadParameter(
        f"'{form_id_or_url}' is not a valid form ID or webform URL.\n"
        f"Expected: numeric form_id (e.g., 2584779) or URL (e.g., https://podio.com/webforms/12345/2584779)"
    )


@app.command("submit")
def submit_webform(
    url: str = typer.Argument(..., help="Webform URL (e.g., https://podio.com/webforms/12345/67890)"),
    json_file: Optional[Path] = typer.Option(
        None,
        "--json-file",
        "-f",
        help="Path to JSON file with field data",
    ),
    attach: Optional[List[Path]] = typer.Option(
        None,
        "--attach",
        "-a",
        help="File(s) to attach to the submission (can be used multiple times)",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Submit data to a Podio webform via HTTP POST.

    This submits directly to the public webform URL, exactly like a browser would.
    No authentication required - uses the public webform endpoint.

    Field data format (using field external_id as keys):
        {
            "title": "My Title",
            "description": "Some text",
            "category": "Option 1"
        }

    File attachments require the webform to have attachments enabled.
    Use 'podio webform attachments status <form>' to check.

    Examples:
        podio webform submit https://podio.com/webforms/30560419/2584779 -f data.json
        podio webform submit https://podio.com/webforms/30560419/2584779 -f data.json --attach document.docx
        podio webform submit https://podio.com/webforms/30560419/2584779 -f data.json -a file1.pdf -a file2.docx
        echo '{"title": "Test"}' | podio webform submit https://podio.com/webforms/30560419/2584779
    """
    try:
        # Parse the webform URL
        try:
            app_id, form_id = _parse_webform_url(url)
        except ValueError as e:
            print_error(str(e))
            print_error("Expected format: https://podio.com/webforms/{app_id}/{form_id}")
            raise typer.Exit(1)

        print_info(f"Webform URL: {url}")
        print_info(f"App ID: {app_id}, Form ID: {form_id}")

        # Validate attachment files exist
        attachment_files = []
        if attach:
            for file_path in attach:
                if not file_path.exists():
                    print_error(f"Attachment file not found: {file_path}")
                    raise typer.Exit(1)
                attachment_files.append(file_path)
            print_info(f"Attachments: {len(attachment_files)} file(s)")

        # Read field data from file or stdin
        if json_file:
            if not json_file.exists():
                print_error(f"File not found: {json_file}")
                raise typer.Exit(1)
            with open(json_file) as f:
                fields_data = json.load(f)
        else:
            # Read from stdin
            if sys.stdin.isatty():
                # No stdin input - allow submission with just attachments or empty fields
                fields_data = {}
            else:
                try:
                    fields_data = json.load(sys.stdin)
                except json.JSONDecodeError as e:
                    print_error(f"Invalid JSON from stdin: {e}")
                    raise typer.Exit(1)

        # Step 1: GET the webform page to extract CSRF token
        print_info("Fetching webform page for CSRF token...")
        session = requests.Session()
        response = session.get(url)

        if response.status_code != 200:
            print_error(f"Failed to fetch webform: HTTP {response.status_code}")
            raise typer.Exit(1)

        csrf_token = _extract_csrf_token(response.text)
        if not csrf_token:
            print_error("Could not extract CSRF token from webform page")
            raise typer.Exit(1)

        print_info("CSRF token obtained")

        # Step 2: Build form data in fields[key] format
        form_data = {}
        for key, value in fields_data.items():
            form_data[f"fields[{key}]"] = value

        # Step 3: POST to the webform
        print_info("Submitting webform...")
        headers = {
            "X-CSRF-Token": csrf_token,
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://podio.com",
            "Referer": url,
        }

        # Build files for multipart upload if attachments provided
        files_to_upload = None
        if attachment_files:
            # Use multipart/form-data with files
            # Format: list of tuples (field_name, (filename, file_object, content_type))
            files_to_upload = []
            for file_path in attachment_files:
                files_to_upload.append(
                    ('attachments[]', (file_path.name, open(file_path, 'rb'), 'application/octet-stream'))
                )

        try:
            if files_to_upload:
                # Multipart form data with files
                post_response = session.post(
                    url,
                    data=form_data,
                    files=files_to_upload,
                    headers=headers,
                )
            else:
                # Regular form data without files
                post_response = session.post(
                    url,
                    data=form_data,
                    headers=headers,
                )
        finally:
            # Close any opened file handles
            if files_to_upload:
                for _, file_tuple in files_to_upload:
                    if hasattr(file_tuple[1], 'close'):
                        file_tuple[1].close()

        # Check response
        if post_response.status_code == 200:
            # Try to parse JSON response
            try:
                result = post_response.json()
                print_success("Webform submitted successfully!")
                print_output(result, table=table)
            except json.JSONDecodeError:
                # Response might be HTML redirect on success
                if "success" in post_response.text.lower() or "thank you" in post_response.text.lower():
                    print_success("Webform submitted successfully!")
                    print_output({"status": "success", "message": "Form submitted"}, table=table)
                else:
                    print_success("Webform submitted (response was not JSON)")
                    print_info(f"Response: {post_response.text[:500]}")
        elif post_response.status_code == 302:
            # Redirect usually means success
            print_success("Webform submitted successfully! (redirected)")
            location = post_response.headers.get("Location", "")
            print_output({"status": "success", "redirect": location}, table=table)
        elif post_response.status_code == 422:
            # Validation error
            print_error("Validation error from webform")
            try:
                error_data = post_response.json()
                print_error(json.dumps(error_data, indent=2))
            except json.JSONDecodeError:
                print_error(post_response.text[:500])
            raise typer.Exit(1)
        else:
            print_error(f"Webform submission failed: HTTP {post_response.status_code}")
            print_error(post_response.text[:500])
            raise typer.Exit(1)

    except requests.RequestException as e:
        print_error(f"HTTP request failed: {e}")
        raise typer.Exit(1)
    except Exception as e:
        if isinstance(e, SystemExit):
            raise
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@field_app.command("get")
def get_webform_field(
    form_id_or_url: str = typer.Argument(
        ...,
        help="Webform ID or URL (e.g., 2584779 or https://podio.com/webforms/12345/2584779)",
        metavar="FORM_ID_OR_URL",
    ),
    field_id: int = typer.Argument(..., help="Field ID to retrieve details for"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Get details about a specific field on a webform.

    The FORM_ID_OR_URL can be either:
      - A numeric form ID (e.g., 2584779)
      - A full webform URL (e.g., https://podio.com/webforms/12345/2584779)

    Examples:
        podio webform field get 2584779 275324144
        podio webform field get https://podio.com/webforms/12345/2584779 275324144
        podio webform field get 2584779 275324144 --table
    """
    try:
        form_id = _parse_form_id(form_id_or_url)
        client = get_client()
        result = client.transport.GET(url=f"/form/{form_id}")

        fields = result.get('fields', [])
        # Find the specific field
        field_data = next((f for f in fields if f.get('field_id') == field_id), None)

        if field_data is None:
            from ..output import print_error
            print_error(f"Field {field_id} not found on webform {form_id}")
            raise typer.Exit(1)

        formatted = format_response(field_data)
        print_output(formatted, table=table)

    except typer.BadParameter:
        raise
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@field_app.command("add")
def add_field_to_webform(
    form_id_or_url: str = typer.Argument(
        ...,
        help="Webform ID or URL (e.g., 2584779 or https://podio.com/webforms/12345/2584779)",
        metavar="FORM_ID_OR_URL",
    ),
    field_id: int = typer.Argument(..., help="Field ID to add to the webform"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Add a field to a webform.

    Adds an app field to the webform so it appears on the public form.

    The FORM_ID_OR_URL can be either:
      - A numeric form ID (e.g., 2584779)
      - A full webform URL (e.g., https://podio.com/webforms/12345/2584779)

    Note: In the URL format /webforms/{app_id}/{form_id}, the form_id is the SECOND number.

    Examples:
        podio webform field add 2584779 275324144
        podio webform field add https://podio.com/webforms/12345/2584779 275324144
        podio webform field add 2584779 275324144 --table
    """
    try:
        form_id = _parse_form_id(form_id_or_url)
        client = get_client()

        # Get current webform configuration
        current_form = client.transport.GET(url=f"/form/{form_id}")

        # Check if field already exists
        existing_field_ids = [f.get('field_id') for f in current_form.get('fields', [])]
        if field_id in existing_field_ids:
            print_error(f"Field {field_id} is already on the webform")
            raise typer.Exit(1)

        # Build update payload with existing fields plus new one
        fields = current_form.get('fields', [])
        fields.append({'field_id': field_id})

        update_data = {
            'settings': current_form.get('settings', {}),
            'domains': current_form.get('domains', []),
            'fields': fields,
            'attachments': current_form.get('attachments', False),
        }

        # Update the webform
        result = client.transport.PUT(
            url=f"/form/{form_id}",
            body=json.dumps(update_data),
            type='application/json'
        )

        print_success(f"Field {field_id} added to webform {form_id}")
        formatted = format_response(result)
        print_output(formatted, table=table)

    except typer.BadParameter:
        raise
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@field_app.command("remove")
def remove_field_from_webform(
    form_id_or_url: str = typer.Argument(
        ...,
        help="Webform ID or URL (e.g., 2584779 or https://podio.com/webforms/12345/2584779)",
        metavar="FORM_ID_OR_URL",
    ),
    field_id: int = typer.Argument(..., help="Field ID to remove from the webform"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Remove a field from a webform.

    Removes an app field from the webform so it no longer appears on the public form.

    The FORM_ID_OR_URL can be either:
      - A numeric form ID (e.g., 2584779)
      - A full webform URL (e.g., https://podio.com/webforms/12345/2584779)

    Note: In the URL format /webforms/{app_id}/{form_id}, the form_id is the SECOND number.

    Examples:
        podio webform field remove 2584779 275324144
        podio webform field remove https://podio.com/webforms/12345/2584779 275324144
        podio webform field remove 2584779 275324144 --table
    """
    try:
        form_id = _parse_form_id(form_id_or_url)
        client = get_client()

        # Get current webform configuration
        current_form = client.transport.GET(url=f"/form/{form_id}")

        # Check if field exists
        existing_field_ids = [f.get('field_id') for f in current_form.get('fields', [])]
        if field_id not in existing_field_ids:
            print_error(f"Field {field_id} is not on the webform")
            raise typer.Exit(1)

        # Build update payload without the specified field
        fields = [f for f in current_form.get('fields', []) if f.get('field_id') != field_id]

        update_data = {
            'settings': current_form.get('settings', {}),
            'domains': current_form.get('domains', []),
            'fields': fields,
            'attachments': current_form.get('attachments', False),
        }

        # Update the webform
        result = client.transport.PUT(
            url=f"/form/{form_id}",
            body=json.dumps(update_data),
            type='application/json'
        )

        print_success(f"Field {field_id} removed from webform {form_id}")
        formatted = format_response(result)
        print_output(formatted, table=table)

    except typer.BadParameter:
        raise
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@field_app.command("list")
def list_webform_fields(
    form_id_or_url: str = typer.Argument(
        ...,
        help="Webform ID or URL (e.g., 2584779 or https://podio.com/webforms/12345/2584779)",
        metavar="FORM_ID_OR_URL",
    ),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum fields to return"),
    filter: Optional[str] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of fields to include"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    List all fields on a webform.

    Shows the field IDs currently configured on the webform.

    The FORM_ID_OR_URL can be either:
      - A numeric form ID (e.g., 2584779)
      - A full webform URL (e.g., https://podio.com/webforms/12345/2584779)

    Note: In the URL format /webforms/{app_id}/{form_id}, the form_id is the SECOND number.

    Examples:
        podio webform field list 2584779
        podio webform field list https://podio.com/webforms/12345/2584779
        podio webform field list 2584779 --table
        podio webform field list 2584779 --limit 10
    """
    try:
        form_id = _parse_form_id(form_id_or_url)
        client = get_client()
        result = client.transport.GET(url=f"/form/{form_id}")

        fields = result.get('fields', [])
        field_ids = result.get('field_ids', [])

        # Apply client-side filter to fields if specified
        if filter and isinstance(fields, list):
            fields = apply_filters(fields, [filter])

        # Apply limit to fields
        if isinstance(fields, list) and len(fields) > limit:
            fields = fields[:limit]

        output = {
            'form_id': form_id,
            'field_count': len(fields),
            'field_ids': field_ids,
            'fields': fields,
        }

        formatted = format_response(output)

        # Apply properties filter
        if properties:
            formatted = apply_properties(formatted, properties)

        print_output(formatted, table=table)

    except typer.BadParameter:
        raise
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


def _update_webform_attachments(form_id: int, enabled: bool) -> dict:
    """Update the attachments setting on a webform.

    Args:
        form_id: The webform ID
        enabled: Whether attachments should be enabled

    Returns:
        The updated webform data
    """
    client = get_client()

    # Get current webform configuration
    current_form = client.transport.GET(url=f"/form/{form_id}")

    # Build update payload with new attachments setting
    update_data = {
        'settings': current_form.get('settings', {}),
        'domains': current_form.get('domains', []),
        'fields': current_form.get('fields', []),
        'attachments': enabled,
    }

    # Update the webform
    result = client.transport.PUT(
        url=f"/form/{form_id}",
        body=json.dumps(update_data),
        type='application/json'
    )

    return result


@attachments_app.command("enable")
def enable_attachments(
    form_id_or_url: str = typer.Argument(
        ...,
        help="Webform ID or URL (e.g., 2584779 or https://podio.com/webforms/12345/2584779)",
        metavar="FORM_ID_OR_URL",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Enable file attachments on a webform.

    When enabled, users can attach files when submitting the webform.

    The FORM_ID_OR_URL can be either:
      - A numeric form ID (e.g., 2584779)
      - A full webform URL (e.g., https://podio.com/webforms/12345/2584779)

    Examples:
        podio webform attachments enable 2584779
        podio webform attachments enable https://podio.com/webforms/12345/2584779
    """
    try:
        form_id = _parse_form_id(form_id_or_url)
        result = _update_webform_attachments(form_id, enabled=True)

        print_success(f"File attachments enabled on webform {form_id}")
        formatted = format_response(result)
        print_output(formatted, table=table)

    except typer.BadParameter:
        raise
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@attachments_app.command("disable")
def disable_attachments(
    form_id_or_url: str = typer.Argument(
        ...,
        help="Webform ID or URL (e.g., 2584779 or https://podio.com/webforms/12345/2584779)",
        metavar="FORM_ID_OR_URL",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Disable file attachments on a webform.

    When disabled, users cannot attach files when submitting the webform.

    The FORM_ID_OR_URL can be either:
      - A numeric form ID (e.g., 2584779)
      - A full webform URL (e.g., https://podio.com/webforms/12345/2584779)

    Examples:
        podio webform attachments disable 2584779
        podio webform attachments disable https://podio.com/webforms/12345/2584779
    """
    try:
        form_id = _parse_form_id(form_id_or_url)
        result = _update_webform_attachments(form_id, enabled=False)

        print_success(f"File attachments disabled on webform {form_id}")
        formatted = format_response(result)
        print_output(formatted, table=table)

    except typer.BadParameter:
        raise
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@attachments_app.command("status")
def attachments_status(
    form_id_or_url: str = typer.Argument(
        ...,
        help="Webform ID or URL (e.g., 2584779 or https://podio.com/webforms/12345/2584779)",
        metavar="FORM_ID_OR_URL",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Check if file attachments are enabled on a webform.

    The FORM_ID_OR_URL can be either:
      - A numeric form ID (e.g., 2584779)
      - A full webform URL (e.g., https://podio.com/webforms/12345/2584779)

    Examples:
        podio webform attachments status 2584779
        podio webform attachments status https://podio.com/webforms/12345/2584779
    """
    try:
        form_id = _parse_form_id(form_id_or_url)
        client = get_client()
        result = client.transport.GET(url=f"/form/{form_id}")

        attachments_enabled = result.get('attachments', False)
        output = {
            'form_id': form_id,
            'attachments_enabled': attachments_enabled,
            'status': 'enabled' if attachments_enabled else 'disabled',
        }

        formatted = format_response(output)
        print_output(formatted, table=table)

    except typer.BadParameter:
        raise
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)
