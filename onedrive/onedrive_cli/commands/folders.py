"""Folders commands for OneDrive CLI.

Manage folders (create, etc.) in OneDrive drives.
"""
import os
import typer
from typing import Optional

from pydantic import BaseModel

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, print_success, print_error, handle_error


app = typer.Typer(help="Manage OneDrive folders", no_args_is_help=True)


def _resolve_drive_id(drive_id: Optional[str]) -> Optional[str]:
    """
    Resolve drive ID from parameter or environment variable.

    If drive_id is explicitly provided, use it.
    Otherwise, check ONEDRIVE_DRIVE_ID environment variable.
    If neither is set, return None to indicate using the user's default drive.

    Args:
        drive_id: Explicitly provided drive ID

    Returns:
        Resolved drive ID or None for default drive
    """
    if drive_id:
        return drive_id
    return os.getenv("ONEDRIVE_DRIVE_ID")


def model_to_dict(item):
    """Convert model or dict to dict for field extraction."""
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


@app.command("create")
def folders_create(
    drive_id: str = typer.Argument(..., help="The drive ID to create the folder in"),
    name: str = typer.Argument(..., help="Name of the new folder"),
    parent: Optional[str] = typer.Option(None, "--parent", "-p", help="Parent folder path (default: root)"),
    conflict: str = typer.Option(
        "fail",
        "--conflict",
        "-c",
        help="Conflict behavior: fail, rename, or replace",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    Create a new folder in OneDrive.

    Creates a folder with the given name. By default creates at the root
    of the drive. Use --parent to specify a different parent folder.

    Conflict behavior options:
      - fail: Return error if folder already exists (default)
      - rename: Automatically rename the new folder
      - replace: Replace the existing folder

    Examples:
        onedrive folders create DRIVE_ID "My Folder"
        onedrive folders create DRIVE_ID "Subfolder" --parent "/Documents"
        onedrive folders create DRIVE_ID "Backup" --conflict rename
        onedrive folders create DRIVE_ID "Reports" --table
    """
    # Validate conflict behavior
    valid_conflicts = ["fail", "rename", "replace"]
    if conflict not in valid_conflicts:
        typer.echo(f"Error: --conflict must be one of: {', '.join(valid_conflicts)}", err=True)
        raise typer.Exit(1)

    try:
        client = get_client()
        folder = client.create_folder(
            drive_id=drive_id,
            name=name,
            parent_path=parent,
            conflict_behavior=conflict,
        )

        print_success(f"Created folder: {folder.name}")

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            folder_dict = model_to_dict(folder)
            folder = {field: folder_dict.get(field) for field in fields}

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([folder], fields, fields)
            else:
                # Convert model to key-value table
                folder_dict = model_to_dict(folder)
                rows = [{"field": k, "value": str(v)} for k, v in folder_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(folder)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


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


@app.command("get")
def folders_get(
    path: str = typer.Argument(..., help="Folder path (e.g., 'Documents/Reports' or '/Documents/Reports')"),
    drive: Optional[str] = typer.Option(
        None,
        "--drive",
        "-d",
        help="Drive ID (uses ONEDRIVE_DRIVE_ID env var or default drive if not specified)",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    Get folder metadata by path.

    Returns folder metadata as JSON if the folder exists.
    Exits with code 1 if the folder doesn't exist (useful for existence checks in scripts).

    Drive resolution order:
      1. --drive option if provided
      2. ONEDRIVE_DRIVE_ID environment variable if set
      3. User's default OneDrive drive

    Examples:
        onedrive folders get "Documents/Reports"
        onedrive folders get "ProgressContentAutomation/WriterDrafts"
        onedrive folders get "My Folder" --drive DRIVE_ID
        onedrive folders get "Reports" --table
        onedrive folders get "Reports" --properties "id,name,webUrl"

    Shell script usage (existence check):
        if onedrive folders get "MyFolder" > /dev/null 2>&1; then
            echo "Folder exists"
        else
            echo "Folder does not exist"
        fi
    """
    try:
        client = get_client()
        resolved_drive_id = _resolve_drive_id(drive)

        folder = client.get_folder_by_path(path=path, drive_id=resolved_drive_id)

        # Verify it's actually a folder
        folder_dict = model_to_dict(folder)
        if not folder_dict.get("folder"):
            print_error(f"Path exists but is not a folder: {path}")
            raise typer.Exit(1)

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            folder = extract_fields([folder], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([folder], fields, fields)
            else:
                # Convert model to key-value table
                folder_dict = model_to_dict(folder)
                rows = [{"field": k, "value": str(v)} for k, v in folder_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(folder)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create-link")
def folders_create_link(
    path: str = typer.Argument(..., help="Folder path (e.g., 'Documents/Reports')"),
    drive: Optional[str] = typer.Option(
        None,
        "--drive",
        "-d",
        help="Drive ID (uses ONEDRIVE_DRIVE_ID env var or default drive if not specified)",
    ),
    link_type: str = typer.Option(
        "view",
        "--type",
        "-t",
        help="Link type: view (read-only), edit (read-write), or embed",
    ),
    scope: Optional[str] = typer.Option(
        None,
        "--scope",
        "-s",
        help="Link scope: anonymous (anyone), organization (org members), users (specific). Defaults to org setting.",
    ),
    expiration: Optional[str] = typer.Option(
        None,
        "--expiration",
        "-e",
        help="Link expiration as ISO 8601 datetime (e.g., 2025-12-31T23:59:59Z)",
    ),
    password: Optional[str] = typer.Option(
        None,
        "--password",
        "-p",
        help="Password for the sharing link (OneDrive Personal only)",
    ),
    table: bool = typer.Option(False, "--table", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    Create a sharing link for a folder.

    Creates a shareable link that grants access to the folder.
    Returns the Permission resource with the sharing link URL.

    Link types:
      - view: Read-only access (default)
      - edit: Read-write access
      - embed: Embeddable link (OneDrive Personal only)

    Link scopes:
      - anonymous: Anyone with the link (may be disabled by admin)
      - organization: Only members of your organization
      - users: Specific users (requires additional invite step)

    Examples:
        onedrive folders share "Documents/Reports"
        onedrive folders share "Shared/Project" --type edit
        onedrive folders share "Public" --scope anonymous
        onedrive folders share "Temp" --expiration 2025-12-31T23:59:59Z
        onedrive folders share "Reports" --properties "link.webUrl"
    """
    # Validate link type
    valid_types = ["view", "edit", "embed"]
    if link_type not in valid_types:
        print_error(f"--type must be one of: {', '.join(valid_types)}")
        raise typer.Exit(1)

    # Validate scope if provided
    if scope:
        valid_scopes = ["anonymous", "organization", "users"]
        if scope not in valid_scopes:
            print_error(f"--scope must be one of: {', '.join(valid_scopes)}")
            raise typer.Exit(1)

    try:
        client = get_client()
        resolved_drive_id = _resolve_drive_id(drive)

        # First, get the folder to obtain its ID
        folder = client.get_folder_by_path(path=path, drive_id=resolved_drive_id)

        # Verify it's actually a folder
        folder_dict = model_to_dict(folder)
        if not folder_dict.get("folder"):
            print_error(f"Path exists but is not a folder: {path}")
            raise typer.Exit(1)

        # Get the drive ID from the folder's parent reference if not explicitly set
        if not resolved_drive_id:
            parent_ref = folder_dict.get("parent_reference") or {}
            resolved_drive_id = parent_ref.get("drive_id")
            if not resolved_drive_id:
                print_error("Could not determine drive ID. Please specify --drive.")
                raise typer.Exit(1)

        # Create the sharing link
        permission = client.create_sharing_link(
            drive_id=resolved_drive_id,
            item_id=folder_dict["id"],
            link_type=link_type,
            scope=scope,
            expiration=expiration,
            password=password,
        )

        print_success(f"Created {link_type} sharing link for: {path}")

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            output = extract_fields([permission], fields)[0]
        else:
            output = permission

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([output], fields, fields)
            else:
                # Convert model to key-value table
                output_dict = model_to_dict(output)
                rows = [{"field": k, "value": str(v)} for k, v in output_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(output)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("invite")
def folders_invite(
    path: str = typer.Argument(..., help="Folder path (e.g., 'Documents/Reports')"),
    emails: str = typer.Argument(..., help="Comma-separated email addresses to invite"),
    role: str = typer.Option(
        "read",
        "--role",
        "-r",
        help="Permission role: read or write",
    ),
    drive: Optional[str] = typer.Option(
        None,
        "--drive",
        "-d",
        help="Drive ID (uses ONEDRIVE_DRIVE_ID env var or default drive if not specified)",
    ),
    message: Optional[str] = typer.Option(
        None,
        "--message",
        "-m",
        help="Optional message to include in the invitation email",
    ),
    no_email: bool = typer.Option(
        False,
        "--no-email",
        help="Don't send email notification to recipients",
    ),
    expiration: Optional[str] = typer.Option(
        None,
        "--expiration",
        "-e",
        help="Permission expiration as ISO 8601 datetime (e.g., 2025-12-31T23:59:59Z)",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    Invite specific people to access a folder.

    Sends sharing invitations to the specified email addresses, granting them
    access to the folder. By default sends an email notification.

    Roles:
      - read: View-only access (default)
      - write: Edit access

    Examples:
        onedrive folders invite "Documents/Reports" "user@example.com"
        onedrive folders invite "Shared/Project" "user1@example.com,user2@example.com" --role write
        onedrive folders invite "Reports" "user@example.com" --message "Here's the folder"
        onedrive folders invite "Reports" "user@example.com" --no-email
        onedrive folders invite "Temp" "user@example.com" --expiration 2025-12-31T23:59:59Z
    """
    # Validate role
    valid_roles = ["read", "write"]
    if role not in valid_roles:
        print_error(f"--role must be one of: {', '.join(valid_roles)}")
        raise typer.Exit(1)

    # Parse email addresses
    email_list = [e.strip() for e in emails.split(",") if e.strip()]
    if not email_list:
        print_error("At least one email address is required")
        raise typer.Exit(1)

    try:
        client = get_client()
        resolved_drive_id = _resolve_drive_id(drive)

        # First, get the folder to obtain its ID
        folder = client.get_folder_by_path(path=path, drive_id=resolved_drive_id)

        # Verify it's actually a folder
        folder_dict = model_to_dict(folder)
        if not folder_dict.get("folder"):
            print_error(f"Path exists but is not a folder: {path}")
            raise typer.Exit(1)

        # Get the drive ID from the folder's parent reference if not explicitly set
        if not resolved_drive_id:
            parent_ref = folder_dict.get("parent_reference") or {}
            resolved_drive_id = parent_ref.get("drive_id")
            if not resolved_drive_id:
                print_error("Could not determine drive ID. Please specify --drive.")
                raise typer.Exit(1)

        # Send invitations
        permissions = client.invite_to_item(
            drive_id=resolved_drive_id,
            item_id=folder_dict["id"],
            recipients=email_list,
            roles=[role],
            send_invitation=not no_email,
            message=message,
            expiration=expiration,
        )

        print_success(f"Invited {len(email_list)} recipient(s) with {role} access to: {path}")

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            output = extract_fields(permissions, fields)
        else:
            output = permissions

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(output, fields, fields)
            else:
                # Show key fields for each permission
                default_fields = ["id", "roles", "granted_to"]
                print_table(output, default_fields, ["ID", "Roles", "Granted To"])
        else:
            print_json(output)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "create": [
        "custom"
    ],
    "create-link": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "invite": [
        "custom"
    ]
}
