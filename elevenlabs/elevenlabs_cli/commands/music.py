"""Music composition commands for ElevenLabs CLI."""
COMMAND_CREDENTIALS = {
    "compose": ["api_key"],
}

from pathlib import Path
from typing import Optional

import typer
from cli_tools_shared.output import command, handle_error, print_json

from ..client import get_client


app = typer.Typer(help="Compose music", no_args_is_help=True)


@app.command("compose")
@command
def music_compose(
    prompt: str = typer.Argument(..., help="Text prompt describing the music"),
    output: Path = typer.Option(..., "--output", "-o", help="Path to write audio file"),
    seconds: Optional[float] = typer.Option(None, "--seconds", min=3, max=600, help="Length in seconds (3-600); model picks when omitted"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="music_v1, music_v2, or music_v2_5 (API default music_v1)"),
    instrumental: Optional[bool] = typer.Option(None, "--instrumental/--no-instrumental", help="Force instrumental output (API default off)"),
    seed: Optional[int] = typer.Option(None, "--seed", help="Seed for reproducible output"),
    output_format: str = typer.Option("mp3_44100_128", "--output-format", help="Audio output format"),
    force: bool = typer.Option(False, "--force", "-F", help="Overwrite an existing output file"),
):
    """Compose music from a prompt and write the audio file."""
    try:
        print_json(
            get_client().compose_music(
                prompt=prompt,
                output_path=output,
                output_format=output_format,
                seconds=seconds,
                force=force,
                model_id=model,
                instrumental=instrumental,
                seed=seed,
            )
        )
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
