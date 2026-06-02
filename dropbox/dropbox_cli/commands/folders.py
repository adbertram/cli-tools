"""Folder operation commands for Dropbox CLI."""
import typer

from ..client import get_client
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
    "restore": [
        "oauth"
    ]
}

app = typer.Typer(help="Manage folders")


@app.command("restore")
def folders_restore(
    path: str = typer.Argument(..., help="Dropbox path to deleted folder"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
    table: bool = typer.Option(False, "--table", "-t", help="Display results as table"),
):
    """
    Restore a deleted folder and all its contents.

    This command finds all deleted files within a folder and restores them
    to their last known state before deletion.

    Examples:
        dropbox folders restore /Projects/old-project
        dropbox folders restore /Documents/deleted-folder --force
        dropbox folders restore /Backup/removed --table
    """
    try:
        if not force:
            if not typer.confirm(f"Restore deleted folder '{path}' and all its contents?"):
                print_info("Aborted")
                raise typer.Exit(0)

        client = get_client()
        print_info(f"Scanning for deleted files in '{path}'...")
        result = client.restore_deleted_folder(path)

        if result["restored_count"] == 0 and result["error_count"] == 0:
            print_info("No deleted files found to restore")
            raise typer.Exit(0)

        print_success(f"Restored {result['restored_count']} files")
        if result["error_count"] > 0:
            print_error(f"Failed to restore {result['error_count']} files")

        if table:
            if result["restored"]:
                table_data = []
                for item in result["restored"]:
                    table_data.append({
                        "name": item.get("name", ""),
                        "path": item.get("path_display", ""),
                        "size": format_size(item.get("size", 0)) if item.get("type") == "file" else "-",
                    })
                print_info("\nRestored files:")
                print_table(
                    table_data,
                    ["name", "path", "size"],
                    ["Name", "Path", "Size"],
                )
            if result["errors"]:
                print_info("\nErrors:")
                print_table(
                    result["errors"],
                    ["path", "error"],
                    ["Path", "Error"],
                )
        else:
            print_json(result)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))
