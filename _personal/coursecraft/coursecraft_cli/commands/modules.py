"""Modules command module."""
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
from ..field_mappings import collect_mapped_updates
from ..external_review import (
    ExternalReviewError,
    execute_transition,
    verified_video_feedback_receipts,
)
from ..artifact_versions import VersioningError
from ..objective_override import ObjectiveOverrideError
from .versions import accept_approved_module_deck

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
        if "status" in module_data:
            print_error("Module Status is computed by Airtable; remove 'status' from module JSON")
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

        # Create the module
        module_record_id = client.create_record("Modules", fields)
        print_success(f"Created module '{module_name}': {module_record_id}")

        # Handle nested clips if present
        if "clips" in module_data and module_data["clips"]:
            from .clips import create_clips_from_json
            create_clips_from_json(client, module_record_id, module_data["clips"])


@app.command("create")
@command
def create_module(
    name: str = typer.Option(..., "--name", "-n", help="Module name"),
    course: str = typer.Option(..., "--course", "-c", help="Course record ID or Course ID (slug)"),
    order: Optional[int] = typer.Option(None, "--order", "-o", help="Module sequence order"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Module description"),
    learning_objectives: Optional[str] = typer.Option(None, "--learning-objectives", "-l", help="Module learning objectives"),
    target_length: Optional[int] = typer.Option(None, "--target-length", "-t", help="Target length in minutes"),
    demo_density: Optional[float] = typer.Option(None, "--demo-density", help="Percentage (0-100) of this module's teaching minutes (Content Slide + demo target minutes) that should be demo; the single dial for how demo-heavy a module is -- high for a technical module that must get into the weeds, low for a conceptual one. Unset or 0 means the demo-first density gate is not enforced for this module"),
    notes: Optional[str] = typer.Option(None, "--notes", help="Internal notes"),
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
        if demo_density is not None:
            fields["Demo Density"] = demo_density
        if notes is not None:
            fields["Notes"] = notes

        # Create the module
        record_id = client.create_record("Modules", fields)
        print_success(f"Created module '{name}': {record_id}")

        # Handle nested clips if provided
        if clips_file or clips_json:
            from .clips import create_clips_from_json

            clips_list = load_batch_payload(clips_json, clips_file)
            create_clips_from_json(client, record_id, clips_list)

        # Output the record ID for scripting
        typer.echo(record_id)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("list")
@command
def list_modules(
    course: Optional[str] = typer.Option(None, "--course", "-c", help="Filter by course record ID or Course ID slug"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum number of records to return"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Property to include (supports dot notation). Repeatable; each value may also be comma-separated."),
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

        # List course modules with an additional filter
        coursecraft modules list --course my-course --filter "order:eq:4"

        # List with table output
        coursecraft modules list --course recXXX --table

        # Limit results
        coursecraft modules list --limit 5

        # Select specific properties
        coursecraft modules list --properties "id,fields.Name,fields.Order"
    """
    try:
        client = get_client()

        # Build filter formula
        formula = None
        if course:
            course_record_id = client.resolve_course_id(course)
            formula = f"{{Course Record ID}}='{course_record_id}'"
            if filter:
                filter_formula = translate_filters(list(filter), 'Modules')
                formula = f"AND({formula},{filter_formula})"
        elif filter:
            formula = translate_filters(list(filter), 'Modules')

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
@command
def get_module(
    record_id: str = typer.Argument(..., help="Module record ID"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Property to include (supports dot notation). Repeatable; each value may also be comma-separated."),
    table_output: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Get a single module record by ID.

    Examples:
        coursecraft modules get recXXXXXXXXXXXXXXX
        coursecraft modules get recXXXXXXXXXXXXXXX --properties "id,fields.Name"
        coursecraft modules get recXXXXXXXXXXXXXXX --table
    """
    try:
        client = get_client()
        record = client.get_record("Modules", record_id)

        if not record:
            print_error(f"Module not found: {record_id}")
            raise typer.Exit(1)

        if properties and not table_output:
            record = project_record(record, properties)

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
@command
def update_module(
    record_id: str = typer.Argument(..., help="Module record ID"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Module name"),
    order: Optional[int] = typer.Option(None, "--order", "-o", help="Module sequence order"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Module description"),
    learning_objectives: Optional[str] = typer.Option(None, "--learning-objectives", "-l", help="Module learning objectives"),
    target_length: Optional[int] = typer.Option(None, "--target-length", help="Target length in minutes"),
    demo_density: Optional[float] = typer.Option(None, "--demo-density", help="Percentage (0-100) of this module's teaching minutes (Content Slide + demo target minutes) that should be demo; the single dial for how demo-heavy a module is -- high for a technical module that must get into the weeds, low for a conceptual one. Unset or 0 means the demo-first density gate is not enforced for this module"),
    notes: Optional[str] = typer.Option(None, "--notes", help="Internal notes"),
    brainstorming_outline: Optional[str] = typer.Option(None, "--brainstorming-outline", "-b", help="Module brainstorming outline content"),
    brainstorming_outline_file: Optional[Path] = typer.Option(None, "--brainstorming-outline-file", help="Path to file containing brainstorming outline"),
    module_plan_complete: Optional[bool] = typer.Option(None, "--module-plan-complete/--no-module-plan-complete", help="Set or clear the module plan complete flag"),
    module_review_complete: Optional[bool] = typer.Option(None, "--module-review-complete/--no-module-review-complete", help="Set or clear the module review complete flag"),
    plan_review_ai: Optional[str] = typer.Option(None, "--plan-review-ai", help="AI review of the module plan"),
    powerpoint_deck_review_ai: Optional[str] = typer.Option(None, "--powerpoint-deck-review-ai", help="AI review of the PowerPoint deck"),
    slide_build_review_ai: Optional[str] = typer.Option(None, "--slide-build-review-ai", help="AI review of the slide build"),
    powerpoint_deck_human_verified: Optional[bool] = typer.Option(None, "--powerpoint-deck-human-verified/--no-powerpoint-deck-human-verified", help="Set or clear the PowerPoint deck human-verified gate flag"),
    slide_build_review_human_verified: Optional[bool] = typer.Option(None, "--slide-build-review-human-verified/--no-slide-build-review-human-verified", help="Set or clear the slide build review human-verified gate flag"),
    slide_narration_approved: Optional[bool] = typer.Option(None, "--slide-narration-approved/--no-slide-narration-approved", help="Set or clear the slide-narration-approved flag, the gate that releases the slide-narration phase (Review Slide Narration) to recording"),
    slide_narration_recorded: Optional[bool] = typer.Option(None, "--slide-narration-recorded/--no-slide-narration-recorded", help="Set or clear the slide-narration-recorded flag, marking the module's slide narration take as recorded"),
    slide_narration_complete: Optional[bool] = typer.Option(None, "--slide-narration-complete/--no-slide-narration-complete", help="Set or clear the module slide-narration-complete flag and sync every child clip and slide"),
    feedback_requested: Optional[bool] = typer.Option(None, "--feedback-requested/--no-feedback-requested", help="Set or clear the feedback-requested gate flag"),
    feedback_requested_at: Optional[str] = typer.Option(None, "--feedback-requested-at", help="ISO 8601 timestamp the feedback gate was requested"),
    description_human_verified: Optional[bool] = typer.Option(None, "--description-human-verified/--no-description-human-verified", help="Set or clear the module Description human-verification gate"),
    learning_objectives_human_verified: Optional[bool] = typer.Option(None, "--learning-objectives-human-verified/--no-learning-objectives-human-verified", help="Set or clear the module Learning Objectives human-verification gate"),
    brainstorming_outline_human_verified: Optional[bool] = typer.Option(None, "--brainstorming-outline-human-verified/--no-brainstorming-outline-human-verified", help="Set or clear the module Brainstorming Outline human-verification gate"),
    base_record: Optional[str] = typer.Option(None, "--base-record", help="Course-update lineage: the module in the base course version this record derives from"),
):
    """
    Update a module record.

    Examples:
        coursecraft modules update recXXX --name "New Name"
        coursecraft modules update recXXX --order 2
        coursecraft modules update recXXX --brainstorming-outline-file outline.md

    Changing --learning-objectives/--description to a value that differs from
    what is already saved bumps the module.plan Version Control entry and
    auto-clears Plan Review (AI) (a no-op resubmission of identical content
    leaves it untouched, and passing --plan-review-ai in the same call as a
    real content change is rejected) -- see the coursecraft_cli.artifact_versions
    write-time versioning engine. The module PowerPoint deck is a file
    artifact registered by `coursecraft versions sync`, not by this command.
    """
    try:
        client = get_client()

        # Verify record exists
        existing = client.get_record("Modules", record_id)
        if not existing:
            print_error(f"Module not found: {record_id}")
            raise typer.Exit(1)

        # Build fields dictionary with only provided values
        fields = collect_mapped_updates(
            "Modules",
            {
                "name": name,
                "order": order,
                "description": description,
                "learning_objectives": learning_objectives,
                "target_length": target_length,
                "demo_density": demo_density,
                "notes": notes,
                "module_plan_complete": module_plan_complete,
                "module_review_complete": module_review_complete,
                "plan_review_ai": plan_review_ai,
                "powerpoint_deck_review_ai": powerpoint_deck_review_ai,
                "slide_build_review_ai": slide_build_review_ai,
                "powerpoint_deck_human_verified": powerpoint_deck_human_verified,
                "slide_build_review_human_verified": slide_build_review_human_verified,
                "slide_narration_approved": slide_narration_approved,
                "slide_narration_recorded": slide_narration_recorded,
                "slide_narration_complete": slide_narration_complete,
                "feedback_requested": feedback_requested,
                "feedback_requested_at": feedback_requested_at,
                "description_human_verified": description_human_verified,
                "learning_objectives_human_verified": learning_objectives_human_verified,
                "brainstorming_outline_human_verified": brainstorming_outline_human_verified,
            },
        )

        # Handle brainstorming outline (file takes precedence over inline)
        if brainstorming_outline_file:
            if not brainstorming_outline_file.exists():
                print_error(f"File not found: {brainstorming_outline_file}")
                raise typer.Exit(1)
            fields["Brainstorming Outline"] = brainstorming_outline_file.read_text()
        elif brainstorming_outline is not None:
            fields["Brainstorming Outline"] = brainstorming_outline

        if base_record is not None:
            fields["Base Record"] = [base_record]

        if not fields:
            print_error("No fields to update. Provide at least one field option.")
            raise typer.Exit(1)

        # Update the record
        client.update_record("Modules", record_id, fields)
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
@command
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
        clip_status = clip_fields.get("Status", "")

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
@command
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


def _run_module_transition(module: str, instance: str, action: str) -> None:
    client = get_client()
    record_id = client.resolve_module_id(module)
    result = execute_transition(client, instance, action, "operator", record_id)
    print_success(f"Applied {instance} action {action!r} to {record_id}")
    print_json(result)


@app.command("submit-slide-deck-for-review")
@command
def modules_submit_slide_deck_for_review(
    module: str = typer.Argument(..., help="Module record ID, ID pattern, or name"),
):
    """Submit or resubmit the current ready Slide Deck revision."""
    try:
        _run_module_transition(module, "slide_deck", "submit")
    except (ClientError, ExternalReviewError, ObjectiveOverrideError) as exc:
        print_error(str(exc))
        raise typer.Exit(1)


@app.command("mark-slide-deck-changes-requested")
@command
def modules_mark_slide_deck_changes_requested(
    module: str = typer.Argument(..., help="Module record ID, ID pattern, or name"),
):
    """Record external Slide Deck changes requested."""
    try:
        _run_module_transition(module, "slide_deck", "request_changes")
    except (ClientError, ExternalReviewError, ObjectiveOverrideError) as exc:
        print_error(str(exc))
        raise typer.Exit(1)


@app.command("mark-slide-deck-approved")
@command
def modules_mark_slide_deck_approved(
    module: str = typer.Argument(..., help="Module record ID, ID pattern, or name"),
):
    """Record external approval of the exact submitted Slide Deck revision."""
    try:
        _run_module_transition(module, "slide_deck", "approve")
    except (ClientError, ExternalReviewError, ObjectiveOverrideError) as exc:
        print_error(str(exc))
        raise typer.Exit(1)


@app.command("accept-approved-slide-deck", hidden=True)
@command
def modules_accept_approved_slide_deck(
    module: str = typer.Argument(..., help="Module record ID, ID pattern, or name"),
    approval_evidence: str = typer.Option(
        ...,
        "--approval-evidence",
        help="Explicit approval-evidence reference selected by the approved-deck release workflow",
    ),
):
    """Accept the canonical returned approved deck in one guarded owner write."""
    try:
        client = get_client()
        record_id = client.resolve_module_id(module)
        result = accept_approved_module_deck(
            client,
            record_id,
            approval_evidence,
        )
        print_success(f"Accepted returned approved Slide Deck for {record_id}")
        print_json(result)
    except (
        ClientError,
        ExternalReviewError,
        ObjectiveOverrideError,
        VersioningError,
    ) as exc:
        print_error(str(exc))
        raise typer.Exit(1)


@app.command("submit-videos-for-review")
@command
def modules_submit_videos_for_review(
    module: str = typer.Argument(..., help="Module record ID, ID pattern, or name"),
):
    """Submit or resubmit the current ready Module Video manifest."""
    try:
        _run_module_transition(module, "module_video", "submit")
    except (ClientError, ExternalReviewError, ObjectiveOverrideError) as exc:
        print_error(str(exc))
        raise typer.Exit(1)


@app.command("mark-videos-approved")
@command
def modules_mark_videos_approved(
    module: str = typer.Argument(..., help="Module record ID, ID pattern, or name"),
):
    """Record external approval of the exact submitted Module Video manifest."""
    try:
        _run_module_transition(module, "module_video", "approve")
    except (ClientError, ExternalReviewError, ObjectiveOverrideError) as exc:
        print_error(str(exc))
        raise typer.Exit(1)


@app.command("mark-video-changes-requested", hidden=True)
@command
def modules_mark_video_changes_requested(
    module: str = typer.Argument(..., help="Module record ID, ID pattern, or name"),
    feedback_record_id: List[str] = typer.Option(
        ...,
        "--feedback-record-id",
        help="Persisted Pluralsight Feedback record ID; repeat for every imported row",
    ),
):
    """Record video changes only after a durable feedback-import readback."""
    try:
        client = get_client()
        record_id = client.resolve_module_id(module)
        receipts = verified_video_feedback_receipts(
            client, record_id, feedback_record_id
        )
        result = execute_transition(
            client,
            "module_video",
            "request_changes",
            "pluralsight_feedback_ingest",
            record_id,
            workflow_receipts=receipts,
        )
        print_success(f"Recorded Module Video changes requested for {record_id}")
        print_json(result)
    except (ClientError, ExternalReviewError, ObjectiveOverrideError) as exc:
        print_error(str(exc))
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
    "accept-approved-slide-deck": ["custom"],
    "mark-slide-deck-approved": ["custom"],
    "mark-slide-deck-changes-requested": ["custom"],
    "mark-video-changes-requested": ["custom"],
    "mark-videos-approved": ["custom"],
    "show": [
        "custom"
    ],
    "submit-slide-deck-for-review": ["custom"],
    "submit-videos-for-review": ["custom"],
    "update": [
        "custom"
    ]
}
