"""Main entry point for OpenAI Whisper CLI wrapper."""
from . import __version__
from cli_tools_shared import create_app, run_app
from .client import ClientError

app = create_app(
    name="openai-whisper",
    help="CLI wrapper for OpenAI Whisper speech-to-text transcription",
    version=__version__,
    cache_support=False,
)

# Register command modules
from . import commands
app.add_typer(commands.app, name="transcripts", help="Transcription operations")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
