"""Main entry point for Cloudflare CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.command_registry import register_commands
from .config import get_config

app = create_app(
    name="cloudflare",
    help="CLI interface for Cloudflare API",
    version=__version__,
)

# Register command modules (local auth/profiles with API verification and standard flags)
from .commands import auth, zones, cache, access_rules, dns
app.add_typer(auth.app, name="auth", help="Manage authentication")
register_commands(app, get_config, zones, name="zones", help="Manage Cloudflare zones")
app.add_typer(cache.app, name="cache", help="Manage Cloudflare cache")
register_commands(app, get_config, access_rules, name="access-rules", help="Manage IP Access rules (whitelist, block, challenge)")
register_commands(app, get_config, dns, name="dns", help="Manage DNS records")
def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
