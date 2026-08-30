"""Courses command module."""
import json
import os
import typer
from typing import Optional, List, Dict
from pathlib import Path

from cli_tools_shared.filters import apply_limit
from cli_tools_shared.output import command
from ..batch import load_batch_payload
from ..client import get_client, ClientError
from ..coursecraft_project import run_coursecraft_script, script_flags
from ..output import apply_properties_filter, project_record, print_success, print_error, print_info, print_json, print_table, warn_policy
from ..filter_map import translate_filters
from ..field_mappings import collect_mapped_updates, validate_field
from ..course_versions import (
    LegacyImportBaseError,
    VersionIdentityError,
    update_slug,
    validate_legacy_import_base,
    validate_version_identity,
)
from ..external_review import ExternalReviewError, execute_transition
from ..objective_override import (
    AUDIT_FIELD,
    CARRY_FORWARD_PLAN_SLUG,
    CORRECTION_REQUESTED,
    FEEDBACK_RESYNCED,
    OBJECTIVES_FIELD,
    OBJECTIVES_OVERRIDE_SLUG,
    OUTLINE_DRAFT_SLUG,
    OUTLINE_REVIEW_FIELD,
    OVERRIDE_ACTIVE,
    OVERRIDE_AUTHORIZED,
    REVIEW_FIELD,
    STATE_FIELD,
    UPDATE_RECEIVED,
    ObjectiveOverrideError,
    append_audit,
    artifact_version_identity,
    content_snapshot,
    current_artifact_version,
    current_requirements_version,
    current_state,
    load_audit,
    now_iso,
    predicted_requirements_version,
    read_replacement,
    require_current_needs_revision_artifact_review,
    require_current_needs_revision_review,
    require_pluralsight,
    require_state,
    sha256_text,
    version_identity,
)

app = typer.Typer(help="Manage course records")

POWERPOINT_SLIDE_DECK_VERSION_FIELD = validate_field("powerpoint_slide_deck_version", "Courses")


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


def _refuse_duplicate_course_name(client, name: str, allow_duplicate: bool = False) -> None:
    """Block a second course with the same Name, unless it is a course update.

    A Pluralsight course update inherits its base course's Name verbatim -- the ``-vN``
    slug and the Version field disambiguate it, not the name (course-update plan
    section 2). Duplicate-name reads are resolved by the list-and-ask rule, so the
    intake touch opts out of this guard; every other create path keeps it.
    """
    if allow_duplicate:
        return
    existing_id = client.check_course_exists(name)
    if existing_id:
        print_error(f"Course with name '{name}' already exists: {existing_id}")
        raise typer.Exit(1)


@app.command("create")
@command
def create_course(
    name: str = typer.Option(..., "--name", "-n", help="Course name"),
    course_id: str = typer.Option(..., "--course-id", "-c", help="Course slug identifier"),
    target_length: int = typer.Option(..., "--target-length", "-t", help="Target length in minutes"),
    deadline: Optional[str] = typer.Option(None, "--deadline", help="Course deadline (YYYY-MM-DD)"),
    course_requirements_link: Optional[str] = typer.Option(None, "--course-requirements-link", "-l", help="Google Doc URL for the Pluralsight course requirements"),
    feedback_sheet_id: Optional[str] = typer.Option(None, "--feedback-sheet-id", help="Google Sheet ID for Pluralsight recording feedback"),
    platform: Optional[str] = typer.Option(None, "--platform", "-p", help="Course platform (Pluralsight, Udemy)"),
    powerpoint_slide_deck_version: Optional[str] = typer.Option(None, "--powerpoint-slide-deck-version", help="PowerPoint slide deck version (e.g., '2026.05.a'); stored verbatim in the singleSelect field"),
    short_description: Optional[str] = typer.Option(None, "--short-description", help="Brief course summary"),
    long_description: Optional[str] = typer.Option(None, "--long-description", help="Detailed description"),
    content_level: Optional[str] = typer.Option(None, "--content-level", help="Entry-level, Intermediate, Advanced"),
    job_role: Optional[str] = typer.Option(None, "--job-role", help="Target job role"),
    learner_profile: Optional[str] = typer.Option(None, "--learner-profile", help="Learner description"),
    prerequisites: Optional[str] = typer.Option(None, "--prerequisites", help="Required learner prerequisites"),
    storyline: Optional[str] = typer.Option(None, "--storyline", help="Course storyline narrative"),
    learning_objectives: Optional[str] = typer.Option(None, "--learning-objectives", help="Course learning objectives"),
    notes: Optional[str] = typer.Option(None, "--notes", help="Internal notes"),
    active: Optional[bool] = typer.Option(None, "--active/--no-active", help="Set or clear Active status"),
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
        _refuse_duplicate_course_name(client, name)

        # Build fields dictionary
        fields = {
            "Name": name,
            "Course ID": course_id,
            "Target Length (Min)": target_length,
        }

        # Add optional fields
        if deadline is not None:
            fields["Deadline"] = deadline
        if course_requirements_link is not None:
            fields["Course Requirements Link"] = course_requirements_link
        if feedback_sheet_id is not None:
            fields["Feedback Sheet ID"] = feedback_sheet_id
        if platform is not None:
            fields["Platform"] = platform
        if powerpoint_slide_deck_version is not None:
            fields[POWERPOINT_SLIDE_DECK_VERSION_FIELD] = powerpoint_slide_deck_version
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
            fields["Active"] = active

        # Create the course
        record_id = client.create_record("Courses", fields)
        print_success(f"Created course '{name}': {record_id}")

        # Handle nested modules if provided
        if modules_file or modules_json:
            from .modules import create_modules_from_json

            modules_list = load_batch_payload(modules_json, modules_file)
            create_modules_from_json(client, record_id, modules_list)

        # Output the record ID for scripting
        typer.echo(record_id)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("list")
@command
def list_courses(
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum number of records to return"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Property to include (supports dot notation). Repeatable; each value may also be comma-separated."),
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
@command
def get_course(
    course: str = typer.Argument(..., help="Course record ID or Course ID slug"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Property to include (supports dot notation). Repeatable; each value may also be comma-separated."),
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
        coursecraft courses get my-course-slug --properties "id,fields.Name"
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

        if properties and not table_output:
            record = project_record(record, properties)

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


@app.command("disable")
@command
def disable_course(
    course: str = typer.Argument(..., help="Course record ID or Course ID slug"),
    why: str = typer.Option(..., "--why", help="Required explanation stored in Disabled Notes"),
):
    """
    Disable a course and block future CourseCraft mutations for it.

    Examples:
        coursecraft courses disable my-course-slug --why "Archived; replaced by 2026 version."
    """
    if not why.strip():
        print_error("--why must not be empty")
        raise typer.Exit(1)

    try:
        client = get_client()
        course_record_id = client.resolve_course_id(course)
        existing = client.get_record("Courses", course_record_id)
        if not existing:
            print_error(f"Course not found: {course}")
            raise typer.Exit(1)

        client.update_record(
            "Courses",
            course_record_id,
            {"Disabled": True, "Disabled Notes": why.strip()},
        )
        print_success(f"Disabled course: {course_record_id}")
        typer.echo(course_record_id)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("update")
@command
def update_course(
    course: str = typer.Argument(..., help="Course record ID or Course ID slug"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Course name"),
    course_id_field: Optional[str] = typer.Option(None, "--course-id", "-c", help="Course slug identifier"),
    target_length: Optional[int] = typer.Option(None, "--target-length", "-t", help="Target length in minutes"),
    deadline: Optional[str] = typer.Option(None, "--deadline", help="Course deadline (YYYY-MM-DD)"),
    course_requirements_link: Optional[str] = typer.Option(None, "--course-requirements-link", "-l", help="Google Doc URL for the Pluralsight course requirements"),
    feedback_sheet_id: Optional[str] = typer.Option(None, "--feedback-sheet-id", help="Google Sheet ID for Pluralsight recording feedback"),
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
    research_report: Optional[str] = typer.Option(None, "--research-report", help="Research report content"),
    research_report_file: Optional[Path] = typer.Option(None, "--research-report-file", help="Path to file containing research report content"),
    course_requirements: Optional[str] = typer.Option(None, "--course-requirements", help="Course requirements content; read-only after the Pluralsight correction lifecycle starts"),
    course_requirements_file: Optional[Path] = typer.Option(None, "--course-requirements-file", help="File containing course requirements; read-only after the Pluralsight correction lifecycle starts"),
    course_requirements_review_ai: Optional[str] = typer.Option(None, "--course-requirements-review-ai", help="AI review verdict for course.requirements"),
    outline_draft: Optional[str] = typer.Option(None, "--outline-draft", help="Course Outline Draft Markdown content"),
    outline_draft_file: Optional[Path] = typer.Option(None, "--outline-draft-file", help="Path to file containing the Course Outline Draft Markdown"),
    outline_draft_review_ai: Optional[str] = typer.Option(None, "--outline-draft-review-ai", help="AI review verdict for course.outline_draft"),
    outline_draft_human_verified: Optional[bool] = typer.Option(None, "--outline-draft-human-verified/--no-outline-draft-human-verified", help="Set or clear Adam's approval of the Course Outline Draft"),
    course_outline: Optional[str] = typer.Option(None, "--course-outline", help="Built Course Outline content"),
    course_outline_file: Optional[Path] = typer.Option(None, "--course-outline-file", help="Path to file containing the built Course Outline"),
    notes: Optional[str] = typer.Option(None, "--notes", help="Internal notes"),
    skill_path: Optional[str] = typer.Option(None, "--skill-path", help="Skill path name"),
    path_placement: Optional[str] = typer.Option(None, "--path-placement", help="Position in skill path (1, 2, 3, etc.)"),
    slack_channel_name: Optional[str] = typer.Option(None, "--slack-channel-name", help="Slack channel name for Pluralsight course communication"),
    powerpoint_slide_deck_version: Optional[str] = typer.Option(None, "--powerpoint-slide-deck-version", help="PowerPoint slide deck version (e.g., '2026.05.a'); stored verbatim in the singleSelect field"),
    active: Optional[bool] = typer.Option(None, "--active/--no-active", help="Set or clear Active status"),
    brainstorming_outline: Optional[str] = typer.Option(None, "--brainstorming-outline", "-B", help="Course brainstorming outline content"),
    brainstorming_outline_file: Optional[Path] = typer.Option(None, "--brainstorming-outline-file", help="Path to file containing brainstorming outline"),
    feedback_requested: Optional[bool] = typer.Option(None, "--feedback-requested/--no-feedback-requested", help="Set or clear the feedback-requested gate flag"),
    feedback_requested_at: Optional[str] = typer.Option(None, "--feedback-requested-at", help="ISO 8601 timestamp the feedback gate was requested"),
    version: Optional[int] = typer.Option(None, "--version", help="Course update version (1 = original contracted course)"),
    base_course: Optional[str] = typer.Option(None, "--base-course", help="Record ID or slug of the immediately prior course version"),
    prior_course_inventory: Optional[str] = typer.Option(None, "--prior-course-inventory", help="update.prior_course_inventory JSON content"),
    prior_course_inventory_file: Optional[Path] = typer.Option(None, "--prior-course-inventory-file", help="Path to a file containing the prior-course inventory"),
    gap_analysis: Optional[str] = typer.Option(None, "--gap-analysis", help="update.gap_analysis content"),
    gap_analysis_file: Optional[Path] = typer.Option(None, "--gap-analysis-file", help="Path to a file containing the gap analysis"),
    carry_forward_plan: Optional[str] = typer.Option(None, "--carry-forward-plan", help="update.carry_forward_plan JSON content"),
    carry_forward_plan_file: Optional[Path] = typer.Option(None, "--carry-forward-plan-file", help="Path to a file containing the carry-forward plan"),
    carry_forward_plan_human_verified: Optional[bool] = typer.Option(None, "--carry-forward-plan-human-verified/--no-carry-forward-plan-human-verified", help="Set or clear Adam's approval of the carry-forward plan"),
):
    """
    Update a course record.

    Examples:
        coursecraft courses update my-course-slug --name "New Name"
        coursecraft courses update recXXX --active
        coursecraft courses update recXXX --no-active
        coursecraft courses update my-course --target-length 60
        coursecraft courses update my-course --brainstorming-outline-file outline.md
        coursecraft courses update my-course --course-outline-file course-outline.md
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

        existing_fields = existing.get("fields", {})
        if (
            (course_requirements is not None or course_requirements_file is not None)
            and existing_fields.get("Platform") == "Pluralsight"
        ):
            state = current_state(existing_fields)
            if state in {
                CORRECTION_REQUESTED,
                FEEDBACK_RESYNCED,
                OVERRIDE_AUTHORIZED,
                OVERRIDE_ACTIVE,
            }:
                print_error(
                    "Course Requirements is read-only provenance after the Pluralsight "
                    f"correction lifecycle starts (state {state!r}). Use courses "
                    "sync-requirements to refresh it verbatim from Course Requirements Link."
                )
                raise typer.Exit(1)

        if learning_objectives is not None and existing_fields.get("Platform") == "Pluralsight":
            state = current_state(existing_fields)
            if state != OVERRIDE_AUTHORIZED:
                rendered = state or "blank"
                print_error(
                    "Pluralsight Learning Objectives are Curriculum-owned. "
                    f"The override state is {rendered!r}, not {OVERRIDE_AUTHORIZED!r}. "
                    "Complete the gated override lifecycle before replacing them."
                )
            else:
                print_error(
                    "The override is authorized, but generic courses update cannot write "
                    "Pluralsight Learning Objectives because it would omit the required audit. "
                    "Use courses apply-objective-override with --reason."
                )
            raise typer.Exit(1)

        # Build fields dictionary with only provided values
        fields = collect_mapped_updates(
            "Courses",
            {
                "name": name,
                "course_id": course_id_field,
                "target_length": target_length,
                "deadline": deadline,
                "course_requirements_link": course_requirements_link,
                "feedback_sheet_id": feedback_sheet_id,
                "short_description": short_description,
                "long_description": long_description,
                "content_level": content_level,
                "content_tags": content_tags,
                "job_role": job_role,
                "learner_profile": learner_profile,
                "prerequisites": prerequisites,
                "platform_versions": platform_versions,
                "storyline": storyline,
                "learning_objectives": learning_objectives,
                "course_requirements_review_ai": course_requirements_review_ai,
                "outline_draft_review_ai": outline_draft_review_ai,
                "outline_draft_human_verified": outline_draft_human_verified,
                "notes": notes,
                "skill_path": skill_path,
                "path_placement": path_placement,
                "powerpoint_slide_deck_version": powerpoint_slide_deck_version,
                "feedback_requested": feedback_requested,
                "feedback_requested_at": feedback_requested_at,
                "version": version,
                "carry_forward_plan_human_verified": carry_forward_plan_human_verified,
            },
        )
        if research_report_file is not None:
            if not research_report_file.exists():
                print_error(f"File not found: {research_report_file}")
                raise typer.Exit(1)
            fields["Research Report"] = research_report_file.read_text()
        elif research_report is not None:
            fields["Research Report"] = research_report
        if course_requirements_file is not None:
            if not course_requirements_file.exists():
                print_error(f"File not found: {course_requirements_file}")
                raise typer.Exit(1)
            fields["Course Requirements"] = course_requirements_file.read_text()
        elif course_requirements is not None:
            fields["Course Requirements"] = course_requirements
        if outline_draft_file is not None:
            if not outline_draft_file.exists():
                print_error(f"File not found: {outline_draft_file}")
                raise typer.Exit(1)
            fields["Outline Draft"] = outline_draft_file.read_text()
        elif outline_draft is not None:
            fields["Outline Draft"] = outline_draft
        course_outline_value = course_outline
        if course_outline_file is not None:
            if not course_outline_file.exists():
                print_error(f"File not found: {course_outline_file}")
                raise typer.Exit(1)
            course_outline_value = course_outline_file.read_text()
        if course_outline_value is not None:
            if not course_outline_value.strip():
                print_error("Course Outline content must not be blank.")
                raise typer.Exit(1)
            fields["Course Outline"] = course_outline_value
        if slack_channel_name is not None:
            fields["Slack Channel Name"] = slack_channel_name
        if active is not None:
            fields["Active"] = active

        # Handle brainstorming outline (file takes precedence over inline)
        if brainstorming_outline_file:
            if not brainstorming_outline_file.exists():
                print_error(f"File not found: {brainstorming_outline_file}")
                raise typer.Exit(1)
            fields["Brainstorming Outline"] = brainstorming_outline_file.read_text()
        elif brainstorming_outline is not None:
            fields["Brainstorming Outline"] = brainstorming_outline

        # Handle feedback gate fields
        # Course-update identity and artifacts
        if base_course is not None:
            fields["Base Course"] = [client.resolve_course_id(base_course)]
        if prior_course_inventory_file is not None:
            if not prior_course_inventory_file.exists():
                print_error(f"File not found: {prior_course_inventory_file}")
                raise typer.Exit(1)
            fields["Prior Course Inventory"] = prior_course_inventory_file.read_text()
        elif prior_course_inventory is not None:
            fields["Prior Course Inventory"] = prior_course_inventory
        if gap_analysis_file is not None:
            if not gap_analysis_file.exists():
                print_error(f"File not found: {gap_analysis_file}")
                raise typer.Exit(1)
            fields["Gap Analysis"] = gap_analysis_file.read_text()
        elif gap_analysis is not None:
            fields["Gap Analysis"] = gap_analysis
        if carry_forward_plan_file is not None:
            if not carry_forward_plan_file.exists():
                print_error(f"File not found: {carry_forward_plan_file}")
                raise typer.Exit(1)
            fields["Carry-Forward Plan"] = carry_forward_plan_file.read_text()
        elif carry_forward_plan is not None:
            fields["Carry-Forward Plan"] = carry_forward_plan
        if "Carry-Forward Plan" in fields and existing_fields.get("Status") != "Gap Analysis":
            ledger_raw = existing_fields.get("Version Control") or "{}"
            try:
                ledger = json.loads(ledger_raw)
            except json.JSONDecodeError as exc:
                raise ObjectiveOverrideError(f"Version Control is not valid JSON: {exc}") from None
            if isinstance(ledger, dict) and CARRY_FORWARD_PLAN_SLUG in ledger:
                warn_policy(
                    "carry_forward_plan.rebuild",
                    "Editing a completed Carry-Forward Plan. update-planner normally "
                    "rebuilds it, and downstream artifacts validated against the old "
                    "structure (module/clip identities, order, and durations) may now "
                    "disagree with it -- re-run update.review and the Outline Draft "
                    "parity check.",
                )

        if not fields:
            print_error("No fields to update. Provide at least one field option.")
            raise typer.Exit(1)

        # One verifier for Version / -vN slug / Base Course, on every write that can
        # touch them (course_versions.validate_version_identity).
        try:
            validate_version_identity(client, existing, fields)
        except VersionIdentityError as e:
            print_error(str(e))
            raise typer.Exit(1)

        # Update the record
        client.update_record("Courses", course_record_id, fields)
        print_success(f"Updated course: {course_record_id}")

        # Output the record ID for scripting
        print_json(course_record_id)

    except (ClientError, ObjectiveOverrideError) as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("delete")
@command
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


COURSES_ROOT = Path(os.environ.get("COURSECRAFT_COURSES_ROOT", "/Users/adam/courses"))

# Basics an update course inherits verbatim from its base version. Name included: the
# slug's -vN suffix and Version disambiguate an update, not its name (plan section 2).
INTAKE_INHERITED_FIELDS = (
    "Name",
    "Platform",
    "Content Level",
    "Job Role",
    "Content Tags",
    "Target Length (Min)",
    "Skill Path",
)


def _scaffold_intake(
    client,
    base: str,
    deadline: Optional[str],
    dry_run: bool,
    legacy_import_base: bool,
) -> int:
    """The intake touch: create the next version of a completed course.

    No outline is involved. Computes Version, the ``-vN`` slug, and the Base Course link,
    inherits the base course's basics, and creates the course folder. Course Folder Root
    is an Airtable formula over Course ID, so the suffixed slug places the folder.
    """
    base_record_id = client.resolve_course_id(base)
    base_record = client.get_record("Courses", base_record_id)
    if not base_record:
        print_error(f"Base course not found: {base}")
        return 1
    base_fields = base_record.get("fields", {})

    base_status = base_fields.get("Status")
    if base_status != "Complete" and not legacy_import_base:
        print_error(
            f"Base course {base_fields.get('Course ID', base_record_id)!r} has Status "
            f"{base_status!r}, not 'Complete'. An update may only be taken from a completed "
            f"course. For a proven published pre-CourseCraft import, pass "
            f"--legacy-import-base."
        )
        return 1

    legacy_import_evidence = None
    if legacy_import_base:
        try:
            legacy_import_evidence = validate_legacy_import_base(
                client, base_record, COURSES_ROOT
            )
        except LegacyImportBaseError as e:
            print_error(str(e))
            return 1

    base_version = base_fields.get("Version")
    if base_version is None or base_version == "":
        print_error(
            f"Base course {base_record_id} has no Version. Backfill Version on the base "
            f"course before taking an update from it."
        )
        return 1

    version = int(base_version) + 1
    base_slug = base_fields.get("Course ID")
    if not base_slug:
        print_error(f"Base course {base_record_id} has no Course ID.")
        return 1
    slug = update_slug(base_slug, version)

    fields = {
        "Course ID": slug,
        "Version": version,
        "Base Course": [base_record_id],
    }
    if deadline is not None:
        fields["Deadline"] = deadline
    for name in INTAKE_INHERITED_FIELDS:
        value = base_fields.get(name)
        if value not in (None, "", []):
            fields[name] = value

    folder_path = COURSES_ROOT / slug

    if dry_run:
        print_info("DRY RUN: planning only -- no records, fields, or folders will be created")
        result = {
            "mode": "intake",
            "dry_run": True,
            "base_course": {
                "id": base_record_id,
                "course_id": base_slug,
                "version": int(base_version),
            },
            "course": {"course_id": slug, "version": version, "fields": fields},
            "course_folder_path": str(folder_path),
        }
        if legacy_import_evidence is not None:
            result["legacy_import_evidence"] = legacy_import_evidence
        print_json(result)
        return 0

    _refuse_duplicate_course_name(client, fields["Name"], allow_duplicate=True)

    try:
        validate_version_identity(client, {"fields": {}}, fields)
    except VersionIdentityError as e:
        print_error(str(e))
        return 1

    record_id = client.create_record("Courses", fields)
    print_success(f"Created course update '{slug}' (version {version}): {record_id}")

    folder_path.mkdir(parents=True, exist_ok=True)
    if not folder_path.is_dir():
        print_error(f"course folder was not created: {folder_path}")
        return 1

    created = client.get_record("Courses", record_id)
    created_fields = created.get("fields", {}) if created else {}
    result = {
        "mode": "intake",
        "dry_run": False,
        "base_course": {
            "id": base_record_id,
            "course_id": base_slug,
            "version": int(base_version),
        },
        "course": {
            "id": record_id,
            "course_id": created_fields.get("Course ID"),
            "version": created_fields.get("Version"),
            "status": created_fields.get("Status"),
            "course_folder_root": created_fields.get("Course Folder Root"),
        },
        "course_folder_path": str(folder_path),
    }
    if legacy_import_evidence is not None:
        result["legacy_import_evidence"] = legacy_import_evidence
    print_json(result)
    return 0


SCAFFOLD_SCRIPT = ".agents/skills/module-scaffolding/tools/module_scaffolding.sh"
# The scaffolder exports the outline (google CLI), extracts it (gemini CLI), then
# creates every module and clip record one CLI call at a time.
SCAFFOLD_TIMEOUT_SECONDS = 1800


def _course_record(client, course: str):
    """Resolve one Course record for a dedicated lifecycle command."""
    record_id = client.resolve_course_id(course)
    record = client.get_record("Courses", record_id)
    if record is None:
        raise ObjectiveOverrideError(f"Course not found: {course}")
    fields = record.get("fields", {})
    return record_id, fields


def _objective_override_course(client, course: str):
    """Resolve one Pluralsight Course record for a dedicated override command."""
    record_id, fields = _course_record(client, course)
    require_pluralsight(fields)
    return record_id, fields


@app.command("request-objective-correction")
@command
def courses_request_objective_correction(
    course: str = typer.Argument(..., help="Course record ID or Course ID slug"),
):
    """Enter the Pluralsight objective-correction lifecycle after a current failed review."""
    try:
        client = get_client()
        record_id, fields = _objective_override_course(client, course)
        if current_state(fields):
            warn_policy(
                "objective_override.state",
                "request-objective-correction normally starts from a blank override "
                f"state; current state is {current_state(fields)!r}.",
            )
        version = current_requirements_version(fields)
        review = require_current_needs_revision_review(fields, version)
        event = {
            "type": "correction_requested",
            "at": now_iso(),
            "requirementsVersion": version,
            "requirementsVersionIdentity": version_identity(version),
            "snapshot": content_snapshot(fields),
            "review": review,
        }
        updates = {
            STATE_FIELD: CORRECTION_REQUESTED,
            AUDIT_FIELD: append_audit(fields, event),
        }
        client.update_record("Courses", record_id, updates)
        print_success(f"Requested Pluralsight objective correction for {record_id}")
        print_json({
            "mode": "request-objective-correction",
            "course": record_id,
            "state": CORRECTION_REQUESTED,
            "requirements_version": version,
        })
    except (ClientError, ObjectiveOverrideError) as exc:
        print_error(str(exc))
        raise typer.Exit(1)


@app.command("mark-requirements-update-received")
@command
def courses_mark_requirements_update_received(
    course: str = typer.Argument(..., help="Course record ID or Course ID slug"),
):
    """Record the external return of corrected Pluralsight requirements."""
    try:
        client = get_client()
        record_id, fields = _objective_override_course(client, course)
        require_state(fields, CORRECTION_REQUESTED)
        audit = load_audit(fields)
        correction_event = audit["events"][-1]
        version = current_requirements_version(fields)
        if correction_event.get("requirementsVersion") != version:
            warn_policy(
                "objective_override.audit",
                "The correction request audit does not match the current Course "
                "Requirements revision.",
            )
        event = {
            "type": "update_received",
            "at": now_iso(),
            "correctionRequestedAt": correction_event.get("at"),
            "requirementsVersion": version,
            "requirementsVersionIdentity": version_identity(version),
        }
        persisted = client.update_record(
            "Courses",
            record_id,
            {
                STATE_FIELD: UPDATE_RECEIVED,
                AUDIT_FIELD: append_audit(fields, event),
            },
        )
        print_success(f"Marked Pluralsight requirements update received for {record_id}")
        print_json({
            "mode": "mark-requirements-update-received",
            "course": record_id,
            "state": persisted.get("fields", {}).get(STATE_FIELD),
            "requirements_version": version,
        })
    except (ClientError, ObjectiveOverrideError) as exc:
        print_error(str(exc))
        raise typer.Exit(1)


def _run_outline_transition(course: str, action: str) -> None:
    client = get_client()
    record_id = client.resolve_course_id(course)
    result = execute_transition(
        client, "course_outline", action, "operator", record_id
    )
    print_success(f"Applied course outline action {action!r} to {record_id}")
    print_json(result)


@app.command("submit-outline-for-review")
@command
def courses_submit_outline_for_review(
    course: str = typer.Argument(..., help="Course record ID or Course ID slug"),
):
    """Submit or resubmit the current ready Course Outline revision."""
    try:
        _run_outline_transition(course, "submit")
    except (ClientError, ExternalReviewError, ObjectiveOverrideError) as exc:
        print_error(str(exc))
        raise typer.Exit(1)


@app.command("mark-outline-changes-requested")
@command
def courses_mark_outline_changes_requested(
    course: str = typer.Argument(..., help="Course record ID or Course ID slug"),
):
    """Record external Course Outline changes requested."""
    try:
        _run_outline_transition(course, "request_changes")
    except (ClientError, ExternalReviewError, ObjectiveOverrideError) as exc:
        print_error(str(exc))
        raise typer.Exit(1)


@app.command("mark-outline-approved")
@command
def courses_mark_outline_approved(
    course: str = typer.Argument(..., help="Course record ID or Course ID slug"),
):
    """Record external approval of the exact submitted Course Outline revision."""
    try:
        _run_outline_transition(course, "approve")
    except (ClientError, ExternalReviewError, ObjectiveOverrideError) as exc:
        print_error(str(exc))
        raise typer.Exit(1)


@app.command("authorize-objective-override")
@command
def courses_authorize_objective_override(
    course: str = typer.Argument(..., help="Course record ID or Course ID slug"),
):
    """Authorize an initial or downstream-reviewed objective override."""
    try:
        client = get_client()
        record_id, fields = _objective_override_course(client, course)
        state = current_state(fields)
        version = current_requirements_version(fields)
        if state == FEEDBACK_RESYNCED:
            review = require_current_needs_revision_review(fields, version)
            event = {
                "type": "override_authorized",
                "at": now_iso(),
                "requirementsVersion": version,
                "requirementsVersionIdentity": version_identity(version),
                "snapshot": content_snapshot(fields),
                "postFeedbackReview": review,
            }
        elif state == OVERRIDE_ACTIVE:
            review_version = current_artifact_version(fields, OUTLINE_DRAFT_SLUG)
            review = require_current_needs_revision_artifact_review(
                fields, OUTLINE_REVIEW_FIELD, OUTLINE_DRAFT_SLUG, review_version
            )
            source_version = current_artifact_version(fields, OBJECTIVES_OVERRIDE_SLUG)
            event = {
                "type": "override_reauthorized",
                "at": now_iso(),
                "requirementsVersion": version,
                "requirementsVersionIdentity": version_identity(version),
                "reviewArtifactVersion": review_version,
                "reviewArtifactVersionIdentity": artifact_version_identity(
                    OUTLINE_DRAFT_SLUG, review_version
                ),
                "downstreamReview": review,
                "sourceArtifactVersion": source_version,
                "sourceArtifactVersionIdentity": artifact_version_identity(
                    OBJECTIVES_OVERRIDE_SLUG, source_version
                ),
                "sourceLearningObjectivesSha256": sha256_text(
                    str(fields.get(OBJECTIVES_FIELD) or "")
                ),
            }
        else:
            rendered = state or "blank"
            warn_policy(
                "objective_override.state",
                "Learning-objective override authorization normally runs from either "
                f"the initial {FEEDBACK_RESYNCED!r} state or an active override with a "
                f"current downstream NEEDS REVISION review; current state is "
                f"{rendered!r}.",
            )
        updates = {
            STATE_FIELD: OVERRIDE_AUTHORIZED,
            AUDIT_FIELD: append_audit(fields, event),
        }
        client.update_record("Courses", record_id, updates)
        print_success(f"Authorized learning-objective override for {record_id}")
        print_json({
            "mode": "authorize-objective-override",
            "course": record_id,
            "state": OVERRIDE_AUTHORIZED,
            "requirements_version": version,
        })
    except (ClientError, ObjectiveOverrideError) as exc:
        print_error(str(exc))
        raise typer.Exit(1)


@app.command("apply-objective-override")
@command
def courses_apply_objective_override(
    course: str = typer.Argument(..., help="Course record ID or Course ID slug"),
    learning_objectives: Optional[str] = typer.Option(
        None, "--learning-objectives", help="Replacement canonical Learning Objectives"
    ),
    learning_objectives_file: Optional[Path] = typer.Option(
        None, "--learning-objectives-file", help="File containing replacement objectives"
    ),
    reason: str = typer.Option(..., "--reason", help="Why the authorized override is required"),
):
    """Apply an authorized override and persist its complete provenance."""
    try:
        if not reason.strip():
            raise ObjectiveOverrideError("--reason cannot be blank.")
        file_value = None
        if learning_objectives_file is not None:
            if not learning_objectives_file.is_file():
                raise ObjectiveOverrideError(f"File not found: {learning_objectives_file}")
            file_value = learning_objectives_file.read_text(encoding="utf-8")
        replacement = read_replacement(learning_objectives, file_value)

        client = get_client()
        record_id, fields = _objective_override_course(client, course)
        require_state(fields, OVERRIDE_AUTHORIZED)
        version = current_requirements_version(fields)
        old_objectives = str(fields.get(OBJECTIVES_FIELD) or "")
        events = load_audit(fields)["events"]
        authorization = events[-1]
        if authorization.get("type") == "override_reauthorized":
            review_version = current_artifact_version(fields, OUTLINE_DRAFT_SLUG)
            review = require_current_needs_revision_artifact_review(
                fields, OUTLINE_REVIEW_FIELD, OUTLINE_DRAFT_SLUG, review_version
            )
            if (
                authorization.get("reviewArtifactVersion") != review_version
                or authorization.get("downstreamReview") != review
            ):
                warn_policy(
                    "objective_override.authorization",
                    "The downstream review changed after objective-override "
                    "authorization; consider authorizing again.",
                )
            if authorization.get("sourceLearningObjectivesSha256") != sha256_text(old_objectives):
                warn_policy(
                    "objective_override.authorization",
                    "Learning Objectives changed after downstream authorization; "
                    "consider authorizing again.",
                )
        event = {
            "type": "override_applied",
            "at": now_iso(),
            "requirementsVersion": version,
            "requirementsVersionIdentity": version_identity(version),
            "oldLearningObjectives": old_objectives,
            "newLearningObjectives": replacement,
            "reason": reason.strip(),
        }
        updates = {
            OBJECTIVES_FIELD: replacement,
            STATE_FIELD: OVERRIDE_ACTIVE,
            AUDIT_FIELD: append_audit(fields, event),
        }
        client.update_record("Courses", record_id, updates)
        print_success(f"Applied learning-objective override for {record_id}")
        print_json({
            "mode": "apply-objective-override",
            "course": record_id,
            "state": OVERRIDE_ACTIVE,
            "requirements_version": version,
            "learning_objectives_sha256": sha256_text(replacement),
        })
    except (ClientError, ObjectiveOverrideError, OSError) as exc:
        print_error(str(exc))
        raise typer.Exit(1)


@app.command("sync-requirements")
@command
def courses_sync_requirements(
    course: str = typer.Argument(
        ..., help="Existing CourseCraft Course record ID or Course ID slug"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Parse and report what would be written, writing nothing",
    ),
):
    """Sync the Pluralsight Curriculum course requirements into the Course record.

    Reads the Google Doc named by Course Requirements Link ONCE, stores it verbatim
    in Course Requirements, and splits out the fields Pluralsight owns and we cannot change:
    Name, Course ID, Skill Path, Path Placement, Job Role, Content Level, Content Tags,
    Target Length (Min), and Learning Objectives.

    Outside the gated objective-override exception it writes nothing else. During that
    exception it also appends the override audit and advances its fail-closed state.
    Short Description, Long Description, Learner Profile,
    (Required) Learner Prerequisites and Storyline are ours and are not knowable until
    Pluralsight approves the outline draft; module-scaffolding writes them after approval.

    Course ID is written only when the record does not have one yet. On an existing record
    the slug is the record's identity -- a course update carries a -vN suffix that
    Curriculum's document does not -- so the document never redirects it.
    """
    from ..google_docs import extract_doc_id, read_document_text
    from ..outline_parser import OutlineParseError, normalize_document, parse_outline

    try:
        client = get_client()
        record_id = client.resolve_course_id(course)
        record = client.get_record("Courses", record_id)
        if record is None:
            print_error(f"Course not found: {course}")
            raise typer.Exit(1)
        current = record.get("fields", {})

        platform = current.get("Platform")
        if platform != "Pluralsight":
            print_error(
                f"sync-requirements is Pluralsight-only; {course} has Platform={platform!r}. "
                "A Udemy course has no Curriculum-supplied requirements."
            )
            raise typer.Exit(1)

        override_state = current_state(current)
        if override_state in {FEEDBACK_RESYNCED, OVERRIDE_AUTHORIZED}:
            print_error(
                "sync-requirements cannot run while the learning-objective override "
                f"lifecycle is in state {override_state!r}. Complete the current "
                "transition before starting another Curriculum resync."
            )
            raise typer.Exit(1)

        if override_state == CORRECTION_REQUESTED:
            print_error(
                "Correction Requested can transition only after the external return is "
                "recorded with mark-requirements-update-received."
            )
            raise typer.Exit(1)

        link = current.get("Course Requirements Link")
        if not link:
            print_error(
                f"{course} has no Course Requirements Link. The phase cannot run "
                "without the document; set the link and re-run."
            )
            raise typer.Exit(1)

        doc_id = extract_doc_id(link)
        outline_text = normalize_document(read_document_text(doc_id))

        try:
            parsed = parse_outline(outline_text)
        except OutlineParseError as exc:
            print_error(
                f"{course}: {exc} This is a defect in the DOCUMENT, not in the sync. "
                "Report it to Curriculum rather than editing around it."
            )
            raise typer.Exit(1)

        # Course ID is the record's identity. Curriculum's doc carries the base slug while a
        # course update carries -vN, so an existing value is never overwritten.
        parsed_slug = parsed.pop("Course ID", None)
        if not current.get("Course ID") and parsed_slug:
            parsed["Course ID"] = parsed_slug

        fields = dict(parsed)
        fields["Course Requirements"] = outline_text
        predicted_version = None
        if override_state in {UPDATE_RECEIVED, OVERRIDE_ACTIVE}:
            before_snapshot = content_snapshot(current)
            before_version = current_requirements_version(current)
            predicted_version = predicted_requirements_version(current, outline_text)

            if override_state == OVERRIDE_ACTIVE:
                # Once authorized and applied, Curriculum resyncs cannot silently
                # replace the canonical override. Every other parsed field still syncs.
                fields.pop(OBJECTIVES_FIELD, None)
                event_type = "requirements_resynced_override_active"
                next_state = OVERRIDE_ACTIVE
            else:
                event_type = "feedback_resynced"
                next_state = FEEDBACK_RESYNCED

            after_snapshot = {
                "courseRequirements": outline_text,
                "learningObjectives": (
                    before_snapshot["learningObjectives"]
                    if override_state == OVERRIDE_ACTIVE
                    else str(parsed.get(OBJECTIVES_FIELD) or "")
                ),
            }
            event = {
                "type": event_type,
                "at": now_iso(),
                "before": {
                    "requirementsVersion": before_version,
                    "requirementsVersionIdentity": version_identity(before_version),
                    "snapshot": before_snapshot,
                },
                "after": {
                    "requirementsVersion": predicted_version,
                    "requirementsVersionIdentity": version_identity(predicted_version),
                    "snapshot": after_snapshot,
                },
            }
            fields[STATE_FIELD] = next_state
            fields[AUDIT_FIELD] = append_audit(current, event)
            fields[REVIEW_FIELD] = ""
        if dry_run:
            print_json({
                "mode": "sync-requirements",
                "dry_run": True,
                "course": {"id": record_id, "course_id": current.get("Course ID")},
                "doc_id": doc_id,
                "requirements_characters": len(outline_text),
                "course_id_write_skipped": bool(current.get("Course ID")) and parsed_slug is not None,
                "fields_would_write": {
                    key: (
                        f"<{len(value)} characters>"
                        if key in {"Course Requirements", AUDIT_FIELD}
                        else value
                    )
                    for key, value in fields.items()
                },
                "override_state_before": override_state or None,
                "override_state_after": fields.get(STATE_FIELD, override_state or None),
                "requirements_version_after": predicted_version,
            })
            raise typer.Exit(0)

        client.update_record("Courses", record_id, fields)

        readback = client.get_record("Courses", record_id).get("fields", {})
        mismatches = [
            key for key, value in fields.items()
            if not (value == "" and readback.get(key) in (None, ""))
            and readback.get(key) != value
        ]
        if predicted_version is not None:
            try:
                persisted_version = current_requirements_version(readback)
            except ObjectiveOverrideError as exc:
                print_error(str(exc))
                raise typer.Exit(1)
            if persisted_version != predicted_version:
                mismatches.append("Version Control/course.requirements")
        if mismatches:
            print_error(
                "sync-requirements wrote but these fields did not persist as sent: "
                + ", ".join(mismatches)
            )
            raise typer.Exit(1)

        print_success(f"Synced Pluralsight course requirements into {record_id}")
        print_json({
            "mode": "sync-requirements",
            "dry_run": False,
            "course": {"id": record_id, "course_id": readback.get("Course ID")},
            "doc_id": doc_id,
            "requirements_characters": len(outline_text),
            "fields_written": sorted(fields),
            "status": readback.get("Status"),
            "override_state": readback.get(STATE_FIELD),
            "requirements_version": predicted_version,
        })
    except (ClientError, ObjectiveOverrideError) as exc:
        print_error(str(exc))
        raise typer.Exit(1)


@app.command("scaffold")
@command
def courses_scaffold(
    course_slug: Optional[str] = typer.Option(
        None, "--course-slug", "-c", help="Existing CourseCraft Course ID slug"
    ),
    google_docs_link: Optional[str] = typer.Option(
        None, "--google-docs-link", help="Approved Google Docs outline URL"
    ),
    file_path: Optional[str] = typer.Option(
        None, "--file-path", "-f", help="Approved outline PDF path"
    ),
    base: Optional[str] = typer.Option(
        None, "--base",
        help="Intake touch: record ID or slug of the completed course this update follows",
    ),
    legacy_import_base: bool = typer.Option(
        False,
        "--legacy-import-base",
        help=(
            "Allow a non-Complete base only after proving it is a shipped "
            "pre-CourseCraft Pluralsight import"
        ),
    ),
    deadline: Optional[str] = typer.Option(
        None,
        "--deadline",
        help="Optional CourseCraft course deadline to write (YYYY-MM-DD)",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Parse and plan only: report what WOULD be created, creating nothing",
    ),
):
    """Scaffold a course from its approved outline (records plus course folder).

    Dispatches the CourseCraft scaffolder, which parses the approved outline and
    creates or verifies the Course, Module, and Clip records plus the course
    folder. Its JSON report goes to stdout and its exit code passes through.

    With --base this is instead the course-update INTAKE touch: no outline is read,
    and it creates only the new Course record (Version, -vN slug, Base Course link,
    inherited basics) plus its course folder. The base course must be Complete unless
    --legacy-import-base proves a shipped pre-CourseCraft Pluralsight predecessor.
    """
    if base is not None:
        if course_slug or google_docs_link or file_path:
            print_error(
                "--base is the intake touch and takes no outline input. Drop "
                "--course-slug/--google-docs-link/--file-path, or drop --base."
            )
            raise typer.Exit(1)
        try:
            raise typer.Exit(
                _scaffold_intake(
                    get_client(), base, deadline, dry_run, legacy_import_base
                )
            )
        except ClientError as e:
            print_error(str(e))
            raise typer.Exit(1)

    if legacy_import_base:
        print_error("--legacy-import-base requires --base.")
        raise typer.Exit(1)

    args = script_flags([
        ("--deadline", deadline),
        ("--course-slug", course_slug),
        ("--google-docs-link", google_docs_link),
        ("--file-path", file_path),
        ("--dry-run", dry_run),
    ])
    raise typer.Exit(
        run_coursecraft_script(
            SCAFFOLD_SCRIPT, args,
            timeout=SCAFFOLD_TIMEOUT_SECONDS,
            # A bash script, so the python3 default interpreter does not apply.
            interpreter=["bash"],
        )
    )


COMMAND_CREDENTIALS = {
    "create": [
        "custom"
    ],
    "scaffold": [
        "custom"
    ],
    "sync-requirements": [
        "custom"
    ],
    "mark-requirements-update-received": ["custom"],
    "submit-outline-for-review": ["custom"],
    "mark-outline-changes-requested": ["custom"],
    "mark-outline-approved": ["custom"],
    "request-objective-correction": [
        "custom"
    ],
    "authorize-objective-override": [
        "custom"
    ],
    "apply-objective-override": [
        "custom"
    ],
    "delete": [
        "custom"
    ],
    "disable": [
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
