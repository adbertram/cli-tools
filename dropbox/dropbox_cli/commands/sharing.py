"""Sharing commands for Dropbox CLI."""
import os
import typer
from typing import Optional

from ..client import get_client, ClientError
from ..output import (
    print_json,
    print_table,
    print_error,
    print_info,
    print_success,
    handle_error,
    format_size,
)

COMMAND_CREDENTIALS = {
    "download": [
        "oauth"
    ],
    "info": [
        "oauth"
    ],
    "ls": [
        "oauth"
    ]
}

app = typer.Typer(help="Work with shared links and folders")


@app.command("info")
def sharing_info(
    url: str = typer.Argument(..., help="Shared link URL"),
    path: Optional[str] = typer.Option(None, "--path", "-p", help="Path within shared folder"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get metadata for a shared link.

    Examples:
        dropbox sharing info "https://www.dropbox.com/scl/fo/..."
        dropbox sharing info "https://www.dropbox.com/scl/fo/..." --table
        dropbox sharing info "https://www.dropbox.com/scl/fo/..." --path /subfolder
    """
    try:
        client = get_client()
        metadata = client.get_shared_link_metadata(url, path=path)

        if table:
            table_data = [{
                "name": metadata.get("name", ""),
                "type": metadata.get("type", ""),
                "path": metadata.get("path_lower", ""),
                "size": format_size(metadata.get("size", 0)) if metadata.get("type") == "file" else "-",
            }]
            print_table(
                table_data,
                ["name", "type", "path", "size"],
                ["Name", "Type", "Path", "Size"],
            )
        else:
            print_json(metadata)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("ls")
def sharing_list(
    url: str = typer.Argument(..., help="Shared folder link URL"),
    path: str = typer.Option("", "--path", "-p", help="Path within shared folder"),
    long: bool = typer.Option(False, "--long", "-l", help="Show detailed information"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    List contents of a shared folder.

    Examples:
        dropbox sharing ls "https://www.dropbox.com/scl/fo/..."
        dropbox sharing ls "https://www.dropbox.com/scl/fo/..." --table
        dropbox sharing ls "https://www.dropbox.com/scl/fo/..." --path /subfolder -l
    """
    try:
        client = get_client()
        entries = client.list_shared_folder_contents(url, path=path)

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


@app.command("download")
def sharing_download(
    url: str = typer.Argument(..., help="Shared folder link URL"),
    local_path: str = typer.Argument(None, help="Local destination directory (default: folder name)"),
    path: str = typer.Option("", "--path", "-p", help="Path within shared folder to download"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress progress output"),
):
    """
    Download all contents of a shared folder.

    Examples:
        dropbox sharing download "https://www.dropbox.com/scl/fo/..."
        dropbox sharing download "https://www.dropbox.com/scl/fo/..." ./downloads
        dropbox sharing download "https://www.dropbox.com/scl/fo/..." --path /subfolder
        dropbox sharing download "https://www.dropbox.com/scl/fo/..." -q
    """
    try:
        client = get_client()

        # Get folder name from metadata if local_path not specified
        if local_path is None:
            metadata = client.get_shared_link_metadata(url, path=path if path else None)
            local_path = metadata.get("name", "shared_folder")

        # Expand user home directory
        local_path = os.path.expanduser(local_path)

        # Progress callback
        def progress(action: str, item_path: str):
            if not quiet:
                if action == "folder":
                    print_info(f"Creating folder: {item_path}")
                else:
                    print_info(f"Downloading: {item_path}")

        stats = client.download_shared_folder(
            url=url,
            local_path=local_path,
            path=path,
            progress_callback=progress,
        )

        # Print summary
        print_success(
            f"Downloaded {stats['files_downloaded']} files, "
            f"created {stats['folders_created']} folders "
            f"({format_size(stats['total_bytes'])})"
        )

        if stats["errors"]:
            print_error(f"{len(stats['errors'])} errors occurred:")
            for err in stats["errors"]:
                print_error(f"  {err['path']}: {err['error']}")

        print_json(stats)

    except Exception as e:
        raise typer.Exit(handle_error(e))