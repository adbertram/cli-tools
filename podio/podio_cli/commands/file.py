"""File commands for Podio CLI."""

COMMAND_CREDENTIALS = {
    "attach": [
        "oauth_authorization_code"
    ],
    "copy": [
        "oauth_authorization_code"
    ],
    "download": [
        "oauth_authorization_code"
    ],
    "get": [
        "oauth_authorization_code"
    ],
    "list": [
        "oauth_authorization_code"
    ],
    "upload": [
        "oauth_authorization_code"
    ]
}
import json
import sys
from io import BytesIO
from typing import Optional
from pathlib import Path
import typer

from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
from ..client import get_client
from ..output import print_json, print_output, print_error, print_success, handle_api_error, format_response
from ..filter_map import FilterMap, apply_properties

app = typer.Typer(help="Manage Podio files")


@app.command("upload")
def upload_file(
    file_path: Path = typer.Argument(..., help="Path to file to upload"),
    filename: Optional[str] = typer.Option(
        None,
        "--filename",
        help="Override filename (defaults to original filename)",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Upload a file to Podio.

    Returns the file_id which can be used to attach the file to items,
    tasks, comments, etc.

    Examples:
        podio file upload document.docx
        podio file upload document.docx --filename "My Document.docx"
        podio file upload document.docx --table
    """
    try:
        if not file_path.exists():
            print_error(f"File not found: {file_path}")
            raise typer.Exit(1)

        client = get_client()

        # Use provided filename or original
        upload_filename = filename or file_path.name

        # Open file as file object for multipart upload
        with open(file_path, "rb") as f:
            # Use the file object directly for proper multipart encoding
            result = client.Files.create(filename=upload_filename, filedata=f)
        formatted = format_response(result)
        print_output(formatted, table=table)
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("attach")
def attach_file(
    file_id: int = typer.Argument(..., help="File ID to attach"),
    ref_type: str = typer.Argument(..., help="Reference type: item, task, comment, status, or space"),
    ref_id: int = typer.Argument(..., help="Reference ID (item_id, task_id, etc.)"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Attach an uploaded file to an object.

    Valid reference types are: item, task, comment, status, space

    Examples:
        podio file attach 12345 item 67890
        podio file attach 12345 task 11111
        podio file attach 12345 comment 22222
        podio file attach 12345 item 67890 --table
    """
    try:
        valid_types = ["item", "task", "comment", "status", "space"]
        if ref_type not in valid_types:
            print_error(f"Invalid ref_type '{ref_type}'. Must be one of: {', '.join(valid_types)}")
            raise typer.Exit(1)

        client = get_client()
        result = client.Files.attach(file_id=file_id, ref_type=ref_type, ref_id=ref_id)
        formatted = format_response(result) if result else {"attached": True}
        print_output(formatted, table=table)
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("list")
def list_files(
    ref_type: str = typer.Argument(..., help="Reference type: item, task, comment, status, or space"),
    ref_id: int = typer.Argument(..., help="Reference ID to list files from"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum files to return"),
    filter: Optional[str] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of fields to include"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    List files attached to an object.

    Valid reference types are: item, task, comment, status, space

    Examples:
        podio file list item 12345
        podio file list task 67890
        podio file list item 12345 --limit 10
        podio file list item 12345 --filter "name:contains:report"
        podio file list item 12345 --properties "file_id,name,mimetype"
        podio file list item 12345 --table
    """
    try:
        valid_types = ["item", "task", "comment", "status", "space"]
        if ref_type not in valid_types:
            print_error(f"Invalid ref_type '{ref_type}'. Must be one of: {', '.join(valid_types)}")
            raise typer.Exit(1)

        client = get_client()
        result = client.Files.find_for_app(ref_type=ref_type, ref_id=ref_id)
        formatted = format_response(result)

        # Apply client-side filter if specified
        if filter and isinstance(formatted, list):
            formatted = apply_filters(formatted, [filter])

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
def get_file(
    file_id: int = typer.Argument(..., help="File ID to retrieve"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Get file metadata by ID.

    Examples:
        podio file get 12345
        podio file get 12345 --table
    """
    try:
        client = get_client()
        result = client.Files.find(file_id=file_id)
        formatted = format_response(result)
        print_output(formatted, table=table)
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("download")
def download_file(
    file_id: int = typer.Argument(..., help="File ID to download"),
    output: Optional[Path] = typer.Option(
        None,
        "--output", "-o",
        help="Output file path (defaults to original filename)",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Download a file from Podio.

    Examples:
        podio file download 12345
        podio file download 12345 --output ./my-document.docx
        podio file download 12345 --table
    """
    try:
        client = get_client()

        # Get file metadata first to get filename
        metadata = client.Files.find(file_id=file_id)
        original_filename = metadata.get("name", f"file_{file_id}")

        # Download raw content
        content = client.Files.find_raw(file_id=file_id)

        # Determine output path
        output_path = output or Path(original_filename)

        # Write to file
        with open(output_path, "wb") as f:
            if isinstance(content, str):
                f.write(content.encode())
            else:
                f.write(content)

        print_success(f"File downloaded to: {output_path}")
        print_output({"file_id": file_id, "filename": str(output_path), "size": output_path.stat().st_size}, table=table)
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("copy")
def copy_file(
    file_id: int = typer.Argument(..., help="File ID to copy"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Copy a file to create a new file with a new file_id.

    Useful when you need to attach the same file to multiple objects.

    Examples:
        podio file copy 12345
        podio file copy 12345 --table
    """
    try:
        client = get_client()
        result = client.Files.copy(file_id=file_id)
        formatted = format_response(result)
        print_success(f"File {file_id} copied successfully")
        print_output(formatted, table=table)
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)
