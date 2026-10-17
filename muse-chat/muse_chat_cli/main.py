"""Main entry point for muse-chat."""

from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app

from . import __version__
from .commands.chat import app as chat_app
from .commands.side import app as side_app
from .config import get_config


app = create_app(
    name="muse-chat",
    help="Chat with Muse through its web app",
    version=__version__,
)
app.add_typer(create_auth_app(get_config, tool_name="muse-chat"), name="auth")
app.add_typer(chat_app, name="chat")
app.add_typer(side_app, name="side")
app.add_typer(create_cache_app(get_config), name="cache")


def main() -> None:
    """Run muse-chat."""
    run_app(app)


if __name__ == "__main__":
    main()
