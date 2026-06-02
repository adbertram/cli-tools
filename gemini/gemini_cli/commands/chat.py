"""Chat commands for Gemini CLI."""
from typing import Optional
from pathlib import Path
import typer
from ..client import get_client
from cli_tools_shared.output import print_success, print_error, print_info, handle_error
from ..file_types import is_supported_file, UnsupportedFileTypeError, get_supported_extensions

app = typer.Typer(help="Chat and content generation")


@app.command("new")
def chat_new(
    prompt: str = typer.Argument(..., help="Prompt to start the conversation"),
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="File to attach to the conversation"),
    model: str = typer.Option("gemini-3.1-pro-preview", "--model", "-m", help="Model to use"),
):
    """
    Start a new chat conversation with a prompt.

    Example:
        gemini chat new "Explain quantum computing in simple terms"
        gemini chat new "What is in this image?" --file photo.jpg
        gemini chat new "Summarize this document" -f report.pdf --model gemini-3.1-pro-preview
    """
    try:
        client = get_client()

        file_refs = None
        if file:
            if not file.exists():
                print_error(f"File not found: {file}")
                raise typer.Exit(1)

            if not is_supported_file(file):
                raise UnsupportedFileTypeError(file)

            print_info(f"Uploading {file.name}...")
            uploaded_file = client.upload_file(str(file))

            print_info("Waiting for file processing...")
            processed_file = client.wait_for_file_processing(uploaded_file.name)
            file_refs = [processed_file]

        print_info(f"Generating with {model}...")
        result = client.generate_content(prompt=prompt, model=model, file_refs=file_refs)

        print_success("Generation complete")
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
    "new": [
        "custom"
    ]
}
