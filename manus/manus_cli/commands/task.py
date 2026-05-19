"""Task commands for Manus CLI."""
import json
import os
from pathlib import Path
import requests
import typer
from typing import Optional, List
from ..client import get_client, ClientError
from ..output import print_json, print_table, print_success, print_status, print_error, handle_error
from ..filters import apply_filters, apply_properties_filter, validate_filters, FilterValidationError


def download_files(task_result: dict, output_dir: Path) -> List[str]:
    """
    Download all files from a task's output.

    Args:
        task_result: The task result dict containing output array
        output_dir: Directory to save files to

    Returns:
        List of downloaded file paths
    """
    downloaded = []
    output_dir.mkdir(parents=True, exist_ok=True)

    for output_item in task_result.get("output", []):
        for content_item in output_item.get("content", []):
            if content_item.get("type") == "output_file":
                file_url = content_item.get("fileUrl")
                file_name = content_item.get("fileName", "download")

                if file_url:
                    file_path = output_dir / file_name
                    try:
                        response = requests.get(file_url, timeout=60)
                        response.raise_for_status()
                        file_path.write_bytes(response.content)
                        downloaded.append(str(file_path))
                    except Exception as e:
                        print_error(f"Failed to download {file_name}: {e}")

    return downloaded

app = typer.Typer(help="Manage Manus AI tasks")


@app.command("create")
def task_create(
    prompt: Optional[str] = typer.Argument(None, help="The task instruction or query"),
    prompt_file: Optional[str] = typer.Option(None, "--prompt-file", "-f", help="Read prompt from file instead of argument"),
    profile: str = typer.Option("manus-1.5", "--profile", "-p", help="Agent profile (manus-1.5, manus-1.5-lite)"),
    mode: str = typer.Option("agent", "--mode", "-m", help="Task mode (chat, adaptive, agent)"),
    wait: bool = typer.Option(True, "--wait/--no-wait", "-w", help="Wait for task completion"),
    timeout: float = typer.Option(900.0, "--timeout", help="Max seconds to wait for completion"),
    poll: float = typer.Option(2.0, "--poll", help="Seconds between status checks"),
    share: bool = typer.Option(False, "--share", "-s", help="Create shareable link"),
    hide: bool = typer.Option(False, "--hide", help="Hide from webapp task list"),
    locale: Optional[str] = typer.Option(None, "--locale", "-l", help="Locale setting (e.g., en-US)"),
    attachment: Optional[List[str]] = typer.Option(None, "--attachment", "-a", help="Attachment as JSON object"),
    connector: Optional[List[str]] = typer.Option(None, "--connector", help="Connector ID to enable"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress status messages"),
):
    """
    Create a new Manus AI task.

    Examples:

        manus task create "Write a Python function to calculate fibonacci"

        manus task create "Analyze this document" --no-wait

        manus task create "Research AI trends" --share --profile manus-1.5

        manus task create --prompt-file /path/to/prompt.txt
    """
    # Handle prompt from file or argument
    if prompt_file:
        try:
            with open(prompt_file, 'r', encoding='utf-8') as f:
                prompt = f.read().strip()
        except FileNotFoundError:
            print_error(f"Prompt file not found: {prompt_file}")
            raise typer.Exit(1)
        except Exception as e:
            print_error(f"Error reading prompt file: {e}")
            raise typer.Exit(1)

    if not prompt:
        print_error("Either provide a prompt argument or use --prompt-file")
        raise typer.Exit(1)

    try:
        client = get_client()

        # Parse attachments if provided
        attachments = None
        if attachment:
            attachments = []
            for att in attachment:
                try:
                    attachments.append(json.loads(att))
                except json.JSONDecodeError:
                    print_error(f"Invalid attachment JSON: {att}")
                    raise typer.Exit(1)

        if wait:
            # Create and wait for completion
            def status_callback(status: str, elapsed: float):
                if not quiet:
                    print_status(f"Status: {status} ({elapsed:.0f}s elapsed)")

            result = client.create_and_wait(
                prompt=prompt,
                agent_profile=profile,
                task_mode=mode,
                attachments=attachments,
                connectors=list(connector) if connector else None,
                hide_in_task_list=hide,
                create_shareable_link=share,
                locale=locale,
                poll_interval=poll,
                max_wait=timeout,
                status_callback=status_callback if not quiet else None,
            )

            print_json(result)
        else:
            # Just create, don't wait
            result = client.create_task(
                prompt=prompt,
                agent_profile=profile,
                task_mode=mode,
                attachments=attachments,
                connectors=list(connector) if connector else None,
                hide_in_task_list=hide,
                create_shareable_link=share,
                locale=locale,
            )
            print_json(result)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("continue")
def task_continue(
    task_id: str = typer.Argument(..., help="Task ID to continue"),
    prompt: Optional[str] = typer.Argument(None, help="The follow-up message"),
    prompt_file: Optional[str] = typer.Option(None, "--prompt-file", "-f", help="Read prompt from file instead of argument"),
    wait: bool = typer.Option(True, "--wait/--no-wait", "-w", help="Wait for task completion"),
    timeout: float = typer.Option(900.0, "--timeout", help="Max seconds to wait for completion"),
    poll: float = typer.Option(2.0, "--poll", help="Seconds between status checks"),
    attachment: Optional[List[str]] = typer.Option(None, "--attachment", "-a", help="Attachment as JSON object"),
    connector: Optional[List[str]] = typer.Option(None, "--connector", help="Connector ID to enable"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress status messages"),
):
    """
    Continue an existing Manus AI task conversation.

    Examples:

        manus task continue task-abc123 "What about error handling?"

        manus task continue task-abc123 --prompt-file /path/to/followup.txt

        manus task continue task-abc123 "Add more details" --no-wait
    """
    # Handle prompt from file or argument
    if prompt_file:
        try:
            with open(prompt_file, 'r', encoding='utf-8') as f:
                prompt = f.read().strip()
        except FileNotFoundError:
            print_error(f"Prompt file not found: {prompt_file}")
            raise typer.Exit(1)
        except Exception as e:
            print_error(f"Error reading prompt file: {e}")
            raise typer.Exit(1)

    if not prompt:
        print_error("Either provide a prompt argument or use --prompt-file")
        raise typer.Exit(1)

    try:
        client = get_client()

        # Parse attachments if provided
        attachments = None
        if attachment:
            attachments = []
            for att in attachment:
                try:
                    attachments.append(json.loads(att))
                except json.JSONDecodeError:
                    print_error(f"Invalid attachment JSON: {att}")
                    raise typer.Exit(1)

        if wait:
            def status_callback(status: str, elapsed: float):
                if not quiet:
                    print_status(f"Status: {status} ({elapsed:.0f}s elapsed)")

            result = client.create_and_wait(
                prompt=prompt,
                task_id=task_id,
                attachments=attachments,
                connectors=list(connector) if connector else None,
                poll_interval=poll,
                max_wait=timeout,
                status_callback=status_callback if not quiet else None,
            )

            print_json(result)
        else:
            result = client.create_task(
                prompt=prompt,
                task_id=task_id,
                attachments=attachments,
                connectors=list(connector) if connector else None,
            )
            print_json(result)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def task_get(
    task_id: str = typer.Argument(..., help="Task ID to retrieve"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as formatted table"),
    download: bool = typer.Option(False, "--download-files", "-d", help="Download output files from the task"),
    output_dir: Optional[str] = typer.Option(None, "--output-dir", "-o", help="Directory for downloaded files (default: current dir)"),
):
    """Get task status and result."""
    try:
        client = get_client()
        result = client.get_task(task_id)

        if download:
            dest_dir = Path(output_dir) if output_dir else Path.cwd()
            downloaded = download_files(result, dest_dir)
            if downloaded:
                for file_path in downloaded:
                    print_success(f"Downloaded: {file_path}")
            else:
                print_status("No files to download")

        if table:
            print_table(result)
        else:
            print_json(result)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("wait")
def task_wait(
    task_id: str = typer.Argument(..., help="Task ID to wait for"),
    timeout: float = typer.Option(900.0, "--timeout", help="Max seconds to wait"),
    poll: float = typer.Option(2.0, "--poll", help="Seconds between status checks"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress status messages"),
):
    """Wait for a task to complete and return the result."""
    try:
        client = get_client()

        def status_callback(status: str, elapsed: float):
            if not quiet:
                print_status(f"Status: {status} ({elapsed:.0f}s elapsed)")

        result = client.wait_for_task(
            task_id=task_id,
            poll_interval=poll,
            max_wait=timeout,
            status_callback=status_callback if not quiet else None,
        )

        print_json(result)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("list")
def task_list(
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum number of tasks to return"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as formatted table"),
    filter_: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of properties to include (supports dot notation)"),
):
    """List recent tasks."""
    try:
        # Validate filters early
        if filter_:
            try:
                validate_filters(filter_)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        client = get_client()
        result = client.list_tasks(limit=limit)

        # Extract tasks from response
        tasks = result.get("data", result) if isinstance(result, dict) else result

        if not isinstance(tasks, list):
            tasks = [tasks] if tasks else []

        # Apply client-side filters
        if filter_:
            tasks = apply_filters(tasks, filter_)

        # Apply properties filter
        if properties:
            tasks = apply_properties_filter(tasks, properties)

        if table:
            if tasks:
                print_table(tasks)
            else:
                print_status("No tasks found.")
        else:
            print_json(tasks)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "continue": [
        "api_key"
    ],
    "create": [
        "api_key"
    ],
    "get": [
        "api_key"
    ],
    "list": [
        "api_key"
    ],
    "wait": [
        "api_key"
    ]
}
