"""Workspace commands for Slack CLI."""
import typer
from ..client import get_client
from ..config import get_config
from cli_tools_shared.output import print_json, print_table, print_success, print_error, print_info, handle_error

app = typer.Typer(help="Manage Slack workspace")


@app.command("list")
def workspace_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    List all configured workspaces.

    Shows all workspaces you're authenticated with and indicates
    which one is currently active.

    Example:
        slack workspace list
        slack workspace list --table
    """
    try:
        config = get_config()
        workspaces = config.get_all_workspaces()
        active_id = config.active_workspace_id

        if not workspaces:
            print_info("No workspaces configured. Run 'slack auth login' to authenticate.")
            raise typer.Exit(0)

        workspace_data = []
        for ws in workspaces:
            is_active = ws.team_id == active_id
            workspace_data.append({
                "active": "*" if is_active else "",
                "team_id": ws.team_id,
                "team_name": ws.team_name,
                "domain": ws.team_domain,
                "added_at": ws.added_at[:10] if ws.added_at else "unknown",
            })

        if table:
            print_table(
                workspace_data,
                ["active", "team_name", "domain", "team_id", "added_at"],
                ["Active", "Workspace", "Domain", "Team ID", "Added"],
            )
        else:
            print_json({
                "active_workspace": active_id,
                "workspaces": workspace_data,
            })

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("switch")
def workspace_switch(
    workspace: str = typer.Argument(..., help="Workspace ID or domain to switch to"),
):
    """
    Switch to a different workspace.

    You can specify either the workspace ID (e.g., T0F2BD3QA)
    or the domain (e.g., atablog).

    Example:
        slack workspace switch T0F2BD3QA
        slack workspace switch atablog
    """
    try:
        config = get_config()
        workspaces = config.get_all_workspaces()

        if not workspaces:
            print_error("No workspaces configured. Run 'slack auth login' to authenticate.")
            raise typer.Exit(2)

        # Try to find workspace by ID first
        target_workspace = config.get_workspace(workspace)

        # If not found by ID, try to find by domain or name
        if not target_workspace:
            workspace_lower = workspace.lower()
            for ws in workspaces:
                if ws.team_domain.lower() == workspace_lower or ws.team_name.lower() == workspace_lower:
                    target_workspace = ws
                    break

        if not target_workspace:
            print_error(f"Workspace '{workspace}' not found.")
            print_info("\nAvailable workspaces:")
            for ws in workspaces:
                print_info(f"  - {ws.team_name} ({ws.team_domain}) - ID: {ws.team_id}")
            raise typer.Exit(2)

        # Check if already active
        if config.active_workspace_id == target_workspace.team_id:
            print_info(f"Workspace '{target_workspace.team_name}' is already active.")
            raise typer.Exit(0)

        # Switch workspace
        config.set_active_workspace(target_workspace.team_id)
        print_success(f"Switched to workspace: {target_workspace.team_name}")
        print_info(f"Domain: {target_workspace.team_domain}")
        print_info(f"Team ID: {target_workspace.team_id}")

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("remove")
def workspace_remove(
    workspace: str = typer.Argument(..., help="Workspace ID or domain to remove"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """
    Remove a workspace from the CLI.

    This removes the stored credentials for the specified workspace.
    You can specify either the workspace ID or domain.

    Example:
        slack workspace remove T0F2BD3QA
        slack workspace remove atablog --force
    """
    try:
        config = get_config()
        workspaces = config.get_all_workspaces()

        if not workspaces:
            print_error("No workspaces configured.")
            raise typer.Exit(2)

        # Try to find workspace by ID first
        target_workspace = config.get_workspace(workspace)

        # If not found by ID, try to find by domain or name
        if not target_workspace:
            workspace_lower = workspace.lower()
            for ws in workspaces:
                if ws.team_domain.lower() == workspace_lower or ws.team_name.lower() == workspace_lower:
                    target_workspace = ws
                    break

        if not target_workspace:
            print_error(f"Workspace '{workspace}' not found.")
            raise typer.Exit(2)

        # Confirm removal
        if not force:
            confirm = typer.confirm(f"Remove workspace '{target_workspace.team_name}'?")
            if not confirm:
                print_info("Cancelled.")
                raise typer.Exit(0)

        # Remove workspace
        was_active = config.active_workspace_id == target_workspace.team_id
        config.remove_workspace(target_workspace.team_id)
        print_success(f"Removed workspace: {target_workspace.team_name}")

        # If this was the last workspace, clear .env too
        remaining = config.get_all_workspaces()
        if not remaining:
            config.clear_credentials()
            print_info("No workspaces remaining. Run 'slack auth login' to authenticate.")
        elif was_active:
            new_active = config.active_workspace
            if new_active:
                print_info(f"Active workspace is now: {new_active.team_name}")

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("info")
def workspace_info(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get information about the current workspace.

    Fetches live workspace information from the Slack API
    for the currently active workspace.

    Example:
        slack workspace info
        slack workspace info --table
    """
    try:
        config = get_config()
        active = config.active_workspace

        if active:
            print_info(f"Active workspace: {active.team_name} ({active.team_domain})", )

        client = get_client()
        response = client.get_team_info()
        team = response.get("team", {})

        # Update workspace info if we have a migrated workspace
        if config.active_workspace_id == "_migrated":
            config.finalize_migration(
                real_team_id=team.get("id"),
                team_name=team.get("name"),
                team_domain=team.get("domain"),
            )

        if table:
            table_data = [
                {
                    "id": team.get("id"),
                    "name": team.get("name"),
                    "domain": team.get("domain"),
                    "email_domain": team.get("email_domain", ""),
                }
            ]
            print_table(
                table_data,
                ["id", "name", "domain", "email_domain"],
                ["ID", "Name", "Domain", "Email Domain"],
            )
        else:
            print_json(team)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("whoami")
def whoami(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Show current authentication information.

    Example:
        slack workspace whoami
        slack workspace whoami --table
    """
    try:
        config = get_config()
        active = config.active_workspace

        if active:
            print_info(f"Active workspace: {active.team_name} ({active.team_domain})", )

        client = get_client()
        response = client.auth_test()

        # Update workspace info if we have a migrated workspace
        if config.active_workspace_id == "_migrated":
            config.finalize_migration(
                real_team_id=response.get("team_id"),
                team_name=response.get("team"),
                team_domain=response.get("url", "").replace("https://", "").split(".")[0],
            )

        if table:
            table_data = [
                {
                    "user": response.get("user"),
                    "user_id": response.get("user_id"),
                    "team": response.get("team"),
                    "team_id": response.get("team_id"),
                    "url": response.get("url"),
                }
            ]
            print_table(
                table_data,
                ["user", "user_id", "team", "team_id", "url"],
                ["User", "User ID", "Team", "Team ID", "URL"],
            )
        else:
            print_json(response)

    except Exception as e:
        raise typer.Exit(handle_error(e))
