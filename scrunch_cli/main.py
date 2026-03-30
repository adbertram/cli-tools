"""Main entry point for Scrunch CLI."""
from . import __version__
from .config import get_config
from cli_tools_common import create_app, run_app
from cli_tools_common.auth_commands import create_auth_app
from cli_tools_common.cache_commands import create_cache_app
from cli_tools_common.profiles_commands import create_profiles_app

app = create_app(name="scrunch", help="CLI interface for Scrunch AI API", version=__version__)

# Register command modules
from .commands import brands, competitors, personas, prompts, query, responses, page_audits, agent_traffic

app.add_typer(brands.app, name="brands", help="Manage brands")
app.add_typer(competitors.app, name="competitors", help="Manage brand competitors")
app.add_typer(personas.app, name="personas", help="Manage brand personas")
app.add_typer(prompts.app, name="prompts", help="Manage brand prompts")
app.add_typer(query.app, name="query", help="Query aggregated metrics")
app.add_typer(responses.app, name="responses", help="View AI responses")
app.add_typer(page_audits.app, name="page-audits", help="Manage page audits")
app.add_typer(agent_traffic.app, name="agent-traffic", help="View agent traffic data")

# Register shared apps
app.add_typer(create_auth_app(get_config, tool_name="scrunch"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")
app.add_typer(create_profiles_app(get_config), name="profiles")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
