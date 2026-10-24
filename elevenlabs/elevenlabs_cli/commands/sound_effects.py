"""Sound effect generation commands for ElevenLabs CLI."""
COMMAND_CREDENTIALS = {
    "create": ["api_key"],
}

from pathlib import Path
from typing import Optional

import typer
from cli_tools_shared.output import command, handle_error, print_json

from ..client import get_client


app = typer.Typer(help="Generate sound effects", no_args_is_help=True)


@app.command("create")
@command
def sound_effects_create(
    text: str = typer.Argument(..., help="Text describing the sound effect"),
    output: Path = typer.Option(..., "--output", "-o", help="Path to write audio file"),
    duration: Optional[float] = typer.Option(None, "--duration", min=0.5, max=30, help="Duration in seconds (0.5-30); API picks when omitted"),
    prompt_influence: Optional[float] = typer.Option(None, "--prompt-influence", min=0, max=1, help="Prompt influence 0-1 (API default 0.3)"),
    loop: Optional[bool] = typer.Option(None, "--loop/--no-loop", help="Create a smoothly looping effect (API default off)"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model ID (API default eleven_text_to_sound_v2)"),
    output_format: str = typer.Option("mp3_44100_128", "--output-format", help="Audio output format"),
    force: bool = typer.Option(False, "--force", "-F", help="Overwrite an existing output file"),
):
    """Generate a sound effect from text and write the audio file."""
    try:
        print_json(
            get_client().create_sound_effect(
                text=text,
                output_path=output,
                output_format=output_format,
                force=force,
                duration_seconds=duration,
                prompt_influence=prompt_influence,
                loop=loop,
                model_id=model,
            )
        )
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
