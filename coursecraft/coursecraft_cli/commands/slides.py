"""Slides command module."""
import json
import typer
from typing import Optional, List, Dict
from pathlib import Path

from ..client import get_client, ClientError
from ..output import print_success, print_error, print_info, print_json, print_table, print_mandatory_review
from ..filter_map import translate_filters
from ..filters import apply_properties_filter, apply_limit
from ..voice_recording_fields import get_voice_recording_invalidation_fields

app = typer.Typer(help="Manage slide records")


@app.command("create")
def create_slide(
    clip: str = typer.Option(..., "--clip", "-c", help="Clip record ID (required)"),
    template: Optional[str] = typer.Option(None, "--template", "-t", help="Slide template record ID"),
    target_length: Optional[float] = typer.Option(None, "--target-length", "-l", help="Target length in minutes (e.g., 0.5)"),
    slides_json: Optional[str] = typer.Option(None, "--json", help="Inline JSON array of slides (batch mode)"),
    slides_file: Optional[Path] = typer.Option(None, "--file", help="Path to JSON file with slide definitions"),
):
    """
    Create slide record(s) in Airtable linked to a clip.

    Supports two modes:
    1. Single slide mode: Use --template to create one slide
    2. Batch mode: Use --json or --file to create multiple slides

    Examples:
        # Single slide
        coursecraft slides create --clip recXXX --template recTEMPLATE

        # Batch from inline JSON
        coursecraft slides create --clip recXXX --json '[{"template":"recT1"},{"template":"recT2"}]'

        # Batch from file
        coursecraft slides create --clip recXXX --file slides.json
    """
    try:
        client = get_client()

        # Determine mode: batch or single
        if slides_file or slides_json:
            # Batch mode
            json_data = None
            if slides_file:
                if not slides_file.exists():
                    print_error(f"File not found: {slides_file}")
                    raise typer.Exit(1)
                json_data = slides_file.read_text()
            elif slides_json:
                json_data = slides_json

            if json_data:
                try:
                    slides_list = json.loads(json_data)
                    print_info(f"Creating {len(slides_list)} slide(s)...")

                    created_ids = []
                    for slide_data in slides_list:
                        # Check if slide with same template already exists in this clip
                        template_id = slide_data.get("template")
                        if template_id:
                            existing_id = client.check_slide_exists(clip, template_id)
                            if existing_id:
                                print_error(f"Slide with template '{template_id}' already exists in this clip: {existing_id}")
                                raise typer.Exit(1)

                        # Build slide fields
                        fields = {
                            "Clip": [clip],
                        }

                        # Add optional template field
                        if template_id:
                            fields["Template"] = [template_id]

                        # Add target length from JSON or CLI
                        if "target_length" in slide_data:
                            fields["Target Length (Min)"] = slide_data["target_length"]
                        elif target_length is not None:
                            fields["Target Length (Min)"] = target_length

                        # Create the slide
                        slide_record_id = client.create_record("Slides", fields)
                        print_success(f"Created slide: {slide_record_id}")
                        created_ids.append(slide_record_id)

                    # Output all created IDs as JSON array for scripting
                    typer.echo(json.dumps(created_ids))

                except json.JSONDecodeError as e:
                    print_error(f"Invalid JSON: {e}")
                    raise typer.Exit(1)
        else:
            # Single slide mode
            # Check if slide with same template already exists in this clip
            if template:
                existing_id = client.check_slide_exists(clip, template)
                if existing_id:
                    print_error(f"Slide with template '{template}' already exists in this clip: {existing_id}")
                    raise typer.Exit(1)

            # Build fields dictionary
            fields = {
                "Clip": [clip],
            }

            # Add optional template field
            if template:
                fields["Template"] = [template]

            # Add target length
            if target_length is not None:
                fields["Target Length (Min)"] = target_length

            # Create the slide
            record_id = client.create_record("Slides", fields)
            print_success(f"Created slide: {record_id}")

            # Output the record ID for scripting
            typer.echo(record_id)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("list")
def list_slides(
    clip: Optional[str] = typer.Option(None, "--clip", "-c", help="Filter by clip record ID"),
    module: Optional[str] = typer.Option(None, "--module", "-m", help="Filter by module record ID (gets all slides in module)"),
    course: Optional[str] = typer.Option(None, "--course", help="Filter by course slug or record ID (gets all slides in course)"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum number of records to return"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of properties to include (supports dot notation)"),
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

        if filter and convenience_options > 0:
            print_error("Cannot use --filter with convenience options (--clip, --module, --course)")
            raise typer.Exit(1)

        # Get records based on filter type
        if course:
            # Hierarchical query: get all slides in course
            records = client.get_slides_by_course(course)
        elif module:
            # Hierarchical query: get all slides in module
            records = client.get_slides_by_module(module)
        elif clip:
            formula = f"{{Clip Record ID}}='{clip}'"
            records = client.list_records("Slides", formula)
        elif filter:
            formula = translate_filters(list(filter), 'Slides')
            records = client.list_records("Slides", formula)
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
def get_slide(
    record_id: str = typer.Argument(..., help="Slide record ID"),
    table_output: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Get a single slide record by ID.

    Examples:
        coursecraft slides get recXXXXXXXXXXXXXXX
        coursecraft slides get recXXXXXXXXXXXXXXX --table
    """
    try:
        client = get_client()
        record = client.get_record("Slides", record_id)

        if not record:
            print_error(f"Slide not found: {record_id}")
            raise typer.Exit(1)

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
def update_slide(
    record_id: str = typer.Argument(..., help="Slide record ID"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Slide name"),
    template: Optional[str] = typer.Option(None, "--template", "-t", help="Slide template record ID"),
    clip: Optional[str] = typer.Option(None, "--clip", "-c", help="Parent clip record ID (re-parent slide to a different clip)"),
    clip_order: Optional[int] = typer.Option(None, "--clip-order", "-o", help="Order within the clip (e.g., 1, 2, 3)"),
    target_length: Optional[float] = typer.Option(None, "--target-length", "-l", help="Target length in minutes (e.g., 0.5)"),
    script: Optional[str] = typer.Option(None, "--script", "-s", help="Slide script text"),
    build_instructions: Optional[str] = typer.Option(None, "--build-instructions", "-b", help="Build instructions for the slide"),
    built: Optional[bool] = typer.Option(None, "--built/--no-built", help="Slide built checkbox"),
    dictation_recorded: Optional[bool] = typer.Option(None, "--dictation-recorded/--no-dictation-recorded", help="Mark slide dictation audio as recorded"),
    recorded: Optional[bool] = typer.Option(None, "--recorded/--no-recorded", help="Mark slide as recorded"),
    status: Optional[str] = typer.Option(None, "--status", help="Slide status (e.g., 'Ready to Build', 'Complete')"),
    demo: Optional[str] = typer.Option(None, "--demo", "-d", help="Demo record ID (for demo intro slides)"),
):
    """
    Update a slide record.

    Examples:
        coursecraft slides update recXXX --template recTEMPLATE
        coursecraft slides update recXXX --clip-order 2
        coursecraft slides update recXXX --clip recCLIPID
        coursecraft slides update recXXX --name "Demo Intro: Setup Demo"
        coursecraft slides update recXXX --script "In this demo, we will..."
        coursecraft slides update recXXX --build-instructions "Configure the API connection"
        coursecraft slides update recXXX --built
        coursecraft slides update recXXX --no-built
        coursecraft slides update recXXX --dictation-recorded
        coursecraft slides update recXXX --recorded
        coursecraft slides update recXXX --status "Complete"
        coursecraft slides update recXXX --demo recDEMOID
    """
    try:
        client = get_client()

        # Verify record exists
        existing = client.get_record("Slides", record_id)
        if not existing:
            print_error(f"Slide not found: {record_id}")
            raise typer.Exit(1)

        # Build fields dictionary with only provided values
        fields = {}
        if name is not None:
            fields["Name"] = name
        if template is not None:
            fields["Template"] = [template]
        if clip is not None:
            fields["Clip"] = [clip]
        if clip_order is not None:
            fields["Clip Order"] = clip_order
        if target_length is not None:
            fields["Target Length (Min)"] = target_length
        if script is not None:
            fields["Script"] = script
            fields.update(get_voice_recording_invalidation_fields())
        if build_instructions is not None:
            fields["Build Instructions"] = build_instructions
        if built is not None:
            fields["Built"] = built
        if dictation_recorded is not None:
            fields["Dictation Recorded"] = dictation_recorded
        if recorded is not None:
            fields["Recorded"] = recorded
        if status is not None:
            fields["Status"] = status
        if demo is not None:
            fields["Demo"] = [demo]

        if not fields:
            print_error("No fields to update. Provide at least one field option.")
            raise typer.Exit(1)

        # Update the record
        updated = client.update_record("Slides", record_id, fields)
        print_success(f"Updated slide: {record_id}")

        # Check for sync warnings
        existing_fields = existing.get("fields", {})
        existing_script = existing_fields.get("Script", "")
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
