"""Entry point for the CJ Affiliate CLI."""

from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

from . import __version__
from .commands import advertisers, links, relationships
from .config import get_config


app = create_app(
    name="cj",
    help="CLI interface for CJ Affiliate (publisher).",
    version=__version__,
)

# Domain command groups -----------------------------------------------
# ``register_commands`` wires the COMMAND_CREDENTIALS table into each
# Typer group so missing creds are caught at command dispatch time.
register_commands(
    app,
    get_config,
    advertisers,
    name="advertisers",
    help="Discover CJ advertiser programs",
)
register_commands(
    app,
    get_config,
    relationships,
    name="relationships",
    help="Manage publisher-to-advertiser relationships (list / apply)",
)
register_commands(
    app,
    get_config,
    links,
    name="links",
    help="Search creatives and generate affiliate tracking URLs",
)

# Shared command groups ------------------------------------------------
app.add_typer(create_auth_app(get_config, tool_name="cj"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Run the Typer app via the shared runner."""
    run_app(app)


if __name__ == "__main__":
    main()
