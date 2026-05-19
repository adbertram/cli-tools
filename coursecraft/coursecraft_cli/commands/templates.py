"""Slide Templates command module."""
import typer
from typing import Optional, List

from ..client import get_client, ClientError
from ..output import print_success, print_error, print_json, print_table
from ..filter_map import translate_filters
from ..filters import apply_properties_filter, apply_limit

app = typer.Typer(help="Manage slide template records")

TABLE_NAME = "Slide Templates"


@app.command("list")
def list_templates(
    platform: Optional[str] = typer.Option(None, "--platform", "-P", help="Filter by platform (e.g., 'Pluralsight', 'Udemy')"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum number of records to return"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of properties to include (supports dot notation)"),
    table_output: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    List slide template records.

    Examples:
        # List all templates
        coursecraft templates list

        # List templates for a platform
        coursecraft templates list --platform Pluralsight

        # List with standard filter
        coursecraft templates list --filter "name:contains:Title"

        # List with table output
        coursecraft templates list --table

        # Limit results
        coursecraft templates list --limit 10

        # Select specific properties
        coursecraft templates list --properties "id,fields.Name,fields.Platform"
    """
    try:
        client = get_client()

        if filter and platform:
            print_error("Cannot use --filter with --platform")
            raise typer.Exit(1)

        # Get records based on filter type
        if platform:
            formula = f"{{Platform}}='{platform}'"
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


@app.command("get")
def get_template(
    record_id: str = typer.Argument(..., help="Template record ID or name"),
    table_output: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Get a single slide template by ID or name.

    Examples:
        coursecraft templates get recXXXXXXXXXXXXXXX
        coursecraft templates get "Course Title"
        coursecraft templates get recXXXXXXXXXXXXXXX --table
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
def create_template(
    name: str = typer.Option(..., "--name", "-n", help="Template name (required)"),
    platform: Optional[str] = typer.Option(None, "--platform", "-P", help="Platform (e.g., 'Pluralsight', 'Udemy')"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Template description"),
    requirements: Optional[str] = typer.Option(None, "--requirements", "-r", help="Template content requirements"),
    use_cases: Optional[str] = typer.Option(None, "--use-cases", "-u", help="Use cases for this template"),
    deck_number: Optional[int] = typer.Option(None, "--deck-number", help="Template deck slide number"),
    template_deck_version: Optional[float] = typer.Option(None, "--template-deck-version", help="Template deck version"),
):
    """
    Create a slide template record.

    Examples:
        # Create a basic template
        coursecraft templates create --name "Course Title" --platform Pluralsight

        # Create with full details
        coursecraft templates create --name "Remember This" --platform Pluralsight \\
            --description "Highlight key takeaways" --use-cases "End of clip summaries"
    """
    try:
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

        # Create the record
        record_id = client.create_record(TABLE_NAME, fields)
        print_success(f"Created template '{name}': {record_id}")

        # Output the record ID for scripting
        typer.echo(record_id)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("update")
def update_template(
    record_id: str = typer.Argument(..., help="Template record ID"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Template name"),
    platform: Optional[str] = typer.Option(None, "--platform", "-P", help="Platform (e.g., 'Pluralsight', 'Udemy')"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Template description"),
    requirements: Optional[str] = typer.Option(None, "--requirements", "-r", help="Template content requirements"),
    use_cases: Optional[str] = typer.Option(None, "--use-cases", "-u", help="Use cases for this template"),
    deck_number: Optional[int] = typer.Option(None, "--deck-number", help="Template deck slide number"),
    template_deck_version: Optional[float] = typer.Option(None, "--template-deck-version", help="Template deck version"),
):
    """
    Update a slide template record.

    Examples:
        coursecraft templates update recXXX --name "New Name"
        coursecraft templates update recXXX --platform Udemy
        coursecraft templates update recXXX --description "Updated description"
        coursecraft templates update recXXX --use-cases "New use cases"
        coursecraft templates update recXXX --deck-number 15
    """
    try:
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

        if not fields:
            print_error("No fields to update. Provide at least one field option.")
            raise typer.Exit(1)

        # Update the record
        client.update_record(TABLE_NAME, record_id, fields)
        print_success(f"Updated template: {record_id}")
        typer.echo(record_id)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)
