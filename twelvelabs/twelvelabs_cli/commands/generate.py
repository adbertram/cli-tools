"""Generate commands for TwelveLabs CLI."""
import sys
import typer
from typing import Optional
from pathlib import Path

from ..client import get_client
from cli_tools_shared.output import print_json, print_error, print_info, handle_error


app = typer.Typer(help="Generate text from indexed videos", no_args_is_help=True)


@app.command("text")
def generate_text(
    video_id: str = typer.Argument(..., help="The video ID to analyze"),
    prompt: Optional[str] = typer.Option(None, "--prompt", "-p", help="The prompt for text generation"),
    prompt_file: Optional[str] = typer.Option(None, "--prompt-file", "-f", help="Path to file containing the prompt"),
    temperature: Optional[float] = typer.Option(None, "--temperature", "-t", help="Controls randomness (0.0=deterministic, 1.0=creative)"),
    engine: str = typer.Option("pegasus1.5", "--engine", "-e", help="Pegasus engine to use: pegasus1.5 or pegasus1.2"),
    index_id: Optional[str] = typer.Option(None, "--index-id", help="Index ID required when --engine pegasus1.5"),
):
    """
    Generate text from an indexed video using a custom prompt.

    Provide either --prompt or --prompt-file, not both.
    Output is sent to stdout for easy piping.

    Examples:
        twelvelabs generate text VIDEO_ID --prompt "Describe this video"
        twelvelabs generate text VIDEO_ID --prompt-file review_prompt.md
        twelvelabs generate text VIDEO_ID --prompt "List all issues" > output.txt
        twelvelabs generate text VIDEO_ID -f prompt.txt | jq '.'
        twelvelabs generate text VIDEO_ID -p "Find issues" -t 0.2
        twelvelabs generate text VIDEO_ID -f prompt.txt --engine pegasus1.5 --index-id INDEX_ID
    """
    try:
        # Validate prompt options
        if prompt and prompt_file:
            print_error("Specify either --prompt or --prompt-file, not both")
            raise typer.Exit(1)

        if not prompt and not prompt_file:
            print_error("Specify either --prompt or --prompt-file")
            raise typer.Exit(1)

        # Load prompt from file if specified
        if prompt_file:
            path = Path(prompt_file)
            if not path.exists():
                print_error(f"Prompt file not found: {prompt_file}")
                raise typer.Exit(1)
            prompt = path.read_text()

        client = get_client()

        # Generate text
        result = client.generate_text(
            video_id=video_id,
            prompt=prompt,
            temperature=temperature,
            engine=engine,
            index_id=index_id,
        )

        # Output to stdout (raw text, not JSON wrapped)
        # This allows the output to be piped or redirected easily
        print(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("json")
def generate_json(
    video_id: str = typer.Argument(..., help="The video ID to analyze"),
    prompt: Optional[str] = typer.Option(None, "--prompt", "-p", help="The prompt for JSON generation"),
    prompt_file: Optional[str] = typer.Option(None, "--prompt-file", "-f", help="Path to file containing the prompt"),
    validate: bool = typer.Option(True, "--validate/--no-validate", help="Validate JSON output (default: validate)"),
    temperature: Optional[float] = typer.Option(None, "--temperature", "-t", help="Controls randomness (0.0=deterministic, 1.0=creative)"),
    engine: str = typer.Option("pegasus1.5", "--engine", "-e", help="Pegasus engine to use: pegasus1.5 or pegasus1.2"),
    index_id: Optional[str] = typer.Option(None, "--index-id", help="Index ID required when --engine pegasus1.5"),
):
    """
    Generate JSON from an indexed video using a custom prompt.

    The prompt should instruct the model to return valid JSON.
    By default, validates that the output is valid JSON.

    Examples:
        twelvelabs generate json VIDEO_ID --prompt "Return a JSON array of issues found"
        twelvelabs generate json VIDEO_ID --prompt-file review_prompt.md
        twelvelabs generate json VIDEO_ID -f prompt.txt > review.json
        twelvelabs generate json VIDEO_ID -p "Find issues as JSON" -t 0.1
        twelvelabs generate json VIDEO_ID -f prompt.txt --engine pegasus1.5 --index-id INDEX_ID
    """
    import json

    try:
        # Validate prompt options
        if prompt and prompt_file:
            print_error("Specify either --prompt or --prompt-file, not both")
            raise typer.Exit(1)

        if not prompt and not prompt_file:
            print_error("Specify either --prompt or --prompt-file")
            raise typer.Exit(1)

        # Load prompt from file if specified
        if prompt_file:
            path = Path(prompt_file)
            if not path.exists():
                print_error(f"Prompt file not found: {prompt_file}")
                raise typer.Exit(1)
            prompt = path.read_text()

        client = get_client()

        # Generate text
        result = client.generate_text(
            video_id=video_id,
            prompt=prompt,
            temperature=temperature,
            engine=engine,
            index_id=index_id,
        )

        # Validate JSON if requested
        if validate:
            try:
                # Try to parse as JSON
                parsed = json.loads(result)
                # Output pretty-printed JSON
                print(json.dumps(parsed, indent=2))
            except json.JSONDecodeError as e:
                print_error(f"Output is not valid JSON: {e}")
                print_info("Raw output:")
                print(result, file=sys.stderr)
                raise typer.Exit(1)
        else:
            # Output raw (might not be valid JSON)
            print(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "json": [
        "custom"
    ],
    "text": [
        "custom"
    ]
}
