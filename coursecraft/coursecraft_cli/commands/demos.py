"""Demos command module."""
import json
import typer
from typing import Optional, List, Dict
from pathlib import Path

from ..client import get_client, ClientError
from ..output import print_success, print_error, print_info, print_json, print_table, print_mandatory_review
from ..filter_map import translate_filters
from ..filters import apply_properties_filter, apply_limit
from ..voice_recording_fields import get_voice_recording_invalidation_fields

app = typer.Typer(help="Manage demo records")


@app.command("create")
def create_demo(
    clip: str = typer.Option(..., "--clip", "-c", help="Clip record ID (required)"),
    clip_order: int = typer.Option(..., "--clip-order", "-o", help="Order within the clip (required, e.g., 1, 2, 3)"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Demo name"),
    target_length: Optional[float] = typer.Option(None, "--target-length", "-l", help="Target length in minutes (e.g., 2.5)"),
    action_summary: Optional[str] = typer.Option(None, "--action-summary", "-a", help="Action summary for the demo"),
    script: Optional[str] = typer.Option(None, "--script", "-s", help="Demo script"),
    demo_environment: Optional[List[str]] = typer.Option(None, "--demo-environment", help="Required demo environment record ID, Environment ID, or exact Name. Repeat to link multiple environments."),
    demos_json: Optional[str] = typer.Option(None, "--json", help="Inline JSON array of demos (batch mode)"),
    demos_file: Optional[Path] = typer.Option(None, "--file", help="Path to JSON file with demo definitions"),
):
    """
    Create demo record(s) in Airtable linked to a clip.

    Supports two modes:
    1. Single demo mode: Use optional fields to create one demo
    2. Batch mode: Use --json or --file to create multiple demos

    The --clip-order is required and specifies the position of the demo within the clip,
    alongside slides which also have a clip order.

    Examples:
        # Single demo
        coursecraft demos create --clip recXXX --clip-order 1 --name "Setup Demo" --demo-environment local-macos

        # Batch from inline JSON (clip_order required in each object)
        coursecraft demos create --clip recXXX --clip-order 1 --demo-environment local-macos --json '[{"name":"Demo 1","clip_order":1},{"name":"Demo 2","clip_order":2}]'

        # Batch from file
        coursecraft demos create --clip recXXX --clip-order 1 --file demos.json
    """
    try:
        client = get_client()
        if not demo_environment:
            print_error("--demo-environment is required")
            raise typer.Exit(1)
        demo_environment_record_ids = [
            client.resolve_environment_id(environment)
            for environment in demo_environment
        ]

        # Determine mode: batch or single
        if demos_file or demos_json:
            # Batch mode
            json_data = None
            if demos_file:
                if not demos_file.exists():
                    print_error(f"File not found: {demos_file}")
                    raise typer.Exit(1)
                json_data = demos_file.read_text()
            elif demos_json:
                json_data = demos_json

            if json_data:
                try:
                    demos_list = json.loads(json_data)
                    print_info(f"Creating {len(demos_list)} demo(s)...")

                    created_ids = []
                    for demo_data in demos_list:
                        # Check if demo name already exists in this clip
                        demo_name = demo_data.get("name")
                        if demo_name:
                            existing_id = client.check_demo_exists(demo_name, clip)
                            if existing_id:
                                print_error(f"Demo with name '{demo_name}' already exists in this clip: {existing_id}")
                                raise typer.Exit(1)

                        # Get clip_order from JSON or use CLI argument
                        demo_clip_order = demo_data.get("clip_order", clip_order)

                        # Build demo fields
                        fields = {
                            "Clip": [clip],
                            "Clip Order": demo_clip_order,
                            "Demo Environment": demo_environment_record_ids,
                        }

                        # Add optional fields
                        if demo_name:
                            fields["Name"] = demo_name
                        if "target_length" in demo_data:
                            fields["Target Length (Min)"] = demo_data["target_length"]
                        elif target_length is not None:
                            fields["Target Length (Min)"] = target_length
                        if "action_summary" in demo_data:
                            fields["Action Summary"] = demo_data["action_summary"]
                        if "script" in demo_data:
                            fields["Script"] = demo_data["script"]

                        # Create the demo
                        demo_record_id = client.create_record("Demos", fields)
                        display_name = demo_data.get("name", "demo")
                        print_success(f"Created demo '{display_name}': {demo_record_id}")
                        created_ids.append(demo_record_id)

                    # Output all created IDs as JSON array for scripting
                    typer.echo(json.dumps(created_ids))

                except json.JSONDecodeError as e:
                    print_error(f"Invalid JSON: {e}")
                    raise typer.Exit(1)
        else:
            # Single demo mode
            # Check if demo name already exists in this clip
            if name:
                existing_id = client.check_demo_exists(name, clip)
                if existing_id:
                    print_error(f"Demo with name '{name}' already exists in this clip: {existing_id}")
                    raise typer.Exit(1)

            # Build fields dictionary
            fields = {
                "Clip": [clip],
                "Clip Order": clip_order,
                "Demo Environment": demo_environment_record_ids,
            }

            # Add optional fields
            if name:
                fields["Name"] = name
            if target_length is not None:
                fields["Target Length (Min)"] = target_length
            if action_summary:
                fields["Action Summary"] = action_summary
            if script:
                fields["Script"] = script

            # Create the demo
            record_id = client.create_record("Demos", fields)
            display_name = name if name else "demo"
            print_success(f"Created demo '{display_name}': {record_id}")

            # Output the record ID for scripting
            typer.echo(record_id)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("list")
def list_demos(
    clip: Optional[str] = typer.Option(None, "--clip", "-c", help="Filter by clip record ID"),
    module: Optional[str] = typer.Option(None, "--module", "-m", help="Filter by module record ID (gets all demos in module)"),
    course: Optional[str] = typer.Option(None, "--course", help="Filter by course slug or record ID (gets all demos in course)"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum number of records to return"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of properties to include (supports dot notation)"),
    table_output: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    List demo records.

    Examples:
        # List all demos
        coursecraft demos list

        # List demos for a clip
        coursecraft demos list --clip recXXX

        # List demos for a module (all clips in module)
        coursecraft demos list --module recXXX

        # List demos for a course (all demos in course)
        coursecraft demos list --course advanced-features-cursor-ai

        # List with standard filter
        coursecraft demos list --filter "status:eq:Complete"

        # Filter by name pattern
        coursecraft demos list --filter "fields.Name:startswith:M1"
        coursecraft demos list --filter "fields.Name:contains:Setup"

        # List with table output
        coursecraft demos list --clip recXXX --table

        # Limit results
        coursecraft demos list --limit 5

        # Select specific properties
        coursecraft demos list --properties "id,fields.Name,fields.Status"
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
            # Hierarchical query: get all demos in course
            records = client.get_demos_by_course(course)
        elif module:
            # Hierarchical query: get all demos in module
            records = client.get_demos_by_module(module)
        elif clip:
            formula = f"{{Clip Record ID}}='{clip}'"
            records = client.list_records("Demos", formula)
        elif filter:
            formula = translate_filters(list(filter), 'Demos')
            records = client.list_records("Demos", formula)
        else:
            records = client.list_records("Demos", None)

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
                    "status": fields.get("Status", ""),
                })
            print_table(rows, ["id", "name", "status"],
                       ["Record ID", "Name", "Status"])
        else:
            print_json(records)

    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("get")
def get_demo(
    record_id: str = typer.Argument(..., help="Demo record ID"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of properties to include (supports dot notation)"),
    table_output: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Get a single demo record by ID.

    Examples:
        coursecraft demos get recXXXXXXXXXXXXXXX
        coursecraft demos get recXXXXXXXXXXXXXXX --properties "id,fields.Name"
        coursecraft demos get recXXXXXXXXXXXXXXX --table
    """
    try:
        client = get_client()
        record = client.get_record("Demos", record_id)

        if not record:
            print_error(f"Demo not found: {record_id}")
            raise typer.Exit(1)

        if properties and not table_output:
            record = apply_properties_filter([record], properties)[0]

        if table_output:
            fields = record.get("fields", {})
            action_summary = fields.get("Action Summary", "")
            rows = [{
                "id": record["id"],
                "name": fields.get("Name", ""),
                "status": fields.get("Status", ""),
                "action_summary": action_summary[:40] + "..." if action_summary and len(action_summary) > 40 else action_summary,
            }]
            print_table(rows, ["id", "name", "status", "action_summary"],
                       ["Record ID", "Name", "Status", "Action Summary"])
        else:
            print_json(record)

    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("update")
def update_demo(
    record_id: str = typer.Argument(..., help="Demo record ID"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Demo name"),
    clip_order: Optional[int] = typer.Option(None, "--clip-order", "-o", help="Order within the clip (e.g., 1, 2, 3)"),
    target_length: Optional[float] = typer.Option(None, "--target-length", "-l", help="Target length in minutes (e.g., 2.5)"),
    action_summary: Optional[str] = typer.Option(None, "--action-summary", "-a", help="Action summary"),
    action_summary_review_ai: Optional[str] = typer.Option(None, "--action-summary-review-ai", help="AI review of the action summary"),
    action_summary_human_review_complete: Optional[bool] = typer.Option(None, "--action-summary-human-review-complete/--no-action-summary-human-review-complete", help="Mark human review of action summary complete"),
    environment_prep_checklist: Optional[str] = typer.Option(None, "--environment-prep-checklist", help="Environment preparation checklist"),
    environment_setup_script_path: Optional[str] = typer.Option(None, "--environment-setup-script-path", help="Absolute path to the env_prep.ps1 script that brings the demo to its starting state"),
    environment_prep_complete: Optional[bool] = typer.Option(None, "--environment-prep-complete/--no-environment-prep-complete", help="Mark environment prep as complete"),
    tested_approved: Optional[bool] = typer.Option(None, "--tested-approved/--no-tested-approved", help="Mark demo as tested and approved"),
    recap: Optional[str] = typer.Option(None, "--recap", help="Demo recap/summary"),
    script: Optional[str] = typer.Option(None, "--script", "-s", help="Demo script"),
    script_review_human: Optional[bool] = typer.Option(None, "--script-review-human/--no-script-review-human", help="Mark script human review as complete"),
    demo_environment: Optional[List[str]] = typer.Option(None, "--demo-environment", help="Demo environment record ID, Environment ID, or exact Name. Repeat to link multiple environments."),
    demo_walkthrough_script_path: Optional[str] = typer.Option(None, "--demo-walkthrough-script-path", help="Absolute path to the demo_walkthrough.ps1 script used to execute the validated demo flow"),
    demo_walkthrough_script_created: Optional[bool] = typer.Option(None, "--demo-walkthrough-script-created/--no-demo-walkthrough-script-created", help="Mark whether the demo_walkthrough.ps1 script has been created for this demo"),
    dictation_recorded: Optional[bool] = typer.Option(None, "--dictation-recorded/--no-dictation-recorded", help="Mark demo dictation audio as recorded"),
    recorded: Optional[bool] = typer.Option(None, "--recorded/--no-recorded", help="Mark demo as recorded"),
):
    """
    Update a demo record.

    Examples:
        coursecraft demos update recXXX --name "New Name"
        coursecraft demos update recXXX --clip-order 2
        coursecraft demos update recXXX --action-summary "Step-by-step demo flow..."
        coursecraft demos update recXXX --tested-approved --script-review-human
        coursecraft demos update recXXX --environment-prep-complete
        coursecraft demos update recXXX --dictation-recorded
        coursecraft demos update recXXX --demo-walkthrough-script-path /Users/adam/courses/example/m2c3/demo_walkthrough.ps1
        coursecraft demos update recXXX --demo-environment azure-adam-the-automator
        coursecraft demos update recXXX --demo-environment azure-adam-the-automator --demo-environment local-macos
    """
    try:
        client = get_client()

        # Verify record exists
        existing = client.get_record("Demos", record_id)
        if not existing:
            print_error(f"Demo not found: {record_id}")
            raise typer.Exit(1)

        # Build fields dictionary with only provided values
        fields = {}
        if name is not None:
            fields["Name"] = name
        if clip_order is not None:
            fields["Clip Order"] = clip_order
        if target_length is not None:
            fields["Target Length (Min)"] = target_length
        if action_summary is not None:
            fields["Action Summary"] = action_summary
        if action_summary_review_ai is not None:
            fields["Action Summary Review (AI)"] = action_summary_review_ai
        if action_summary_human_review_complete is not None:
            fields["Action Summary Review (Human)"] = action_summary_human_review_complete
        if environment_prep_checklist is not None:
            fields["Environment Prep Checklist"] = environment_prep_checklist
        if environment_setup_script_path is not None:
            fields["Environment Setup Script Path"] = environment_setup_script_path
        if environment_prep_complete is not None:
            fields["Environment Prep Complete"] = environment_prep_complete
        if tested_approved is not None:
            fields["Tested and Approved"] = tested_approved
        if recap is not None:
            fields["Recap"] = recap
        if script is not None:
            fields["Script"] = script
            fields.update(get_voice_recording_invalidation_fields())
        if script_review_human is not None:
            fields["Script Review (Human)"] = script_review_human
        if demo_environment:
            fields["Demo Environment"] = [
                client.resolve_environment_id(environment)
                for environment in demo_environment
            ]
        if demo_walkthrough_script_path is not None:
            fields["Demo Walkthrough Script Path"] = demo_walkthrough_script_path
        if demo_walkthrough_script_created is not None:
            fields["Demo Walkthrough Script Created"] = demo_walkthrough_script_created
        if dictation_recorded is not None:
            fields["Dictation Recorded"] = dictation_recorded
        if recorded is not None:
            fields["Recorded"] = recorded

        if not fields:
            print_error("No fields to update. Provide at least one field option.")
            raise typer.Exit(1)

        # Update the record
        updated = client.update_record("Demos", record_id, fields)
        print_success(f"Updated demo: {record_id}")

        # Check for sync and workflow warnings
        existing_fields = existing.get("fields", {})
        existing_script = existing_fields.get("Script", "")
        existing_action_summary = existing_fields.get("Action Summary", "")
        existing_recap = existing_fields.get("Recap", "")
        existing_env_prep_complete = existing_fields.get("Environment Prep Complete", False)
        existing_tested_approved = existing_fields.get("Tested and Approved", False)
        existing_action_summary_reviewed = existing_fields.get("Action Summary Review (Human)", False)
        effective_env_prep_complete = environment_prep_complete or existing_env_prep_complete
        effective_tested_approved = tested_approved or existing_tested_approved

        # Action Summary / Script sync warnings
        if action_summary is not None and existing_script:
            print_mandatory_review(
                title="Script",
                action="Update the Script to match the new Action Summary",
                reason="Action Summary changed - Script must reflect the updated steps",
                preview=existing_script,
            )

        if script is not None and existing_action_summary:
            print_mandatory_review(
                title="Action Summary",
                action="Verify the Action Summary matches the updated Script",
                reason="Script changed - Action Summary must document the same steps",
                preview=existing_action_summary,
            )

        # Script / Recap sync warnings
        if script is not None and existing_recap:
            print_mandatory_review(
                title="Recap",
                action="Update the Recap to summarize the new Script",
                reason="Script changed - Recap must reflect what's actually demonstrated",
                preview=existing_recap,
            )

        if recap is not None and existing_script:
            print_info("")
            print_info("ℹ️  TIP: Ensure the Recap accurately summarizes the Script content.")
            print_info(f"   Script preview: {existing_script[:100]}..." if len(existing_script) > 100 else f"   Script preview: {existing_script}")

        # Environment Prep warnings
        if environment_prep_checklist is not None and existing_action_summary:
            print_info("")
            print_info("ℹ️  TIP: Ensure the Environment Prep Checklist covers all prerequisites from the Action Summary.")

        if environment_prep_complete and not existing_action_summary:
            print_info("")
            print_info("⚠️  WARNING: No Action Summary exists for this demo.")
            print_info("   Environment prep may be incomplete without knowing the demo steps.")

        # Workflow sequence warnings
        if tested_approved and not effective_env_prep_complete:
            print_info("")
            print_info("⚠️  WARNING: Environment Prep is not marked complete.")
            print_info("   Testing may be invalid if the environment wasn't properly prepared.")

        if recorded and not effective_tested_approved:
            print_info("")
            print_info("⚠️  WARNING: Demo has not been marked as Tested and Approved.")
            print_info("   Consider completing testing before recording.")

        if script_review_human and not existing_action_summary_reviewed:
            print_info("")
            print_info("⚠️  WARNING: Action Summary human review is not complete.")
            print_info("   The Script is derived from the Action Summary - consider reviewing that first.")

        # Output the record ID for scripting
        typer.echo(record_id)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("delete")
def delete_demo(
    record_id: str = typer.Argument(..., help="Demo record ID"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
):
    """
    Delete a demo record.

    This action is PERMANENT and cannot be undone.

    Examples:
        # Delete with confirmation prompt
        coursecraft demos delete recXXXXXXXXXXXXXXX

        # Delete without confirmation (for scripting)
        coursecraft demos delete recXXXXXXXXXXXXXXX --force
    """
    try:
        client = get_client()

        # Verify record exists
        record = client.get_record("Demos", record_id)
        if not record:
            print_error(f"Demo not found: {record_id}")
            raise typer.Exit(1)

        demo_name = record.get("fields", {}).get("Name", record_id)

        # Confirm deletion
        if not force:
            if not typer.confirm(f"Are you sure you want to delete demo '{demo_name}'?"):
                print_info("Deletion cancelled.")
                raise typer.Exit(0)

        # Delete the record
        client.delete_record("Demos", record_id)
        print_success(f"Deleted demo: {record_id}")

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
