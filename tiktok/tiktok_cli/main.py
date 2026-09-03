"""Main entry point for Tiktok CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.command_registry import register_commands
from .client import ClientError
from .config import get_config

app = create_app(
    name="tiktok",
    help="TikTok transcript downloader using yt-dlp",
    version=__version__,
    cache_support=False,
)

# Register command modules
from .commands import transcripts, favorites
register_commands(app, get_config, transcripts, name="transcripts", help="Download TikTok video transcripts")
register_commands(app, get_config, favorites, name="favorites", help="Manage saved (favorited) TikTok videos")
app.add_typer(create_auth_app(get_config, tool_name="tiktok"), name="auth")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
