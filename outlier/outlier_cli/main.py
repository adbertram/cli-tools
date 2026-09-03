"""Main entry point for Outlier CLI."""

import typer
from typing import List, Optional

from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.filters import apply_filters, apply_properties_filter, validate_filters
from cli_tools_shared.output import command, print_output

from . import __version__
from .client import ClientError, get_client
from .config import get_config

app = create_app(
    name="outlier",
    help="CLI interface for Outlier AI (browser automation, worker side)",
    version=__version__,
)
tasks_app = typer.Typer(help="Inspect queued Outlier work assignments", no_args_is_help=True)
queue_app = typer.Typer(help="Inspect the Outlier task queue itself", no_args_is_help=True)
onboarding_app = typer.Typer(
    help="Inspect and advance Outlier expert onboarding", no_args_is_help=True
)
steps_app = typer.Typer(help="Inspect individual onboarding steps", no_args_is_help=True)
phone_app = typer.Typer(help="Phone verification for the Create Profile step", no_args_is_help=True)
skills_app = typer.Typer(help="The Import skills onboarding step", no_args_is_help=True)

COLUMNS = {
    "id": "Task ID",
    "type": "Type",
    "display_name": "Name",
    "qualification_type": "Qualification",
    "qualification_status": "Status",
    "is_assessment": "Assessment",
    "url": "URL",
}
DETAIL_COLUMNS = {
    "id": "Task ID",
    "type": "Type",
    "assignment_type": "Assignment Type",
    "project_id": "Project ID",
    "display_name": "Name",
    "description": "Description",
    "qualification_type": "Qualification",
    "qualification_status": "Status",
    "qualification_list_status": "Qualification List Status",
    "qualification_estimated_time": "Estimated Time",
    "is_assessment": "Assessment",
    "review_level": "Review Level",
    "url": "URL",
}
QUEUE_COLUMNS = {
    "is_empty_queue": "Empty",
    "assignment_count": "Assignments",
    "empty_queue_reason": "Empty Reason",
    "active_worker_team": "Worker Team",
    "requested_at": "Requested At",
}
ONBOARDING_COLUMNS = {
    "result": "Result",
    "step_display_name": "Current Step",
    "step_type": "Step Type",
    "step_status": "Step Status",
    "next_step_id": "Next Step",
    "next_step_status": "Next Status",
    "flow_display_name": "Flow",
}
STEP_COLUMNS = {
    "id": "Step ID",
    "title": "Title",
    "status": "Status",
    "description": "Description",
}
PROFILE_COLUMNS = {
    "worker_id": "Worker ID",
    "status": "Status",
    "first_name": "First Name",
    "last_name": "Last Name",
    "country_code": "Country",
    "state": "State",
    "phone_number": "Phone",
    "phone_number_verified": "Phone Verified",
}
IDENTITY_COLUMNS = {
    "persona_identity_verification": "Persona Inquiry",
    "idv_audit_status": "IDV Audit Status",
}
RESUME_COLUMNS = {
    "uploaded": "Uploaded",
    "resume_file": "Resume File",
    "url": "URL",
}
PHONE_VERIFY_COLUMNS = {
    "verified": "Verified",
    "phone_number": "Phone",
    "channel": "Channel",
    "requested_at_ms": "Requested At (ms)",
    "url": "URL",
}


def _emit(rows, table: bool, properties: Optional[str], columns: dict) -> None:
    """Render list output (a list of dicts) or single-item output (one dict)."""
    if properties:
        keys = [field.strip() for field in properties.split(",") if field.strip()]
        if isinstance(rows, list):
            rows = apply_properties_filter(rows, properties)
        else:
            rows = apply_properties_filter([rows], properties)[0]
        print_output(rows, table=table, columns=keys, headers=keys)
        return
    print_output(rows, table=table, columns=list(columns), headers=list(columns.values()))


@tasks_app.command("list")
@command
def tasks_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of tasks"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter: field:op:value (e.g., type:eq:OUTLIER_QUALIFICATION_IN_QUEUE)"
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated properties"
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """List the work assignments currently queued for this Outlier account."""
    if filter:
        validate_filters(filter)
    client = get_client(profile)
    try:
        rows = client.list_tasks(limit=limit)
    finally:
        client.close()
    if filter:
        rows = apply_filters(rows, filter)
    _emit(rows, table, properties, COLUMNS)


@tasks_app.command("get")
@command
def tasks_get(
    task_id: str = typer.Argument(..., help="Task ID (the `id` field from 'tasks list')"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated properties"
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Get full detail for a single queued assignment."""
    client = get_client(profile)
    try:
        row = client.get_task(task_id)
    finally:
        client.close()
    _emit(row, table, properties, DETAIL_COLUMNS)


@queue_app.command("status")
@command
def queue_status(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated properties"
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Show queue state, including why the queue is empty when it is."""
    client = get_client(profile)
    try:
        row = client.get_queue_status()
    finally:
        client.close()
    _emit(row, table, properties, QUEUE_COLUMNS)


@onboarding_app.command("status")
@command
def onboarding_status(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated properties"
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Show the live onboarding step, its status, and every step's state."""
    client = get_client(profile)
    try:
        row = client.get_onboarding_status()
    finally:
        client.close()
    _emit(row, table, properties, ONBOARDING_COLUMNS)


@steps_app.command("list")
@command
def onboarding_steps_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of steps"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter: field:op:value (e.g., status:eq:unstarted)"
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated properties"
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """List every onboarding step Outlier requires, with its current status."""
    if filter:
        validate_filters(filter)
    client = get_client(profile)
    try:
        rows = client.list_onboarding_steps(limit=limit)
    finally:
        client.close()
    if filter:
        rows = apply_filters(rows, filter)
    _emit(rows, table, properties, STEP_COLUMNS)


@steps_app.command("get")
@command
def onboarding_steps_get(
    step_id: str = typer.Argument(..., help="Step ID (e.g., complete-profile)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated properties"
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Get one onboarding step by its ID."""
    client = get_client(profile)
    try:
        row = client.get_onboarding_step(step_id)
    finally:
        client.close()
    _emit(row, table, properties, STEP_COLUMNS)


@onboarding_app.command("profile")
@command
def onboarding_profile(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated properties"
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Show the worker profile the Create Profile step is prefilled from."""
    client = get_client(profile)
    try:
        row = client.get_profile()
    finally:
        client.close()
    _emit(row, table, properties, PROFILE_COLUMNS)


@phone_app.command("verify")
@command
def phone_verify(
    phone: str = typer.Option(..., "--phone", help="Phone number, national format"),
    channel: str = typer.Option(
        "sms", "--channel", "-c", help="Delivery channel: sms or whatsapp"
    ),
    first_name: Optional[str] = typer.Option(
        None, "--first-name", help="Overwrite the legal first name before submitting"
    ),
    last_name: Optional[str] = typer.Option(
        None, "--last-name", help="Overwrite the legal last name before submitting"
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated properties"
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Complete Create Profile: submit it, read the SMS code, and enter it."""
    client = get_client(profile)
    try:
        row = client.verify_phone(
            phone, channel=channel, first_name=first_name, last_name=last_name
        )
    finally:
        client.close()
    _emit(row, table, properties, PHONE_VERIFY_COLUMNS)


@onboarding_app.command("identity")
@command
def onboarding_identity(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated properties"
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Show identity-verification state (the Persona / Verify identity step)."""
    client = get_client(profile)
    try:
        row = client.get_identity_verification()
    finally:
        client.close()
    _emit(row, table, properties, IDENTITY_COLUMNS)


@skills_app.command("upload-resume")
@command
def skills_upload_resume(
    file: str = typer.Option(..., "--file", help="Path to a .pdf or .docx resume"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated properties"
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Attach a resume to the Import skills step."""
    client = get_client(profile)
    try:
        row = client.upload_resume(file)
    finally:
        client.close()
    _emit(row, table, properties, RESUME_COLUMNS)


app.add_typer(tasks_app, name="tasks")
app.add_typer(queue_app, name="queue")
onboarding_app.add_typer(steps_app, name="steps")
onboarding_app.add_typer(phone_app, name="phone")
onboarding_app.add_typer(skills_app, name="skills")
app.add_typer(onboarding_app, name="onboarding")
app.add_typer(create_auth_app(get_config, tool_name="outlier"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
