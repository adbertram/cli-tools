"""Slide Templates command module."""
import json
from pathlib import Path

import typer
from typing import Optional, List

from cli_tools_shared.filters import apply_limit
from cli_tools_shared.output import command
from ..client import get_client, ClientError
from ..output import apply_properties_filter, project_record, print_success, print_error, print_info, print_json, print_table
from ..filter_translator import translate_filters

app = typer.Typer(help="Manage slide template records")

TABLE_NAME = "Slide Templates"

PLACEHOLDERS_FIELD = "Placeholders"
IMAGE_FIELD = "Image"


def _resolve_placeholders(
    placeholders: Optional[str],
    placeholders_file: Optional[Path],
) -> Optional[str]:
    """Resolve and JSON-validate the Placeholders blob.

    The file wins when both an inline value and a file are provided. Returns the
    raw JSON string to store verbatim in the Airtable long-text field, or None
    when neither option was supplied. Exits 1 on a missing file or invalid JSON.
    """
    if placeholders_file is not None:
        if not placeholders_file.is_file():
            print_error(f"Placeholders file not found: {placeholders_file}")
            raise typer.Exit(1)
        raw = placeholders_file.read_text()
    elif placeholders is not None:
        raw = placeholders
    else:
        return None

    try:
        json.loads(raw)
    except json.JSONDecodeError as exc:
        source = (
            f"file {placeholders_file}"
            if placeholders_file is not None
            else "--placeholders value"
        )
        print_error(f"Invalid JSON in {source}: {exc}")
        raise typer.Exit(1)

    return raw


def _validate_image_options(image: Optional[Path], image_url: Optional[str]) -> None:
    """Reject using --image and --image-url together (both target Image)."""
    if image is not None and image_url is not None:
        print_error("Cannot use --image with --image-url. Provide only one.")
        raise typer.Exit(1)
    if image is not None and not image.is_file():
        print_error(f"Image file not found: {image}")
        raise typer.Exit(1)


@app.command("list")
@command
def list_templates(
    platform: Optional[str] = typer.Option(None, "--platform", "-P", help="Filter by platform (e.g., 'Pluralsight', 'Udemy')"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum number of records to return"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Property to include (supports dot notation). Repeatable; each value may also be comma-separated."),
    table_output: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    List slide template records.

    Examples:
        # List all templates
        coursecraft slide-templates list

        # List templates for a platform
        coursecraft slide-templates list --platform Pluralsight

        # List with standard filter
        coursecraft slide-templates list --filter "name:contains:Title"

        # Combine --platform with an additional filter
        coursecraft slide-templates list --platform Pluralsight --filter "name:contains:Title"

        # List with table output
        coursecraft slide-templates list --table

        # Limit results
        coursecraft slide-templates list --limit 10

        # Select specific properties
        coursecraft slide-templates list --properties "id,fields.Name,fields.Platform"
    """
    try:
        client = get_client()

        # --platform and --filter combine (AND-ed together), the same pattern
        # list_modules uses for --course + --filter.
        if platform:
            formula = f"{{Platform}}='{platform}'"
            if filter:
                filter_formula = translate_filters(list(filter), TABLE_NAME)
                formula = f"AND({formula},{filter_formula})"
            records = client.list_records(TABLE_NAME, formula)
        elif filter:
            formula = translate_filters(list(filter), TABLE_NAME)
            records = client.list_records(TABLE_NAME, formula)
        else:
            records = client.list_records(TABLE_NAME, None)

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
                desc = fields.get("Description", "")
                rows.append({
                    "id": rec["id"],
                    "name": fields.get("Name", ""),
                    "platform": fields.get("Platform", ""),
                    "deck_number": fields.get("Template Deck Number", ""),
                    "description": desc[:50] + "..." if desc and len(desc) > 50 else desc,
                })
            print_table(rows, ["id", "name", "platform", "deck_number", "description"],
                       ["Record ID", "Name", "Platform", "Deck #", "Description"])
        else:
            print_json(records)

    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


COMMAND_CREDENTIALS = {
    "create": ["custom"],
    "delete": ["custom"],
    "get": ["custom"],
    "list": ["custom"],
    "update": ["custom"],
}


@app.command("get")
@command
def get_template(
    record_id: str = typer.Argument(..., help="Template record ID or name"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Property to include (supports dot notation). Repeatable; each value may also be comma-separated."),
    table_output: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Get a single slide template by ID or name.

    Examples:
        coursecraft slide-templates get recXXXXXXXXXXXXXXX
        coursecraft slide-templates get "Course Title"
        coursecraft slide-templates get recXXXXXXXXXXXXXXX --properties "id,fields.Name"
        coursecraft slide-templates get recXXXXXXXXXXXXXXX --table
    """
    try:
        client = get_client()

        # If not a record ID, search by name
        if not record_id.startswith("rec"):
            escaped_name = record_id.replace("'", "\\'")
            filter_formula = f"{{Name}}='{escaped_name}'"
            records = client.list_records(TABLE_NAME, filter_formula)
            if not records:
                print_error(f"Template not found: {record_id}")
                raise typer.Exit(1)
            record = records[0]
        else:
            record = client.get_record(TABLE_NAME, record_id)
            if not record:
                print_error(f"Template not found: {record_id}")
                raise typer.Exit(1)

        if properties and not table_output:
            record = project_record(record, properties)

        if table_output:
            fields = record.get("fields", {})
            desc = fields.get("Description", "")
            rows = [{
                "id": record["id"],
                "name": fields.get("Name", ""),
                "platform": fields.get("Platform", ""),
                "deck_number": fields.get("Template Deck Number", ""),
                "description": desc[:60] + "..." if desc and len(desc) > 60 else desc,
            }]
            print_table(rows, ["id", "name", "platform", "deck_number", "description"],
                       ["Record ID", "Name", "Platform", "Deck #", "Description"])
        else:
            print_json(record)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("create")
@command
def create_template(
    name: str = typer.Option(..., "--name", "-n", help="Template name (required)"),
    platform: Optional[str] = typer.Option(None, "--platform", "-P", help="Platform (e.g., 'Pluralsight', 'Udemy')"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Template description"),
    requirements: Optional[str] = typer.Option(None, "--requirements", "-r", help="Template content requirements"),
    use_cases: Optional[str] = typer.Option(None, "--use-cases", "-u", help="Use cases for this template"),
    deck_number: Optional[int] = typer.Option(None, "--deck-number", help="Template deck slide number"),
    template_deck_version: Optional[str] = typer.Option(None, "--template-deck-version", help="Template deck version (e.g., '2026.05.a'); stored verbatim in the singleSelect field"),
    placeholders: Optional[str] = typer.Option(None, "--placeholders", help="Placeholders JSON blob (string). --placeholders-file wins if both given."),
    placeholders_file: Optional[Path] = typer.Option(None, "--placeholders-file", help="Path to a file containing the Placeholders JSON blob"),
    image: Optional[Path] = typer.Option(None, "--image", help="Local image file to upload to the Image attachment field"),
    image_url: Optional[str] = typer.Option(None, "--image-url", help="URL to attach to the Image field (alternative to --image)"),
):
    """
    Create a slide template record.

    Examples:
        # Create a basic template
        coursecraft slide-templates create --name "Course Title" --platform Pluralsight

        # Create with full details
        coursecraft slide-templates create --name "Remember This" --platform Pluralsight \\
            --description "Highlight key takeaways" --use-cases "End of clip summaries"

        # Create with a Placeholders JSON blob from a file and a local image
        coursecraft slide-templates create --name "Image with Three Points" --platform Pluralsight \\
            --placeholders-file ./placeholders.json --image ./preview.png

        # Create with an image by URL
        coursecraft slide-templates create --name "Course Title" --platform Pluralsight \\
            --image-url "https://example.com/preview.png"
    """
    try:
        # Validate inputs before any write.
        placeholders_value = _resolve_placeholders(placeholders, placeholders_file)
        _validate_image_options(image, image_url)

        client = get_client()

        # Check if template with same name already exists on the same platform
        escaped_name = name.replace("'", "\\'")
        if platform:
            escaped_platform = platform.replace("'", "\\'")
            filter_formula = f"AND({{Name}}='{escaped_name}',{{Platform}}='{escaped_platform}')"
        else:
            filter_formula = f"{{Name}}='{escaped_name}'"
        existing = client.list_records(TABLE_NAME, filter_formula)
        if existing:
            print_error(f"Template with name '{name}' already exists on {platform or 'this platform'}: {existing[0]['id']}")
            raise typer.Exit(1)

        # Build fields dictionary
        fields = {
            "Name": name,
        }

        if platform is not None:
            fields["Platform"] = platform
        if description is not None:
            fields["Description"] = description
        if requirements is not None:
            fields["Requirements"] = requirements
        if use_cases is not None:
            fields["Use Cases"] = use_cases
        if deck_number is not None:
            fields["Template Deck Number"] = deck_number
        if template_deck_version is not None:
            fields["Template Deck Version"] = template_deck_version
        if placeholders_value is not None:
            fields[PLACEHOLDERS_FIELD] = placeholders_value
        if image_url is not None:
            fields[IMAGE_FIELD] = [{"url": image_url}]

        # Create the record
        record_id = client.create_record(TABLE_NAME, fields)

        # A local image upload needs an existing record, so upload after create.
        if image is not None:
            client.upload_attachment(record_id, IMAGE_FIELD, str(image))

        print_success(f"Created template '{name}': {record_id}")

        # Output the record ID for scripting
        typer.echo(record_id)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("update")
@command
def update_template(
    record_id: str = typer.Argument(..., help="Template record ID"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Template name"),
    platform: Optional[str] = typer.Option(None, "--platform", "-P", help="Platform (e.g., 'Pluralsight', 'Udemy')"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Template description"),
    requirements: Optional[str] = typer.Option(None, "--requirements", "-r", help="Template content requirements"),
    use_cases: Optional[str] = typer.Option(None, "--use-cases", "-u", help="Use cases for this template"),
    deck_number: Optional[int] = typer.Option(None, "--deck-number", help="Template deck slide number"),
    template_deck_version: Optional[str] = typer.Option(None, "--template-deck-version", help="Template deck version (e.g., '2026.05.a'); stored verbatim in the singleSelect field"),
    placeholders: Optional[str] = typer.Option(None, "--placeholders", help="Placeholders JSON blob (string). --placeholders-file wins if both given."),
    placeholders_file: Optional[Path] = typer.Option(None, "--placeholders-file", help="Path to a file containing the Placeholders JSON blob"),
    image: Optional[Path] = typer.Option(None, "--image", help="Local image file to upload to the Image attachment field"),
    image_url: Optional[str] = typer.Option(None, "--image-url", help="URL to attach to the Image field (alternative to --image)"),
):
    """
    Update a slide template record.

    Examples:
        coursecraft slide-templates update recXXX --name "New Name"
        coursecraft slide-templates update recXXX --platform Udemy
        coursecraft slide-templates update recXXX --description "Updated description"
        coursecraft slide-templates update recXXX --use-cases "New use cases"
        coursecraft slide-templates update recXXX --deck-number 15
        coursecraft slide-templates update recXXX --placeholders-file ./placeholders.json
        coursecraft slide-templates update recXXX --image ./preview.png
        coursecraft slide-templates update recXXX --image-url "https://example.com/preview.png"
    """
    try:
        # Validate inputs before any write.
        placeholders_value = _resolve_placeholders(placeholders, placeholders_file)
        _validate_image_options(image, image_url)

        client = get_client()

        # Verify record exists
        existing = client.get_record(TABLE_NAME, record_id)
        if not existing:
            print_error(f"Template not found: {record_id}")
            raise typer.Exit(1)

        # Build fields dictionary with only provided values
        fields = {}
        if name is not None:
            fields["Name"] = name
        if platform is not None:
            fields["Platform"] = platform
        if description is not None:
            fields["Description"] = description
        if requirements is not None:
            fields["Requirements"] = requirements
        if use_cases is not None:
            fields["Use Cases"] = use_cases
        if deck_number is not None:
            fields["Template Deck Number"] = deck_number
        if template_deck_version is not None:
            fields["Template Deck Version"] = template_deck_version
        if placeholders_value is not None:
            fields[PLACEHOLDERS_FIELD] = placeholders_value
        if image_url is not None:
            fields[IMAGE_FIELD] = [{"url": image_url}]

        # A local image upload is a separate write and counts as an update.
        if not fields and image is None:
            print_error("No fields to update. Provide at least one field option.")
            raise typer.Exit(1)

        # Update standard fields (and image-by-URL) when any were provided.
        if fields:
            client.update_record(TABLE_NAME, record_id, fields)

        # Upload a local image to the existing record's attachment field.
        if image is not None:
            client.upload_attachment(record_id, IMAGE_FIELD, str(image))

        print_success(f"Updated template: {record_id}")
        typer.echo(record_id)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("delete")
@command
def delete_template(
    record_id: str = typer.Argument(..., help="Template record ID"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
):
    """
    Delete a slide template record.

    This action is PERMANENT and cannot be undone. Slides and slide build
    products that reference this template are unlinked, not deleted.

    Examples:
        # Delete with confirmation prompt
        coursecraft slide-templates delete recXXXXXXXXXXXXXXX

        # Delete without confirmation (for scripting)
        coursecraft slide-templates delete recXXXXXXXXXXXXXXX --force
    """
    try:
        client = get_client()

        # Verify record exists
        record = client.get_record(TABLE_NAME, record_id)
        if not record:
            print_error(f"Template not found: {record_id}")
            raise typer.Exit(1)

        template_name = record.get("fields", {}).get("Name", record_id)

        # Confirm deletion
        if not force:
            if not typer.confirm(f"Are you sure you want to delete template '{template_name}'?"):
                print_info("Deletion cancelled.")
                raise typer.Exit(0)

        # Delete the record
        client.delete_record(TABLE_NAME, record_id)
        print_success(f"Deleted template: {record_id}")

        # Output the deleted ID for scripting
        typer.echo(record_id)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)
