"""Main entry point for Tiktok CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from .client import ClientError
from .config import get_config

app = create_app(
    name="tiktok",
    help="TikTok transcript downloader using yt-dlp",
    version=__version__,
    cache_support=False,
)

# Register command modules
from .commands import transcripts
app.add_typer(transcripts.app, name="transcripts", help="Download TikTok video transcripts")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
