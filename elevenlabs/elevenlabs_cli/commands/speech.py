"""Text-to-speech commands for ElevenLabs CLI."""
COMMAND_CREDENTIALS = {
    "create": ["api_key"],
}

from pathlib import Path
from typing import List, Optional

import typer
from cli_tools_shared.output import handle_error, print_json, print_table

from ..client import get_client
from .common import key_value_rows


app = typer.Typer(help="Generate speech audio", no_args_is_help=True)


@app.command("create")
def speech_create(
    voice_id: str = typer.Argument(..., help="Voice ID"),
    text: str = typer.Argument(..., help="Text to convert to speech"),
    output: Path = typer.Option(..., "--output", "-o", help="Path to write audio file"),
    model_id: str = typer.Option("eleven_multilingual_v2", "--model-id", "-m", help="Text-to-speech model ID"),
    output_format: str = typer.Option("mp3_44100_128", "--output-format", help="Audio output format"),
    language_code: Optional[str] = typer.Option(None, "--language-code", help="ISO 639-1 language code"),
    stability: Optional[float] = typer.Option(None, "--stability", min=0, max=1, help="Voice stability"),
    similarity_boost: Optional[float] = typer.Option(None, "--similarity-boost", min=0, max=1, help="Similarity boost"),
    style: Optional[float] = typer.Option(None, "--style", min=0, max=1, help="Style exaggeration"),
    use_speaker_boost: Optional[bool] = typer.Option(None, "--speaker-boost/--no-speaker-boost", help="Speaker boost"),
    speed: Optional[float] = typer.Option(None, "--speed", min=0.7, max=1.2, help="Voice speed"),
    seed: Optional[int] = typer.Option(None, "--seed", min=0, max=4294967295, help="Generation seed"),
    apply_text_normalization: Optional[str] = typer.Option(None, "--text-normalization", help="auto, on, or off"),
    pronunciation_dictionary: Optional[List[str]] = typer.Option(
        None,
        "--pronunciation-dictionary",
        help="Pronunciation dictionary locator pronunciation_dictionary_id:version_id. Repeat up to 3 times.",
    ),
    enable_logging: bool = typer.Option(True, "--enable-logging/--disable-logging", help="Enable request logging"),
    table: bool = typer.Option(False, "--table", "-t", help="Display result as table"),
):
    """Convert text into speech and write the audio file."""
    try:
        result = get_client().create_speech(
            voice_id=voice_id,
            text=text,
            output_path=output,
            model_id=model_id,
            output_format=output_format,
            language_code=language_code,
            stability=stability,
            similarity_boost=similarity_boost,
            style=style,
            use_speaker_boost=use_speaker_boost,
            speed=speed,
            seed=seed,
            apply_text_normalization=apply_text_normalization,
            enable_logging=enable_logging,
            pronunciation_dictionaries=pronunciation_dictionary,
        )
        if table:
            print_table(key_value_rows(result), ["field", "value"], ["Field", "Value"])
        else:
            print_json(result)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
