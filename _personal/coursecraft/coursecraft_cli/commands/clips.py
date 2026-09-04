"""Clips command module."""
import json
import typer
from typing import Optional, List, Dict
from pathlib import Path
from rich.console import Console

from cli_tools_shared.filters import apply_limit
from cli_tools_shared.output import command
from ..batch import load_batch_payload
from ..client import get_client, ClientError, CourseCraftClient
from ..output import apply_properties_filter, project_record, print_success, print_error, print_info, print_json, print_table
from ..filter_translator import translate_filters

# Rich console for colored output
_console = Console()

app = typer.Typer(help="Manage clip records")


def create_clips_from_json(client: CourseCraftClient, module_record_id: str, clips_list: List[Dict]):
    """
    Create clips from JSON data (called by modules.py for nested creation).

    Args:
        client: CourseCraft client instance
        module_record_id: Parent module record ID
        clips_list: List of clip definitions
    """
    print_info(f"Creating {len(clips_list)} clip(s)...")

    created_ids = []
    for clip_data in clips_list:
        clip_name = clip_data.get("name")
        if not clip_name:
            print_error("Clip missing 'name' field")
            raise typer.Exit(1)
        if "status" in clip_data:
            print_error("Clip Status is computed by Airtable; remove 'status' from clip JSON")
            raise typer.Exit(1)

        # Check if clip name already exists in this module
        existing_id = client.check_clip_exists(clip_name, module_record_id)
        if existing_id:
            print_error(f"Clip with name '{clip_name}' already exists in this module: {existing_id}")
            raise typer.Exit(1)

        # Build clip fields
        fields = {
            "Name": clip_name,
            "Module": [module_record_id],
        }

        # Add optional fields
        if "order" in clip_data:
            fields["Order"] = clip_data["order"]
        if "description" in clip_data:
            fields["Description"] = clip_data["description"]
        if "story" in clip_data:
            fields["Story"] = clip_data["story"]
        if "target_length" in clip_data:
            fields["Target Length (Min)"] = clip_data["target_length"]

        # Create the clip
        clip_record_id = client.create_record("Clips", fields)
        print_success(f"Created clip '{clip_name}': {clip_record_id}")
        created_ids.append(clip_record_id)

    return created_ids


@app.command("create")
@command
def create_clip(
    module: str = typer.Option(..., "--module", "-m", help="Module record ID (required)"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Clip name (required in single mode)"),
    order: Optional[int] = typer.Option(None, "--order", "-o", help="Clip sequence order"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Clip description from the course outline"),
    story: Optional[str] = typer.Option(None, "--story", "-s", help="Clip story/narrative"),
    target_length: Optional[float] = typer.Option(None, "--target-length", "-t", help="Target length in minutes (e.g., 5.2)"),
    notes: Optional[str] = typer.Option(None, "--notes", help="Internal notes"),
    clips_json: Optional[str] = typer.Option(None, "--json", help="Inline JSON array of clips (batch mode)"),
    clips_file: Optional[Path] = typer.Option(None, "--file", help="Path to JSON file with clip definitions"),
):
    """
    Create clip record(s) in Airtable.

    Supports two modes:
    1. Single clip mode: Use --name to create one clip
    2. Batch mode: Use --json or --file to create multiple clips

    Examples:
        # Single clip
        coursecraft clips create --module recXXX --name "Introduction" --order 1

        # Batch from inline JSON
        coursecraft clips create --module recXXX --json '[{"name":"Clip 1"},{"name":"Clip 2"}]'

        # Batch from file
        coursecraft clips create --module recXXX --file clips.json
    """
    try:
        client = get_client()

        # Determine mode: batch or single
        if clips_file or clips_json:
            # Batch mode
            clips_list = load_batch_payload(clips_json, clips_file)
            created_ids = create_clips_from_json(client, module, clips_list)

            # Output all created IDs as JSON array for scripting
            typer.echo(json.dumps(created_ids))
        else:
            # Single clip mode
            if not name:
                print_error("--name is required in single clip mode")
                raise typer.Exit(1)

            # Check if clip name already exists in this module
            existing_id = client.check_clip_exists(name, module)
            if existing_id:
                print_error(f"Clip with name '{name}' already exists in this module: {existing_id}")
                raise typer.Exit(1)

            # Build fields dictionary
            fields = {
                "Name": name,
                "Module": [module],
            }

            # Add optional fields
            if order is not None:
                fields["Order"] = order
            if description:
                fields["Description"] = description
            if story:
                fields["Story"] = story
            if target_length is not None:
                fields["Target Length (Min)"] = target_length
            if notes is not None:
                fields["Notes"] = notes

            # Create the clip
            record_id = client.create_record("Clips", fields)
            print_success(f"Created clip '{name}': {record_id}")

            # Output the record ID for scripting
            typer.echo(record_id)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("list")
@command
def list_clips(
    module: Optional[str] = typer.Option(None, "--module", "-m", help="Filter by module record ID"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum number of records to return"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Property to include (supports dot notation). Repeatable; each value may also be comma-separated."),
    table_output: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    List clip records.

    Examples:
        # List all clips
        coursecraft clips list

        # List clips for a module
        coursecraft clips list --module recXXX

        # List with standard filter
        coursecraft clips list --filter "status:eq:Complete"

        # Match the CourseCraft clip ID field
        coursecraft clips list --filter "id:eq:M3C2"

        # Combine --module with an additional filter
        coursecraft clips list --module recXXX --filter "name:contains:Intro"

        # List with table output
        coursecraft clips list --module recXXX --table

        # Limit results
        coursecraft clips list --limit 10

        # Select specific properties
        coursecraft clips list --properties "id,fields.Name,fields.Status"
    """
    try:
        client = get_client()

        # Build filter formula. --module and --filter combine (AND-ed
        # together), the same pattern list_modules uses for --course + --filter.
        formula = None
        if module:
            formula = f"{{Module Record ID}}='{module}'"
            if filter:
                filter_formula = translate_filters(list(filter), 'Clips')
                formula = f"AND({formula},{filter_formula})"
        elif filter:
            formula = translate_filters(list(filter), 'Clips')

        records = client.list_records("Clips", formula)

        # Apply limit
        records = apply_limit(records, limit)

        # Apply properties filter for JSON output
        if properties and not table_output:
            records = apply_properties_filter(records, properties)

        if table_output:
            # Format for table display
            rows = []
            for rec in records:
                fields = rec.get("fields", {})
                rows.append({
                    "id": rec["id"],
                    "name": fields.get("Name", ""),
                    "order": fields.get("Order", ""),
                    "status": fields.get("Status", ""),
                    "target_length": fields.get("Target Length (Min)", ""),
                })
            print_table(rows, ["id", "name", "order", "status", "target_length"],
                       ["Record ID", "Name", "Order", "Status", "Target Length"])
        else:
            print_json(records)

    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("get")
@command
def get_clip(
    record_id: str = typer.Argument(..., help="Clip record ID"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Property to include (supports dot notation). Repeatable; each value may also be comma-separated."),
    table_output: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Get a single clip record by ID.

    Examples:
        coursecraft clips get recXXXXXXXXXXXXXXX
        coursecraft clips get recXXXXXXXXXXXXXXX --properties "id,fields.Name"
        coursecraft clips get recXXXXXXXXXXXXXXX --table
    """
    try:
        client = get_client()
        record = client.get_record("Clips", record_id)

        if not record:
            print_error(f"Clip not found: {record_id}")
            raise typer.Exit(1)

        if properties and not table_output:
            record = project_record(record, properties)

        if table_output:
            fields = record.get("fields", {})
            story = fields.get("Story", "")
            rows = [{
                "id": record["id"],
                "name": fields.get("Name", ""),
                "order": fields.get("Order", ""),
                "story": story[:50] + "..." if story and len(story) > 50 else story,
                "status": fields.get("Status", ""),
                "target_length": fields.get("Target Length (Min)", ""),
            }]
            print_table(rows, ["id", "name", "order", "story", "status", "target_length"],
                       ["Record ID", "Name", "Order", "Story", "Status", "Target Length"])
        else:
            print_json(record)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("update")
@command
def update_clip(
    record_id: str = typer.Argument(..., help="Clip record ID"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Clip name"),
    module: Optional[str] = typer.Option(None, "--module", "-m", help="Parent module record ID"),
    order: Optional[int] = typer.Option(None, "--order", "-o", help="Clip sequence order"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Clip description from the course outline"),
    story: Optional[str] = typer.Option(None, "--story", "-s", help="Clip story/narrative"),
    learning_objectives: Optional[str] = typer.Option(None, "--learning-objectives", "-l", help="Clip learning objectives"),
    target_length: Optional[float] = typer.Option(None, "--target-length", help="Target length in minutes (e.g., 5.2)"),
    notes: Optional[str] = typer.Option(None, "--notes", help="Internal notes"),
    clip_plan_review_ai: Optional[str] = typer.Option(None, "--clip-plan-review-ai", help="AI review of the clip plan"),
    content_done: Optional[bool] = typer.Option(None, "--content-done/--no-content-done", help="Set or clear the clip content-structure-complete flag"),
    recording_review_human: Optional[bool] = typer.Option(None, "--recording-review-human/--no-recording-review-human", help="Set or clear the clip recording human-review flag"),
    feedback_requested: Optional[bool] = typer.Option(None, "--feedback-requested/--no-feedback-requested", help="Set or clear the feedback-requested gate flag"),
    feedback_requested_at: Optional[str] = typer.Option(None, "--feedback-requested-at", help="ISO 8601 timestamp the feedback gate was requested"),
    base_record: Optional[str] = typer.Option(None, "--base-record", help="Course-update lineage: the clip in the base course version this record derives from"),
    slide_narration_complete: Optional[bool] = typer.Option(None, "--slide-narration-complete/--no-slide-narration-complete", help="Set or clear the slide narration complete flag"),
):
    """
    Update a clip record.

    Examples:
        coursecraft clips update recXXX --name "New Name"
        coursecraft clips update recXXX --order 2
        coursecraft clips update recXXX --learning-objectives "- Objective 1\\n- Objective 2"
        coursecraft clips update recXXX --content-done
    """
    try:
        client = get_client()

        # Verify record exists
        existing = client.get_record("Clips", record_id)
        if not existing:
            print_error(f"Clip not found: {record_id}")
            raise typer.Exit(1)

        # Build fields dictionary with only provided values
        fields = {}
        if name is not None:
            fields["Name"] = name
        if module is not None:
            fields["Module"] = [module]
        if order is not None:
            fields["Order"] = order
        if description is not None:
            fields["Description"] = description
        if story is not None:
            fields["Story"] = story
        if learning_objectives is not None:
            fields["Learning Objectives"] = learning_objectives
        if target_length is not None:
            fields["Target Length (Min)"] = target_length
        if notes is not None:
            fields["Notes"] = notes
        if clip_plan_review_ai is not None:
            fields["Clip Plan Review (AI)"] = clip_plan_review_ai
        if content_done is not None:
            fields["Clip Structure Confirmed"] = content_done
        if recording_review_human is not None:
            fields["Recording Human Verified"] = recording_review_human
        if feedback_requested is not None:
            fields["Feedback Requested"] = feedback_requested
        if feedback_requested_at is not None:
            fields["Feedback Requested At"] = feedback_requested_at
        if slide_narration_complete is not None:
            fields["Slide Narration Complete"] = slide_narration_complete

        # Guard runs after every field (including boolean flags) is collected so a
        # standalone flag such as --content-done counts as an update.
        if base_record is not None:
            fields["Base Record"] = [base_record]

        if not fields:
            print_error("No fields to update. Provide at least one field option.")
            raise typer.Exit(1)

        # Update the record
        client.update_record("Clips", record_id, fields)
        print_success(f"Updated clip: {record_id}")

        # Check for sync warnings
        # Output the record ID for scripting
        typer.echo(record_id)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


def _collect_clip_records(client, clip_record_id: str) -> Dict[str, List[Dict]]:
    """
    Collect all records that belong to a clip (demos, slides).

    Returns dict with keys: clip, demos, slides
    """
    result = {
        "clip": None,
        "demos": [],
        "slides": []
    }

    # Get the clip record
    clip = client.get_record("Clips", clip_record_id)
    if not clip:
        raise ClientError(f"Clip not found: {clip_record_id}")
    result["clip"] = clip

    # Get all demos and slides
    result["demos"] = client.get_demos_by_clip(clip_record_id)
    result["slides"] = client.get_slides_by_clip(clip_record_id)

    return result


def _delete_clip_cascade(client, records: Dict[str, List[Dict]]) -> Dict[str, int]:
    """
    Delete all records in cascade order (children first).

    Returns dict with counts of deleted records by type.
    """
    deleted = {"slides": 0, "demos": 0, "clip": 0}

    # Delete slides first
    for slide in records["slides"]:
        client.delete_record("Slides", slide["id"])
        deleted["slides"] += 1

    # Delete demos
    for demo in records["demos"]:
        client.delete_record("Demos", demo["id"])
        deleted["demos"] += 1

    # Delete clip
    client.delete_record("Clips", records["clip"]["id"])
    deleted["clip"] = 1

    return deleted


@app.command("delete")
@command
def delete_clip(
    record_id: str = typer.Argument(..., help="Clip record ID"),
    cascade: bool = typer.Option(False, "--cascade", help="Delete all child records (demos, slides)"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompts"),
):
    """
    Delete a clip record.

    By default, only the clip record is deleted. Use --cascade to also delete
    all child records (demos, slides).

    Examples:
        # Delete clip only (prompts if children exist)
        coursecraft clips delete recXXXXXXXXXXXXXXX

        # Delete clip and all children
        coursecraft clips delete recXXXXXXXXXXXXXXX --cascade

        # Delete without confirmation (for scripting)
        coursecraft clips delete recXXXXXXXXXXXXXXX --force
        coursecraft clips delete recXXXXXXXXXXXXXXX --cascade --force
    """
    try:
        client = get_client()

        # Collect all records
        print_info("Collecting records...")
        records = _collect_clip_records(client, record_id)

        clip_name = records["clip"].get("fields", {}).get("Name", record_id)
        child_count = len(records["demos"]) + len(records["slides"])

        if cascade:
            # Cascading delete - show summary and confirm
            print_info(f"\nClip: {clip_name}")
            print_info(f"  Demos: {len(records['demos'])}")
            print_info(f"  Slides: {len(records['slides'])}")

            total = 1 + child_count
            print_info(f"\nTotal records to delete: {total}")

            if not force:
                print_info("")
                if not typer.confirm("Are you sure you want to delete all these records?"):
                    print_info("Deletion cancelled.")
                    raise typer.Exit(0)

            # Perform cascading delete
            print_info("\nDeleting records...")
            deleted = _delete_clip_cascade(client, records)

            # Report results
            total = sum(deleted.values())
            print_success(f"Deleted {total} records:")
            print_info(f"  - {deleted['slides']} slides")
            print_info(f"  - {deleted['demos']} demos")
            print_info(f"  - {deleted['clip']} clip")
        else:
            # Single record delete
            if child_count > 0 and not force:
                print_info(f"\nClip: {clip_name}")
                print_info(f"  Demos: {len(records['demos'])}")
                print_info(f"  Slides: {len(records['slides'])}")
                print_info(f"\nWarning: This will leave {child_count} orphaned child record(s).")
                print_info("Use --cascade to delete all children, or --force to allow orphans.")
                print_info("")
                if not typer.confirm("Continue and leave orphaned records?"):
                    print_info("Deletion cancelled.")
                    raise typer.Exit(0)

            # Delete only the clip
            client.delete_record("Clips", record_id)
            print_success(f"Deleted clip: {record_id}")

        # Output the deleted clip ID for scripting
        typer.echo(record_id)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


def _print_clip_tree(clip: Dict, demos: List[Dict], slides: List[Dict]):
    """
    Print clip hierarchy as colored ASCII tree with emojis.
    """
    clip_fields = clip.get("fields", {})
    clip_name = clip_fields.get("Name", clip["id"])
    clip_status = clip_fields.get("Status", "")

    # Clip header
    status_display = f"({clip_status})" if clip_status else "(No Status)"
    _console.print(f"[bold yellow]🎬 Clip:[/bold yellow] [yellow]{clip_name}[/yellow] [dim]{status_display}[/dim]")

    # Combine demos and slides, sort by Clip Order
    children = []
    for demo in demos:
        children.append(("Demo", demo))
    for slide in slides:
        children.append(("Slide", slide))

    children.sort(key=lambda x: x[1].get("fields", {}).get("Clip Order", 999))

    if not children:
        _console.print("[dim]└── (No content)[/dim]")
        return

    for child_idx, (child_type, child) in enumerate(children):
        is_last = child_idx == len(children) - 1
        child_fields = child.get("fields", {})
        # For slides, use Template Name as fallback if Name is empty
        child_name = child_fields.get("Name")
        if not child_name and child_type == "Slide":
            template_names = child_fields.get("Template Name", [])
            child_name = template_names[0] if template_names else child["id"]
        elif not child_name:
            child_name = child["id"]
        child_status = child_fields.get("Status", "")

        connector = "└── " if is_last else "├── "
        child_status_display = f"({child_status})" if child_status else "(No Status)"

        if child_type == "Slide":
            _console.print(f"{connector}[bold magenta]🖼️  Slide:[/bold magenta] [magenta]{child_name}[/magenta] [dim]{child_status_display}[/dim]")
        else:  # Demo
            _console.print(f"{connector}[bold green]💻 Demo:[/bold green] [green]{child_name}[/green] [dim]{child_status_display}[/dim]")


@app.command("show")
@command
def show_clip(
    clip_identifier: str = typer.Argument(..., help="Clip record ID, ID pattern (M1C1, M1C2), or name"),
    course: Optional[str] = typer.Option(None, "--course", "-c", help="Course to scope the search (record ID or slug)"),
):
    """
    Display clip hierarchy as an ASCII tree diagram.

    Shows the clip with all its demos and slides along with their statuses.

    Examples:
        # By ID pattern (searches active course)
        coursecraft clips show M1C3

        # By record ID
        coursecraft clips show recXXXXXXXXXXXXXXX

        # Scoped to specific course
        coursecraft clips show M2C1 --course advanced-features-cursor-ai
    """
    try:
        client = get_client()

        # If no course specified, try to use active course
        if not course:
            active_courses = client.list_records("Courses", "{Active}=TRUE()")
            if active_courses:
                course = active_courses[0]["id"]

        # Resolve clip identifier and collect records
        clip_record_id = client.resolve_clip_id(clip_identifier, course)
        records = _collect_clip_records(client, clip_record_id)

        # Print colored tree
        _console.print("")  # Empty line before tree
        _print_clip_tree(records["clip"], records["demos"], records["slides"])

        # Summary
        _console.print("")
        _console.print(f"[bold]Total:[/bold] {len(records['demos'])} demos, {len(records['slides'])} slides")

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


COMMAND_CREDENTIALS = {
    "create": [
        "custom"
    ],
    "delete": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "show": [
        "custom"
    ],
    "update": [
        "custom"
    ]
}
