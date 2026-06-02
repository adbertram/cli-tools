"""Main entry point for Gemini CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands
from .client import ClientError
from .config import get_config

app = create_app(
    name="gemini",
    help="CLI interface for Gemini API",
    version=__version__,
)

# Register command modules
from .commands import auth, chat, files, image, models, usage, video, research
app.add_typer(auth.app, name="auth", help="Manage Gemini API authentication")
register_commands(app, get_config, chat, name="chat", help="Chat and content generation")
register_commands(app, get_config, files, name="files", help="File operations with Gemini Files API")
register_commands(app, get_config, image, name="image", help="Image generation with Nano Banana Pro")
register_commands(app, get_config, models, name="models", help="List available Gemini models")
register_commands(app, get_config, research, name="research", help="Deep Research using Gemini Deep Research Agent")
register_commands(app, get_config, usage, name="usage", help="View API usage statistics")
register_commands(app, get_config, video, name="video", help="Video analysis operations")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
