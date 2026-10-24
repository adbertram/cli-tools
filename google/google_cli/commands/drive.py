"""Google Drive commands."""
COMMAND_CREDENTIALS = {
    "list": ["custom"],
    "get": ["custom"],
    "search": ["custom"],
    "download": ["custom"],
}

import re
import typer
from typing import Optional, List
from googleapiclient.errors import HttpError
from ..client import get_client
from cli_tools_shared.output import command, print_json, print_table, handle_error, print_success, print_error
from cli_tools_shared.filters import apply_filters as _client_side_filter_reference
from ..filter_translator import translate_drive_filters

app = typer.Typer(help="Manage Google Drive files")

# Google Drive IDs are URL-safe base64-ish tokens; anything else would build a
# malformed ``q`` clause, so reject it before the API request is made.
_FOLDER_ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]{10,}$')

@app.command("list")
@command
def drive_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of files to list"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    folder: Optional[str] = typer.Option(None, "--folder", "-F", help="Only list direct children of this Google Drive folder ID"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Properties to include in output"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """List files in Google Drive."""
    try:
        if folder is not None and not _FOLDER_ID_PATTERN.match(folder):
            raise typer.BadParameter(
                f"Invalid value for '--folder' / '-F': {folder!r} is not a valid "
                f"Google Drive folder ID (expected at least 10 characters from [A-Za-z0-9_-])",
                param_hint="'--folder' / '-F'",
            )

        client = get_client(profile=profile)
        service = client.get_drive_service()

        # Build query from filters (supports both standard and native formats)
        filter_query = translate_drive_filters(filter) if filter else ""

        # Restrict to one folder's direct children via the Drive API parents clause.
        if folder is not None:
            parents_query = f"'{folder}' in parents"
            if filter_query:
                query = f"({parents_query}) and ({filter_query})"
            else:
                query = parents_query
        else:
            query = filter_query

        # Build fields based on requested properties
        all_fields = ['id', 'name', 'mimeType', 'createdTime', 'modifiedTime', 'size', 'parents', 'webViewLink', 'shortcutDetails']
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
@command
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
            fields="id, name, mimeType, createdTime, modifiedTime, size, parents, webViewLink, shortcutDetails"
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
@command
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
        all_fields = ['id', 'name', 'mimeType', 'createdTime', 'modifiedTime', 'size', 'parents', 'webViewLink', 'shortcutDetails']
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
@command
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
