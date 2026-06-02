"""Main entry point for LastPass CLI wrapper."""
from . import __version__
import typer
from .client import ClientError
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app

app = create_app(name="lastpass", help="LastPass password manager CLI wrapper", version=__version__)

# Register command modules
from .commands import auth, items
from cli_tools_shared.command_registry import register_commands
from .config import get_config

app.add_typer(auth.app, name="auth", help="Manage LastPass authentication")
app.add_typer(create_cache_app(get_config), name="cache")
register_commands(app, get_config, items, name="items", help="Manage vault entries")


@app.command("sync")
def sync_vault():
    """
    Sync local vault cache with LastPass servers.

    Examples:
        lastpass sync
    """
    from .client import get_client
    from cli_tools_shared.output import print_success, handle_error
    try:
        client = get_client()
        result = client.sync()
        if result["success"]:
            print_success(result.get("message") or "Vault synced")
        else:
            from cli_tools_shared.output import print_error
            print_error(result.get("message", "Sync failed"))
            raise typer.Exit(1)
    except ClientError as e:
        raise typer.Exit(handle_error(e))


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
