"""Video analysis commands for Gemini CLI."""
from typing import List, Optional
import typer
import json
from pathlib import Path
from ..client import get_client
from cli_tools_shared.output import print_json, print_success, print_error, print_info, handle_error
from ..file_types import is_supported_file, UnsupportedFileTypeError, get_file_category

app = typer.Typer(help="Video analysis operations")


@app.command("analyze")
def video_analyze(
    file_path: str = typer.Argument(..., help="Path to video file"),
    prompt: str = typer.Option(None, "--prompt", "-p", help="Analysis prompt (inline text)"),
    prompt_file: str = typer.Option(None, "--prompt-file", "-f", help="Path to file containing prompt"),
    files: List[str] = typer.Option(None, "--files", help="Additional files to include (can specify multiple times)"),
    model: str = typer.Option("gemini-3.1-pro-preview", "--model", "-m", help="Model to use"),
    no_wait: bool = typer.Option(False, "--no-wait", help="Don't wait for processing (large files only)"),
    json_schema: str = typer.Option(None, "--json-schema", "-s", help="Path to JSON schema file for structured output"),
    fps: float = typer.Option(None, "--fps", help="Frames per second for video sampling (default: 1). Use higher values (2-5) for fast-action or sync detection."),
):
    """
    Upload and analyze a video file with Gemini.

    For videos < 20MB, the video is analyzed immediately using inline upload.
    For videos >= 20MB, the video is uploaded to Files API first.

    Provide a prompt either inline with --prompt or from a file with --prompt-file.
    Additional context files (PDFs, docs, etc.) can be included with --files.
    Use --json-schema for structured JSON output that guarantees valid JSON.

    Example:
        gemini video analyze video.mp4 --prompt "Summarize this video"
        gemini video analyze video.mp4 --prompt-file prompts/review.txt
        gemini video analyze lecture.mp4 -p "What are the key topics discussed?"
        gemini video analyze demo.mp4 -f analysis_prompt.txt --model gemini-3.1-pro-preview
        gemini video analyze video.mp4 -p "Review this" --files outline.pdf --files notes.txt
        gemini video analyze video.mp4 -p "Review this" --json-schema schema.json
    """
    try:
        # Validate prompt options
        if prompt and prompt_file:
            print_error("Cannot use both --prompt and --prompt-file. Choose one.")
            raise typer.Exit(1)

        if not prompt and not prompt_file:
            print_error("Must provide either --prompt or --prompt-file")
            raise typer.Exit(1)

        # Load prompt from file if specified
        if prompt_file:
            prompt_path = Path(prompt_file)
            if not prompt_path.exists():
                print_error(f"Prompt file not found: {prompt_file}")
                raise typer.Exit(1)
            prompt = prompt_path.read_text().strip()
            if not prompt:
                print_error(f"Prompt file is empty: {prompt_file}")
                raise typer.Exit(1)

        # Load JSON schema if specified
        response_schema = None
        if json_schema:
            schema_path = Path(json_schema)
            if not schema_path.exists():
                print_error(f"Schema file not found: {json_schema}")
                raise typer.Exit(1)
            try:
                response_schema = json.loads(schema_path.read_text())
                print_info(f"Using JSON schema from: {json_schema}")
            except json.JSONDecodeError as e:
                print_error(f"Invalid JSON in schema file: {e}")
                raise typer.Exit(1)

        client = get_client()

        # Validate file exists
        video_path = Path(file_path)
        if not video_path.exists():
            print_error(f"File not found: {file_path}")
            raise typer.Exit(1)

        # Validate file type
        if not is_supported_file(video_path):
            raise UnsupportedFileTypeError(video_path)

        file_category = get_file_category(video_path)
        if file_category != "video":
            print_error(f"File is not a video: {video_path.name} (detected as {file_category})")
            raise typer.Exit(1)

        # Get file size for user info
        file_size = video_path.stat().st_size
        file_size_mb = file_size / (1024 * 1024)

        print_info(f"Analyzing video: {video_path.name} ({file_size_mb:.2f} MB)")

        if fps is not None:
            print_info(f"Using custom frame rate: {fps} FPS")

        if file_size_mb >= 20 or files:
            if no_wait:
                print_info("Large file detected. Uploading to Files API (you'll need to check status separately)...")
            else:
                print_info("Large file detected. Uploading and waiting for processing...")

        # Validate additional files if provided
        if files:
            for f in files:
                f_path = Path(f)
                if not f_path.exists():
                    print_error(f"Additional file not found: {f}")
                    raise typer.Exit(1)
                if not is_supported_file(f_path):
                    raise UnsupportedFileTypeError(f_path)
            print_info(f"Including {len(files)} additional file(s)")

        # Analyze video
        result = client.analyze_video(
            video_path=str(video_path),
            prompt=prompt,
            model=model,
            auto_wait=not no_wait,
            additional_files=files,
            response_schema=response_schema,
            fps=fps
        )

        # Display result
        print_success("Analysis complete")
        print()
        print(result)

    except UnsupportedFileTypeError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "analyze": [
        "custom"
    ]
}
