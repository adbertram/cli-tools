"""Official Descript API CLI wrapper commands."""
from __future__ import annotations

from typing import List, Optional

import typer

from cli_tools_shared.output import print_error

from ..platform import (
    PlatformCLIError,
    _append_bool,
    _append_option,
    _append_repeated,
    run_platform_passthrough,
)


app = typer.Typer(
    help="Run official Descript API CLI commands",
    no_args_is_help=True,
)

FOLDER_IMPORT_TEAM_ACCESS_LEVELS = {"edit", "comment", "view"}


def _run(args: list[str], *, profile: Optional[str] = None) -> None:
    try:
        code = run_platform_passthrough(args, profile=profile)
    except PlatformCLIError as exc:
        print_error(str(exc))
        raise typer.Exit(1)
    raise typer.Exit(code)


def _validate_folder_import_team_access(folder: Optional[str], team_access: Optional[str]) -> None:
    if folder is not None and team_access not in FOLDER_IMPORT_TEAM_ACCESS_LEVELS:
        print_error("Importing into --folder requires --team-access edit, comment, or view.")
        raise typer.Exit(1)


@app.command("import")
def import_media(
    profile: Optional[str] = typer.Option(None, "--profile", help="Official descript-api profile"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Project name for new projects"),
    project_id: Optional[str] = typer.Option(None, "--project-id", "-p", help="Existing project ID"),
    media: Optional[List[str]] = typer.Option(None, "--media", "-m", help="Media URL(s) or local file path(s)"),
    folder: Optional[str] = typer.Option(None, "--folder", help="Folder path for a new project"),
    team_access: Optional[str] = typer.Option(
        None,
        "--team-access",
        help="Team access level; required for --folder imports (edit, comment, or view)",
    ),
    callback_url: Optional[str] = typer.Option(None, "--callback-url", help="Callback URL"),
    timeout: Optional[int] = typer.Option(None, "--timeout", help="Job polling timeout in minutes"),
    no_wait: bool = typer.Option(False, "--no-wait", help="Create job without waiting"),
    new: bool = typer.Option(False, "--new", help="Create new project with default name"),
    no_composition: bool = typer.Option(False, "--no-composition", help="Skip composition creation"),
    language: Optional[str] = typer.Option(None, "--language", help="ISO 639-1 transcription language code"),
) -> None:
    """Import media, sequences, and compositions with the official CLI."""
    _validate_folder_import_team_access(folder, team_access)
    args = ["import"]
    _append_option(args, "--name", name)
    _append_option(args, "--project-id", project_id)
    _append_repeated(args, "--media", media)
    _append_option(args, "--folder", folder)
    _append_option(args, "--team-access", team_access)
    _append_option(args, "--callback-url", callback_url)
    _append_option(args, "--timeout", timeout)
    _append_bool(args, "--no-wait", no_wait)
    _append_bool(args, "--new", new)
    _append_bool(args, "--no-composition", no_composition)
    _append_option(args, "--language", language)
    _run(args, profile=profile)


@app.command("agent")
def agent(
    profile: Optional[str] = typer.Option(None, "--profile", help="Official descript-api profile"),
    project_id: Optional[str] = typer.Option(None, "--project-id", "-p", help="Existing project ID"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Project name for new projects"),
    composition_id: Optional[str] = typer.Option(None, "--composition-id", "-c", help="Composition to edit"),
    prompt: Optional[str] = typer.Option(None, "--prompt", help="Natural language editing instruction"),
    model: Optional[str] = typer.Option(None, "--model", help="AI model to use"),
    callback_url: Optional[str] = typer.Option(None, "--callback-url", help="Callback URL"),
    team_access: Optional[str] = typer.Option(None, "--team-access", help="Team access level"),
    timeout: Optional[int] = typer.Option(None, "--timeout", help="Job polling timeout in minutes"),
    no_wait: bool = typer.Option(False, "--no-wait", help="Create job without waiting"),
    new: bool = typer.Option(False, "--new", help="Create new project with default name"),
) -> None:
    """Run official Underlord agent editing on a project."""
    args = ["agent"]
    _append_option(args, "--project-id", project_id)
    _append_option(args, "--name", name)
    _append_option(args, "--composition-id", composition_id)
    _append_option(args, "--prompt", prompt)
    _append_option(args, "--model", model)
    _append_option(args, "--callback-url", callback_url)
    _append_option(args, "--team-access", team_access)
    _append_option(args, "--timeout", timeout)
    _append_bool(args, "--no-wait", no_wait)
    _append_bool(args, "--new", new)
    _run(args, profile=profile)


@app.command("job-status")
def job_status(
    job_id: str = typer.Argument(..., help="Job ID to check"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Official descript-api profile"),
    no_wait: bool = typer.Option(False, "--no-wait", help="Show current status without waiting"),
    timeout: Optional[int] = typer.Option(None, "--timeout", help="Job polling timeout in minutes"),
) -> None:
    """Get official job status."""
    args = ["job-status", job_id]
    _append_bool(args, "--no-wait", no_wait)
    _append_option(args, "--timeout", timeout)
    _run(args, profile=profile)


@app.command("list-jobs")
def list_jobs(
    profile: Optional[str] = typer.Option(None, "--profile", help="Official descript-api profile"),
    project_id: Optional[str] = typer.Option(None, "--project-id", "-p", help="Filter by project ID"),
    job_type: Optional[str] = typer.Option(None, "--type", "-t", help="Filter by job type"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Number of jobs per page"),
    cursor: Optional[str] = typer.Option(None, "--cursor", help="Pagination cursor"),
    created_after: Optional[str] = typer.Option(None, "--created-after", help="Created after ISO 8601 timestamp"),
    created_before: Optional[str] = typer.Option(None, "--created-before", help="Created before ISO 8601 timestamp"),
    no_interactive: bool = typer.Option(False, "--no-interactive", help="Disable interactive selection"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON response"),
) -> None:
    """List official Descript API jobs."""
    args = ["list-jobs"]
    _append_option(args, "--project-id", project_id)
    _append_option(args, "--type", job_type)
    _append_option(args, "--limit", limit)
    _append_option(args, "--cursor", cursor)
    _append_option(args, "--created-after", created_after)
    _append_option(args, "--created-before", created_before)
    _append_bool(args, "--no-interactive", no_interactive)
    _append_bool(args, "--json", json_output)
    _run(args, profile=profile)


@app.command("job-cancel")
def job_cancel(
    job_id: str = typer.Argument(..., help="Job ID to cancel"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Official descript-api profile"),
) -> None:
    """Cancel an official Descript API job."""
    _run(["job-cancel", job_id], profile=profile)


@app.command("list-projects")
def list_projects(
    profile: Optional[str] = typer.Option(None, "--profile", help="Official descript-api profile"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Filter projects by name"),
    folder_path: Optional[str] = typer.Option(None, "--folder-path", help="Filter by folder path"),
    created_by: Optional[str] = typer.Option(None, "--created-by", help="Filter by creator user ID"),
    created_after: Optional[str] = typer.Option(None, "--created-after", help="Created after ISO 8601 timestamp"),
    created_before: Optional[str] = typer.Option(None, "--created-before", help="Created before ISO 8601 timestamp"),
    updated_after: Optional[str] = typer.Option(None, "--updated-after", help="Updated after ISO 8601 timestamp"),
    updated_before: Optional[str] = typer.Option(None, "--updated-before", help="Updated before ISO 8601 timestamp"),
    sort: Optional[str] = typer.Option(None, "--sort", "-s", help="Sort field"),
    direction: Optional[str] = typer.Option(None, "--direction", help="Sort direction"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Number of projects per page"),
    cursor: Optional[str] = typer.Option(None, "--cursor", help="Pagination cursor"),
    no_interactive: bool = typer.Option(False, "--no-interactive", help="Disable interactive selection"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON response"),
) -> None:
    """List projects through the official Descript API CLI."""
    args = ["list-projects"]
    _append_option(args, "--name", name)
    _append_option(args, "--folder-path", folder_path)
    _append_option(args, "--created-by", created_by)
    _append_option(args, "--created-after", created_after)
    _append_option(args, "--created-before", created_before)
    _append_option(args, "--updated-after", updated_after)
    _append_option(args, "--updated-before", updated_before)
    _append_option(args, "--sort", sort)
    _append_option(args, "--direction", direction)
    _append_option(args, "--limit", limit)
    _append_option(args, "--cursor", cursor)
    _append_bool(args, "--no-interactive", no_interactive)
    _append_bool(args, "--json", json_output)
    _run(args, profile=profile)


@app.command("get-project")
def get_project(
    project_id: Optional[str] = typer.Argument(None, help="Project UUID"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Official descript-api profile"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON response"),
) -> None:
    """Get an official project summary."""
    args = ["get-project"]
    _append_bool(args, "--json", json_output)
    if project_id is not None:
        args.append(project_id)
    _run(args, profile=profile)


@app.command("list-folders")
def list_folders(
    profile: Optional[str] = typer.Option(None, "--profile", help="Official descript-api profile"),
    parent_path: Optional[str] = typer.Option(None, "--parent-path", help="Parent folder path"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON response"),
) -> None:
    """List folders through the official Descript API CLI."""
    args = ["list-folders"]
    _append_option(args, "--parent-path", parent_path)
    _append_bool(args, "--json", json_output)
    _run(args, profile=profile)


@app.command("publish")
def publish(
    profile: Optional[str] = typer.Option(None, "--profile", help="Official descript-api profile"),
    project_id: Optional[str] = typer.Option(None, "--project-id", "-p", help="Project ID to publish"),
    composition_id: Optional[str] = typer.Option(None, "--composition-id", "-c", help="Composition ID to publish"),
    media_type: Optional[str] = typer.Option(None, "--media-type", "-m", help="Published media type"),
    resolution: Optional[str] = typer.Option(None, "--resolution", "-r", help="Published resolution"),
    callback_url: Optional[str] = typer.Option(None, "--callback-url", help="Callback URL"),
    access_level: Optional[str] = typer.Option(None, "--access-level", help="Share page access level"),
    timeout: Optional[int] = typer.Option(None, "--timeout", help="Job polling timeout in minutes"),
    no_wait: bool = typer.Option(False, "--no-wait", help="Create job without waiting"),
) -> None:
    """Publish a project composition through the official CLI."""
    args = ["publish"]
    _append_option(args, "--project-id", project_id)
    _append_option(args, "--composition-id", composition_id)
    _append_option(args, "--media-type", media_type)
    _append_option(args, "--resolution", resolution)
    _append_option(args, "--callback-url", callback_url)
    _append_option(args, "--access-level", access_level)
    _append_option(args, "--timeout", timeout)
    _append_bool(args, "--no-wait", no_wait)
    _run(args, profile=profile)


@app.command("export-transcript")
def export_transcript(
    profile: Optional[str] = typer.Option(None, "--profile", help="Official descript-api profile"),
    project_id: Optional[str] = typer.Option(None, "--project-id", "-p", help="Project ID to export from"),
    fmt: Optional[str] = typer.Option(None, "--format", "-f", help="Transcript format"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output path or '-' for stdout"),
    composition_id: Optional[str] = typer.Option(None, "--composition-id", "-c", help="Composition ID"),
    speaker_labels: Optional[str] = typer.Option(None, "--speaker-labels", help="Speaker label mode"),
    timecodes: bool = typer.Option(False, "--timecodes", help="Include timecodes"),
    timecode_on_paragraphs: bool = typer.Option(False, "--timecode-on-paragraphs", help="Timecodes at paragraph breaks"),
    timecode_on_speakers: bool = typer.Option(False, "--timecode-on-speakers", help="Timecodes at speaker changes"),
    markers: bool = typer.Option(False, "--markers", help="Include markers"),
) -> None:
    """Export a transcript through the official CLI."""
    args = ["export-transcript"]
    _append_option(args, "--project-id", project_id)
    _append_option(args, "--format", fmt)
    _append_option(args, "--output", output)
    _append_option(args, "--composition-id", composition_id)
    _append_option(args, "--speaker-labels", speaker_labels)
    _append_bool(args, "--timecodes", timecodes)
    _append_bool(args, "--timecode-on-paragraphs", timecode_on_paragraphs)
    _append_bool(args, "--timecode-on-speakers", timecode_on_speakers)
    _append_bool(args, "--markers", markers)
    _run(args, profile=profile)


@app.command("update")
def update() -> None:
    """Check for official Descript API CLI updates."""
    _run(["update"])


@app.command("help")
def help_command(command: Optional[str] = typer.Argument(None, help="Official command name")) -> None:
    """Show official Descript API CLI help."""
    args = ["help"]
    if command is not None:
        args.append(command)
    _run(args)


COMMAND_CREDENTIALS = {
    "agent": ["custom"],
    "export-transcript": ["custom"],
    "get-project": ["custom"],
    "help": ["no_auth"],
    "import": ["custom"],
    "job-cancel": ["custom"],
    "job-status": ["custom"],
    "list-folders": ["custom"],
    "list-jobs": ["custom"],
    "list-projects": ["custom"],
    "publish": ["custom"],
    "update": ["no_auth"],
}
