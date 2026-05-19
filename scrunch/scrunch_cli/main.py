"""Main entry point for Scrunch CLI."""
from . import __version__
from .config import get_config
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

app = create_app(name="scrunch", help="CLI interface for Scrunch AI API", version=__version__)

# Register command modules
from .commands import brands, competitors, personas, prompts, query, responses, page_audits, agent_traffic

register_commands(app, get_config, brands, name="brands", help="Manage brands")
register_commands(app, get_config, competitors, name="competitors", help="Manage brand competitors")
register_commands(app, get_config, personas, name="personas", help="Manage brand personas")
register_commands(app, get_config, prompts, name="prompts", help="Manage brand prompts")
register_commands(app, get_config, query, name="query", help="Query aggregated metrics")
register_commands(app, get_config, responses, name="responses", help="View AI responses")
register_commands(app, get_config, page_audits, name="page-audits", help="Manage page audits")
register_commands(app, get_config, agent_traffic, name="agent-traffic", help="View agent traffic data")
# Register shared apps
app.add_typer(create_auth_app(get_config, tool_name="scrunch"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
