"""Slides command module."""
import json
import typer
from typing import Optional, List, Dict
from pathlib import Path

from cli_tools_shared.filters import apply_limit
from cli_tools_shared.output import command
from ..batch import load_batch_payload
from ..client import get_client, ClientError
from ..output import apply_properties_filter, project_record, print_success, print_error, print_info, print_json, print_table, print_mandatory_review
from ..filter_translator import translate_filters
from ..field_mappings import validate_field
from ..voice_recording_fields import get_slide_narration_invalidation_fields

app = typer.Typer(help="Manage slide records")

# The AI review paired with a slide's Script, cleared whenever the Script it
# reviewed actually changes (matches the demos.py content/review pairing).
# Resolved through field_mappings.py so the Airtable field name has one home.
SCRIPT_REVIEW_AI_FIELD = validate_field("script_review_ai", "Slides")


def _create_one_slide(
    client,
    clip: str,
    *,
    template: Optional[str] = None,
    clip_order: Optional[int] = None,
    demo: Optional[str] = None,
    target_length: Optional[float] = None,
    notes: Optional[str] = None,
) -> str:
    """
    Create one slide, refusing an exact (clip, template, clip order) duplicate.

    The guard is for idempotency on re-runs only. A clip may hold several slides
    built from one template as long as their clip orders differ, so two demos in
    a clip can each get their own Demo Intro slide from the one Demo Intro
    template.
    """
    existing_id = client.check_slide_exists(clip, template, clip_order)
    if existing_id:
        template_display = template if template else "(none)"
        order_display = clip_order if clip_order is not None else "(none)"
        print_error(
            f"Slide with template '{template_display}' at clip order {order_display} "
            f"already exists in this clip: {existing_id}"
        )
        raise typer.Exit(1)

    fields: Dict = {
        "Clip": [clip],
    }
    if template:
        fields["Template"] = [template]
    if clip_order is not None:
        fields["Clip Order"] = clip_order
    if demo:
        fields["Demo"] = [demo]
    if target_length is not None:
        fields["Target Length (Min)"] = target_length
    if notes is not None:
        fields["Notes"] = notes

    record_id = client.create_record("Slides", fields)
    print_success(f"Created slide: {record_id}")
    return record_id


@app.command("create")
@command
def create_slide(
    clip: str = typer.Option(..., "--clip", "-c", help="Clip record ID (required)"),
    template: Optional[str] = typer.Option(None, "--template", "-t", help="Slide template record ID"),
    clip_order: Optional[int] = typer.Option(None, "--clip-order", "-o", help="Order within the clip (e.g., 1, 2, 3)"),
    demo: Optional[str] = typer.Option(None, "--demo", "-d", help="Demo record ID (for demo intro slides)"),
    target_length: Optional[float] = typer.Option(None, "--target-length", "-l", help="Target length in minutes (e.g., 0.5)"),
    notes: Optional[str] = typer.Option(None, "--notes", help="Internal notes"),
    slides_json: Optional[str] = typer.Option(None, "--json", help="Inline JSON array of slides (batch mode)"),
    slides_file: Optional[Path] = typer.Option(None, "--file", help="Path to JSON file with slide definitions"),
):
    """
    Create slide record(s) in Airtable linked to a clip.

    Supports two modes:
    1. Single slide mode: Use --template to create one slide
    2. Batch mode: Use --json or --file to create multiple slides

    A slide is a duplicate only when its clip, template, AND clip order all match
    an existing slide, so one clip can hold several slides from the same template
    at different clip orders (two demos need two Demo Intro slides).

    In batch mode the per-slide JSON keys "template", "clip_order", "demo",
    "target_length", and "notes" set each slide's values; "clip_order", "demo",
    "target_length", and "notes" fall back to the matching CLI option when the
    key is absent.

    Examples:
        # Single slide
        coursecraft slides create --clip recXXX --template recTEMPLATE

        # Single slide placed in the clip and linked to its demo
        coursecraft slides create --clip recXXX --template recTEMPLATE --clip-order 3 --demo recDEMO

        # Batch from inline JSON
        coursecraft slides create --clip recXXX --json '[{"template":"recT1","clip_order":1},{"template":"recT2","clip_order":2}]'

        # Batch from file
        coursecraft slides create --clip recXXX --file slides.json
    """
    try:
        client = get_client()

        # Determine mode: batch or single
        if slides_file or slides_json:
            # Batch mode
            slides_list = load_batch_payload(slides_json, slides_file)

            print_info(f"Creating {len(slides_list)} slide(s)...")

            created_ids = []
            for slide_data in slides_list:
                created_ids.append(
                    _create_one_slide(
                        client,
                        clip,
                        # --template is not a batch default; each slide names its own
                        template=slide_data.get("template"),
                        clip_order=slide_data.get("clip_order", clip_order),
                        demo=slide_data.get("demo", demo),
                        target_length=slide_data.get("target_length", target_length),
                        notes=slide_data.get("notes", notes),
                    )
                )

            # Output all created IDs as JSON array for scripting
            typer.echo(json.dumps(created_ids))
        else:
            # Single slide mode
            record_id = _create_one_slide(
                client,
                clip,
                template=template,
                clip_order=clip_order,
                demo=demo,
                target_length=target_length,
                notes=notes,
            )

            # Output the record ID for scripting
            typer.echo(record_id)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("list")
@command
def list_slides(
    clip: Optional[str] = typer.Option(None, "--clip", "-c", help="Filter by clip record ID"),
    module: Optional[str] = typer.Option(None, "--module", "-m", help="Filter by module record ID (gets all slides in module)"),
    course: Optional[str] = typer.Option(None, "--course", help="Filter by course slug or record ID (gets all slides in course)"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum number of records to return"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Property to include (supports dot notation). Repeatable; each value may also be comma-separated."),
    table_output: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    List slide records.

    Examples:
        # List all slides
        coursecraft slides list

        # List slides for a clip
        coursecraft slides list --clip recXXX

        # List slides for a module (all clips in module)
        coursecraft slides list --module recXXX

        # List slides for a course (all slides in course)
        coursecraft slides list --course advanced-features-cursor-ai

        # List with standard filter
        coursecraft slides list --filter "name:contains:intro"

        # Combine a convenience option with --filter (AND-ed together)
        coursecraft slides list --course advanced-features-cursor-ai --filter "name:contains:intro"

        # List with table output
        coursecraft slides list --clip recXXX --table

        # Limit results
        coursecraft slides list --limit 10

        # Select specific properties
        coursecraft slides list --properties "id,fields.Template"
    """
    try:
        client = get_client()

        # Count how many convenience options are used
        convenience_options = sum(1 for opt in [clip, module, course] if opt is not None)
        if convenience_options > 1:
            print_error("Cannot use multiple convenience options (--clip, --module, --course) together")
            raise typer.Exit(1)

        # --filter combines with a convenience option (AND-ed together), the
        # same pattern list_modules uses for --course + --filter.
        filter_formula = translate_filters(list(filter), 'Slides') if filter else None

        # Get records based on filter type
        if course:
            # Hierarchical query: get all slides in course, optionally AND-ed with --filter
            records = client.get_slides_by_course(course, filter_formula=filter_formula)
        elif module:
            # Hierarchical query: get all slides in module, optionally AND-ed with --filter
            records = client.get_slides_by_module(module, filter_formula=filter_formula)
        elif clip:
            formula = f"{{Clip Record ID}}='{clip}'"
            if filter_formula:
                formula = f"AND({formula},{filter_formula})"
            records = client.list_records("Slides", formula)
        elif filter:
            records = client.list_records("Slides", filter_formula)
        else:
            records = client.list_records("Slides", None)

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
                # Get template name if linked
                template = fields.get("Template", [])
                template_display = template[0] if template else ""
                rows.append({
                    "id": rec["id"],
                    "template": template_display,
                })
            print_table(rows, ["id", "template"],
                       ["Record ID", "Template"])
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
def get_slide(
    record_id: str = typer.Argument(..., help="Slide record ID"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Property to include (supports dot notation). Repeatable; each value may also be comma-separated."),
    table_output: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Get a single slide record by ID.

    Examples:
        coursecraft slides get recXXXXXXXXXXXXXXX
        coursecraft slides get recXXXXXXXXXXXXXXX --properties "id,fields.Name"
        coursecraft slides get recXXXXXXXXXXXXXXX --table
    """
    try:
        client = get_client()
        record = client.get_record("Slides", record_id)

        if not record:
            print_error(f"Slide not found: {record_id}")
            raise typer.Exit(1)

        if properties and not table_output:
            record = project_record(record, properties)

        if table_output:
            fields = record.get("fields", {})
            template = fields.get("Template", [])
            template_display = template[0] if template else ""
            clip = fields.get("Clip", [])
            clip_display = clip[0] if clip else ""
            rows = [{
                "id": record["id"],
                "clip": clip_display,
                "template": template_display,
            }]
            print_table(rows, ["id", "clip", "template"],
                       ["Record ID", "Clip", "Template"])
        else:
            print_json(record)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("update")
@command
def update_slide(
    record_id: str = typer.Argument(..., help="Slide record ID"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Slide name"),
    template: Optional[str] = typer.Option(None, "--template", "-t", help="Slide template record ID"),
    clear_template: bool = typer.Option(False, "--clear-template", help="Clear the linked Template field (leave the slide with no template)"),
    clip: Optional[str] = typer.Option(None, "--clip", "-c", help="Parent clip record ID (re-parent slide to a different clip); pass \"\" to unlink the slide from its clip"),
    clip_order: Optional[int] = typer.Option(None, "--clip-order", "-o", help="Order within the clip (e.g., 1, 2, 3)"),
    target_length: Optional[float] = typer.Option(None, "--target-length", "-l", help="Target length in minutes (e.g., 0.5)"),
    notes: Optional[str] = typer.Option(None, "--notes", help="Internal notes"),
    script: Optional[str] = typer.Option(None, "--script", "-s", help="Slide script text"),
    build_instructions: Optional[str] = typer.Option(None, "--build-instructions", "-b", help="Build instructions for the slide"),
    built: Optional[bool] = typer.Option(None, "--built/--no-built", help="Slide built checkbox"),
    dictation_recorded: Optional[bool] = typer.Option(None, "--dictation-recorded/--no-dictation-recorded", help="Mark slide dictation audio as recorded"),
    recorded: Optional[bool] = typer.Option(None, "--recorded/--no-recorded", help="Mark slide as recorded"),
    slide_type_human_verified: Optional[bool] = typer.Option(None, "--slide-type-human-verified/--no-slide-type-human-verified", help="Mark the slide's chosen type/template as human-verified"),
    script_human_verified: Optional[bool] = typer.Option(None, "--script-human-verified/--no-script-human-verified", help="Mark the slide's Script as human-verified"),
    script_review_ai: Optional[str] = typer.Option(None, "--script-review-ai", help="AI review verdict of the slide Script (artifact-reviewer only)"),
    demo: Optional[str] = typer.Option(None, "--demo", "-d", help="Demo record ID (for demo intro slides)"),
    feedback_requested: Optional[bool] = typer.Option(None, "--feedback-requested/--no-feedback-requested", help="Set or clear the feedback-requested gate flag"),
    feedback_requested_at: Optional[str] = typer.Option(None, "--feedback-requested-at", help="ISO 8601 timestamp the feedback gate was requested"),
    estimated_length: Optional[float] = typer.Option(None, "--estimated-length", help="Estimated slide length in minutes"),
    clip_slide_narration_complete: Optional[bool] = typer.Option(None, "--clip-slide-narration-complete/--no-clip-slide-narration-complete", help="Set or clear the clip slide-narration-complete flag"),
    base_record: Optional[str] = typer.Option(None, "--base-record", help="Course-update lineage: the slide in the base course version this record derives from"),
):
    """
    Update a slide record.

    Examples:
        coursecraft slides update recXXX --template recTEMPLATE
        coursecraft slides update recXXX --clear-template
        coursecraft slides update recXXX --clip-order 2
        coursecraft slides update recXXX --clip recCLIPID
        coursecraft slides update recXXX --clip ""  # unlink the slide from its clip
        coursecraft slides update recXXX --name "Demo Intro: Setup Demo"
        coursecraft slides update recXXX --script "In this demo, we will..."
        coursecraft slides update recXXX --build-instructions "Configure the API connection"
        coursecraft slides update recXXX --built
        coursecraft slides update recXXX --no-built
        coursecraft slides update recXXX --dictation-recorded
        coursecraft slides update recXXX --recorded
        coursecraft slides update recXXX --slide-type-human-verified
        coursecraft slides update recXXX --no-slide-type-human-verified
        coursecraft slides update recXXX --script-human-verified
        coursecraft slides update recXXX --no-script-human-verified
        coursecraft slides update recXXX --script-review-ai "PASS -- no unmet requirements."
        coursecraft slides update recXXX --demo recDEMOID

    Changing --script or --template/--clear-template to a value that differs
    from what is already saved bumps that slide's Version Control entry and
    auto-clears its paired review fields (a no-op resubmission of identical
    content leaves them untouched, and passing the paired review flag
    explicitly in the same call as a real content change is rejected) -- see
    the coursecraft_cli.artifact_versions write-time versioning engine.
    --script-review-ai is written only by artifact-reviewer after it
    evaluates the Script.
    """
    try:
        if template is not None and clear_template:
            print_error("Cannot use --template with --clear-template. Provide only one.")
            raise typer.Exit(1)

        client = get_client()

        # Verify record exists
        existing = client.get_record("Slides", record_id)
        if not existing:
            print_error(f"Slide not found: {record_id}")
            raise typer.Exit(1)

        existing_fields = existing.get("fields", {})
        existing_script = existing_fields.get("Script") or ""

        # A no-op resubmission (identical content) must not fire the
        # voice-recording invalidation below; only a real content difference
        # does. (Paired review-flag auto-clear/mutual-exclusion is now owned
        # by the write-time versioning engine in client.py.)
        script_changed = script is not None and script.strip() != existing_script.strip()

        # Build fields dictionary with only provided values
        fields = {}
        if name is not None:
            fields["Name"] = name
        if template is not None:
            fields["Template"] = [template]
        if clear_template:
            fields["Template"] = []
        if clip is not None:
            # An empty string is the explicit "unlink" sentinel: send an empty
            # linked-record array instead of a single-element list containing
            # "", which Airtable rejects as an invalid record ID.
            fields["Clip"] = [clip] if clip else []
        if clip_order is not None:
            fields["Clip Order"] = clip_order
        if target_length is not None:
            fields["Target Length (Min)"] = target_length
        if notes is not None:
            fields["Notes"] = notes
        if script is not None:
            fields["Script"] = script
            # A no-op resubmission (identical, only-whitespace-differing
            # content) must not clear Dictation Recorded; only a real content
            # difference does.
            if script_changed:
                fields.update(get_slide_narration_invalidation_fields())
        if build_instructions is not None:
            fields["Build Instructions"] = build_instructions
        if built is not None:
            fields["Built"] = built
        if dictation_recorded is not None:
            fields["Dictation Recorded"] = dictation_recorded
        if recorded is not None:
            fields["Recorded"] = recorded
        if slide_type_human_verified is not None:
            fields["Slide Type Human Verified"] = slide_type_human_verified
        if script_human_verified is not None:
            fields["Script Human Verified"] = script_human_verified
        if script_review_ai is not None:
            fields[SCRIPT_REVIEW_AI_FIELD] = script_review_ai
        if demo is not None:
            fields["Demo"] = [demo]
        if feedback_requested is not None:
            fields["Feedback Requested"] = feedback_requested
        if feedback_requested_at is not None:
            fields["Feedback Requested At"] = feedback_requested_at

        if estimated_length is not None:
            fields["Estimated Length"] = estimated_length
        if clip_slide_narration_complete is not None:
            fields["Clip Slide Narration Complete"] = clip_slide_narration_complete
        if base_record is not None:
            fields["Base Record"] = [base_record]

        if not fields:
            print_error("No fields to update. Provide at least one field option.")
            raise typer.Exit(1)

        # Airtable rejects the whole write when a field name does not exist, so
        # a missing paired review field fails loudly instead of silently
        # skipping the clear.
        try:
            client.update_record("Slides", record_id, fields)
        except ClientError as e:
            if SCRIPT_REVIEW_AI_FIELD in fields and "Unknown field name" in str(e):
                print_error(
                    f"The Slides table has no {SCRIPT_REVIEW_AI_FIELD!r} field, so "
                    f"this Script change cannot clear its paired AI review. Add "
                    f"{SCRIPT_REVIEW_AI_FIELD!r} to the Slides table (exact name), "
                    f"then retry. Nothing was written. Airtable said: {e}"
                )
                raise typer.Exit(1)
            raise
        print_success(f"Updated slide: {record_id}")

        # Check for sync warnings
        existing_build_instructions = existing_fields.get("Build Instructions", "")

        if build_instructions is not None and existing_script:
            print_mandatory_review(
                title="Script",
                action="Update the Script to match the new Build Instructions",
                reason="Build Instructions changed - Script must reflect the updated slide content",
                preview=existing_script,
            )

        if script is not None and existing_build_instructions:
            print_mandatory_review(
                title="Build Instructions",
                action="Verify Build Instructions match the updated Script",
                reason="Script changed - Build Instructions must document the same content",
                preview=existing_build_instructions,
            )

        # Output the record ID for scripting
        typer.echo(record_id)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("delete")
@command
def delete_slide(
    record_id: str = typer.Argument(..., help="Slide record ID"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
):
    """
    Delete a slide record.

    This action is PERMANENT and cannot be undone.

    Examples:
        # Delete with confirmation prompt
        coursecraft slides delete recXXXXXXXXXXXXXXX

        # Delete without confirmation (for scripting)
        coursecraft slides delete recXXXXXXXXXXXXXXX --force
    """
    try:
        client = get_client()

        # Verify record exists
        record = client.get_record("Slides", record_id)
        if not record:
            print_error(f"Slide not found: {record_id}")
            raise typer.Exit(1)

        # Confirm deletion
        if not force:
            if not typer.confirm(f"Are you sure you want to delete slide '{record_id}'?"):
                print_info("Deletion cancelled.")
                raise typer.Exit(0)

        # Delete the record
        client.delete_record("Slides", record_id)
        print_success(f"Deleted slide: {record_id}")

        # Output the deleted ID for scripting
        typer.echo(record_id)

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
