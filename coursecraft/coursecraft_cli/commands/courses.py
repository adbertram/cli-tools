"""Courses command module."""
import json
import typer
from typing import Optional, List, Dict
from pathlib import Path

from ..client import get_client, ClientError
from ..output import print_success, print_error, print_info, print_json, print_table
from ..filter_map import translate_filters
from ..filters import apply_properties_filter, apply_limit

app = typer.Typer(help="Manage course records")


def _collect_course_records(client, course_record_id: str) -> Dict[str, List[Dict]]:
    """
    Collect all records that belong to a course (modules, clips, demos, slides).

    Returns dict with keys: course, modules, clips, demos, slides
    """
    result = {
        "course": None,
        "modules": [],
        "clips": [],
        "demos": [],
        "slides": []
    }

    # Get the course record
    course = client.get_record("Courses", course_record_id)
    if not course:
        raise ClientError(f"Course not found: {course_record_id}")
    result["course"] = course

    # Get all modules
    modules = client.get_modules_by_course(course_record_id)
    result["modules"] = modules

    # Get all clips for each module
    for module in modules:
        clips = client.get_clips_by_module(module["id"])
        result["clips"].extend(clips)

    # Get all demos and slides for each clip
    for clip in result["clips"]:
        demos = client.get_demos_by_clip(clip["id"])
        slides = client.get_slides_by_clip(clip["id"])
        result["demos"].extend(demos)
        result["slides"].extend(slides)

    return result


def _print_deletion_summary(records: Dict[str, List[Dict]]) -> None:
    """Print a summary of what will be deleted."""
    course = records["course"]
    course_name = course.get("fields", {}).get("Name", course["id"])

    print_info(f"\nCourse: {course_name}")
    print_info(f"  Modules: {len(records['modules'])}")
    print_info(f"  Clips: {len(records['clips'])}")
    print_info(f"  Demos: {len(records['demos'])}")
    print_info(f"  Slides: {len(records['slides'])}")

    total = 1 + len(records["modules"]) + len(records["clips"]) + \
            len(records["demos"]) + len(records["slides"])
    print_info(f"\nTotal records to delete: {total}")


def _delete_records_cascade(client, records: Dict[str, List[Dict]]) -> Dict[str, int]:
    """
    Delete all records in cascade order (children first).

    Returns dict with counts of deleted records by type.
    """
    deleted = {"slides": 0, "demos": 0, "clips": 0, "modules": 0, "course": 0}

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

    # Delete modules
    for module in records["modules"]:
        client.delete_record("Modules", module["id"])
        deleted["modules"] += 1

    # Delete course
    client.delete_record("Courses", records["course"]["id"])
    deleted["course"] = 1

    return deleted


@app.command("create")
def create_course(
    name: str = typer.Option(..., "--name", "-n", help="Course name"),
    course_id: str = typer.Option(..., "--course-id", "-c", help="Course slug identifier"),
    target_length: int = typer.Option(..., "--target-length", "-t", help="Target length in minutes"),
    course_outline_link: Optional[str] = typer.Option(None, "--course-outline-link", "-l", help="Google Doc URL for course outline"),
    platform: Optional[str] = typer.Option(None, "--platform", "-p", help="Course platform (Pluralsight, Udemy)"),
    short_description: Optional[str] = typer.Option(None, "--short-description", help="Brief course summary"),
    long_description: Optional[str] = typer.Option(None, "--long-description", help="Detailed description"),
    content_level: Optional[str] = typer.Option(None, "--content-level", help="Entry-level, Intermediate, Advanced"),
    job_role: Optional[str] = typer.Option(None, "--job-role", help="Target job role"),
    learner_profile: Optional[str] = typer.Option(None, "--learner-profile", help="Learner description"),
    prerequisites: Optional[str] = typer.Option(None, "--prerequisites", help="Required learner prerequisites"),
    storyline: Optional[str] = typer.Option(None, "--storyline", help="Course storyline narrative"),
    learning_objectives: Optional[str] = typer.Option(None, "--learning-objectives", help="Course learning objectives"),
    notes: Optional[str] = typer.Option(None, "--notes", help="Internal notes"),
    active: Optional[bool] = typer.Option(None, "--active", help="Active status (true/false)"),
    modules_json: Optional[str] = typer.Option(None, "--json", help="Inline JSON for nested module/clip creation"),
    modules_file: Optional[Path] = typer.Option(None, "--file", help="Path to JSON file with module/clip definitions"),
):
    """
    Create a course record, optionally with modules and clips.

    Examples:
        # Create course only
        coursecraft courses create --name "My Course" --course-id "my-course" --target-length 120

        # Create course with modules from JSON
        coursecraft courses create --name "My Course" --course-id "my-course" --target-length 120 \\
            --json '[{"name":"Module 1","clips":[{"name":"Intro"}]}]'
    """
    try:
        client = get_client()

        # Check if course name already exists
        existing_id = client.check_course_exists(name)
        if existing_id:
            print_error(f"Course with name '{name}' already exists: {existing_id}")
            raise typer.Exit(1)

        # Build fields dictionary
        fields = {
            "Name": name,
            "Course ID": course_id,
            "Target Length (Min)": target_length,
        }

        # Add optional fields
        if course_outline_link is not None:
            fields["Pluralsight Course Outline Link"] = course_outline_link
        if platform is not None:
            fields["Platform"] = platform
        if short_description:
            fields["Short Description"] = short_description
        if long_description:
            fields["Long Description"] = long_description
        if content_level:
            fields["Content Level"] = content_level
        if job_role:
            fields["Job Role"] = job_role
        if learner_profile:
            fields["Learner Profile"] = learner_profile
        if prerequisites:
            fields["(Required) Learner Prerequisites"] = prerequisites
        if storyline:
            fields["Storyline"] = storyline
        if learning_objectives:
            fields["Learning Objectives"] = learning_objectives
        if notes:
            fields["Notes"] = notes
        if active is not None:
            fields["Active"] = str(active).lower()

        # Create the course
        record_id = client.create_record("Courses", fields)
        print_success(f"Created course '{name}': {record_id}")

        # Handle nested modules if provided
        if modules_file or modules_json:
            from .modules import create_modules_from_json

            json_data = None
            if modules_file:
                if not modules_file.exists():
                    print_error(f"File not found: {modules_file}")
                    raise typer.Exit(1)
                json_data = modules_file.read_text()
            elif modules_json:
                json_data = modules_json

            if json_data:
                try:
                    modules_list = json.loads(json_data)
                    create_modules_from_json(client, record_id, modules_list)
                except json.JSONDecodeError as e:
                    print_error(f"Invalid JSON: {e}")
                    raise typer.Exit(1)

        # Output the record ID for scripting
        typer.echo(record_id)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("list")
def list_courses(
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum number of records to return"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of properties to include (supports dot notation)"),
    table_output: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
    active: bool = typer.Option(False, "--active", "-a", help="Return only the active course"),
):
    """
    List course records.

    Examples:
        # List all courses
        coursecraft courses list

        # Get the active course
        coursecraft courses list --active

        # List with table output
        coursecraft courses list --table

        # Limit results
        coursecraft courses list --limit 10

        # Select specific properties
        coursecraft courses list --properties "id,fields.Name,fields.Status"
    """
    try:
        client = get_client()

        # Build filter formula
        formula = None
        filter_list = list(filter) if filter else []

        # Add active filter if --active flag is set
        if active:
            filter_list.append("active:eq:true")

        if filter_list:
            formula = translate_filters(filter_list, 'Courses')

        records = client.list_records("Courses", formula)

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
                    "course_id": fields.get("Course ID", ""),
                    "status": fields.get("Status", ""),
                    "target_length": fields.get("Target Length (Min)", ""),
                    "active": fields.get("Active", ""),
                })
            print_table(rows, ["id", "name", "course_id", "status", "target_length", "active"],
                       ["Record ID", "Name", "Course ID", "Status", "Target (Min)", "Active"])
        else:
            print_json(records)

    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("get")
def get_course(
    course: str = typer.Argument(..., help="Course record ID or Course ID slug"),
    table_output: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
    include_modules: bool = typer.Option(False, "--include-modules", "-m", help="Include nested module records in output"),
    include_clips: bool = typer.Option(False, "--include-clips", "-c", help="Include nested clip records (implies --include-modules)"),
):
    """
    Get a single course record by ID or slug.

    Use --include-modules to embed module records in the JSON output.
    Use --include-clips to also embed clip records within each module.

    Examples:
        coursecraft courses get recXXXXXXXXXXXXXXX
        coursecraft courses get my-course-slug
        coursecraft courses get my-course-slug --table
        coursecraft courses get my-course-slug --include-modules
        coursecraft courses get my-course-slug --include-clips
    """
    try:
        client = get_client()

        # Resolve course identifier to record ID
        course_record_id = client.resolve_course_id(course)
        record = client.get_record("Courses", course_record_id)

        if not record:
            print_error(f"Course not found: {course}")
            raise typer.Exit(1)

        # --include-clips implies --include-modules
        if include_clips:
            include_modules = True

        # Fetch and embed modules if requested
        if include_modules:
            modules = client.get_modules_by_course(course_record_id)

            # Sort modules by order if available
            modules.sort(key=lambda m: m.get("fields", {}).get("Order", 999))

            # Fetch and embed clips for each module if requested
            if include_clips:
                for module in modules:
                    clips = client.get_clips_by_module(module["id"])
                    # Sort clips by order if available
                    clips.sort(key=lambda c: c.get("fields", {}).get("Order", 999))
                    module["clips"] = clips

            record["modules"] = modules

        if table_output:
            fields = record.get("fields", {})
            rows = [{
                "id": record["id"],
                "name": fields.get("Name", ""),
                "course_id": fields.get("Course ID", ""),
                "status": fields.get("Status", ""),
                "target_length": fields.get("Target Length (Min)", ""),
                "active": fields.get("Active", ""),
                "content_level": fields.get("Content Level", ""),
            }]
            print_table(rows, ["id", "name", "course_id", "status", "target_length", "active", "content_level"],
                       ["Record ID", "Name", "Course ID", "Status", "Target (Min)", "Active", "Level"])

            # If modules included, also show module table
            if include_modules and record.get("modules"):
                print_info(f"\nModules ({len(record['modules'])}):")
                module_rows = []
                for mod in record["modules"]:
                    mod_fields = mod.get("fields", {})
                    clip_count = len(mod.get("clips", [])) if include_clips else mod_fields.get("Clips", [])
                    if isinstance(clip_count, list):
                        clip_count = len(clip_count)
                    module_rows.append({
                        "id": mod["id"],
                        "order": mod_fields.get("Order", ""),
                        "name": mod_fields.get("Name", ""),
                        "status": mod_fields.get("Status", ""),
                        "clips": clip_count,
                    })
                print_table(module_rows, ["id", "order", "name", "status", "clips"],
                           ["Record ID", "#", "Name", "Status", "Clips"])

                # If clips included, show clip details per module
                if include_clips:
                    for mod in record["modules"]:
                        mod_clips = mod.get("clips", [])
                        if mod_clips:
                            mod_name = mod.get("fields", {}).get("Name", mod["id"])
                            print_info(f"\n  Clips for '{mod_name}' ({len(mod_clips)}):")
                            clip_rows = []
                            for clip in mod_clips:
                                clip_fields = clip.get("fields", {})
                                clip_rows.append({
                                    "id": clip["id"],
                                    "order": clip_fields.get("Order", ""),
                                    "name": clip_fields.get("Name", ""),
                                    "status": clip_fields.get("Status", ""),
                                })
                            print_table(clip_rows, ["id", "order", "name", "status"],
                                       ["Record ID", "#", "Name", "Status"])
        else:
            print_json(record)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("update")
def update_course(
    course: str = typer.Argument(..., help="Course record ID or Course ID slug"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Course name"),
    course_id_field: Optional[str] = typer.Option(None, "--course-id", "-c", help="Course slug identifier"),
    target_length: Optional[int] = typer.Option(None, "--target-length", "-t", help="Target length in minutes"),
    course_outline_link: Optional[str] = typer.Option(None, "--course-outline-link", "-l", help="Google Doc URL for course outline"),
    course_outline: Optional[str] = typer.Option(None, "--course-outline", help="Course outline content (markdown)"),
    course_outline_file: Optional[Path] = typer.Option(None, "--course-outline-file", help="Path to file containing course outline content"),
    short_description: Optional[str] = typer.Option(None, "--short-description", help="Brief course summary"),
    long_description: Optional[str] = typer.Option(None, "--long-description", help="Detailed description"),
    content_level: Optional[str] = typer.Option(None, "--content-level", help="Entry-level, Intermediate, Advanced"),
    content_tags: Optional[str] = typer.Option(None, "--content-tags", help="Comma-separated content tags"),
    job_role: Optional[str] = typer.Option(None, "--job-role", help="Target job role"),
    learner_profile: Optional[str] = typer.Option(None, "--learner-profile", help="Learner description"),
    prerequisites: Optional[str] = typer.Option(None, "--prerequisites", help="Required learner prerequisites"),
    platform_versions: Optional[str] = typer.Option(None, "--platform-versions", help="Platform/tool versions"),
    storyline: Optional[str] = typer.Option(None, "--storyline", help="Course storyline narrative"),
    learning_objectives: Optional[str] = typer.Option(None, "--learning-objectives", help="Course learning objectives"),
    notes: Optional[str] = typer.Option(None, "--notes", help="Internal notes"),
    skill_path: Optional[str] = typer.Option(None, "--skill-path", help="Skill path name"),
    path_placement: Optional[str] = typer.Option(None, "--path-placement", help="Position in skill path (1, 2, 3, etc.)"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Course status"),
    active: Optional[bool] = typer.Option(None, "--active", help="Active status (true/false)"),
    brainstorming_outline: Optional[str] = typer.Option(None, "--brainstorming-outline", "-B", help="Course brainstorming outline content"),
    brainstorming_outline_file: Optional[Path] = typer.Option(None, "--brainstorming-outline-file", help="Path to file containing brainstorming outline"),
    brainstorming_outline_fact_checked: Optional[bool] = typer.Option(None, "--brainstorming-outline-fact-checked", help="Mark brainstorming outline as fact-checked"),
):
    """
    Update a course record.

    Examples:
        coursecraft courses update my-course-slug --name "New Name"
        coursecraft courses update recXXX --status "Complete" --active true
        coursecraft courses update my-course --target-length 60
        coursecraft courses update my-course --brainstorming-outline-file outline.md
    """
    try:
        client = get_client()

        # Resolve course identifier to record ID
        course_record_id = client.resolve_course_id(course)

        # Verify record exists
        existing = client.get_record("Courses", course_record_id)
        if not existing:
            print_error(f"Course not found: {course}")
            raise typer.Exit(1)

        # Build fields dictionary with only provided values
        fields = {}
        if name is not None:
            fields["Name"] = name
        if course_id_field is not None:
            fields["Course ID"] = course_id_field
        if target_length is not None:
            fields["Target Length (Min)"] = target_length
        if course_outline_link is not None:
            fields["Pluralsight Course Outline Link"] = course_outline_link
        # Handle course outline content from file or direct input
        if course_outline_file is not None:
            if not course_outline_file.exists():
                print_error(f"File not found: {course_outline_file}")
                raise typer.Exit(1)
            fields["Course Outline"] = course_outline_file.read_text()
        elif course_outline is not None:
            fields["Course Outline"] = course_outline
        if short_description is not None:
            fields["Short Description"] = short_description
        if long_description is not None:
            fields["Long Description"] = long_description
        if content_level is not None:
            fields["Content Level"] = content_level
        if content_tags is not None:
            fields["Content Tags"] = content_tags
        if job_role is not None:
            fields["Job Role"] = job_role
        if learner_profile is not None:
            fields["Learner Profile"] = learner_profile
        if prerequisites is not None:
            fields["(Required) Learner Prerequisites"] = prerequisites
        if platform_versions is not None:
            fields["Platform/Tools"] = platform_versions
        if storyline is not None:
            fields["Storyline"] = storyline
        if learning_objectives is not None:
            fields["Learning Objectives"] = learning_objectives
        if notes is not None:
            fields["Notes"] = notes
        if skill_path is not None:
            fields["Skill Path"] = skill_path
        if path_placement is not None:
            fields["Path Placement"] = path_placement
        if status is not None:
            fields["Status"] = status
        if active is not None:
            fields["Active"] = str(active).lower()

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

        if not fields:
            print_error("No fields to update. Provide at least one field option.")
            raise typer.Exit(1)

        # Update the record
        client.update_record("Courses", course_record_id, fields)
        print_success(f"Updated course: {course_record_id}")

        # Output the record ID for scripting
        typer.echo(course_record_id)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("delete")
def delete_course(
    course: str = typer.Option(..., "--course", "-c", help="Course record ID or Course ID slug"),
    cascade: bool = typer.Option(False, "--cascade", help="Delete all child records (modules, clips, demos, slides)"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompts"),
):
    """
    Delete a course record.

    By default, only the course record is deleted. Use --cascade to also delete
    all child records (modules, clips, demos, slides).

    Examples:
        # Delete course only (prompts if children exist)
        coursecraft courses delete --course my-course-id

        # Delete course and all children
        coursecraft courses delete --course my-course-id --cascade

        # Delete without confirmation (for scripting)
        coursecraft courses delete --course my-course-id --force
        coursecraft courses delete --course my-course-id --cascade --force
    """
    try:
        client = get_client()

        # Resolve course identifier to record ID
        course_record_id = client.resolve_course_id(course)

        # Collect all records
        print_info("Collecting records...")
        records = _collect_course_records(client, course_record_id)

        course_name = records["course"].get("fields", {}).get("Name", course_record_id)
        child_count = len(records["modules"]) + len(records["clips"]) + \
                      len(records["demos"]) + len(records["slides"])

        if cascade:
            # Cascading delete - show summary and confirm
            _print_deletion_summary(records)

            if not force:
                print_info("")
                if not typer.confirm("Are you sure you want to delete all these records?"):
                    print_info("Deletion cancelled.")
                    raise typer.Exit(0)

            # Perform cascading delete
            print_info("\nDeleting records...")
            deleted = _delete_records_cascade(client, records)

            # Report results
            total = sum(deleted.values())
            print_success(f"Deleted {total} records:")
            print_info(f"  - {deleted['slides']} slides")
            print_info(f"  - {deleted['demos']} demos")
            print_info(f"  - {deleted['clips']} clips")
            print_info(f"  - {deleted['modules']} modules")
            print_info(f"  - {deleted['course']} course")
        else:
            # Single record delete
            if child_count > 0 and not force:
                print_info(f"\nCourse: {course_name}")
                print_info(f"  Modules: {len(records['modules'])}")
                print_info(f"  Clips: {len(records['clips'])}")
                print_info(f"  Demos: {len(records['demos'])}")
                print_info(f"  Slides: {len(records['slides'])}")
                print_info(f"\nWarning: This will leave {child_count} orphaned child record(s).")
                print_info("Use --cascade to delete all children, or --force to allow orphans.")
                print_info("")
                if not typer.confirm("Continue and leave orphaned records?"):
                    print_info("Deletion cancelled.")
                    raise typer.Exit(0)

            # Delete only the course
            client.delete_record("Courses", course_record_id)
            print_success(f"Deleted course: {course_record_id}")

        # Output the deleted course ID for scripting
        typer.echo(course_record_id)

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
    "update": [
        "custom"
    ]
}
