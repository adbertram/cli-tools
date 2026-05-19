"""Link commands for OneDrive CLI.

Manage sharing links and permissions for OneDrive items.
"""
import typer
from typing import Optional, List

from pydantic import BaseModel

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, print_success, print_info, handle_error


app = typer.Typer(help="Manage sharing links", no_args_is_help=True)


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


@app.command("create")
def link_create(
    drive_id: str = typer.Argument(..., help="The drive ID"),
    item_id: str = typer.Argument(..., help="The item ID to create a sharing link for"),
    link_type: str = typer.Option("view", "--type", "-t", help="Link type: view, edit, or embed"),
    scope: Optional[str] = typer.Option(None, "--scope", "-s", help="Link scope: anonymous (anyone), organization, or users"),
    expiration: Optional[str] = typer.Option(None, "--expiration", "-e", help="Expiration datetime (ISO 8601)"),
    password: Optional[str] = typer.Option(None, "--password", "-p", help="Password for the link (OneDrive Personal only)"),
    table: bool = typer.Option(False, "--table", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    Create a sharing link for a file or folder.

    Creates a new sharing link that can be shared with others. The link type
    determines the permissions granted:

    - view: Read-only access
    - edit: Read-write access
    - embed: Embeddable link (for files that support embedding)

    The scope determines who can use the link:

    - anonymous: Anyone with the link (no sign-in required)
    - organization: Only members of your organization
    - users: Only specific people (use invite instead)

    Examples:
        # Create a view-only link accessible to anyone
        onedrive link create DRIVE_ID ITEM_ID --scope anonymous

        # Create an edit link for organization members
        onedrive link create DRIVE_ID ITEM_ID --type edit --scope organization

        # Create a link with expiration
        onedrive link create DRIVE_ID ITEM_ID --scope anonymous --expiration 2025-12-31T23:59:59Z
    """
    try:
        client = get_client()
        permission = client.create_sharing_link(
            drive_id=drive_id,
            item_id=item_id,
            link_type=link_type,
            scope=scope,
            expiration=expiration,
            password=password,
        )

        # Extract the web URL for easy access
        perm_dict = model_to_dict(permission)
        link_url = perm_dict.get("link", {}).get("web_url") if perm_dict.get("link") else None

        if link_url:
            print_success(f"Created sharing link: {link_url}")
        else:
            print_success("Created sharing link")

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            perm_dict = extract_fields([permission], fields)[0]
            permission = perm_dict

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([permission], fields, fields)
            else:
                # Flatten for table display
                rows = [{
                    "id": perm_dict.get("id"),
                    "type": perm_dict.get("link", {}).get("type") if perm_dict.get("link") else None,
                    "scope": perm_dict.get("link", {}).get("scope") if perm_dict.get("link") else None,
                    "web_url": link_url,
                    "expiration": perm_dict.get("expiration_date_time"),
                }]
                print_table(rows, ["id", "type", "scope", "web_url", "expiration"], ["ID", "Type", "Scope", "URL", "Expiration"])
        else:
            print_json(permission)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("list")
def link_list(
    drive_id: str = typer.Argument(..., help="The drive ID"),
    item_id: str = typer.Argument(..., help="The item ID to list permissions for"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List all sharing links and permissions on an item.

    Shows all permissions including sharing links, direct shares, and
    inherited permissions.

    Examples:
        onedrive link list DRIVE_ID ITEM_ID
        onedrive link list DRIVE_ID ITEM_ID --table
    """
    try:
        client = get_client()
        permissions = client.list_permissions(drive_id=drive_id, item_id=item_id)

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            permissions = extract_fields(permissions, fields)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(permissions, fields, fields)
            else:
                # Flatten for table display
                rows = []
                for perm in permissions:
                    perm_dict = model_to_dict(perm)
                    link_info = perm_dict.get("link", {}) or {}
                    rows.append({
                        "id": perm_dict.get("id"),
                        "type": link_info.get("type") or "direct",
                        "scope": link_info.get("scope") or "-",
                        "roles": ", ".join(perm_dict.get("roles") or []),
                        "web_url": link_info.get("web_url") or "-",
                    })
                print_table(rows, ["id", "type", "scope", "roles", "web_url"], ["ID", "Type", "Scope", "Roles", "URL"])
        else:
            print_json(permissions)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def link_update(
    drive_id: str = typer.Argument(..., help="The drive ID"),
    item_id: str = typer.Argument(..., help="The item ID"),
    permission_id: str = typer.Argument(..., help="The permission ID to update"),
    roles: Optional[str] = typer.Option(None, "--roles", "-r", help="New roles: read or write"),
    expiration: Optional[str] = typer.Option(None, "--expiration", "-e", help="New expiration datetime (ISO 8601)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    Update a sharing link's permissions.

    Update the roles or expiration of an existing sharing link or permission.
    Use 'onedrive link list' to find the permission ID.

    Roles:
    - read: View-only access
    - write: Edit access

    Examples:
        # Change permission to write access
        onedrive link update DRIVE_ID ITEM_ID PERM_ID --roles write

        # Set expiration date
        onedrive link update DRIVE_ID ITEM_ID PERM_ID --expiration 2025-12-31T23:59:59Z

        # Change both roles and expiration
        onedrive link update DRIVE_ID ITEM_ID PERM_ID --roles read --expiration 2025-06-30T00:00:00Z
    """
    try:
        # Parse roles if provided
        roles_list = None
        if roles:
            roles_list = [roles.strip()]

        client = get_client()
        permission = client.update_permission(
            drive_id=drive_id,
            item_id=item_id,
            permission_id=permission_id,
            roles=roles_list,
            expiration=expiration,
        )

        print_success(f"Updated permission {permission_id}")

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            permission = extract_fields([permission], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([permission], fields, fields)
            else:
                perm_dict = model_to_dict(permission)
                link_info = perm_dict.get("link", {}) or {}
                rows = [{
                    "id": perm_dict.get("id"),
                    "type": link_info.get("type") or "direct",
                    "scope": link_info.get("scope") or "-",
                    "roles": ", ".join(perm_dict.get("roles") or []),
                    "expiration": perm_dict.get("expiration_date_time") or "-",
                }]
                print_table(rows, ["id", "type", "scope", "roles", "expiration"], ["ID", "Type", "Scope", "Roles", "Expiration"])
        else:
            print_json(permission)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def link_delete(
    drive_id: str = typer.Argument(..., help="The drive ID"),
    item_id: str = typer.Argument(..., help="The item ID"),
    permission_id: str = typer.Argument(..., help="The permission ID to delete"),
    force: bool = typer.Option(False, "--force", "-F", help="Skip confirmation prompt"),
):
    """
    Delete a sharing link or permission.

    Removes access for the specified sharing link or permission.
    Use 'onedrive link list' to find the permission ID.

    Examples:
        onedrive link delete DRIVE_ID ITEM_ID PERM_ID
        onedrive link delete DRIVE_ID ITEM_ID PERM_ID --force
    """
    try:
        client = get_client()

        if not force:
            # Get permission info to show what will be deleted
            perm = client.get_permission(drive_id=drive_id, item_id=item_id, permission_id=permission_id)
            perm_dict = model_to_dict(perm)
            link_info = perm_dict.get("link", {}) or {}
            perm_type = link_info.get("type") or "direct share"
            perm_scope = link_info.get("scope") or ""

            desc = f"{perm_type}"
            if perm_scope:
                desc += f" ({perm_scope})"

            confirm = typer.confirm(f"Delete permission '{permission_id}' ({desc})?")
            if not confirm:
                print_info("Cancelled")
                raise typer.Exit(0)

        client.delete_permission(drive_id=drive_id, item_id=item_id, permission_id=permission_id)
        print_success(f"Deleted permission {permission_id}")
        print_json({"deleted": permission_id, "success": True})

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def link_get(
    drive_id: str = typer.Argument(..., help="The drive ID"),
    item_id: str = typer.Argument(..., help="The item ID"),
    permission_id: str = typer.Argument(..., help="The permission ID to get"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    Get details of a specific sharing link or permission.

    Examples:
        onedrive link get DRIVE_ID ITEM_ID PERM_ID
        onedrive link get DRIVE_ID ITEM_ID PERM_ID --table
    """
    try:
        client = get_client()
        permission = client.get_permission(drive_id=drive_id, item_id=item_id, permission_id=permission_id)

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            permission = extract_fields([permission], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([permission], fields, fields)
            else:
                perm_dict = model_to_dict(permission)
                rows = [{"field": k, "value": str(v)} for k, v in perm_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(permission)

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "create": [
        "custom"
    ],
    "delete": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "update": [
        "custom"
    ]
}
