"""Permission management helpers for Copilot CLI entities.

This module provides reusable functions and configuration for managing
Dataverse record permissions (grant, revoke, list) across different entity types.
"""
import typer
from typing import Optional

from .client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, print_success, print_error


# Entity configuration for permission operations
ENTITY_CONFIG = {
    "prompt": {
        "logical_name": "msdyn_aimodel",
        "id_field": "msdyn_aimodelid",
        "odata_type": "Microsoft.Dynamics.CRM.msdyn_aimodel",
        "display_name": "AI Builder prompt",
    },
    "agent": {
        "logical_name": "bot",
        "id_field": "botid",
        "odata_type": "Microsoft.Dynamics.CRM.bot",
        "display_name": "agent",
    },
    "agent_flow": {
        "logical_name": "workflow",
        "id_field": "workflowid",
        "odata_type": "Microsoft.Dynamics.CRM.workflow",
        "display_name": "agent flow",
    },
}


# Access level mapping
ACCESS_LEVELS = {
    "read": "ReadAccess",
    "write": "WriteAccess",
    "delete": "DeleteAccess",
    "share": "ShareAccess",
    "assign": "AssignAccess",
    "full": "ReadAccess,WriteAccess,DeleteAccess,ShareAccess,AssignAccess",
}


def grant_permission(
    entity_type: str,
    entity_id: str,
    principal_id: str,
    level: str = "read",
) -> None:
    """
    Grant access to an entity for a principal.

    Args:
        entity_type: Entity type key from ENTITY_CONFIG (e.g., "prompt", "agent")
        entity_id: The GUID of the entity record
        principal_id: The GUID of the systemuser to grant access to
        level: Access level key from ACCESS_LEVELS (e.g., "read", "write", "full")

    Raises:
        typer.Exit: On error
    """
    config = ENTITY_CONFIG.get(entity_type)
    if not config:
        print_error(f"Unknown entity type: {entity_type}")
        raise typer.Exit(1)

    access_mask = ACCESS_LEVELS.get(level.lower())
    if not access_mask:
        print_error(f"Unknown access level: {level}. Valid options: {', '.join(ACCESS_LEVELS.keys())}")
        raise typer.Exit(1)

    try:
        client = get_client()
        client.grant_access(
            odata_type=config["odata_type"],
            id_field=config["id_field"],
            entity_id=entity_id,
            principal_id=principal_id,
            access_mask=access_mask,
        )
        print_success(f"Granted {access_mask} to {config['display_name']} {entity_id}")
    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


def revoke_permission(
    entity_type: str,
    entity_id: str,
    principal_id: str,
) -> None:
    """
    Revoke all access to an entity for a principal.

    Args:
        entity_type: Entity type key from ENTITY_CONFIG
        entity_id: The GUID of the entity record
        principal_id: The GUID of the systemuser to revoke access from

    Raises:
        typer.Exit: On error
    """
    config = ENTITY_CONFIG.get(entity_type)
    if not config:
        print_error(f"Unknown entity type: {entity_type}")
        raise typer.Exit(1)

    try:
        client = get_client()
        client.revoke_access(
            odata_type=config["odata_type"],
            id_field=config["id_field"],
            entity_id=entity_id,
            principal_id=principal_id,
        )
        print_success(f"Revoked access from {config['display_name']} {entity_id}")
    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


def list_permissions(
    entity_type: str,
    entity_id: str,
    table_format: bool = False,
    limit: int = 100,
    filter: Optional[list[str]] = None,
    properties: Optional[str] = None,
) -> None:
    """
    List all principals with explicit access to an entity.

    Args:
        entity_type: Entity type key from ENTITY_CONFIG
        entity_id: The GUID of the entity record
        table_format: If True, output as formatted table; otherwise JSON
        limit: Maximum number of results to return
        filter: Filter expressions using field:op:value syntax
        properties: Comma-separated list of fields to include in output

    Raises:
        typer.Exit: On error
    """
    config = ENTITY_CONFIG.get(entity_type)
    if not config:
        print_error(f"Unknown entity type: {entity_type}")
        raise typer.Exit(1)

    try:
        client = get_client()
        principals = client.list_principals_with_access(
            entity_logical_name=config["logical_name"],
            entity_id=entity_id,
        )

        # Enrich with user names
        enriched = []
        for p in principals:
            try:
                user = client.get_systemuser_by_id(p["principal_id"])
                p["name"] = user.get("fullname", "Unknown")
                p["email"] = user.get("internalemailaddress", "")
            except ClientError:
                p["name"] = "Unknown"
                p["email"] = ""
            enriched.append(p)

        # Apply filters
        if filter:
            from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
            try:
                validate_filters(filter)
                enriched = apply_filters(enriched, filter)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Apply limit
        enriched = enriched[:limit]

        # Apply properties filter
        if properties:
            property_list = [p.strip() for p in properties.split(",")]
            enriched = [{k: v for k, v in item.items() if k in property_list} for item in enriched]

        if table_format:
            if not enriched:
                print("No explicit permissions found.")
                return
            print_table(
                enriched,
                columns=["name", "principal_type", "access_rights_display", "principal_id"],
                headers=["Name", "Type", "Access", "Principal ID"],
            )
        else:
            print_json(enriched)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


def create_permissions_app(entity_type: str) -> typer.Typer:
    """
    Create a Typer app with grant, revoke, and list commands for an entity type.

    This factory function creates a reusable permissions subcommand group
    that can be added to any entity's command module.

    Args:
        entity_type: Entity type key from ENTITY_CONFIG

    Returns:
        typer.Typer: Configured app with permission commands
    """
    config = ENTITY_CONFIG.get(entity_type, {})
    display_name = config.get("display_name", entity_type)

    app = typer.Typer(help=f"Manage permissions for {display_name}s")

    @app.command("grant")
    def cmd_grant(
        entity_id: str = typer.Argument(..., help=f"The {display_name} ID (GUID)"),
        principal: str = typer.Option(..., "--principal", "-p", help="User ID (GUID) to grant access to"),
        level: str = typer.Option("read", "--level", "-l", help="Access level: read, write, delete, share, assign, full"),
    ):
        """Grant access to a principal (user or service principal)."""
        grant_permission(entity_type, entity_id, principal, level)

    @app.command("revoke")
    def cmd_revoke(
        entity_id: str = typer.Argument(..., help=f"The {display_name} ID (GUID)"),
        principal: str = typer.Option(..., "--principal", "-p", help="User ID (GUID) to revoke access from"),
    ):
        """Revoke all access from a principal."""
        revoke_permission(entity_type, entity_id, principal)

    @app.command("list")
    def cmd_list(
        entity_id: str = typer.Argument(..., help=f"The {display_name} ID (GUID)"),
        table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
        limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results to return"),
        filter: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Filter results using field:op:value syntax"),
        properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of fields to include in output"),
    ):
        """List all principals with explicit access."""
        list_permissions(entity_type, entity_id, table, limit=limit, filter=filter, properties=properties)

    @app.command("get")
    def cmd_get(
        entity_id: str = typer.Argument(..., help=f"The {display_name} ID (GUID)"),
        principal_id: str = typer.Argument(..., help="Principal (user/service principal) object ID (GUID)"),
        table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
    ):
        """Get permissions for a specific principal on this entity."""
        try:
            client = get_client()
            principals = client.list_principals_with_access(
                entity_logical_name=config["logical_name"],
                entity_id=entity_id,
            )

            # Find the specific principal
            match = [p for p in principals if p.get("principal_id") == principal_id]

            if not match:
                print_json({"principal_id": principal_id, "access_rights_display": "None", "message": "No explicit permissions found"})
                return

            # Enrich with user name
            result = match[0]
            try:
                user = client.get_systemuser_by_id(principal_id)
                result["name"] = user.get("fullname", "Unknown")
                result["email"] = user.get("internalemailaddress", "")
            except ClientError:
                result["name"] = "Unknown"
                result["email"] = ""

            if table:
                print_table(
                    [result],
                    columns=["name", "principal_type", "access_rights_display", "principal_id"],
                    headers=["Name", "Type", "Access", "Principal ID"],
                )
            else:
                print_json(result)

        except ClientError as e:
            print_error(str(e))
            raise typer.Exit(1)

    return app
