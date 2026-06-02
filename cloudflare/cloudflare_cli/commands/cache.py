"""Cache commands for Cloudflare CLI."""
import typer

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, print_success, handle_error


app = typer.Typer(help="Manage Cloudflare cache", no_args_is_help=True)


@app.command("purge")
def cache_purge(
    zone_id: str = typer.Argument(..., help="The zone ID to purge cache for"),
    force: bool = typer.Option(False, "--force", "-F", help="Skip confirmation prompt"),
    table: bool = typer.Option(False, "--table", "-t", help="Display result as table"),
):
    """
    Purge all cache for a zone.

    WARNING: This will purge ALL cached content for the zone.

    Examples:
        cloudflare cache purge ZONE_ID
        cloudflare cache purge ZONE_ID --force
        cloudflare cache purge ZONE_ID --table
    """
    try:
        # Confirmation prompt unless --force is specified
        if not force:
            confirm = typer.confirm(
                f"Purge ALL cache for zone {zone_id}? This cannot be undone.",
                default=False
            )
            if not confirm:
                print_success("Cache purge cancelled")
                raise typer.Exit(0)

        client = get_client()
        # Returns PurgeResult model
        result = client.purge_cache(zone_id)

        if table:
            print_table(
                [{"id": result.id, "status": "purged"}],
                ["id", "status"],
                ["Purge ID", "Status"],
            )
        else:
            print_json({"id": result.id, "status": "purged", "zone_id": zone_id})

        print_success(f"Cache purged successfully for zone {zone_id}")

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))
