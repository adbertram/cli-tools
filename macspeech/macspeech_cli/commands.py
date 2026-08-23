"""Transcripts commands for macspeech CLI.

Transcribe local audio on-device via Apple SFSpeechRecognizer (the MacSpeech.app
helper). The headline capability is `transcripts create`, which biases the
recognizer with contextual strings for technical vocabulary.
"""

import json
from pathlib import Path
from typing import List, Optional

import typer

from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import handle_error, print_error, print_info, print_json, print_table

from .client import get_client
from .config import DEFAULT_TIMEOUT, get_config, parse_contextual_strings

app = typer.Typer(help="Transcription operations", no_args_is_help=True)


@app.command("create")
def transcripts_create(
    file_path: str = typer.Argument(..., help="Path to the audio file to transcribe"),
    language: str = typer.Option("en", "--language", "-L", help="Language code (e.g., en, es, fr). 'en' maps to locale en-US."),
    contextual_strings: Optional[str] = typer.Option(
        None,
        "--contextual-strings",
        help=(
            "Semicolon-separated phrases fed to SFSpeechRecognitionRequest.contextualStrings "
            "for vocabulary biasing (e.g. 'worktree;subagent;detached HEAD'). "
            "Defaults to MACSPEECH_CONTEXTUAL_STRINGS; omitted entirely when empty."
        ),
    ),
    punctuation: bool = typer.Option(
        True,
        "--punctuation/--no-punctuation",
        help="Add automatic punctuation (SFSpeechRecognitionRequest.addsPunctuation, macOS 13+).",
    ),
    timeout: int = typer.Option(DEFAULT_TIMEOUT, "--timeout", help="Transcription timeout in seconds"),
    table: bool = typer.Option(False, "--table", "-t", help="Display per-word segments as a table"),
):
    """Transcribe an audio file on-device via Apple Speech.

    Outputs JSON with top-level `text` (full transcript), `language`, and `words`
    (per-word {text, start, end, confidence}; start/end in seconds) — uniform with
    the whisper CLIs.

    Examples:
        macspeech transcripts create audio.wav
        macspeech transcripts create audio.wav --language en
        macspeech transcripts create audio.wav --contextual-strings "worktree;subagent;Codex"
        macspeech transcripts create audio.wav --no-punctuation
        macspeech transcripts create audio.wav --table
    """
    try:
        config = get_config()

        # Resolve contextual strings: explicit flag wins, else env default.
        if contextual_strings is None:
            phrases = config.default_contextual_strings
        else:
            phrases = parse_contextual_strings(contextual_strings)

        if not Path(file_path).exists():
            print_error(f"File not found: {file_path}")
            raise typer.Exit(1)

        print_info(f"Transcribing {file_path} on-device (locale derived from '{language}')...")

        client = get_client()
        transcript = client.transcribe(
            file_path=file_path,
            language=language,
            contextual_strings=phrases,
            punctuation=punctuation,
            timeout=timeout,
        )

        if table:
            words = transcript.get("words", [])
            if not words:
                print_info("No word segments found.")
                return
            rows = [
                {
                    "start": f"{word['start']:.2f}s",
                    "end": f"{word['end']:.2f}s",
                    "confidence": f"{word['confidence']:.2f}",
                    "text": word["text"],
                }
                for word in words
            ]
            print_table(rows, ["start", "end", "confidence", "text"], ["Start", "End", "Confidence", "Text"])
        else:
            print_json(transcript)

    except typer.Exit:
        raise
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("status")
def transcripts_status(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Show Speech Recognition authorization status (passive — never prompts).

    Reads SFSpeechRecognizer.authorizationStatus() without requesting access, so
    it cannot pop the macOS permission dialog. authorization_status raw values:
    0=notDetermined, 1=denied, 2=restricted, 3=authorized.

    Examples:
        macspeech transcripts status
        macspeech transcripts status --table
    """
    try:
        result = get_client().authorization_status()
        if table:
            rows = [{"field": key, "value": str(value)} for key, value in result.items()]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(result)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("list")
def transcripts_list(
    directory: str = typer.Argument(".", help="Directory to search for transcript JSON files"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., language:eq:en)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """List macspeech transcript JSON files in a directory.

    Examples:
        macspeech transcripts list
        macspeech transcripts list ./transcripts/
        macspeech transcripts list --filter "language:eq:en"
        macspeech transcripts list --table
    """
    try:
        if filter:
            try:
                validate_filters(filter)
            except FilterValidationError as exc:
                print_error(str(exc))
                raise typer.Exit(1)

        search_path = Path(directory).resolve()
        json_files = sorted(search_path.glob("*.json"))

        transcripts = []
        for json_file in json_files[:limit]:
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            # Recognize a macspeech/whisper-style transcript: top-level text + words.
            if isinstance(data, dict) and "text" in data and "words" in data:
                transcripts.append({
                    "file": str(json_file),
                    "language": data.get("language", "unknown"),
                    "word_count": len(data.get("words", [])),
                    "text_length": len(data.get("text", "")),
                })

        if filter and transcripts:
            transcripts = apply_filters(transcripts, filter)

        if properties:
            transcripts = apply_properties_filter(transcripts, properties)

        if table:
            columns = [f.strip() for f in properties.split(",") if f.strip()] if properties else ["file", "language", "word_count"]
            headers = columns if properties else ["File", "Language", "Words"]
            print_table(transcripts, columns, headers)
        else:
            print_json(transcripts)

    except typer.Exit:
        raise
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def transcripts_get(
    file_path: str = typer.Argument(..., help="Path to a transcript JSON file"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    table: bool = typer.Option(False, "--table", "-t", help="Display per-word segments as a table"),
):
    """Get details of an existing macspeech transcript file.

    Examples:
        macspeech transcripts get audio.json
        macspeech transcripts get audio.json --table
        macspeech transcripts get audio.json --properties "text,language"
    """
    try:
        path = Path(file_path)
        if not path.exists():
            print_error(f"File not found: {file_path}")
            raise typer.Exit(1)

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print_error(f"Invalid JSON file: {file_path}")
            raise typer.Exit(1)

        if properties:
            print_json(apply_properties_filter([data], properties)[0])
            return

        if table:
            words = data.get("words", []) if isinstance(data, dict) else []
            if not words:
                print_info("No word segments found.")
                return
            rows = [
                {
                    "start": f"{word.get('start', 0):.2f}s",
                    "end": f"{word.get('end', 0):.2f}s",
                    "text": word.get("text", ""),
                }
                for word in words
            ]
            print_table(rows, ["start", "end", "text"], ["Start", "End", "Text"])
        else:
            print_json(data)

    except typer.Exit:
        raise
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
