"""Task commands for Manus CLI."""
COMMAND_CREDENTIALS = {
    "confirm": ["api_key"],
    "continue": ["api_key"],
    "create": ["api_key"],
    "delete": ["api_key"],
    "get": ["api_key"],
    "list": ["api_key"],
    "messages": ["api_key"],
    "send": ["api_key"],
    "stop": ["api_key"],
    "update": ["api_key"],
    "wait": ["api_key"],
}

import json
from pathlib import Path
from typing import Any, Optional

import requests
import typer

from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    apply_properties_filter,
    validate_filters,
)

from ..client import ClientError, get_client
from ..output import handle_error, print_error, print_json, print_status, print_success, print_table

DEFAULT_AGENT_PROFILE = "manus-1.6"
VALID_AGENT_PROFILES = ("manus-1.6", "manus-1.6-lite", "manus-1.6-max")
VALID_SHARE_VISIBILITY = ("private", "team", "public")
VALID_ORDER = ("asc", "desc")
VALID_SCOPE = ("all", "agent_subtask", "project", "standard")
VALID_SLIDES_FORMAT = ("html", "pptx")

app = typer.Typer(help="Manage Manus AI tasks", no_args_is_help=True)


def _read_text_file(path: str, label: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        raise ClientError(f"{label} file not found: {path}")
    except OSError as exc:
        raise ClientError(f"Unable to read {label} file {path}: {exc}") from exc


def _parse_json_value(raw_value: str, label: str) -> Any:
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ClientError(f"Invalid {label} JSON: {exc}") from exc


def _load_optional_json(raw_value: Optional[str], file_path: Optional[str], label: str) -> Optional[dict[str, Any]]:
    if raw_value and file_path:
        raise ClientError(f"Use either --{label.replace(' ', '-')} or --{label.replace(' ', '-')}-file, not both.")
    if raw_value:
        value = _parse_json_value(raw_value, label)
    elif file_path:
        value = _parse_json_value(_read_text_file(file_path, label), label)
    else:
        return None

    if not isinstance(value, dict):
        raise ClientError(f"{label} must be a JSON object.")
    return value


def _validate_choice(name: str, value: Optional[str], allowed: tuple[str, ...]) -> None:
    if value is None:
        return
    if value not in allowed:
        raise ClientError(f"Invalid {name}: {value}. Expected one of: {', '.join(allowed)}")


def _build_message_content(
    prompt: Optional[str],
    prompt_file: Optional[str],
    content_parts: Optional[list[str]],
) -> str | list[dict[str, Any]]:
    prompt_text = _read_text_file(prompt_file, "prompt") if prompt_file else (prompt or "")
    parts: list[dict[str, Any]] = []

    for raw_part in content_parts or []:
        parsed = _parse_json_value(raw_part, "content-part")
        if isinstance(parsed, list):
            for item in parsed:
                if not isinstance(item, dict):
                    raise ClientError("Each --content-part array item must be a JSON object.")
                parts.append(item)
        elif isinstance(parsed, dict):
            parts.append(parsed)
        else:
            raise ClientError("Each --content-part value must be a JSON object or array of objects.")

    if prompt_text and not parts:
        return prompt_text

    if prompt_text:
        parts.insert(0, {"type": "text", "text": prompt_text})

    if not parts:
        raise ClientError("Provide prompt text or at least one --content-part value.")

    return parts


def _build_message_payload(
    prompt: Optional[str],
    prompt_file: Optional[str],
    content_parts: Optional[list[str]],
    connectors: Optional[list[str]],
    enable_skills: Optional[list[str]],
    force_skills: Optional[list[str]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "content": _build_message_content(prompt, prompt_file, content_parts),
    }
    if connectors:
        payload["connectors"] = connectors
    if enable_skills:
        payload["enable_skills"] = enable_skills
    if force_skills:
        payload["force_skills"] = force_skills
    return payload


def _print_wait_status(status: str, elapsed: float, latest_status: Optional[dict[str, Any]]) -> None:
    status_update = (latest_status or {}).get("status_update") or {}
    brief = status_update.get("brief") or status_update.get("description")
    suffix = f" - {brief}" if brief else ""
    print_status(f"Status: {status} ({elapsed:.0f}s elapsed){suffix}")


def _message_summary(message: dict[str, Any]) -> str:
    message_type = message.get("type")
    if message_type == "user_message":
        payload = message.get("user_message") or {}
        return payload.get("content", "")
    if message_type == "assistant_message":
        payload = message.get("assistant_message") or {}
        return payload.get("content", "")
    if message_type == "error_message":
        payload = message.get("error_message") or {}
        return payload.get("content", "")
    if message_type == "status_update":
        payload = message.get("status_update") or {}
        return payload.get("brief") or payload.get("description") or ""
    return ""


def _messages_table_rows(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for message in messages:
        status_update = message.get("status_update") or {}
        rows.append(
            {
                "id": message.get("id"),
                "type": message.get("type"),
                "timestamp": message.get("timestamp"),
                "agent_status": status_update.get("agent_status"),
                "summary": _message_summary(message),
            }
        )
    return rows


def _download_message_attachments(messages: list[dict[str, Any]], output_dir: Path) -> list[str]:
    downloaded: list[str] = []
    output_dir.mkdir(parents=True, exist_ok=True)

    for message in messages:
        for payload_key in ("assistant_message", "user_message"):
            payload = message.get(payload_key) or {}
            for attachment in payload.get("attachments", []):
                file_url = attachment.get("url")
                if not file_url:
                    continue

                file_name = attachment.get("filename") or Path(file_url).name or "download"
                file_path = output_dir / file_name
                try:
                    response = requests.get(file_url, timeout=60)
                    response.raise_for_status()
                    file_path.write_bytes(response.content)
                    downloaded.append(str(file_path))
                except Exception as exc:  # pragma: no cover - stderr-only fallback
                    print_error(f"Failed to download {file_name}: {exc}")

    return downloaded


@app.command("create")
def task_create(
    prompt: Optional[str] = typer.Argument(None, help="Prompt text for the initial task message."),
    prompt_file: Optional[str] = typer.Option(None, "--prompt-file", "-f", help="Read prompt text from a file."),
    content_part: Optional[list[str]] = typer.Option(
        None,
        "--content-part",
        "-c",
        help="Additional message content part as JSON object or array of objects.",
    ),
    agent_profile: str = typer.Option(
        DEFAULT_AGENT_PROFILE,
        "--agent-profile",
        "-a",
        help="Manus agent profile (manus-1.6, manus-1.6-lite, manus-1.6-max).",
    ),
    project_id: Optional[str] = typer.Option(None, "--project-id", help="Associate the task with a project ID."),
    interactive: bool = typer.Option(
        False,
        "--interactive/--no-interactive",
        help="Allow the agent to pause and ask follow-up questions.",
    ),
    wait: bool = typer.Option(True, "--wait/--no-wait", "-w", help="Wait until the task stops, errors, or pauses for confirmation."),
    timeout: float = typer.Option(900.0, "--timeout", help="Max seconds to wait for completion."),
    poll: float = typer.Option(2.0, "--poll", help="Seconds between status checks."),
    share_visibility: str = typer.Option(
        "private",
        "--share-visibility",
        help="Task visibility (private, team, public).",
    ),
    hide: bool = typer.Option(False, "--hide", help="Hide the task from the Manus webapp task list."),
    locale: Optional[str] = typer.Option(None, "--locale", "-l", help="Output locale (for example: en, zh-CN, ja)."),
    title: Optional[str] = typer.Option(None, "--title", help="Custom task title."),
    connector: Optional[list[str]] = typer.Option(None, "--connector", help="Connector ID to enable for the task."),
    enable_skill: Optional[list[str]] = typer.Option(
        None, "--enable-skill", help="Skill ID to enable for the task."
    ),
    force_skill: Optional[list[str]] = typer.Option(
        None, "--force-skill", help="Skill ID the agent must invoke."
    ),
    structured_output_schema: Optional[str] = typer.Option(
        None, "--structured-output-schema", help="Structured output JSON schema."
    ),
    structured_output_schema_file: Optional[str] = typer.Option(
        None, "--structured-output-schema-file", help="Read structured output JSON schema from a file."
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress status messages."),
):
    """Create a new Manus AI task using the v2 API."""
    try:
        _validate_choice("agent profile", agent_profile, VALID_AGENT_PROFILES)
        _validate_choice("share visibility", share_visibility, VALID_SHARE_VISIBILITY)
        client = get_client()
        message = _build_message_payload(
            prompt=prompt,
            prompt_file=prompt_file,
            content_parts=content_part,
            connectors=connector,
            enable_skills=enable_skill,
            force_skills=force_skill,
        )
        schema = _load_optional_json(
            structured_output_schema,
            structured_output_schema_file,
            "structured output schema",
        )

        if wait:
            result = client.create_and_wait(
                message=message,
                agent_profile=agent_profile,
                project_id=project_id,
                locale=locale,
                interactive_mode=interactive,
                hide_in_task_list=hide,
                share_visibility=share_visibility,
                title=title,
                structured_output_schema=schema,
                poll_interval=poll,
                max_wait=timeout,
                status_callback=None if quiet else _print_wait_status,
            )
        else:
            result = client.create_task(
                message=message,
                agent_profile=agent_profile,
                project_id=project_id,
                locale=locale,
                interactive_mode=interactive,
                hide_in_task_list=hide,
                share_visibility=share_visibility,
                title=title,
                structured_output_schema=schema,
            )

        print_json(result)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


def _send_task_message(
    task_id: str,
    prompt: Optional[str],
    prompt_file: Optional[str],
    content_part: Optional[list[str]],
    agent_profile: Optional[str],
    wait: bool,
    timeout: float,
    poll: float,
    connector: Optional[list[str]],
    enable_skill: Optional[list[str]],
    force_skill: Optional[list[str]],
    structured_output_schema: Optional[str],
    structured_output_schema_file: Optional[str],
    quiet: bool,
) -> None:
    if agent_profile is not None:
        _validate_choice("agent profile", agent_profile, VALID_AGENT_PROFILES)

    client = get_client()
    message = _build_message_payload(
        prompt=prompt,
        prompt_file=prompt_file,
        content_parts=content_part,
        connectors=connector,
        enable_skills=enable_skill,
        force_skills=force_skill,
    )
    schema = _load_optional_json(
        structured_output_schema,
        structured_output_schema_file,
        "structured output schema",
    )

    if wait:
        result = client.send_and_wait(
            task_id=task_id,
            message=message,
            agent_profile=agent_profile,
            structured_output_schema=schema,
            poll_interval=poll,
            max_wait=timeout,
            status_callback=None if quiet else _print_wait_status,
        )
    else:
        result = client.send_message(
            task_id=task_id,
            message=message,
            agent_profile=agent_profile,
            structured_output_schema=schema,
        )

    print_json(result)


@app.command("send")
def task_send(
    task_id: str = typer.Argument(..., help="Task ID to send the message to."),
    prompt: Optional[str] = typer.Argument(None, help="Follow-up prompt text."),
    prompt_file: Optional[str] = typer.Option(None, "--prompt-file", "-f", help="Read prompt text from a file."),
    content_part: Optional[list[str]] = typer.Option(
        None,
        "--content-part",
        "-c",
        help="Additional message content part as JSON object or array of objects.",
    ),
    agent_profile: Optional[str] = typer.Option(
        None,
        "--agent-profile",
        "-a",
        help="Optional Manus agent profile override for this turn.",
    ),
    wait: bool = typer.Option(True, "--wait/--no-wait", "-w", help="Wait until the task stops, errors, or pauses for confirmation."),
    timeout: float = typer.Option(900.0, "--timeout", help="Max seconds to wait for completion."),
    poll: float = typer.Option(2.0, "--poll", help="Seconds between status checks."),
    connector: Optional[list[str]] = typer.Option(None, "--connector", help="Connector ID to enable for this turn."),
    enable_skill: Optional[list[str]] = typer.Option(
        None, "--enable-skill", help="Skill ID to enable for this turn."
    ),
    force_skill: Optional[list[str]] = typer.Option(
        None, "--force-skill", help="Skill ID the agent must invoke during this turn."
    ),
    structured_output_schema: Optional[str] = typer.Option(
        None, "--structured-output-schema", help="Structured output JSON schema."
    ),
    structured_output_schema_file: Optional[str] = typer.Option(
        None, "--structured-output-schema-file", help="Read structured output JSON schema from a file."
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress status messages."),
):
    """Send a follow-up message to an existing task."""
    try:
        _send_task_message(
            task_id=task_id,
            prompt=prompt,
            prompt_file=prompt_file,
            content_part=content_part,
            agent_profile=agent_profile,
            wait=wait,
            timeout=timeout,
            poll=poll,
            connector=connector,
            enable_skill=enable_skill,
            force_skill=force_skill,
            structured_output_schema=structured_output_schema,
            structured_output_schema_file=structured_output_schema_file,
            quiet=quiet,
        )
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("continue")
def task_continue(
    task_id: str = typer.Argument(..., help="Task ID to continue."),
    prompt: Optional[str] = typer.Argument(None, help="Follow-up prompt text."),
    prompt_file: Optional[str] = typer.Option(None, "--prompt-file", "-f", help="Read prompt text from a file."),
    content_part: Optional[list[str]] = typer.Option(
        None,
        "--content-part",
        "-c",
        help="Additional message content part as JSON object or array of objects.",
    ),
    agent_profile: Optional[str] = typer.Option(
        None,
        "--agent-profile",
        "-a",
        help="Optional Manus agent profile override.",
    ),
    wait: bool = typer.Option(True, "--wait/--no-wait", "-w", help="Wait until the task stops, errors, or pauses for confirmation."),
    timeout: float = typer.Option(900.0, "--timeout", help="Max seconds to wait for completion."),
    poll: float = typer.Option(2.0, "--poll", help="Seconds between status checks."),
    connector: Optional[list[str]] = typer.Option(None, "--connector", help="Connector ID to enable for this turn."),
    enable_skill: Optional[list[str]] = typer.Option(None, "--enable-skill", help="Skill ID to enable for this turn."),
    force_skill: Optional[list[str]] = typer.Option(None, "--force-skill", help="Skill ID the agent must invoke."),
    structured_output_schema: Optional[str] = typer.Option(
        None, "--structured-output-schema", help="Structured output JSON schema."
    ),
    structured_output_schema_file: Optional[str] = typer.Option(
        None, "--structured-output-schema-file", help="Read structured output JSON schema from a file."
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress status messages."),
):
    """Hidden compatibility alias for task send."""
    task_send(
        task_id=task_id,
        prompt=prompt,
        prompt_file=prompt_file,
        content_part=content_part,
        agent_profile=agent_profile,
        wait=wait,
        timeout=timeout,
        poll=poll,
        connector=connector,
        enable_skill=enable_skill,
        force_skill=force_skill,
        structured_output_schema=structured_output_schema,
        structured_output_schema_file=structured_output_schema_file,
        quiet=quiet,
    )


@app.command("get")
def task_get(
    task_id: str = typer.Argument(..., help="Task ID to retrieve."),
    table: bool = typer.Option(False, "--table", "-t", help="Display the task as a formatted table."),
):
    """Get task metadata and current status."""
    try:
        result = get_client().get_task(task_id)
        if table:
            print_table([result])
        else:
            print_json(result)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("wait")
def task_wait(
    task_id: str = typer.Argument(..., help="Task ID to wait for."),
    timeout: float = typer.Option(900.0, "--timeout", help="Max seconds to wait."),
    poll: float = typer.Option(2.0, "--poll", help="Seconds between status checks."),
    verbose_messages: bool = typer.Option(
        False,
        "--verbose-messages",
        help="Include verbose message events while polling.",
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress status messages."),
):
    """Wait for a task to stop or pause for confirmation."""
    try:
        result = get_client().wait_for_task(
            task_id=task_id,
            poll_interval=poll,
            max_wait=timeout,
            status_callback=None if quiet else _print_wait_status,
            verbose_messages=verbose_messages,
        )
        print_json(result)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("list")
def task_list(
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum number of tasks to return."),
    table: bool = typer.Option(False, "--table", "-t", help="Display tasks as a formatted table."),
    filter_: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value."),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of properties to include (supports dot notation).",
    ),
    cursor: Optional[str] = typer.Option(None, "--cursor", help="Pagination cursor from a previous task list call."),
    order: str = typer.Option("desc", "--order", help="Sort direction (asc or desc)."),
    scope: Optional[str] = typer.Option(None, "--scope", help="Task scope filter."),
    agent_id: Optional[str] = typer.Option(None, "--agent-id", help="Filter by agent ID."),
    project_id: Optional[str] = typer.Option(None, "--project-id", help="Filter by project ID."),
):
    """List tasks from the Manus v2 API."""
    try:
        if filter_:
            validate_filters(filter_)
        _validate_choice("order", order, VALID_ORDER)
        _validate_choice("scope", scope, VALID_SCOPE)

        result = get_client().list_tasks(
            limit=limit,
            cursor=cursor,
            order=order,
            scope=scope,
            agent_id=agent_id,
            project_id=project_id,
        )
        tasks = result.get("data", [])
        if filter_:
            tasks = apply_filters(tasks, filter_)
        if properties:
            tasks = apply_properties_filter(tasks, properties)

        if table:
            if tasks:
                print_table(tasks)
            else:
                print_status("No tasks found.")
        else:
            print_json(tasks)
    except FilterValidationError as exc:
        print_error(str(exc))
        raise typer.Exit(1)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("messages")
def task_messages(
    task_id: str = typer.Argument(..., help="Task ID to list messages for."),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum number of messages to return."),
    table: bool = typer.Option(False, "--table", "-t", help="Display messages as a formatted table."),
    filter_: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value."),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of properties to include (supports dot notation).",
    ),
    cursor: Optional[str] = typer.Option(None, "--cursor", help="Pagination cursor from a previous messages call."),
    order: str = typer.Option("desc", "--order", help="Sort direction (asc or desc)."),
    verbose: bool = typer.Option(False, "--verbose", help="Include detailed tool/plan/explanation events."),
    slides_format: Optional[str] = typer.Option(
        None,
        "--slides-format",
        help="Slide attachment format when applicable (html or pptx).",
    ),
    download_files: bool = typer.Option(
        False,
        "--download-files",
        "-d",
        help="Download message attachments returned by the API.",
    ),
    output_dir: Optional[str] = typer.Option(
        None,
        "--output-dir",
        "-o",
        help="Directory for downloaded files (default: current directory).",
    ),
):
    """List task event messages from the Manus v2 API."""
    try:
        if filter_:
            validate_filters(filter_)
        _validate_choice("order", order, VALID_ORDER)
        _validate_choice("slides format", slides_format, VALID_SLIDES_FORMAT)

        result = get_client().list_messages(
            task_id=task_id,
            limit=limit,
            cursor=cursor,
            order=order,
            verbose=verbose,
            slides_format=slides_format,
        )
        messages = result.get("messages", [])
        if filter_:
            messages = apply_filters(messages, filter_)
        if download_files:
            destination = Path(output_dir) if output_dir else Path.cwd()
            downloaded = _download_message_attachments(messages, destination)
            if downloaded:
                for file_path in downloaded:
                    print_success(f"Downloaded: {file_path}")
            else:
                print_status("No attachments to download.")

        if properties:
            messages = apply_properties_filter(messages, properties)

        if table:
            rows = messages if properties else _messages_table_rows(messages)
            if rows:
                print_table(rows)
            else:
                print_status("No messages found.")
        else:
            print_json(messages)
    except FilterValidationError as exc:
        print_error(str(exc))
        raise typer.Exit(1)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("update")
def task_update(
    task_id: str = typer.Argument(..., help="Task ID to update."),
    title: Optional[str] = typer.Option(None, "--title", help="New title for the task."),
    share_visibility: Optional[str] = typer.Option(
        None,
        "--share-visibility",
        help="New task visibility (private, team, public).",
    ),
    visible_in_task_list: bool = typer.Option(
        False,
        "--visible-in-task-list",
        help="Show the task in the Manus webapp task list.",
    ),
    hidden_in_task_list: bool = typer.Option(
        False,
        "--hidden-in-task-list",
        help="Hide the task from the Manus webapp task list.",
    ),
):
    """Update task metadata."""
    try:
        if visible_in_task_list and hidden_in_task_list:
            raise ClientError("Use either --visible-in-task-list or --hidden-in-task-list, not both.")
        visibility_override: Optional[bool] = None
        if visible_in_task_list:
            visibility_override = True
        elif hidden_in_task_list:
            visibility_override = False

        if title is None and share_visibility is None and visibility_override is None:
            raise ClientError(
                "Provide at least one update option: --title, --share-visibility, "
                "--visible-in-task-list, or --hidden-in-task-list."
            )
        _validate_choice("share visibility", share_visibility, VALID_SHARE_VISIBILITY)
        result = get_client().update_task(
            task_id=task_id,
            title=title,
            share_visibility=share_visibility,
            visible_in_task_list=visibility_override,
        )
        print_json(result)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("stop")
def task_stop(task_id: str = typer.Argument(..., help="Task ID to stop.")):
    """Stop a running task."""
    try:
        print_json(get_client().stop_task(task_id))
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("delete")
def task_delete(task_id: str = typer.Argument(..., help="Task ID to delete.")):
    """Delete a task."""
    try:
        print_json(get_client().delete_task(task_id))
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("confirm")
def task_confirm(
    task_id: str = typer.Argument(..., help="Task ID with the pending action."),
    event_id: str = typer.Argument(..., help="Waiting event ID from task messages."),
    input_json: Optional[str] = typer.Option(None, "--input", help="Optional JSON input for the confirmation."),
    input_file: Optional[str] = typer.Option(
        None, "--input-file", help="Read optional confirmation JSON input from a file."
    ),
):
    """Confirm a pending action so a waiting task can resume."""
    try:
        input_data = _load_optional_json(input_json, input_file, "confirmation input")
        print_json(get_client().confirm_action(task_id=task_id, event_id=event_id, input_data=input_data))
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
