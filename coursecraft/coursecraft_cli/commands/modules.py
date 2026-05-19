"""Modules command module."""
import json
import typer
from typing import Optional, List, Dict
from pathlib import Path
from rich.console import Console

from ..client import get_client, ClientError, CourseCraftClient
from ..output import print_success, print_error, print_info, print_json, print_table
from ..filter_map import translate_filters
from ..filters import apply_properties_filter, apply_limit

# Rich console for colored output
_console = Console()

app = typer.Typer(help="Manage module records")


def create_modules_from_json(client: CourseCraftClient, course_record_id: str, modules_list: List[Dict]):
    """
    Create modules from JSON data (called by courses.py for nested creation).

    Args:
        client: CourseCraft client instance
        course_record_id: Parent course record ID
        modules_list: List of module definitions
    """
    print_info(f"Creating {len(modules_list)} module(s)...")

    for module_data in modules_list:
        module_name = module_data.get("name")
        if not module_name:
            print_error("Module missing 'name' field")
            raise typer.Exit(1)

        # Check if module name already exists in this course
        existing_id = client.check_module_exists(module_name, course_record_id)
        if existing_id:
            print_error(f"Module with name '{module_name}' already exists in this course: {existing_id}")
            raise typer.Exit(1)

        # Build module fields
        fields = {
            "Name": module_name,
            "Course": [course_record_id],
        }

        # Add optional fields
        if "order" in module_data:
            fields["Order"] = module_data["order"]
        if "description" in module_data:
            fields["Description"] = module_data["description"]
        if "target_length" in module_data:
            fields["Target Length (Min)"] = module_data["target_length"]
        if "learning_objectives" in module_data:
            fields["Learning Objectives"] = module_data["learning_objectives"]
        if "status" in module_data:
            fields["Status"] = module_data["status"]

        # Create the module
        module_record_id = client.create_record("Modules", fields)
        print_success(f"Created module '{module_name}': {module_record_id}")

        # Handle nested clips if present
        if "clips" in module_data and module_data["clips"]:
            from .clips import create_clips_from_json
            create_clips_from_json(client, module_record_id, module_data["clips"])


@app.command("create")
def create_module(
    name: str = typer.Option(..., "--name", "-n", help="Module name"),
    course: str = typer.Option(..., "--course", "-c", help="Course record ID or Course ID (slug)"),
    order: Optional[int] = typer.Option(None, "--order", "-o", help="Module sequence order"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Module description"),
    learning_objectives: Optional[str] = typer.Option(None, "--learning-objectives", "-l", help="Module learning objectives"),
    target_length: Optional[int] = typer.Option(None, "--target-length", "-t", help="Target length in minutes"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Module status"),
    clips_json: Optional[str] = typer.Option(None, "--json", help="Inline JSON array of clips to create"),
    clips_file: Optional[Path] = typer.Option(None, "--file", help="Path to JSON file with clip definitions"),
):
    """
    Create a module record, optionally with clips.

    Examples:
        # Create module only
        coursecraft modules create --name "Getting Started" --course recXXX --order 1

        # Create module with clips
        coursecraft modules create --name "Getting Started" --course my-course --json '[{"name":"Intro"}]'
    """
    try:
        client = get_client()

        # Resolve course identifier to record ID
        print_info(f"Resolving course identifier '{course}'...")
        course_record_id = client.resolve_course_id(course)
        print_success(f"Resolved to: {course_record_id}")

        # Check if module name already exists in this course
        existing_id = client.check_module_exists(name, course_record_id)
        if existing_id:
            print_error(f"Module with name '{name}' already exists in this course: {existing_id}")
            raise typer.Exit(1)

        # Build fields dictionary
        fields = {
            "Name": name,
            "Course": [course_record_id],
        }

        # Add optional fields
        if order is not None:
            fields["Order"] = order
        if description:
            fields["Description"] = description
        if learning_objectives:
            fields["Learning Objectives"] = learning_objectives
        if target_length is not None:
            fields["Target Length (Min)"] = target_length
        if status:
            fields["Status"] = status

        # Create the module
        record_id = client.create_record("Modules", fields)
        print_success(f"Created module '{name}': {record_id}")

        # Handle nested clips if provided
        if clips_file or clips_json:
            from .clips import create_clips_from_json

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
                    create_clips_from_json(client, record_id, clips_list)
                except json.JSONDecodeError as e:
                    print_error(f"Invalid JSON: {e}")
                    raise typer.Exit(1)

        # Output the record ID for scripting
        typer.echo(record_id)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("list")
def list_modules(
    course: Optional[str] = typer.Option(None, "--course", "-c", help="Filter by course record ID or Course ID slug"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum number of records to return"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of properties to include (supports dot notation)"),
    table_output: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    List module records.

    Examples:
        # List all modules
        coursecraft modules list

        # List modules for a course
        coursecraft modules list --course my-course

        # List with standard filter
        coursecraft modules list --filter "order:gte:3"

        # List with table output
        coursecraft modules list --course recXXX --table

        # Limit results
        coursecraft modules list --limit 5

        # Select specific properties
        coursecraft modules list --properties "id,fields.Name,fields.Order"
    """
    try:
        client = get_client()

        # Check for conflicts
        if filter and course:
            print_error("Cannot use --filter with --course convenience option")
            raise typer.Exit(1)

        # Build filter formula
        formula = None
        if filter:
            formula = translate_filters(list(filter), 'Modules')
        elif course:
            course_record_id = client.resolve_course_id(course)
            formula = f"{{Course Record ID}}='{course_record_id}'"

        records = client.list_records("Modules", formula)

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
def get_module(
    record_id: str = typer.Argument(..., help="Module record ID"),
    table_output: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Get a single module record by ID.

    Examples:
        coursecraft modules get recXXXXXXXXXXXXXXX
        coursecraft modules get recXXXXXXXXXXXXXXX --table
    """
    try:
        client = get_client()
        record = client.get_record("Modules", record_id)

        if not record:
            print_error(f"Module not found: {record_id}")
            raise typer.Exit(1)

        if table_output:
            fields = record.get("fields", {})
            rows = [{
                "id": record["id"],
                "name": fields.get("Name", ""),
                "order": fields.get("Order", ""),
                "description": fields.get("Description", "")[:50] + "..." if fields.get("Description", "") and len(fields.get("Description", "")) > 50 else fields.get("Description", ""),
                "status": fields.get("Status", ""),
                "target_length": fields.get("Target Length (Min)", ""),
            }]
            print_table(rows, ["id", "name", "order", "description", "status", "target_length"],
                       ["Record ID", "Name", "Order", "Description", "Status", "Target Length"])
        else:
            print_json(record)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("update")
def update_module(
    record_id: str = typer.Argument(..., help="Module record ID"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Module name"),
    order: Optional[int] = typer.Option(None, "--order", "-o", help="Module sequence order"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Module description"),
    learning_objectives: Optional[str] = typer.Option(None, "--learning-objectives", "-l", help="Module learning objectives"),
    target_length: Optional[int] = typer.Option(None, "--target-length", help="Target length in minutes"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Module status"),
    brainstorming_outline: Optional[str] = typer.Option(None, "--brainstorming-outline", "-b", help="Module brainstorming outline content"),
    brainstorming_outline_file: Optional[Path] = typer.Option(None, "--brainstorming-outline-file", help="Path to file containing brainstorming outline"),
    brainstorming_outline_fact_checked: Optional[bool] = typer.Option(None, "--brainstorming-outline-fact-checked", help="Mark brainstorming outline as fact-checked"),
    slides_submitted: Optional[bool] = typer.Option(None, "--slides-submitted", help="Mark slide deck as submitted for review (Pluralsight only)"),
):
    """
    Update a module record.

    Examples:
        coursecraft modules update recXXX --name "New Name"
        coursecraft modules update recXXX --order 2 --status "Complete"
        coursecraft modules update recXXX --brainstorming-outline-file outline.md
    """
    try:
        client = get_client()

        # Verify record exists
        existing = client.get_record("Modules", record_id)
        if not existing:
            print_error(f"Module not found: {record_id}")
            raise typer.Exit(1)

        # Build fields dictionary with only provided values
        fields = {}
        if name is not None:
            fields["Name"] = name
        if order is not None:
            fields["Order"] = order
        if description is not None:
            fields["Description"] = description
        if learning_objectives is not None:
            fields["Learning Objectives"] = learning_objectives
        if target_length is not None:
            fields["Target Length (Min)"] = target_length
        if status is not None:
            fields["Status"] = status
        # Check for fact-check reset warning
        existing_fields = existing.get("fields", {})
        existing_fact_checked = existing_fields.get("Brainstorming Outline Fact Checked", False)
        updating_brainstorming = brainstorming_outline is not None or brainstorming_outline_file is not None

        # Handle brainstorming outline (file takes precedence over inline)
        if brainstorming_outline_file:
            if not brainstorming_outline_file.exists():
                print_error(f"File not found: {brainstorming_outline_file}")
                raise typer.Exit(1)
            fields["Brainstorming Outline"] = brainstorming_outline_file.read_text()
        elif brainstorming_outline is not None:
            fields["Brainstorming Outline"] = brainstorming_outline

        # If updating brainstorming outline and it was previously fact-checked, warn and reset
        if updating_brainstorming and existing_fact_checked:
            print_info("")
            print_info("⚠️  WARNING: The previous Brainstorming Outline was marked as Fact-Checked.")
            print_info("   This update resets the fact-check status. Re-verification may be needed.")
            # Automatically reset the fact-check flag
            fields["Brainstorming Outline Fact Checked"] = False

        # Handle explicit fact-checked checkbox (overrides auto-reset if explicitly set)
        if brainstorming_outline_fact_checked is not None:
            fields["Brainstorming Outline Fact Checked"] = brainstorming_outline_fact_checked

        # Handle slides submitted checkbox (Pluralsight-only; no-op warning for Udemy)
        if slides_submitted is not None:
            fields["Slides Submitted for Pluralsight Review"] = slides_submitted

        if not fields:
            print_error("No fields to update. Provide at least one field option.")
            raise typer.Exit(1)

        # Update the record
        updated = client.update_record("Modules", record_id, fields)
        print_success(f"Updated module: {record_id}")

        # Output the record ID for scripting
        typer.echo(record_id)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


def _collect_module_records(client, module_record_id: str) -> Dict[str, List[Dict]]:
    """
    Collect all records that belong to a module (clips, demos, slides).

    Returns dict with keys: module, clips, demos, slides
    """
    result = {
        "module": None,
        "clips": [],
        "demos": [],
        "slides": []
    }

    # Get the module record
    module = client.get_record("Modules", module_record_id)
    if not module:
        raise ClientError(f"Module not found: {module_record_id}")
    result["module"] = module

    # Get all clips
    clips = client.get_clips_by_module(module_record_id)
    result["clips"] = clips

    # Get all demos and slides for each clip
    for clip in clips:
        demos = client.get_demos_by_clip(clip["id"])
        slides = client.get_slides_by_clip(clip["id"])
        result["demos"].extend(demos)
        result["slides"].extend(slides)

    return result


def _delete_module_cascade(client, records: Dict[str, List[Dict]]) -> Dict[str, int]:
    """
    Delete all records in cascade order (children first).

    Returns dict with counts of deleted records by type.
    """
    deleted = {"slides": 0, "demos": 0, "clips": 0, "module": 0}

    # Delete slides first
    for slide in records["slides"]:
        client.delete_record("Slides", slide["id"])
        deleted["slides"] += 1

    # Delete demos
    for demo in records["demos"]:
        client.delete_record("Demos", demo["id"])
        deleted["demos"] += 1

    # Delete clips
    for clip in records["clips"]:
        client.delete_record("Clips", clip["id"])
        deleted["clips"] += 1

    # Delete module
    client.delete_record("Modules", records["module"]["id"])
    deleted["module"] = 1

    return deleted


@app.command("delete")
def delete_module(
    record_id: str = typer.Argument(..., help="Module record ID"),
    cascade: bool = typer.Option(False, "--cascade", help="Delete all child records (clips, demos, slides)"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompts"),
):
    """
    Delete a module record.

    By default, only the module record is deleted. Use --cascade to also delete
    all child records (clips, demos, slides).

    Examples:
        # Delete module only (prompts if children exist)
        coursecraft modules delete recXXXXXXXXXXXXXXX

        # Delete module and all children
        coursecraft modules delete recXXXXXXXXXXXXXXX --cascade

        # Delete without confirmation (for scripting)
        coursecraft modules delete recXXXXXXXXXXXXXXX --force
        coursecraft modules delete recXXXXXXXXXXXXXXX --cascade --force
    """
    try:
        client = get_client()

        # Collect all records
        print_info("Collecting records...")
        records = _collect_module_records(client, record_id)

        module_name = records["module"].get("fields", {}).get("Name", record_id)
        child_count = len(records["clips"]) + len(records["demos"]) + len(records["slides"])

        if cascade:
            # Cascading delete - show summary and confirm
            print_info(f"\nModule: {module_name}")
            print_info(f"  Clips: {len(records['clips'])}")
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
            deleted = _delete_module_cascade(client, records)

            # Report results
            total = sum(deleted.values())
            print_success(f"Deleted {total} records:")
            print_info(f"  - {deleted['slides']} slides")
            print_info(f"  - {deleted['demos']} demos")
            print_info(f"  - {deleted['clips']} clips")
            print_info(f"  - {deleted['module']} module")
        else:
            # Single record delete
            if child_count > 0 and not force:
                print_info(f"\nModule: {module_name}")
                print_info(f"  Clips: {len(records['clips'])}")
                print_info(f"  Demos: {len(records['demos'])}")
                print_info(f"  Slides: {len(records['slides'])}")
                print_info(f"\nWarning: This will leave {child_count} orphaned child record(s).")
                print_info("Use --cascade to delete all children, or --force to allow orphans.")
                print_info("")
                if not typer.confirm("Continue and leave orphaned records?"):
                    print_info("Deletion cancelled.")
                    raise typer.Exit(0)

            # Delete only the module
            client.delete_record("Modules", record_id)
            print_success(f"Deleted module: {record_id}")

        # Output the deleted module ID for scripting
        typer.echo(record_id)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


def _print_module_tree(module: Dict, clips: List[Dict], demos_by_clip: Dict[str, List[Dict]], slides_by_clip: Dict[str, List[Dict]]):
    """
    Print module hierarchy as colored ASCII tree with emojis.
    """
    module_fields = module.get("fields", {})
    module_name = module_fields.get("Name", module["id"])
    module_status = module_fields.get("Status", "")

    # Module header
    status_display = f"({module_status})" if module_status else "(No Status)"
    _console.print(f"[bold cyan]📦 Module:[/bold cyan] [cyan]{module_name}[/cyan] [dim]{status_display}[/dim]")

    if not clips:
        _console.print("[dim]└── (No clips)[/dim]")
        return

    # Sort clips by Order
    sorted_clips = sorted(clips, key=lambda c: c.get("fields", {}).get("Order", 999))

    for clip_idx, clip in enumerate(sorted_clips):
        is_last_clip = clip_idx == len(sorted_clips) - 1
        clip_fields = clip.get("fields", {})
        clip_name = clip_fields.get("Name", clip["id"])
        clip_status = clip_fields.get("Status Formula", "") or clip_fields.get("Status", "")

        # Clip line
        clip_connector = "└── " if is_last_clip else "├── "
        clip_status_display = f"({clip_status})" if clip_status else "(No Status)"
        _console.print(f"{clip_connector}[bold yellow]🎬 Clip:[/bold yellow] [yellow]{clip_name}[/yellow] [dim]{clip_status_display}[/dim]")

        # Get demos and slides for this clip
        clip_demos = demos_by_clip.get(clip["id"], [])
        clip_slides = slides_by_clip.get(clip["id"], [])

        # Combine and sort by Clip Order
        children = []
        for demo in clip_demos:
            children.append(("Demo", demo))
        for slide in clip_slides:
            children.append(("Slide", slide))

        children.sort(key=lambda x: x[1].get("fields", {}).get("Clip Order", 999))

        # Determine prefix for children
        child_prefix = "    " if is_last_clip else "│   "

        if not children:
            _console.print(f"{child_prefix}[dim]└── (No content)[/dim]")
        else:
            for child_idx, (child_type, child) in enumerate(children):
                is_last_child = child_idx == len(children) - 1
                child_fields = child.get("fields", {})
                # For slides, use Template Name as fallback if Name is empty
                child_name = child_fields.get("Name")
                if not child_name and child_type == "Slide":
                    template_names = child_fields.get("Template Name", [])
                    child_name = template_names[0] if template_names else child["id"]
                elif not child_name:
                    child_name = child["id"]
                child_status = child_fields.get("Status", "")

                child_connector = "└── " if is_last_child else "├── "
                child_status_display = f"({child_status})" if child_status else "(No Status)"

                if child_type == "Slide":
                    _console.print(f"{child_prefix}{child_connector}[bold magenta]🖼️  Slide:[/bold magenta] [magenta]{child_name}[/magenta] [dim]{child_status_display}[/dim]")
                else:  # Demo
                    _console.print(f"{child_prefix}{child_connector}[bold green]💻 Demo:[/bold green] [green]{child_name}[/green] [dim]{child_status_display}[/dim]")


@app.command("show")
def show_module(
    module_identifier: str = typer.Argument(..., help="Module record ID, ID pattern (M1, M2), or name"),
    course: Optional[str] = typer.Option(None, "--course", "-c", help="Course to scope the search (record ID or slug)"),
):
    """
    Display module hierarchy as an ASCII tree diagram.

    Shows the module with all its clips, demos, and slides along with their statuses.

    Examples:
        # By ID pattern (searches active course)
        coursecraft modules show M1

        # By record ID
        coursecraft modules show recXXXXXXXXXXXXXXX

        # Scoped to specific course
        coursecraft modules show M2 --course advanced-features-cursor-ai
    """
    try:
        client = get_client()

        # If no course specified, try to use active course
        if not course:
            active_courses = client.list_records("Courses", "{Active}=TRUE()")
            if active_courses:
                course = active_courses[0]["id"]

        # Resolve module identifier and collect records
        module_record_id = client.resolve_module_id(module_identifier, course)
        records = _collect_module_records(client, module_record_id)

        # Organize demos and slides by clip
        demos_by_clip: Dict[str, List[Dict]] = {}
        slides_by_clip: Dict[str, List[Dict]] = {}

        for clip in records["clips"]:
            clip_id = clip["id"]
            demos_by_clip[clip_id] = [d for d in records["demos"] if clip_id in (d.get("fields", {}).get("Clip") or [])]
            slides_by_clip[clip_id] = [s for s in records["slides"] if clip_id in (s.get("fields", {}).get("Clip") or [])]

        # Print colored tree
        _console.print("")  # Empty line before tree
        _print_module_tree(records["module"], records["clips"], demos_by_clip, slides_by_clip)

        # Summary
        _console.print("")
        _console.print(f"[bold]Total:[/bold] {len(records['clips'])} clips, {len(records['demos'])} demos, {len(records['slides'])} slides")

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
