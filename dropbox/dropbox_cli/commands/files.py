"""File operation commands for Dropbox CLI."""
import os
from datetime import datetime, timedelta
import typer
from typing import Optional
from pathlib import Path

from ..client import get_client, ClientError
from ..output import (
    print_json,
    print_table,
    print_success,
    print_error,
    print_info,
    handle_error,
    format_size,
)

COMMAND_CREDENTIALS = {
    "changes": [
        "oauth"
    ],
    "cp": [
        "oauth"
    ],
    "get": [
        "oauth"
    ],
    "history": [
        "oauth"
    ],
    "info": [
        "oauth"
    ],
    "list": [
        "oauth"
    ],
    "ls": [
        "oauth"
    ],
    "mkdir": [
        "oauth"
    ],
    "mv": [
        "oauth"
    ],
    "put": [
        "oauth"
    ],
    "restore": [
        "oauth"
    ],
    "rm": [
        "oauth"
    ],
    "search": [
        "oauth"
    ]
}

app = typer.Typer(help="Manage files and folders")


@app.command("ls")
def files_list(
    path: str = typer.Argument("", help="Dropbox path to list (empty for root)"),
    recursive: bool = typer.Option(False, "--recursive", "-R", help="List recursively"),
    long: bool = typer.Option(False, "--long", "-l", help="Show detailed information"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    include_deleted: bool = typer.Option(False, "--deleted", "-d", help="Include deleted files"),
):
    """
    List files and folders.

    Examples:
        dropbox files ls
        dropbox files ls /Documents
        dropbox files ls -l /Photos
        dropbox files ls -R /Projects
    """
    try:
        client = get_client()
        entries = client.list_folder(
            path=path,
            recursive=recursive,
            include_deleted=include_deleted,
        )

        if table or long:
            table_data = []
            for entry in entries:
                row = {
                    "type": entry.get("type", "")[0].upper() if entry.get("type") else "",
                    "name": entry.get("name", ""),
                    "path": entry.get("path_display", ""),
                }
                if long:
                    row["size"] = format_size(entry.get("size", 0)) if entry.get("type") == "file" else "-"
                    row["modified"] = entry.get("server_modified", "-") if entry.get("type") == "file" else "-"
                table_data.append(row)

            if long:
                print_table(
                    table_data,
                    ["type", "name", "size", "modified"],
                    ["T", "Name", "Size", "Modified"],
                )
            else:
                print_table(
                    table_data,
                    ["type", "name", "path"],
                    ["T", "Name", "Path"],
                )
        else:
            print_json(entries)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("list")
def files_list_alias(
    path: str = typer.Argument("", help="Dropbox path to list (empty for root)"),
    recursive: bool = typer.Option(False, "--recursive", "-R", help="List recursively"),
    long: bool = typer.Option(False, "--long", "-l", help="Show detailed information"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    include_deleted: bool = typer.Option(False, "--deleted", "-d", help="Include deleted files"),
    limit: int = typer.Option(50, "--limit", help="Maximum number of results to return"),
    filter: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
):
    """
    List files and folders.

    Examples:
        dropbox files list
        dropbox files list /Documents
        dropbox files list -l /Photos
        dropbox files list --limit 10
    """
    try:
        client = get_client()
        entries = client.list_folder(
            path=path,
            recursive=recursive,
            include_deleted=include_deleted,
        )

        # Apply client-side filtering
        if filter:
            from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError
            try:
                validate_filters(filter)
                entries = apply_filters(entries, filter)
            except FilterValidationError as e:
                print_error(f"Invalid filter: {e}")
                raise typer.Exit(1)

        # Apply limit
        entries = entries[:limit]

        # Apply property selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            entries = [{f: e.get(f) for f in fields} for e in entries]

        if table or long:
            table_data = []
            for entry in entries:
                row = {
                    "type": entry.get("type", "")[0].upper() if entry.get("type") else "",
                    "name": entry.get("name", ""),
                    "path": entry.get("path_display", ""),
                }
                if long:
                    row["size"] = format_size(entry.get("size", 0)) if entry.get("type") == "file" else "-"
                    row["modified"] = entry.get("server_modified", "-") if entry.get("type") == "file" else "-"
                table_data.append(row)

            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(table_data, fields, fields)
            elif long:
                print_table(
                    table_data,
                    ["type", "name", "size", "modified"],
                    ["T", "Name", "Size", "Modified"],
                )
            else:
                print_table(
                    table_data,
                    ["type", "name", "path"],
                    ["T", "Name", "Path"],
                )
        else:
            print_json(entries)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


def _parse_datetime(value: str) -> datetime:
    """Parse a datetime string in various formats.

    Supports:
        2026-03-02T18:00:00     ISO format
        2026-03-02 18:00:00     Date and time with space
        2026-03-02 18:00        Date and time (no seconds)
        2026-03-02              Date only (midnight)
        18:00                   Time today
        yesterday               Yesterday at midnight
        yesterday 18:00         Yesterday at specific time
    """
    value = value.strip()

    # Handle "yesterday" keyword
    if value.startswith("yesterday"):
        base = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        rest = value[len("yesterday"):].strip()
        if rest:
            # Parse time portion
            for fmt in ("%H:%M:%S", "%H:%M"):
                try:
                    t = datetime.strptime(rest, fmt)
                    return base.replace(hour=t.hour, minute=t.minute, second=t.second)
                except ValueError:
                    continue
            raise typer.BadParameter(f"Cannot parse time in: {value}")
        return base

    # Handle "today" keyword
    if value.startswith("today"):
        base = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        rest = value[len("today"):].strip()
        if rest:
            for fmt in ("%H:%M:%S", "%H:%M"):
                try:
                    t = datetime.strptime(rest, fmt)
                    return base.replace(hour=t.hour, minute=t.minute, second=t.second)
                except ValueError:
                    continue
            raise typer.BadParameter(f"Cannot parse time in: {value}")
        return base

    # Try standard formats
    formats = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    # Try time-only (assume today)
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            t = datetime.strptime(value, fmt)
            now = datetime.now()
            return now.replace(hour=t.hour, minute=t.minute, second=t.second, microsecond=0)
        except ValueError:
            continue

    raise typer.BadParameter(
        f"Cannot parse datetime: '{value}'. "
        "Use formats like: 2026-03-02 18:00, yesterday 18:00, 18:00, yesterday"
    )


@app.command("changes")
def files_changes(
    path: str = typer.Argument("", help="Dropbox path to check (empty for root)"),
    after: str = typer.Option(None, "--after", "-a", help="Show files modified after this time (e.g. 'yesterday 18:00', '2026-03-02 18:00')"),
    before: str = typer.Option(None, "--before", "-b", help="Show files modified before this time"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    recursive: bool = typer.Option(True, "--recursive/--no-recursive", "-R", help="Search recursively (default: true)"),
):
    """
    Show files changed within a date/time range.

    Lists files modified between --after and --before timestamps.
    Uses server_modified time from Dropbox.

    Date formats:
        yesterday, yesterday 18:00, today, today 14:30,
        2026-03-02, 2026-03-02 18:00, 18:00, 2026-03-02T18:00:00

    Examples:
        dropbox files changes /Projects --after "yesterday 18:00" --before "yesterday 20:00"
        dropbox files changes --after yesterday --before today
        dropbox files changes /Documents --after "2026-03-01" --table
        dropbox files changes --after 18:00
    """
    try:
        if not after and not before:
            print_error("At least one of --after or --before is required")
            raise typer.Exit(1)

        after_dt = _parse_datetime(after) if after else None
        before_dt = _parse_datetime(before) if before else None

        if after_dt and before_dt and after_dt >= before_dt:
            print_error(f"--after ({after_dt}) must be before --before ({before_dt})")
            raise typer.Exit(1)

        client = get_client()
        if recursive:
            # Large recursive listings may need more time
            client.set_timeout(300)
            print_info(f"Scanning {path or '/'} recursively...")
        entries = client.list_folder(path=path, recursive=recursive)

        # Filter to files only (folders don't have server_modified)
        # and filter by date range
        filtered = []
        for entry in entries:
            if entry.get("type") != "file":
                continue
            mod_str = entry.get("server_modified")
            if not mod_str:
                continue
            try:
                mod_dt = datetime.fromisoformat(mod_str)
            except (ValueError, TypeError):
                continue
            if after_dt and mod_dt <= after_dt:
                continue
            if before_dt and mod_dt >= before_dt:
                continue
            filtered.append(entry)

        # Sort by server_modified ascending
        filtered.sort(key=lambda e: e.get("server_modified", ""))

        if not filtered:
            range_desc = ""
            if after_dt:
                range_desc += f" after {after_dt}"
            if before_dt:
                range_desc += f" before {before_dt}"
            print_info(f"No files changed{range_desc} in {path or '/'}")
            return

        if table:
            table_data = []
            for entry in filtered:
                table_data.append({
                    "name": entry.get("name", ""),
                    "path": entry.get("path_display", ""),
                    "size": format_size(entry.get("size", 0)),
                    "modified": entry.get("server_modified", "-"),
                })
            print_table(
                table_data,
                ["name", "path", "size", "modified"],
                ["Name", "Path", "Size", "Modified"],
            )
        else:
            print_json(filtered)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def files_download(
    dropbox_path: str = typer.Argument(..., help="Dropbox path or id: to get info/download"),
    local_path: str = typer.Argument(None, help="Local destination path (default: current directory)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display metadata as table"),
):
    """
    Get file/folder info by ID or download a file by path.

    When given an id: argument, returns metadata. When given a path,
    downloads the file to the local filesystem.

    Examples:
        dropbox files get id:abc123def456
        dropbox files get /Documents/report.pdf
        dropbox files get /Documents/report.pdf ./downloads/report.pdf
        dropbox files get /Documents/report.pdf --table
    """
    try:
        client = get_client()

        # If given an id: reference, return metadata instead of downloading
        if dropbox_path.startswith("id:"):
            metadata = client.get_metadata(dropbox_path)

            if table:
                table_data = [{
                    "name": metadata.get("name", ""),
                    "type": metadata.get("type", ""),
                    "path": metadata.get("path_display", ""),
                    "size": format_size(metadata.get("size", 0)) if metadata.get("type") == "file" else "-",
                    "modified": metadata.get("server_modified", "-"),
                }]
                print_table(
                    table_data,
                    ["name", "type", "path", "size", "modified"],
                    ["Name", "Type", "Path", "Size", "Modified"],
                )
            else:
                print_json(metadata)
            return

        # Default local path to filename in current directory
        if local_path is None:
            local_path = os.path.basename(dropbox_path)

        # Expand user home directory
        local_path = os.path.expanduser(local_path)

        # Create parent directories if needed
        parent_dir = os.path.dirname(local_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        metadata = client.download_file(dropbox_path, local_path)
        print_success(f"Downloaded: {metadata['path_display']} -> {local_path}")

        if table:
            table_data = [{
                "name": metadata.get("name", ""),
                "path": metadata.get("path_display", ""),
                "size": format_size(metadata.get("size", 0)),
                "modified": metadata.get("server_modified", "-"),
            }]
            print_table(
                table_data,
                ["name", "path", "size", "modified"],
                ["Name", "Path", "Size", "Modified"],
            )
        else:
            print_json(metadata)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("put")
def files_upload(
    local_path: str = typer.Argument(..., help="Local file path to upload"),
    dropbox_path: str = typer.Argument(None, help="Destination Dropbox path"),
    overwrite: bool = typer.Option(False, "--overwrite", "-o", help="Overwrite existing file"),
):
    """
    Upload a file to Dropbox.

    Examples:
        dropbox files put ./report.pdf /Documents/report.pdf
        dropbox files put ./report.pdf /Documents/
        dropbox files put ./report.pdf --overwrite
    """
    try:
        client = get_client()

        # Expand local path
        local_path = os.path.expanduser(local_path)

        if not os.path.exists(local_path):
            print_error(f"Local file not found: {local_path}")
            raise typer.Exit(1)

        # Default dropbox path to root with same filename
        if dropbox_path is None:
            dropbox_path = "/" + os.path.basename(local_path)
        elif dropbox_path.endswith("/"):
            dropbox_path = dropbox_path + os.path.basename(local_path)

        metadata = client.upload_file(local_path, dropbox_path, overwrite=overwrite)
        print_success(f"Uploaded: {local_path} -> {metadata['path_display']}")
        print_json(metadata)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("rm")
def files_delete(
    path: str = typer.Argument(..., help="Dropbox path to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """
    Delete a file or folder.

    Examples:
        dropbox files rm /Documents/old-file.txt
        dropbox files rm /Temp --force
    """
    try:
        if not force:
            if not typer.confirm(f"Delete '{path}'?"):
                print_info("Aborted")
                raise typer.Exit(0)

        client = get_client()
        metadata = client.delete(path)
        print_success(f"Deleted: {metadata['path_display']}")

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("mkdir")
def files_mkdir(
    path: str = typer.Argument(..., help="Dropbox path for new folder"),
):
    """
    Create a new folder.

    Examples:
        dropbox files mkdir /Projects/NewProject
    """
    try:
        client = get_client()
        metadata = client.create_folder(path)
        print_success(f"Created folder: {metadata['path_display']}")
        print_json(metadata)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("mv")
def files_move(
    from_path: str = typer.Argument(..., help="Source Dropbox path"),
    to_path: str = typer.Argument(..., help="Destination Dropbox path"),
):
    """
    Move a file or folder.

    Examples:
        dropbox files mv /Documents/report.pdf /Archive/report.pdf
        dropbox files mv /Temp/folder /Documents/folder
    """
    try:
        client = get_client()
        metadata = client.move(from_path, to_path)
        print_success(f"Moved: {from_path} -> {metadata['path_display']}")
        print_json(metadata)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("cp")
def files_copy(
    from_path: str = typer.Argument(..., help="Source Dropbox path"),
    to_path: str = typer.Argument(..., help="Destination Dropbox path"),
):
    """
    Copy a file or folder.

    Examples:
        dropbox files cp /Documents/report.pdf /Backup/report.pdf
        dropbox files cp /Projects/template /Projects/new-project
    """
    try:
        client = get_client()
        metadata = client.copy(from_path, to_path)
        print_success(f"Copied: {from_path} -> {metadata['path_display']}")
        print_json(metadata)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("search")
def files_search(
    query: str = typer.Argument(..., help="Search query"),
    path: str = typer.Option("", "--path", "-p", help="Path to search within"),
    max_results: int = typer.Option(100, "--max", "-m", help="Maximum results"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Search for files and folders.

    Examples:
        dropbox files search "report"
        dropbox files search "*.pdf" --path /Documents
        dropbox files search "project" --table
    """
    try:
        client = get_client()
        results = client.search(query, path=path, max_results=max_results)

        if table:
            table_data = []
            for entry in results:
                table_data.append({
                    "type": entry.get("type", "")[0].upper() if entry.get("type") else "",
                    "name": entry.get("name", ""),
                    "path": entry.get("path_display", ""),
                    "size": format_size(entry.get("size", 0)) if entry.get("type") == "file" else "-",
                })
            print_table(
                table_data,
                ["type", "name", "path", "size"],
                ["T", "Name", "Path", "Size"],
            )
        else:
            print_json(results)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("info")
def files_info(
    path: str = typer.Argument(..., help="Dropbox path to get info for"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get detailed information about a file or folder.

    Examples:
        dropbox files info /Documents/report.pdf
    """
    try:
        client = get_client()
        metadata = client.get_metadata(path)

        if table:
            table_data = [{
                "name": metadata.get("name", ""),
                "type": metadata.get("type", ""),
                "path": metadata.get("path_display", ""),
                "size": format_size(metadata.get("size", 0)) if metadata.get("type") == "file" else "-",
                "modified": metadata.get("server_modified", "-"),
            }]
            print_table(
                table_data,
                ["name", "type", "path", "size", "modified"],
                ["Name", "Type", "Path", "Size", "Modified"],
            )
        else:
            print_json(metadata)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("history")
def files_history(
    path: str = typer.Argument(..., help="Dropbox file path"),
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum revisions to show"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Show version history for a file.

    Examples:
        dropbox files history /Documents/report.pdf
        dropbox files history /Documents/report.pdf --limit 20
        dropbox files history /Documents/report.pdf --table
    """
    try:
        client = get_client()
        revisions = client.list_revisions(path, limit=limit)

        if not revisions:
            print_info(f"No revisions found for: {path}")
            return

        if table:
            table_data = []
            for i, rev in enumerate(revisions):
                table_data.append({
                    "#": i + 1,
                    "rev": rev.get("rev", "")[:12],
                    "size": format_size(rev.get("size", 0)),
                    "modified": rev.get("server_modified", "-"),
                })
            print_table(
                table_data,
                ["#", "rev", "size", "modified"],
                ["#", "Revision", "Size", "Modified"],
            )
        else:
            print_json(revisions)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("restore")
def files_restore(
    path: str = typer.Argument(..., help="Dropbox file path to restore"),
    rev: str = typer.Option(..., "--rev", "-r", help="Revision ID to restore to"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """
    Restore a file to a previous version.

    First use 'history' command to find the revision ID, then restore:

    Examples:
        dropbox files history /Documents/report.pdf --table
        dropbox files restore /Documents/report.pdf --rev abc123def456
        dropbox files restore /Documents/report.pdf -r abc123def456 --force
    """
    try:
        if not force:
            if not typer.confirm(f"Restore '{path}' to revision '{rev}'?"):
                print_info("Aborted")
                raise typer.Exit(0)

        client = get_client()
        metadata = client.restore_file(path, rev)
        print_success(f"Restored: {metadata['path_display']} to revision {rev}")
        print_json(metadata)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))
