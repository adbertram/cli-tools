"""Main entry point for Youtube CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.command_registry import register_commands
from .api_client import ApiClientError
from .client import ClientError
from .config import get_config

app = create_app(
    name="youtube",
    help="YouTube transcript and video downloader (yt-dlp) plus channel management (Data API v3)",
    version=__version__,
    cache_support=False,
)

# Register command modules
from .commands import auth, channel, channels, transcripts, videos

app.add_typer(auth.app, name="auth", help="Manage authentication")
register_commands(app, get_config, transcripts, name="transcripts", help="Download YouTube video transcripts")
register_commands(app, get_config, videos, name="videos", help="Download / list public YouTube videos (yt-dlp)")
register_commands(app, get_config, channel, name="channel", help="Manage your authenticated YouTube channel")
register_commands(app, get_config, channels, name="channels", help="Inspect owned channels and channel-creation guidance")


def main():
    """Main entry point."""
    run_app(app, error_types=(ClientError, ApiClientError))


if __name__ == "__main__":
    main()
