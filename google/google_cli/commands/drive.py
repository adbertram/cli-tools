"""Google Drive commands."""
COMMAND_CREDENTIALS = {
    "list": ["custom"],
    "get": ["custom"],
    "search": ["custom"],
    "download": ["custom"],
    "copy": ["custom"],
    "create-folder": ["custom"],
    "move": ["custom"],
}

import re
import typer
from typing import Optional, List
from googleapiclient.errors import HttpError
from ..client import get_client, DRIVE_ALL_DRIVES, DRIVE_LIST_ALL_DRIVES
from ..properties import parse_properties
from cli_tools_shared.output import command, print_json, print_table, handle_error, print_success, print_error
from cli_tools_shared.filters import apply_filters as _client_side_filter_reference
from ..filter_translator import translate_drive_filters

app = typer.Typer(help="Manage Google Drive files")

# Google Drive IDs are URL-safe base64-ish tokens; anything else would build a
# malformed ``q`` clause, so reject it before the API request is made.
_FOLDER_ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]{10,}$')

_DRIVE_URL_ID_PATTERN = re.compile(r'(?:/(?:d|folders)/|[?&]id=)([A-Za-z0-9_-]+)')


def parse_drive_id(file_id_or_url: str) -> str:
    """Return the Drive file ID from a Drive/Docs URL, or the value itself when it is an ID."""
    if file_id_or_url.startswith(("http://", "https://")):
        match = _DRIVE_URL_ID_PATTERN.search(file_id_or_url)
        if not match:
            raise typer.BadParameter(f"Could not extract file ID from URL: {file_id_or_url}")
        return match.group(1)
    return file_id_or_url


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
        properties = parse_properties(properties)
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
        fields_str = f"nextPageToken, files({', '.join(all_fields)})"

        files = []
        page_token = None
        while len(files) < limit:
            results = service.files().list(
                pageSize=min(1000, limit - len(files)),
                pageToken=page_token,
                q=query,
                fields=fields_str,
                **DRIVE_LIST_ALL_DRIVES,
            ).execute()
            files.extend(results.get('files', []))
            page_token = results.get('nextPageToken')
            if not page_token:
                break

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
            fields="id, name, mimeType, createdTime, modifiedTime, size, parents, webViewLink, shortcutDetails",
            **DRIVE_ALL_DRIVES,
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
        properties = parse_properties(properties)
        client = get_client(profile=profile)
        service = client.get_drive_service()

        # Build fields based on requested properties
        all_fields = ['id', 'name', 'mimeType', 'createdTime', 'modifiedTime', 'size', 'parents', 'webViewLink', 'shortcutDetails']
        fields_str = f"files({', '.join(all_fields)})"

        results = service.files().list(
            pageSize=limit,
            q=f"name contains '{query}'",
            fields=fields_str,
            **DRIVE_LIST_ALL_DRIVES,
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
        file = service.files().get(fileId=file_id, **DRIVE_ALL_DRIVES).execute()
        file_name = file.get('name')

        # Download file
        request = service.files().get_media(fileId=file_id, **DRIVE_ALL_DRIVES)
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


@app.command("copy")
@command
def drive_copy(
    file_id_or_url: str = typer.Argument(..., help="File ID or URL"),
    name: str = typer.Option(..., "--name", help="Name of the copy"),
    parent: Optional[str] = typer.Option(None, "--parent", help="Folder ID to place the copy in"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Copy a file."""
    try:
        client = get_client(profile=profile)
        service = client.get_drive_service()

        body = {"name": name}
        if parent:
            body["parents"] = [parent]
        copied = service.files().copy(
            fileId=parse_drive_id(file_id_or_url),
            body=body,
            fields="id, name, webViewLink, parents",
            **DRIVE_ALL_DRIVES,
        ).execute()

        print_json({
            "id": copied.get("id"),
            "name": copied.get("name"),
            "url": copied.get("webViewLink"),
            "parents": copied.get("parents"),
        })

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create-folder")
@command
def drive_create_folder(
    name: str = typer.Option(..., "--name", help="Folder name"),
    parent: Optional[str] = typer.Option(None, "--parent", help="Folder ID to create the folder in"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Create a folder."""
    try:
        client = get_client(profile=profile)
        service = client.get_drive_service()

        body = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
        if parent:
            body["parents"] = [parent]
        folder = service.files().create(
            body=body,
            fields="id, name, webViewLink",
            **DRIVE_ALL_DRIVES,
        ).execute()

        print_json({
            "id": folder.get("id"),
            "name": folder.get("name"),
            "url": folder.get("webViewLink"),
        })

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("move")
@command
def drive_move(
    file_id_or_url: str = typer.Argument(..., help="File ID or URL"),
    to: str = typer.Option(..., "--to", help="Destination folder ID"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Move a file to a folder, removing it from all its current parents."""
    try:
        client = get_client(profile=profile)
        service = client.get_drive_service()
        file_id = parse_drive_id(file_id_or_url)

        current = service.files().get(fileId=file_id, fields="id, parents", **DRIVE_ALL_DRIVES).execute()
        moved = service.files().update(
            fileId=file_id,
            addParents=to,
            removeParents=",".join(p for p in current.get("parents", []) if p != to),
            fields="id, name, parents",
            **DRIVE_ALL_DRIVES,
        ).execute()

        print_json({
            "id": moved.get("id"),
            "name": moved.get("name"),
            "parents": moved.get("parents"),
        })

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))
