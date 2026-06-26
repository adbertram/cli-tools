"""Adobe Podcast CLI — enhance audio using Adobe Podcast Enhance."""

from pathlib import Path
from typing import Annotated, Optional

import typer
from cli_tools_shared import create_app, get_activity_logger, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import command, print_error, print_info, print_json, print_success

_logger = get_activity_logger("adobe-podcast")

from . import __version__
from .client import AdobePodcastClient
from .config import get_config

app = create_app(
    name="adobe-podcast",
    help="Adobe Podcast Enhance — upload audio, run AI speech enhancement, download result",
    version=__version__,
)
enhance_app = typer.Typer(help="Audio enhancement commands", no_args_is_help=True)


@enhance_app.command("run")
@command
def enhance_run(
    input_file: Annotated[Path, typer.Argument(help="Audio/video file to enhance")],
    output: Annotated[Optional[Path], typer.Option("--output", "-o", help="Output file path")] = None,
    enhanced_gain: Annotated[float, typer.Option("--enhanced-gain", help="Enhanced speech gain (0.0–1.0)")] = 1.0,
    background_gain: Annotated[float, typer.Option("--background-gain", help="Background audio gain (0.0–1.0)")] = 0.0,
    isolated_gain: Annotated[float, typer.Option("--isolated-gain", help="Isolated speech gain (0.0–1.0)")] = 1.0,
):
    """Upload a file, run Adobe Podcast Enhance, and download the enhanced result.

    Example:
        adobe-podcast enhance run recording.wav
        adobe-podcast enhance run recording.wav --output enhanced.wav
        adobe-podcast enhance run podcast.mp3 --background-gain 0.2
    """
    _logger.info("enhance run: input=%s output=%s", input_file, output)
    if not input_file.exists():
        print_error(f"File not found: {input_file}")
        raise typer.Exit(1)

    if output is None:
        stem = input_file.stem
        output = input_file.with_name(f"{stem}-enhanced.wav")

    print_info(f"Uploading {input_file.name}…")

    last_progress = [-1]

    def on_progress(pct: float) -> None:
        pct_int = int(pct * 100) if pct <= 1.0 else int(pct)
        if pct_int != last_progress[0] and pct_int % 10 == 0:
            print_info(f"  Enhancing… {pct_int}%")
            last_progress[0] = pct_int

    try:
        client = AdobePodcastClient()
        result = client.enhance(
            input_path=input_file,
            output_path=output,
            enhanced_gain=enhanced_gain,
            background_gain=background_gain,
            isolated_gain=isolated_gain,
            on_progress=on_progress,
        )
    except ClientError as exc:
        print_error(str(exc))
        raise typer.Exit(1)

    print_success(f"Saved to {output}")
    print_json(result)


app.add_typer(enhance_app, name="enhance")
app.add_typer(create_auth_app(get_config, tool_name="adobe-podcast"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
