"""File operations for Gemini CLI."""
import typer
from pathlib import Path
from typing import List, Optional
from ..client import get_client
from cli_tools_shared.output import print_json, print_table, print_success, print_error, print_info, handle_error
from ..file_types import is_supported_file, UnsupportedFileTypeError
from cli_tools_shared.filters import apply_filters, apply_limit, apply_properties_filter

app = typer.Typer(help="File operations with Gemini Files API")


@app.command("upload")
def files_upload(
    file_path: str = typer.Argument(..., help="Path to file to upload"),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Wait for processing"),
):
    """
    Upload a file to Gemini Files API.

    Example:
        gemini files upload document.pdf
        gemini files upload video.mp4 --wait
    """
    try:
        client = get_client()

        path = Path(file_path)
        if not path.exists():
            print_error(f"File not found: {file_path}")
            raise typer.Exit(1)

        if not is_supported_file(path):
            raise UnsupportedFileTypeError(path)

        print_info(f"Uploading {path.name}...")
        uploaded_file = client.upload_file(str(path))

        if wait:
            print_info("Waiting for processing...")
            uploaded_file = client.wait_for_file_processing(uploaded_file.name)

        result = {
            "name": uploaded_file.name,
            "display_name": getattr(uploaded_file, 'display_name', path.name),
            "mime_type": getattr(uploaded_file, 'mime_type', 'unknown'),
            "size_bytes": getattr(uploaded_file, 'size_bytes', 0),
            "state": uploaded_file.state.name if uploaded_file.state else "UNKNOWN",
            "uri": getattr(uploaded_file, 'uri', ''),
        }

        print_success("File uploaded successfully")
        print_json(result)

    except UnsupportedFileTypeError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("list")
def files_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of files to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List all uploaded files.

    Example:
        gemini files list
        gemini files list --table
    """
    try:
        client = get_client()
        files = client.list_files(limit=limit)

        if not files:
            if table:
                print_table([], [], [])
            else:
                print_json([])
            return

        file_data = []
        for f in files:
            file_data.append({
                "name": f.name,
                "display_name": getattr(f, 'display_name', 'N/A'),
                "mime_type": getattr(f, 'mime_type', 'unknown'),
                "size_bytes": getattr(f, 'size_bytes', 0),
                "state": f.state.name if f.state else "UNKNOWN",
            })

        if filter:
            file_data = apply_filters(file_data, filter)
        file_data = apply_limit(file_data, limit)
        if properties:
            file_data = apply_properties_filter(file_data, properties)

        if table:
            if properties:
                fields = [field.strip() for field in properties.split(",")]
                print_table(file_data, fields, fields)
            else:
                print_table(
                    file_data,
                    ["name", "display_name", "mime_type", "size_bytes", "state"],
                    ["Name", "Display Name", "MIME Type", "Size (bytes)", "State"]
                )
        else:
            print_json(file_data)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def files_get(
    file_name: str = typer.Argument(..., help="File name (e.g., files/abc123)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get file metadata.

    Example:
        gemini files get files/abc123
        gemini files get files/abc123 --table
    """
    try:
        client = get_client()
        file_obj = client.get_file(file_name)

        result = {
            "name": file_obj.name,
            "display_name": getattr(file_obj, 'display_name', 'N/A'),
            "mime_type": getattr(file_obj, 'mime_type', 'unknown'),
            "size_bytes": getattr(file_obj, 'size_bytes', 0),
            "state": file_obj.state.name if file_obj.state else "UNKNOWN",
            "uri": getattr(file_obj, 'uri', ''),
        }

        if table:
            print_table(
                [result],
                ["name", "display_name", "mime_type", "size_bytes", "state"],
                ["Name", "Display Name", "MIME Type", "Size (bytes)", "State"]
            )
        else:
            print_json(result)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def files_delete(
    file_name: str = typer.Argument(..., help="File name to delete (e.g., files/abc123)"),
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """
    Delete an uploaded file.

    Example:
        gemini files delete files/abc123
        gemini files delete files/abc123 --yes
    """
    try:
        client = get_client()

        if not confirm:
            confirmed = typer.confirm(f"Delete file '{file_name}'?")
            if not confirmed:
                print_info("Cancelled")
                return

        client.delete_file(file_name)
        print_success(f"File '{file_name}' deleted")

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "delete": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "upload": [
        "custom"
    ]
}
