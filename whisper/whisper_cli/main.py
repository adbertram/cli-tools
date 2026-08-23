"""Main entry point for the whisper.cpp CLI wrapper."""

from pathlib import Path
from typing import Optional

import typer
from cli_tools_shared import create_app, run_app
from cli_tools_shared.output import (
    command,
    print_error,
    print_info,
    print_json,
    print_table,
)

from . import __version__
from .client import get_client
from .config import get_config

app = create_app(
    name="whisper",
    help="CLI wrapper for whisper.cpp (whisper-cli) local speech-to-text",
    version=__version__,
    cache_support=False,
)
transcripts_app = typer.Typer(
    help="Transcription operations", no_args_is_help=True
)


@transcripts_app.command("create")
@command
def transcripts_create(
    file_path: str = typer.Argument(
        ..., help="Path to audio/video file to transcribe"
    ),
    language: str = typer.Option(
        "en", "--language", "-L", help="Language code (e.g., en, es, fr, de)"
    ),
    word_timestamps: bool = typer.Option(
        False,
        "--word-timestamps",
        "-w",
        help="Emit word-level timestamps (adds a 'words' array)",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        "-m",
        help="Path to a ggml model file (default: WHISPER_CPP_MODEL or small.en)",
    ),
    output_dir: Optional[str] = typer.Option(
        None, "--output-dir", "-o", help="Directory to save the JSON transcript"
    ),
    prompt: Optional[str] = typer.Option(
        None,
        "--prompt",
        "-P",
        help=(
            "Initial prompt to bias vocabulary/spellings "
            "(default: WHISPER_CPP_PROMPT, else none)"
        ),
    ),
    table: bool = typer.Option(
        False, "--table", "-t", help="Display segments as a table"
    ),
    timeout: int = typer.Option(
        600, "--timeout", help="Transcription timeout in seconds"
    ),
):
    """Transcribe an audio or video file using whisper.cpp.

    Outputs a JSON transcript with joined text and timestamped segments
    (seconds). With --word-timestamps, also includes a word-level array.

    A non-empty initial prompt biases whisper.cpp toward the listed
    vocabulary/spellings. Resolution: explicit --prompt wins, else the
    configured WHISPER_CPP_PROMPT, else no prompt is passed.

    Examples:
        whisper transcripts create audio.wav
        whisper transcripts create video.mp4 --language es
        whisper transcripts create audio.wav --word-timestamps
        whisper transcripts create audio.wav -m /path/to/ggml-small.en.bin
        whisper transcripts create audio.wav -o ./transcripts/ --table
        whisper transcripts create audio.wav --prompt "worktree, subagent, Codex"
    """
    if not Path(file_path).exists():
        print_error(f"File not found: {file_path}")
        raise typer.Exit(1)

    resolved_prompt = prompt if prompt else get_config().prompt

    print_info(f"Transcribing {file_path} with whisper.cpp...")

    transcript = get_client().transcribe(
        file_path=file_path,
        model=model,
        language=language,
        word_timestamps=word_timestamps,
        output_dir=output_dir,
        timeout=timeout,
        prompt=resolved_prompt,
    )

    if table:
        segments = transcript["segments"]
        if not segments:
            print_info("No segments found.")
            return
        rows = [
            {
                "start": f"{seg['start']:.2f}s",
                "end": f"{seg['end']:.2f}s",
                "text": seg["text"],
            }
            for seg in segments
        ]
        print_table(rows, ["start", "end", "text"], ["Start", "End", "Text"])
    else:
        print_json(transcript)


@transcripts_app.command("models")
@command
def transcripts_models(
    table: bool = typer.Option(
        False, "--table", "-t", help="Display as a table"
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include",
    ),
):
    """List local ggml model files found in the models directory.

    Examples:
        whisper transcripts models
        whisper transcripts models --table
    """
    models = get_client().list_models()

    if properties:
        fields = [field.strip() for field in properties.split(",") if field.strip()]
        models = [
            {field: model.get(field) for field in fields} for model in models
        ]

    if table:
        if not models:
            print_info("No local ggml models found.")
            return
        columns = list(models[0].keys())
        print_table(
            models,
            columns,
            [column.replace("_", " ").title() for column in columns],
        )
    else:
        print_json(models)


app.add_typer(transcripts_app, name="transcripts")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
