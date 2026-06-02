"""Plagiarism detection commands for Grammarly CLI."""
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

import typer

from ..client import get_client, ClientError, SUPPORTED_EXTENSIONS
from ..models import PlagiarismStatus
from cli_tools_shared.output import print_json, print_table, print_error, print_info, handle_error

app = typer.Typer(help="Plagiarism detection commands", no_args_is_help=True)


@app.command("check")
def plagiarism_check(
    file_path: Optional[str] = typer.Argument(
        None,
        help="Path to file to check (.doc, .docx, .odt, .txt, .rtf)",
    ),
    text: Optional[str] = typer.Option(
        None,
        "--text",
        help="Text to check (use - for stdin)",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display result as table",
    ),
    wait: bool = typer.Option(
        True,
        "--wait/--no-wait",
        help="Wait for result (default: wait)",
    ),
    poll_interval: int = typer.Option(
        5,
        "--poll-interval",
        help="Seconds between status checks",
    ),
    max_wait: int = typer.Option(
        120,
        "--max-wait",
        help="Maximum seconds to wait for result",
    ),
):
    """Check a document or text for plagiarism.

    Submit a file or text for plagiarism detection. By default, waits for
    the result (polls until COMPLETED or FAILED).

    Examples:
        grammarly plagiarism check document.docx
        grammarly plagiarism check document.txt --table
        grammarly plagiarism check --text "Your text here"
        echo "Text from stdin" | grammarly plagiarism check --text -
        grammarly plagiarism check document.docx --no-wait
    """
    try:
        # Validate input - need either file_path or text
        if not file_path and not text:
            print_error("Provide either a file path or --text option")
            raise typer.Exit(1)

        if file_path and text:
            print_error("Provide either a file path or --text, not both")
            raise typer.Exit(1)

        temp_file = None
        actual_file_path = file_path

        # Handle text input
        if text:
            # Read from stdin if text is "-"
            if text == "-":
                print_info("Reading from stdin...")
                text_content = sys.stdin.read()
            else:
                text_content = text

            if not text_content.strip():
                print_error("Text content is empty")
                raise typer.Exit(1)

            # Create temp file for text input
            temp_file = tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".txt",
                delete=False,
            )
            temp_file.write(text_content)
            temp_file.close()
            actual_file_path = temp_file.name
            filename = "text_input.txt"
        else:
            # Validate file exists and is supported format
            path = Path(file_path)
            if not path.exists():
                print_error(f"File not found: {file_path}")
                raise typer.Exit(1)

            suffix = path.suffix.lower()
            if suffix not in SUPPORTED_EXTENSIONS:
                print_error(
                    f"Unsupported file format: {suffix}. "
                    f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
                )
                raise typer.Exit(1)

            filename = path.name

        client = get_client()

        # Step 1: Create plagiarism request
        print_info(f"Creating plagiarism check request for: {filename}")
        transaction = client.create_plagiarism_request(filename)
        print_info(f"Request ID: {transaction.score_request_id}")

        # Step 2: Upload file to S3
        print_info("Uploading file...")
        client.upload_file_to_s3(transaction.file_upload_url, actual_file_path)
        print_info("File uploaded successfully")

        # Clean up temp file
        if temp_file:
            Path(temp_file.name).unlink(missing_ok=True)

        # Step 3: Get result (poll if waiting)
        if not wait:
            # Return transaction info without waiting
            result = client.get_plagiarism_result(transaction.score_request_id)
            if table:
                print_table(result)
            else:
                print_json(result)
            return

        # Poll for result
        print_info("Waiting for result...")
        start_time = time.time()
        while True:
            result = client.get_plagiarism_result(transaction.score_request_id)

            if result.status == PlagiarismStatus.COMPLETED:
                print_info("Check completed")
                break
            elif result.status == PlagiarismStatus.FAILED:
                print_error("Plagiarism check failed")
                if table:
                    print_table(result)
                else:
                    print_json(result)
                raise typer.Exit(1)

            # Check timeout
            elapsed = time.time() - start_time
            if elapsed >= max_wait:
                print_error(f"Timeout after {max_wait} seconds. Use 'grammarly plagiarism status {transaction.score_request_id}' to check later.")
                if table:
                    print_table(result)
                else:
                    print_json(result)
                raise typer.Exit(1)

            # Wait before next poll
            print_info(f"Status: {result.status.value}. Waiting {poll_interval}s...")
            time.sleep(poll_interval)

        # Output final result
        if table:
            print_table(result)
        else:
            print_json(result)

    except typer.Exit:
        raise
    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("status")
def plagiarism_status(
    score_request_id: str = typer.Argument(
        ...,
        help="Score request ID from a previous check",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display result as table",
    ),
):
    """Get the status of a plagiarism check.

    Check the status and result of a previously submitted plagiarism
    detection request.

    Examples:
        grammarly plagiarism status abc-123-def
        grammarly plagiarism status abc-123-def --table
    """
    try:
        client = get_client()
        result = client.get_plagiarism_result(score_request_id)

        if table:
            print_table(result)
        else:
            print_json(result)

    except typer.Exit:
        raise
    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "check": [
        "custom"
    ],
    "status": [
        "custom"
    ]
}
