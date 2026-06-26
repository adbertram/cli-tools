"""Transcripts commands for Whisper CLI wrapper.

Commands for transcribing audio/video files using OpenAI Whisper.
"""
import typer
from typing import Optional, List
from pathlib import Path

from pydantic import BaseModel

from .client import get_client
from .models import WhisperModel
from cli_tools_shared.output import print_json, print_table, handle_error

app = typer.Typer(help="Transcription operations", no_args_is_help=True)


def model_to_dict(item):
    """Convert model or dict to dict for field extraction."""
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


def extract_field(item, field: str):
    """Extract a field value, supporting dot-notation for nested fields."""
    data = model_to_dict(item)
    parts = field.split(".")
    value = data
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def extract_fields(items: list, fields: list) -> list:
    """Extract specified fields from items, supporting dot-notation."""
    result = []
    for item in items:
        extracted = {}
        for field in fields:
            value = extract_field(item, field)
            extracted[field] = value
        result.append(extracted)
    return result


@app.command("create")
def transcripts_create(
    file_path: str = typer.Argument(..., help="Path to audio/video file to transcribe"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Whisper model: tiny, base, small, medium, large, turbo (and .en/large-v* variants). Defaults to OPENAI_WHISPER_MODEL or 'turbo'."),
    language: str = typer.Option("en", "--language", "-L", help="Language code (e.g., en, es, fr, de)"),
    word_timestamps: bool = typer.Option(False, "--word-timestamps", "-w", help="Enable word-level timestamps"),
    output_dir: Optional[str] = typer.Option(None, "--output-dir", "-o", help="Directory to save output files"),
    table: bool = typer.Option(False, "--table", "-t", help="Display segments as table"),
    timeout: int = typer.Option(600, "--timeout", help="Transcription timeout in seconds"),
    initial_prompt: Optional[str] = typer.Option(None, "--initial-prompt", help="Vocabulary-biasing prompt passed to Whisper as --initial_prompt. Defaults to OPENAI_WHISPER_INITIAL_PROMPT; omitted entirely when empty."),
    temperature: Optional[float] = typer.Option(None, "--temperature", help="Sampling temperature passed to Whisper as --temperature. Omitted when not provided."),
):
    """
    Transcribe an audio or video file using OpenAI Whisper.

    Outputs JSON transcript with text and timestamped segments.

    Examples:
        openai-whisper transcripts create video.mp4
        openai-whisper transcripts create video.mp4 --model base
        openai-whisper transcripts create audio.wav --language es
        openai-whisper transcripts create video.mp4 --word-timestamps
        openai-whisper transcripts create video.mp4 -o ./transcripts/ --table
        openai-whisper transcripts create audio.mp3 --initial-prompt "worktree, subagent, Codex"
        openai-whisper transcripts create audio.mp3 --temperature 0
    """
    try:
        from .config import get_config
        config = get_config()

        # Resolve model: explicit flag wins, else env default (OPENAI_WHISPER_MODEL), else 'turbo'.
        resolved_model = model if model is not None else config.default_model

        # Validate model
        try:
            whisper_model = WhisperModel(resolved_model.lower())
        except ValueError:
            from cli_tools_shared.output import print_error
            valid_models = ", ".join([m.value for m in WhisperModel])
            print_error(f"Invalid model '{resolved_model}'. Valid models: {valid_models}")
            raise typer.Exit(1)

        # Resolve initial prompt: explicit flag wins, else env default; empty -> no prompt.
        resolved_initial_prompt = initial_prompt if initial_prompt is not None else config.default_initial_prompt
        if resolved_initial_prompt is not None and resolved_initial_prompt.strip() == "":
            resolved_initial_prompt = None

        # Validate file exists
        if not Path(file_path).exists():
            from cli_tools_shared.output import print_error
            print_error(f"File not found: {file_path}")
            raise typer.Exit(1)

        from cli_tools_shared.output import print_info
        print_info(f"Transcribing {file_path} with model '{whisper_model.value}'...")

        client = get_client()
        transcript = client.transcribe(
            file_path=file_path,
            model=whisper_model,
            language=language,
            word_timestamps=word_timestamps,
            output_dir=output_dir,
            timeout=timeout,
            initial_prompt=resolved_initial_prompt,
            temperature=temperature,
        )

        if table:
            # Display segments as table
            if not transcript.segments:
                print("No segments found.")
                return

            rows = []
            for seg in transcript.segments:
                rows.append({
                    "start": f"{seg.start:.2f}s",
                    "end": f"{seg.end:.2f}s",
                    "text": seg.text[:80] + "..." if len(seg.text) > 80 else seg.text,
                })
            print_table(rows, ["start", "end", "text"], ["Start", "End", "Text"])
        else:
            print_json(transcript)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("list")
def transcripts_list(
    directory: str = typer.Argument(".", help="Directory to search for transcript JSON files"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List existing transcript JSON files in a directory.

    Examples:
        openai-whisper transcripts list
        openai-whisper transcripts list ./transcripts/
        openai-whisper transcripts list --table
        openai-whisper transcripts list --filter "language:eq:en"
    """
    import json
    import glob
    from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError

    try:
        # Validate filters if provided
        if filter:
            try:
                validate_filters(filter)
            except FilterValidationError as e:
                from cli_tools_shared.output import print_error
                print_error(str(e))
                raise typer.Exit(1)

        # Find all JSON files that look like Whisper output
        search_path = Path(directory).resolve()
        json_files = list(search_path.glob("*.json"))

        transcripts = []
        for json_file in json_files[:limit]:
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Check if it looks like a Whisper transcript
                if "text" in data and "segments" in data:
                    transcripts.append({
                        "file": str(json_file),
                        "language": data.get("language", "unknown"),
                        "segment_count": len(data.get("segments", [])),
                        "text_length": len(data.get("text", "")),
                    })
            except (json.JSONDecodeError, KeyError):
                continue

        # Apply client-side filters
        if filter and transcripts:
            transcripts = apply_filters(transcripts, filter)

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            transcripts = extract_fields(transcripts, fields)

        if table:
            if properties:
                columns = [f.strip() for f in properties.split(",")]
                # If no data, create an empty placeholder row so table structure is shown
                if not transcripts:
                    transcripts = [{col: "" for col in columns}]
                    transcripts = []  # Clear for empty table with headers
                print_table(transcripts if transcripts else [{}], columns, columns)
            else:
                columns = ["file", "language", "segment_count"]
                headers = ["File", "Language", "Segments"]
                # Show empty table with headers when no data
                if not transcripts:
                    transcripts = [{"file": "", "language": "", "segment_count": ""}]
                print_table(transcripts, columns, headers)
        else:
            print_json(transcripts)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def transcripts_get(
    file_path: str = typer.Argument(..., help="Path to transcript JSON file"),
    table: bool = typer.Option(False, "--table", "-t", help="Display segments as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    Get details of an existing transcript file.

    Examples:
        openai-whisper transcripts get video.json
        openai-whisper transcripts get video.json --table
        openai-whisper transcripts get video.json --properties "text,language"
    """
    import json
    from .models import create_transcript

    try:
        path = Path(file_path)
        if not path.exists():
            from cli_tools_shared.output import print_error
            print_error(f"File not found: {file_path}")
            raise typer.Exit(1)

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        transcript = create_transcript(data, source_file=str(path))

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            result = extract_fields([transcript], fields)[0]
            print_json(result)
            return

        if table:
            # Display segments as table
            if not transcript.segments:
                print("No segments found.")
                return

            rows = []
            for seg in transcript.segments:
                rows.append({
                    "id": seg.id,
                    "start": f"{seg.start:.2f}s",
                    "end": f"{seg.end:.2f}s",
                    "text": seg.text[:60] + "..." if len(seg.text) > 60 else seg.text,
                })
            print_table(rows, ["id", "start", "end", "text"], ["ID", "Start", "End", "Text"])
        else:
            print_json(transcript)

    except json.JSONDecodeError:
        from cli_tools_shared.output import print_error
        print_error(f"Invalid JSON file: {file_path}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("models")
def transcripts_models(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    List available Whisper models.

    Examples:
        openai-whisper transcripts models
        openai-whisper transcripts models --table
    """
    try:
        models = [
            {"name": "tiny", "params": "39M", "speed": "Fastest", "quality": "Lower"},
            {"name": "base", "params": "74M", "speed": "Fast", "quality": "Good"},
            {"name": "small", "params": "244M", "speed": "Medium", "quality": "Better"},
            {"name": "medium", "params": "769M", "speed": "Slow", "quality": "High"},
            {"name": "large", "params": "1550M", "speed": "Slowest", "quality": "Highest"},
            {"name": "turbo", "params": "809M", "speed": "Fast", "quality": "High (Default)"},
        ]

        if table:
            print_table(models, ["name", "params", "speed", "quality"], ["Model", "Parameters", "Speed", "Quality"])
        else:
            print_json(models)

    except Exception as e:
        raise typer.Exit(handle_error(e))
