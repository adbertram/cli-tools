"""Items commands for OneDrive CLI.

Manage files and folders (drive items) in OneDrive drives.
"""
import typer
from pathlib import Path
from typing import Optional, List

from pydantic import BaseModel

from ..client import get_client
from ..filter_map import apply_filters
from cli_tools_shared.output import print_json, print_table, print_success, print_info, handle_error


app = typer.Typer(help="Manage OneDrive items (files and folders)", no_args_is_help=True)


def model_to_dict(item):
    """Convert model or dict to dict for field extraction."""
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


def extract_field(item, field: str):
    """Extract a field value, supporting dot-notation for nested fields."""
    data = model_to_dict(item)
    parts = field.split(".")
    value = data
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def extract_fields(items: list, fields: list) -> list:
    """Extract specified fields from items, supporting dot-notation."""
    result = []
    for item in items:
        extracted = {}
        for field in fields:
            value = extract_field(item, field)
            extracted[field] = value
        result.append(extracted)
    return result


def format_size(size_bytes: Optional[int]) -> str:
    """Format size in bytes to human-readable format."""
    if size_bytes is None:
        return "-"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(size_bytes) < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


@app.command("list")
def items_list(
    drive_id: str = typer.Argument(..., help="The drive ID to list items from"),
    path: Optional[str] = typer.Argument(None, help="Folder path (default: root)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of items to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List items in a drive folder.

    List files and folders in the specified drive. If path is omitted,
    lists items at the root of the drive.

    Examples:
        onedrive items list DRIVE_ID
        onedrive items list DRIVE_ID /Documents
        onedrive items list DRIVE_ID --table
        onedrive items list DRIVE_ID --properties "id,name,size"
        onedrive items list DRIVE_ID /Documents --limit 50
    """
    try:
        client = get_client()
        items = client.list_items(drive_id=drive_id, path=path, limit=limit, filters=filter)

        if filter:
            items = apply_filters([model_to_dict(item) for item in items], filter)

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            items = extract_fields(items, fields)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(items, fields, fields)
            else:
                # Custom table with item type indicator
                table_data = []
                for item in items:
                    item_dict = model_to_dict(item)
                    item_type = "folder" if item_dict.get("folder") else "file"
                    table_data.append({
                        "name": item_dict.get("name"),
                        "type": item_type,
                        "size": format_size(item_dict.get("size")) if item_type == "file" else "-",
                        "id": item_dict.get("id"),
                    })
                print_table(
                    table_data,
                    ["name", "type", "size", "id"],
                    ["Name", "Type", "Size", "ID"],
                )
        else:
            print_json(items)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def items_get(
    drive_id: str = typer.Argument(..., help="The drive ID"),
    item_ref: str = typer.Argument(..., help="Item ID or path (e.g., 'ABC123' or '/Documents/file.txt')"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    Get details for a specific item.

    Item can be specified by ID or by path.

    Examples:
        onedrive items get DRIVE_ID ITEM_ID
        onedrive items get DRIVE_ID /Documents/report.pdf
        onedrive items get DRIVE_ID ITEM_ID --table
        onedrive items get DRIVE_ID ITEM_ID --properties "id,name,size,webUrl"
    """
    try:
        client = get_client()
        item = client.get_item(drive_id=drive_id, item_ref=item_ref)

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            item = extract_fields([item], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([item], fields, fields)
            else:
                # Convert model to key-value table
                item_dict = model_to_dict(item)
                rows = [{"field": k, "value": str(v)} for k, v in item_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(item)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("upload")
def items_upload(
    drive_id: str = typer.Argument(..., help="The drive ID to upload to"),
    local_path: str = typer.Argument(..., help="Local file path to upload"),
    remote_path: str = typer.Argument(..., help="Remote path (e.g., '/Documents/file.txt')"),
    table: bool = typer.Option(False, "--table", "-t", help="Display result as table"),
):
    """
    Upload a file to OneDrive.

    Automatically uses simple upload for files < 4MB, resumable upload
    for larger files.

    Examples:
        onedrive items upload DRIVE_ID ./report.pdf /Documents/report.pdf
        onedrive items upload DRIVE_ID ./data.csv /Backups/data.csv --table
    """
    try:
        # Validate local path
        local_path_obj = Path(local_path)
        if not local_path_obj.exists():
            from cli_tools_shared.output import print_error
            print_error(f"Local file not found: {local_path}")
            raise typer.Exit(1)

        if not local_path_obj.is_file():
            from cli_tools_shared.output import print_error
            print_error(f"Not a file: {local_path}")
            raise typer.Exit(1)

        file_size = local_path_obj.stat().st_size
        print_info(f"Uploading {local_path_obj.name} ({format_size(file_size)})...")

        client = get_client()
        item = client.upload_item(drive_id=drive_id, local_path=local_path, remote_path=remote_path)

        print_success(f"Uploaded: {item.name}")

        if table:
            item_dict = model_to_dict(item)
            rows = [{"field": k, "value": str(v)} for k, v in item_dict.items() if v is not None]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(item)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("download")
def items_download(
    drive_id: str = typer.Argument(..., help="The drive ID"),
    item_ref: str = typer.Argument(..., help="Item ID or path to download"),
    local_path: str = typer.Argument(..., help="Local path to save the file"),
):
    """
    Download a file from OneDrive.

    Item can be specified by ID or by path.

    Examples:
        onedrive items download DRIVE_ID ITEM_ID ./downloaded.pdf
        onedrive items download DRIVE_ID /Documents/report.pdf ./report.pdf
    """
    try:
        print_info(f"Downloading to {local_path}...")

        client = get_client()
        result_path = client.download_item(drive_id=drive_id, item_ref=item_ref, local_path=local_path)

        print_success(f"Downloaded: {result_path}")
        print_json({"path": result_path, "success": True})

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def items_delete(
    drive_id: str = typer.Argument(..., help="The drive ID"),
    item_ref: str = typer.Argument(..., help="Item ID or path to delete"),
    force: bool = typer.Option(False, "--force", "-F", help="Skip confirmation prompt"),
):
    """
    Delete a file or folder from OneDrive.

    Item can be specified by ID or by path. Use --force to skip
    the confirmation prompt.

    Examples:
        onedrive items delete DRIVE_ID ITEM_ID
        onedrive items delete DRIVE_ID /Documents/old-file.txt
        onedrive items delete DRIVE_ID ITEM_ID --force
    """
    try:
        # Get item info first to show what will be deleted
        client = get_client()

        if not force:
            item = client.get_item(drive_id=drive_id, item_ref=item_ref)
            item_type = "folder" if item.folder else "file"
            confirm = typer.confirm(f"Delete {item_type} '{item.name}'?")
            if not confirm:
                print_info("Cancelled")
                raise typer.Exit(0)

        client.delete_item(drive_id=drive_id, item_ref=item_ref)
        print_success(f"Deleted: {item_ref}")
        print_json({"deleted": item_ref, "success": True})

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


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
