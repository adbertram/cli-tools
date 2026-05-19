"""Slide Build Products command module."""
import json
import xml.etree.ElementTree as ET
import typer
from typing import Optional, List
from pathlib import Path

from ..client import get_client, ClientError
from ..output import print_success, print_error, print_info, print_json, print_table
from ..filter_map import translate_filters
from ..filters import apply_properties_filter, apply_limit

app = typer.Typer(help="Manage slide build product definitions")

# Default path to XML files
DEFAULT_XML_PATH = Path.home() / "Dropbox/GitRepos/Agent-CourseCraft/docs/slide-build-products"
TABLE_NAME = "Slide Build Products"


def parse_xml_build_product(xml_path: Path) -> dict:
    """
    Parse an XML build product file into a dictionary.

    Args:
        xml_path: Path to the XML file

    Returns:
        Dictionary with build product fields matching Airtable schema:
        - Name
        - Description
        - Requirements (markdown formatted)
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # Extract metadata
    metadata = root.find("metadata")
    name = metadata.find("name").text if metadata.find("name") is not None else ""

    # Extract description
    desc_elem = root.find("description")
    description = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else ""

    # Extract requirements and format as markdown
    # Handle both <requirements> with sections and <requirements> with direct items
    requirements_parts = []
    requirements_elem = root.find("requirements")
    if requirements_elem is not None:
        # Check for sections
        sections = requirements_elem.findall("section")
        if sections:
            for section in sections:
                title = section.get("title", "")
                if title:
                    requirements_parts.append(f"**{title}**")
                for item in section.findall("item"):
                    item_text = item.text.strip() if item.text else ""
                    subitems = item.findall("subitem")
                    if subitems:
                        requirements_parts.append(f"- {item_text}")
                        for subitem in subitems:
                            subtext = subitem.text.strip() if subitem.text else ""
                            requirements_parts.append(f"    {subtext}")
                    else:
                        requirements_parts.append(f"- {item_text}")
        else:
            # Direct items without sections
            for item in requirements_elem.findall("item"):
                item_text = item.text.strip() if item.text else ""
                requirements_parts.append(f"- {item_text}")

    requirements = "\n".join(requirements_parts)

    result = {
        "Name": name,
        "Description": description,
    }

    # Only include non-empty fields
    if requirements:
        result["Requirements"] = requirements

    return result


@app.command("list")
def list_build_products(
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum number of records to return"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of properties to include (supports dot notation)"),
    table_output: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    List slide build product definitions.

    Examples:
        coursecraft slide-build-products list
        coursecraft slide-build-products list --table
        coursecraft slide-build-products list --limit 10
        coursecraft slide-build-products list --filter "name:contains:Slide"
    """
    try:
        client = get_client()

        # Build filter formula
        formula = None
        if filter:
            formula = translate_filters(list(filter), TABLE_NAME)

        records = client.list_records(TABLE_NAME, formula)

        # Apply limit
        records = apply_limit(records, limit)

        # Apply properties filter for JSON output
        if properties and not table_output:
            records = apply_properties_filter(records, properties)

        if table_output:
            rows = []
            for rec in records:
                fields = rec.get("fields", {})
                rows.append({
                    "id": rec["id"],
                    "name": fields.get("Name", ""),
                    "version": fields.get("Version", ""),
                    "category": fields.get("Category", ""),
                })
            print_table(rows, ["id", "name", "version", "category"],
                       ["Record ID", "Name", "Version", "Category"])
        else:
            print_json(records)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("get")
def get_build_product(
    record_id: str = typer.Argument(..., help="Build product record ID or name"),
    table_output: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Get a single slide build product by ID or name.

    Examples:
        coursecraft slide-build-products get recXXXXXXXXXXXXXXX
        coursecraft slide-build-products get "Demo Intro Slide"
    """
    try:
        client = get_client()

        # If not a record ID, search by name
        if not record_id.startswith("rec"):
            escaped_name = record_id.replace("'", "\\'")
            filter_formula = f"{{Name}}='{escaped_name}'"
            records = client.list_records(TABLE_NAME, filter_formula)
            if not records:
                print_error(f"Build product not found: {record_id}")
                raise typer.Exit(1)
            record = records[0]
        else:
            record = client.get_record(TABLE_NAME, record_id)
            if not record:
                print_error(f"Build product not found: {record_id}")
                raise typer.Exit(1)

        if table_output:
            fields = record.get("fields", {})
            desc = fields.get("Description", "")
            rows = [{
                "id": record["id"],
                "name": fields.get("Name", ""),
                "version": fields.get("Version", ""),
                "description": desc[:60] + "..." if desc and len(desc) > 60 else desc,
            }]
            print_table(rows, ["id", "name", "version", "description"],
                       ["Record ID", "Name", "Version", "Description"])
        else:
            print_json(record)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("sync")
def sync_build_products(
    xml_path: Optional[Path] = typer.Option(
        None, "--path", "-p",
        help=f"Path to XML files directory (default: {DEFAULT_XML_PATH})"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show what would be updated without making changes"),
    file: Optional[str] = typer.Option(None, "--file", "-f", help="Sync only a specific XML file"),
):
    """
    Sync slide build products from XML files to Airtable.

    Reads XML files from the docs/slide-build-products directory and updates
    corresponding records in the Slide Build Products table.

    Examples:
        # Sync all slide build products
        coursecraft slide-build-products sync

        # Dry run to see what would change
        coursecraft slide-build-products sync --dry-run

        # Sync a specific file
        coursecraft slide-build-products sync --file demo-intro-slide.xml

        # Use custom path
        coursecraft slide-build-products sync --path /custom/path/to/xml
    """
    try:
        client = get_client()

        # Determine XML directory
        xml_dir = xml_path if xml_path else DEFAULT_XML_PATH

        if not xml_dir.exists():
            print_error(f"XML directory not found: {xml_dir}")
            raise typer.Exit(1)

        # Get list of XML files
        if file:
            xml_files = [xml_dir / file]
            if not xml_files[0].exists():
                print_error(f"XML file not found: {xml_files[0]}")
                raise typer.Exit(1)
        else:
            xml_files = list(xml_dir.glob("*.xml"))

        if not xml_files:
            print_info("No XML files found to sync.")
            return

        print_info(f"Found {len(xml_files)} XML file(s) to sync")

        # Get existing records from Airtable
        existing_records = client.list_records(TABLE_NAME, None)
        records_by_name = {r.get("fields", {}).get("Name", ""): r for r in existing_records}

        created = 0
        updated = 0
        skipped = 0

        for xml_file in xml_files:
            try:
                # Parse XML file
                bp_data = parse_xml_build_product(xml_file)
                name = bp_data["Name"]

                if not name:
                    print_info(f"  Skipping {xml_file.name}: No name found in metadata")
                    skipped += 1
                    continue

                if name in records_by_name:
                    # Update existing record
                    record = records_by_name[name]
                    record_id = record["id"]

                    if dry_run:
                        print_info(f"  Would update: {name} ({record_id})")
                    else:
                        client.update_record(TABLE_NAME, record_id, bp_data)
                        print_success(f"  Updated: {name} ({record_id})")
                    updated += 1
                else:
                    # Create new record
                    if dry_run:
                        print_info(f"  Would create: {name}")
                    else:
                        record_id = client.create_record(TABLE_NAME, bp_data)
                        print_success(f"  Created: {name} ({record_id})")
                    created += 1

            except ET.ParseError as e:
                print_error(f"  Error parsing {xml_file.name}: {e}")
                skipped += 1
            except Exception as e:
                print_error(f"  Error processing {xml_file.name}: {e}")
                skipped += 1

        # Summary
        print_info("")
        if dry_run:
            print_info(f"Dry run complete: {created} would be created, {updated} would be updated, {skipped} skipped")
        else:
            print_success(f"Sync complete: {created} created, {updated} updated, {skipped} skipped")

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("update")
def update_build_product(
    record_id: str = typer.Argument(..., help="Build product record ID"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Build product name"),
    version: Optional[str] = typer.Option(None, "--version", "-v", help="Version"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Description"),
    definition: Optional[str] = typer.Option(None, "--definition", help="Full XML definition"),
):
    """
    Update a slide build product record.

    Examples:
        coursecraft slide-build-products update recXXX --version "2.0"
        coursecraft slide-build-products update recXXX --description "New description"
    """
    try:
        client = get_client()

        # Verify record exists
        existing = client.get_record(TABLE_NAME, record_id)
        if not existing:
            print_error(f"Build product not found: {record_id}")
            raise typer.Exit(1)

        # Build fields dictionary
        fields = {}
        if name is not None:
            fields["Name"] = name
        if version is not None:
            fields["Version"] = version
        if description is not None:
            fields["Description"] = description
        if definition is not None:
            fields["Definition"] = definition

        if not fields:
            print_error("No fields to update. Provide at least one field option.")
            raise typer.Exit(1)

        # Update the record
        client.update_record(TABLE_NAME, record_id, fields)
        print_success(f"Updated build product: {record_id}")
        typer.echo(record_id)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


COMMAND_CREDENTIALS = {
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "sync": [
        "custom"
    ],
    "update": [
        "custom"
    ]
}
