"""Google Drive commands."""
COMMAND_CREDENTIALS = {
    "list": ["custom"],
    "get": ["custom"],
    "search": ["custom"],
    "download": ["custom"],
}

import typer
from typing import Optional, List
from googleapiclient.errors import HttpError
from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error, print_success, print_error
from cli_tools_shared.filters import apply_filters as _client_side_filter_reference
from ..filter_translator import translate_drive_filters

app = typer.Typer(help="Manage Google Drive files")

@app.command("list")
def drive_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of files to list"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Properties to include in output"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """List files in Google Drive."""
    try:
        client = get_client(profile=profile)
        service = client.get_drive_service()

        # Build query from filters (supports both standard and native formats)
        query = translate_drive_filters(filter) if filter else ""

        # Build fields based on requested properties
        all_fields = ['id', 'name', 'mimeType', 'createdTime', 'modifiedTime', 'size', 'parents', 'webViewLink']
        fields_str = f"files({', '.join(all_fields)})"

        results = service.files().list(
            pageSize=limit,
            q=query,
            fields=fields_str
        ).execute()

        files = results.get('files', [])

        # Filter to requested properties
        if properties:
            files = [{k: v for k, v in f.items() if k in properties} for f in files]

        if table:
            table_cols = properties[:3] if properties else ['name', 'id', 'mimeType']
            table_headers = [c.title() if c != 'mimeType' else 'Type' for c in table_cols]
            print_table(files, table_cols, table_headers)
        else:
            print_json(files)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))

@app.command("get")
def drive_get(
    file_id: str = typer.Argument(..., help="File ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Get file metadata."""
    try:
        client = get_client(profile=profile)
        service = client.get_drive_service()

        file = service.files().get(
            fileId=file_id,
            fields="id, name, mimeType, createdTime, modifiedTime, size, parents, webViewLink"
        ).execute()

        if table:
            data = [file]
            print_table(data, ['name', 'id', 'mimeType'], ['Name', 'ID', 'Type'])
        else:
            print_json(file)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))

@app.command("search")
def drive_search(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Properties to include in output"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Search for files in Google Drive."""
    try:
        client = get_client(profile=profile)
        service = client.get_drive_service()

        # Build fields based on requested properties
        all_fields = ['id', 'name', 'mimeType', 'createdTime', 'modifiedTime', 'size', 'parents', 'webViewLink']
        fields_str = f"files({', '.join(all_fields)})"

        results = service.files().list(
            pageSize=limit,
            q=f"name contains '{query}'",
            fields=fields_str
        ).execute()

        files = results.get('files', [])

        # Filter to requested properties
        if properties:
            files = [{k: v for k, v in f.items() if k in properties} for f in files]

        if table:
            table_cols = properties[:3] if properties else ['name', 'id', 'mimeType']
            table_headers = [c.title() if c != 'mimeType' else 'Type' for c in table_cols]
            print_table(files, table_cols, table_headers)
        else:
            print_json(files)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))

@app.command("download")
def drive_download(
    file_id: str = typer.Argument(..., help="File ID"),
    output: str = typer.Option(".", "--output", "-o", help="Output directory"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Download a file from Google Drive."""
    try:
        import io
        import os
        from googleapiclient.http import MediaIoBaseDownload

        client = get_client(profile=profile)
        service = client.get_drive_service()

        # Get file metadata
        file = service.files().get(fileId=file_id).execute()
        file_name = file.get('name')

        # Download file
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)

        done = False
        while done is False:
            status, done = downloader.next_chunk()

        # Write to disk
        output_path = os.path.join(output, file_name)
        with open(output_path, 'wb') as f:
            f.write(fh.getvalue())

        print_success(f"Downloaded to {output_path}")
        print_json({'file': file_name, 'path': output_path})

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))
