"""Clips command module."""
import json
import typer
from typing import Optional, List, Dict
from pathlib import Path
from rich.console import Console

from cli_tools_shared.filters import apply_properties_filter, apply_limit
from ..client import get_client, ClientError, CourseCraftClient
from ..output import print_success, print_error, print_info, print_json, print_table, print_mandatory_review
from ..filter_map import translate_filters

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
        if "story" in clip_data:
            fields["Story"] = clip_data["story"]
        if "target_length" in clip_data:
            fields["Target Length (Min)"] = clip_data["target_length"]
        if "status" in clip_data:
            fields["Status"] = clip_data["status"]

        # Create the clip
        clip_record_id = client.create_record("Clips", fields)
        print_success(f"Created clip '{clip_name}': {clip_record_id}")
        created_ids.append(clip_record_id)

    return created_ids


@app.command("create")
def create_clip(
    module: str = typer.Option(..., "--module", "-m", help="Module record ID (required)"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Clip name (required in single mode)"),
    order: Optional[int] = typer.Option(None, "--order", "-o", help="Clip sequence order"),
    story: Optional[str] = typer.Option(None, "--story", "-s", help="Clip story/narrative"),
    target_length: Optional[int] = typer.Option(None, "--target-length", "-t", help="Target length in minutes"),
    status: Optional[str] = typer.Option(None, "--status", help="Clip status"),
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
            json_data = None
            if clips_file:
                if not clips_file.exists():
                    print_error(f"File not found: {clips_file}")
                    raise typer.Exit(1)
                json_data = clips_file.read_text()
            elif clips_json:
                json_data = clips_json

            if json_data:
                try:
                    clips_list = json.loads(json_data)
                    created_ids = create_clips_from_json(client, module, clips_list)
                    # Output all created IDs as JSON array for scripting
                    typer.echo(json.dumps(created_ids))
                except json.JSONDecodeError as e:
                    print_error(f"Invalid JSON: {e}")
                    raise typer.Exit(1)
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
            if story:
                fields["Story"] = story
            if target_length is not None:
                fields["Target Length (Min)"] = target_length
            if status:
                fields["Status"] = status

            # Create the clip
            record_id = client.create_record("Clips", fields)
            print_success(f"Created clip '{name}': {record_id}")

            # Output the record ID for scripting
            typer.echo(record_id)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("list")
def list_clips(
    module: Optional[str] = typer.Option(None, "--module", "-m", help="Filter by module record ID"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum number of records to return"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of properties to include (supports dot notation)"),
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

        # List with table output
        coursecraft clips list --module recXXX --table

        # Limit results
        coursecraft clips list --limit 10

        # Select specific properties
        coursecraft clips list --properties "id,fields.Name,fields.Status"
    """
    try:
        client = get_client()

        # Check for conflicts
        if filter and module:
            print_error("Cannot use --filter with --module convenience option")
            raise typer.Exit(1)

        # Build filter formula
        formula = None
        if filter:
            formula = translate_filters(list(filter), 'Clips')
        elif module:
            formula = f"{{Module Record ID}}='{module}'"

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
def get_clip(
    record_id: str = typer.Argument(..., help="Clip record ID"),
    table_output: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Get a single clip record by ID.

    Examples:
        coursecraft clips get recXXXXXXXXXXXXXXX
        coursecraft clips get recXXXXXXXXXXXXXXX --table
    """
    try:
        client = get_client()
        record = client.get_record("Clips", record_id)

        if not record:
            print_error(f"Clip not found: {record_id}")
            raise typer.Exit(1)

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
def update_clip(
    record_id: str = typer.Argument(..., help="Clip record ID"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Clip name"),
    module: Optional[str] = typer.Option(None, "--module", "-m", help="Parent module record ID"),
    order: Optional[int] = typer.Option(None, "--order", "-o", help="Clip sequence order"),
    story: Optional[str] = typer.Option(None, "--story", "-s", help="Clip story/narrative"),
    learning_objectives: Optional[str] = typer.Option(None, "--learning-objectives", "-l", help="Clip learning objectives"),
    target_length: Optional[int] = typer.Option(None, "--target-length", help="Target length in minutes"),
    status: Optional[str] = typer.Option(None, "--status", help="Clip status"),
    brainstorming_outline: Optional[str] = typer.Option(None, "--brainstorming-outline", "-b", help="Brainstorming outline content"),
    brainstorming_outline_fact_checked: Optional[bool] = typer.Option(None, "--brainstorming-outline-fact-checked", help="Mark brainstorming outline as fact-checked"),
    content_done: Optional[bool] = typer.Option(None, "--content-done", help="Mark clip content structure as complete"),
):
    """
    Update a clip record.

    Examples:
        coursecraft clips update recXXX --name "New Name"
        coursecraft clips update recXXX --order 2 --status "Complete"
        coursecraft clips update recXXX --learning-objectives "- Objective 1\\n- Objective 2"
        coursecraft clips update recXXX --brainstorming-outline "---"
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
        if story is not None:
            fields["Story"] = story
        if learning_objectives is not None:
            fields["Learning Objectives"] = learning_objectives
        if target_length is not None:
            fields["Target Length (Min)"] = target_length
        if status is not None:
            fields["Status"] = status
        if brainstorming_outline is not None:
            fields["Brainstorming Outline"] = brainstorming_outline
        if content_done is not None:
            fields["Clip Structure Confirmed"] = content_done

        if not fields:
            print_error("No fields to update. Provide at least one field option.")
            raise typer.Exit(1)

        # Check for fact-check reset warning BEFORE updating
        existing_fields = existing.get("fields", {})
        existing_fact_checked = existing_fields.get("Brainstorming Outline Fact Checked", False)

        # If updating brainstorming outline and it was previously fact-checked, warn and reset
        if brainstorming_outline is not None and existing_fact_checked:
            print_info("")
            print_info("⚠️  WARNING: The previous Brainstorming Outline was marked as Fact-Checked.")
            print_info("   This update resets the fact-check status. Re-verification may be needed.")
            # Automatically reset the fact-check flag
            fields["Brainstorming Outline Fact Checked"] = False

        # Explicit fact-check flag overrides the automatic reset.
        if brainstorming_outline_fact_checked is not None:
            fields["Brainstorming Outline Fact Checked"] = brainstorming_outline_fact_checked

        # Update the record
        updated = client.update_record("Clips", record_id, fields)
        print_success(f"Updated clip: {record_id}")

        # Check for sync warnings
        existing_story = existing_fields.get("Story", "")
        existing_brainstorming = existing_fields.get("Brainstorming Outline", "")

        if brainstorming_outline is not None and existing_story:
            print_mandatory_review(
                title="Story",
                action="Update the Story to reflect the new Brainstorming Outline",
                reason="Brainstorming Outline changed - Story must incorporate the updated content",
                preview=existing_story,
            )

        if story is not None and existing_brainstorming:
            print_info("")
            print_info("ℹ️  TIP: The Story should be informed by the Brainstorming Outline.")
            print_info(f"   Brainstorming preview: {existing_brainstorming[:100]}..." if len(existing_brainstorming) > 100 else f"   Brainstorming preview: {existing_brainstorming}")

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
    clip_status = clip_fields.get("Status Formula", "") or clip_fields.get("Status", "")

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
