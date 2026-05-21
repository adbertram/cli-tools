"""File management commands for Slack CLI."""

COMMAND_CREDENTIALS = {
    "delete": [
        "custom"
    ],
    "download": [
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

import typer
from typing import Optional, List
from pathlib import Path
from ..client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, print_success, print_warning, handle_error
from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError, apply_properties_filter

app = typer.Typer(help="Manage Slack files")


@app.command("list")
def list_files(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    channel: Optional[str] = typer.Option(None, "--channel", "-c", help="Filter by channel ID (API filter)"),
    user: Optional[str] = typer.Option(None, "--user", "-u", help="Filter by user ID (API filter)"),
    types: Optional[str] = typer.Option(
        None,
        "--types",
        help="Filter by file type: all, spaces, snippets, images, gdocs, zips, pdfs (API filter)",
    ),
    ts_from: Optional[str] = typer.Option(None, "--ts-from", help="Filter files created after this timestamp (API filter)"),
    ts_to: Optional[str] = typer.Option(None, "--ts-to", help="Filter files created before this timestamp (API filter)"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of files"),
    count: int = typer.Option(100, "--count", help="Number of results per page"),
    page: int = typer.Option(1, "--page", help="Page number"),
    filter_: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., name:eq:report.pdf, filetype:eq:pdf)",
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """
    List files in the workspace.

    API filters (server-side): --channel, --user, --types, --ts-from, --ts-to
    Client-side filters: --filter for name, size, filetype, etc.

    Example:
        slack files list --table
        slack files list --channel C1234567890
        slack files list --user U1234567890 --count 50
        slack files list --types images
        slack files list --filter "size:gt:1000000"
        slack files list --filter "filetype:eq:pdf"
    """
    try:
        # Validate client-side filters first
        if filter_:
            try:
                validate_filters(filter_)
            except FilterValidationError as e:
                raise typer.BadParameter(str(e))

        client = get_client()
        response = client.list_files(
            channel=channel,
            user=user,
            types=types,
            ts_from=ts_from,
            ts_to=ts_to,
            count=count,
            page=page,
        )
        files = response.get("files", [])
        total_count = response.get("paging", {}).get("total", len(files))

        # Apply client-side filters for unsupported fields
        if filter_:
            files = apply_filters(files, filter_)

        # Apply limit
        files = files[:limit]

        if properties:
            files = apply_properties_filter(files, properties)

        if table:
            table_data = [
                {
                    "id": f.get("id"),
                    "name": f.get("name"),
                    "title": f.get("title", "")[:30],
                    "filetype": f.get("filetype"),
                    "size": f.get("size", 0),
                    "created": f.get("created"),
                }
                for f in files
            ]
            columns = ["id", "name", "title", "filetype", "size", "created"]
            headers = ["ID", "Name", "Title", "Type", "Size", "Created"]
            print_table(table_data, columns, headers)
        else:
            print_json({
                "files": files,
                "count": len(files),
                "total": total_count,
            })

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("upload")
def upload_file(
    file_path: str = typer.Argument(..., help="Path to file to upload"),
    channels: Optional[str] = typer.Option(None, "--channels", "-c", help="Comma-separated channel IDs"),
    title: Optional[str] = typer.Option(None, "--title", "-t", help="File title"),
    comment: Optional[str] = typer.Option(None, "--comment", help="Initial comment"),
):
    """
    Upload a file to Slack.

    Example:
        slack files upload document.pdf --channels C1234567890
        slack files upload image.png --channels C1234567890,C9876543210 --title "Screenshot"
    """
    try:
        # Validate file exists
        path = Path(file_path)
        if not path.exists():
            raise typer.BadParameter(f"File not found: {file_path}")

        client = get_client()
        response = client.upload_file(
            file_path=file_path,
            channels=channels,
            title=title or path.name,
            initial_comment=comment,
        )

        file_info = response.get("file", {})

        print_success(f"File uploaded successfully: {file_info.get('title', file_info.get('id'))}")
        print_json({
            "id": file_info.get("id"),
            "title": file_info.get("title"),
        })

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def file_get(
    file_id: str = typer.Argument(..., help="File ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get information about a file.

    Example:
        slack files get F1234567890
        slack files get F1234567890 --table
    """
    try:
        client = get_client()
        response = client.get_file_info(file_id)
        file = response.get("file", {})

        if table:
            table_data = [
                {
                    "id": file.get("id"),
                    "name": file.get("name"),
                    "title": file.get("title"),
                    "filetype": file.get("filetype"),
                    "size": file.get("size"),
                    "created": file.get("created"),
                    "user": file.get("user"),
                }
            ]
            print_table(
                table_data,
                ["id", "name", "title", "filetype", "size", "created", "user"],
                ["ID", "Name", "Title", "Type", "Size", "Created", "User"],
            )
        else:
            print_json(file)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def delete_file(
    file_id: str = typer.Argument(..., help="File ID to delete"),
):
    """
    Delete a file.

    Example:
        slack files delete F1234567890
    """
    try:
        client = get_client()
        client.delete_file(file_id)
        print_success(f"File {file_id} deleted successfully")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("download")
def download_file(
    file_id: str = typer.Argument(..., help="File ID to download"),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help="Output path (defaults to current directory with original filename)"
    ),
):
    """
    Download a file from Slack.

    Example:
        slack files download F1234567890
        slack files download F1234567890 --output ./downloads/report.pdf
        slack files download F1234567890 -o ~/Documents/
    """
    try:
        client = get_client()

        # If output not specified or is a directory, get file info first for the filename
        if output is None:
            file_info = client.get_file_info(file_id)
            filename = file_info.get("file", {}).get("name", f"{file_id}")
            output_path = Path.cwd() / filename
        else:
            output_path = Path(output).expanduser()
            if output_path.is_dir():
                # Get filename from file info
                file_info = client.get_file_info(file_id)
                filename = file_info.get("file", {}).get("name", f"{file_id}")
                output_path = output_path / filename

        # Create parent directories if they don't exist
        output_path.parent.mkdir(parents=True, exist_ok=True)

        result = client.download_file(file_id, str(output_path))

        print_success(f"Downloaded: {result['name']} ({result['size']} bytes)")
        print_json({
            "file_id": result["file_id"],
            "name": result["name"],
            "path": result["path"],
            "size": result["size"],
        })

    except Exception as e:
        raise typer.Exit(handle_error(e))
