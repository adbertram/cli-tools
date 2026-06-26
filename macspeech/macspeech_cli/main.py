"""Main entry point for macspeech CLI.

macspeech wraps a local Apple SFSpeechRecognizer helper (MacSpeech.app) to
transcribe audio on-device, with contextual-string vocabulary biasing.
"""

from cli_tools_shared import create_app, run_app
from cli_tools_shared.exceptions import ClientError

from . import __version__
from . import commands

app = create_app(
    name="macspeech",
    help="Transcribe local audio on-device via Apple SFSpeechRecognizer",
    version=__version__,
    cache_support=False,
)

app.add_typer(commands.app, name="transcripts", help="Transcription operations")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
