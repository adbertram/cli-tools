"""Field (property schema) commands for Notion CLI."""
import json
import typer
from typing import Optional, List

from ..client import get_client
from ..output import (
    print_json,
    print_table,
    command,
    print_success,
    print_warning,
)
from cli_tools_shared.filters import apply_filters

app = typer.Typer(help="Manage database field schemas (properties)")
option_app = typer.Typer(help="Manage field options for select/multi_select/status fields")
app.add_typer(option_app, name="option")

# Supported property types for creation
SUPPORTED_TYPES = [
    "rich_text",
    "number",
    "select",
    "multi_select",
    "status",
    "date",
    "people",
    "files",
    "checkbox",
    "url",
    "email",
    "phone_number",
    "formula",
    "relation",
]


RELATION_TYPES = ("dual_property", "single_property")


def build_property_schema(
    prop_type: str,
    options: Optional[List[str]] = None,
    formula_expression: Optional[str] = None,
    relation_data_source_id: Optional[str] = None,
    relation_type: str = "dual_property",
    number_format: Optional[str] = None,
) -> dict:
    """
    Build a Notion property schema object for database updates.

    Args:
        prop_type: The property type
        options: Options for select/multi_select/status types
        formula_expression: Expression for formula type
        relation_data_source_id: The TARGET's data_source ID for relation type
            (API 2025-09-03 requires relation.data_source_id, not database_id)
        relation_type: Relation type for relation properties
            (dual_property or single_property)
        number_format: Format for number type

    Returns:
        Property schema object
    """
    schema: dict = {}

    if prop_type == "rich_text":
        schema["rich_text"] = {}

    elif prop_type == "number":
        number_config = {}
        if number_format:
            number_config["format"] = number_format
        schema["number"] = number_config

    elif prop_type == "select":
        select_config = {}
        if options:
            select_config["options"] = [{"name": opt} for opt in options]
        schema["select"] = select_config

    elif prop_type == "multi_select":
        multi_config = {}
        if options:
            multi_config["options"] = [{"name": opt} for opt in options]
        schema["multi_select"] = multi_config

    elif prop_type == "status":
        status_config = {}
        if options:
            status_config["options"] = [{"name": opt} for opt in options]
        schema["status"] = status_config

    elif prop_type == "date":
        schema["date"] = {}

    elif prop_type == "people":
        schema["people"] = {}

    elif prop_type == "files":
        schema["files"] = {}

    elif prop_type == "checkbox":
        schema["checkbox"] = {}

    elif prop_type == "url":
        schema["url"] = {}

    elif prop_type == "email":
        schema["email"] = {}

    elif prop_type == "phone_number":
        schema["phone_number"] = {}

    elif prop_type == "formula":
        if not formula_expression:
            raise ValueError("Formula type requires --formula-expression")
        schema["formula"] = {"expression": formula_expression}

    elif prop_type == "relation":
        if not relation_data_source_id:
            raise ValueError(
                "Relation type requires --relation-database "
                "(the target's database container ID or data_source ID)"
            )
        if relation_type not in RELATION_TYPES:
            raise ValueError(
                f"--relation-type must be one of {', '.join(RELATION_TYPES)}"
            )
        # API 2025-09-03 requires relation.data_source_id (NOT database_id).
        schema["relation"] = {
            "data_source_id": relation_data_source_id,
            "type": relation_type,
            relation_type: {},
        }

    else:
        raise ValueError(f"Unsupported property type: {prop_type}")

    return schema


@app.command("list")
@command
def field_list(
    database_id: str = typer.Option(
        ...,
        "--database-id",
        "-d",
        help="The database ID to list fields for",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display as formatted table",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
        help="Maximum number of fields to return",
    ),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., name:eq:MyItem, type:eq:select, name:contains:Status)",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include in output (e.g., name,type)",
    ),
):
    """
    List all fields (properties) in a database schema.

    Limiting: Client-side (schema endpoint returns all fields)
    Filtering: Client-side by field name or type

    Examples:
        notion field list --database-id abc123
        notion field list --database-id abc123 --table
        notion field list --database-id abc123 --filter "type:select"
        notion field list --database-id abc123 --limit 10
    """
    client = get_client()
    db = client.get_database(database_id)

    fields = []
    for prop_name, prop_def in db.get("properties", {}).items():
        prop_type = prop_def.get("type", "")
        field_info = {
            "name": prop_name,
            "type": prop_type,
            "id": prop_def.get("id", ""),
        }

        # Include options for select/multi_select/status
        if prop_type == "select":
            options = prop_def.get("select", {}).get("options", [])
            field_info["options"] = [o.get("name") for o in options]
        elif prop_type == "multi_select":
            options = prop_def.get("multi_select", {}).get("options", [])
            field_info["options"] = [o.get("name") for o in options]
        elif prop_type == "status":
            options = prop_def.get("status", {}).get("options", [])
            field_info["options"] = [o.get("name") for o in options]
        elif prop_type == "number":
            field_info["format"] = prop_def.get("number", {}).get("format", "")
        elif prop_type == "formula":
            field_info["expression"] = prop_def.get("formula", {}).get("expression", "")
        elif prop_type == "relation":
            field_info["relation_database"] = prop_def.get("relation", {}).get("database_id", "")

        fields.append(field_info)

    # Apply client-side filtering
    if filter:
        fields = apply_filters(fields, filter)

    # Apply client-side limit
    fields = fields[:limit]

    # Filter to requested properties if specified
    if properties:
        props_list = [p.strip() for p in properties.split(",")]
        filtered_fields = []
        for f in fields:
            filtered = {}
            for prop in props_list:
                if "." in prop:
                    # Dot-notation for nested properties
                    keys = prop.split(".")
                    value = f
                    for key in keys:
                        if isinstance(value, dict) and key in value:
                            value = value[key]
                        else:
                            value = None
                            break
                    if value is not None:
                        filtered[prop] = value
                elif prop in f:
                    filtered[prop] = f[prop]
            filtered_fields.append(filtered)
        fields = filtered_fields

    if table:
        if properties:
            cols = [p.strip() for p in properties.split(",")]
            print_table(fields, cols, cols)
        else:
            rows = []
            for f in fields:
                row = {
                    "name": f["name"],
                    "type": f["type"],
                    "options": ", ".join(f.get("options", [])) if f.get("options") else "",
                }
                rows.append(row)
            print_table(rows, ["name", "type", "options"], ["Name", "Type", "Options"])
    else:
        print_json(fields)

    typer.echo(f"\n{len(fields)} field(s) found.", err=True)


@app.command("get")
@command
def field_get(
    database_id: str = typer.Argument(
        ...,
        help="The database ID",
    ),
    name: str = typer.Argument(
        ...,
        help="Name of the field to retrieve",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display as formatted table",
    ),
):
    """
    Get a specific field (property) definition by name.

    Examples:
        notion field get DB_ID "Priority"
        notion field get DB_ID "Status" --table
    """
    client = get_client()
    db = client.get_database(database_id)

    field_def = db.get("properties", {}).get(name)

    if not field_def:
        print_warning(f"Field '{name}' not found.")
        raise typer.Exit(1)

    prop_type = field_def.get("type", "")
    field_info = {
        "name": name,
        "type": prop_type,
        "id": field_def.get("id", ""),
    }

    # Include type-specific details
    if prop_type == "select":
        options = field_def.get("select", {}).get("options", [])
        field_info["options"] = [o.get("name") for o in options]
    elif prop_type == "multi_select":
        options = field_def.get("multi_select", {}).get("options", [])
        field_info["options"] = [o.get("name") for o in options]
    elif prop_type == "status":
        options = field_def.get("status", {}).get("options", [])
        field_info["options"] = [o.get("name") for o in options]
    elif prop_type == "number":
        field_info["format"] = field_def.get("number", {}).get("format", "")
    elif prop_type == "formula":
        field_info["expression"] = field_def.get("formula", {}).get("expression", "")
    elif prop_type == "relation":
        field_info["relation_database"] = field_def.get("relation", {}).get("database_id", "")

    if table:
        rows = [{"field": k, "value": str(v)} for k, v in field_info.items()]
        print_table(rows, ["field", "value"], ["Field", "Value"])
    else:
        print_json(field_info)


@app.command("add")
@command
def field_add(
    database_id: str = typer.Argument(
        ...,
        help="The database ID to add the field to",
    ),
    name: str = typer.Argument(
        ...,
        help="Name of the new field",
    ),
    prop_type: str = typer.Option(
        ...,
        "--type",
        "-t",
        help=f"Field type: {', '.join(SUPPORTED_TYPES)}",
    ),
    options: Optional[str] = typer.Option(
        None,
        "--options",
        "-o",
        help="Comma-separated options for select/multi_select/status types",
    ),
    formula_expression: Optional[str] = typer.Option(
        None,
        "--formula-expression",
        help="Expression for formula type",
    ),
    relation_database: Optional[str] = typer.Option(
        None,
        "--relation-database",
        "--relation-data-source",
        help="For relation type: the TARGET's database container ID OR "
        "data_source ID. Resolved to the target's data_source_id "
        "(API 2025-09-03).",
    ),
    relation_type: str = typer.Option(
        "dual_property",
        "--relation-type",
        help="Relation type for relation fields (dual_property or single_property)",
    ),
    number_format: Optional[str] = typer.Option(
        None,
        "--number-format",
        help="Format for number type (number, number_with_commas, percent, dollar, etc.)",
    ),
):
    """
    Add a new field (property) to a database.

    Examples:
        notion field add DB_ID "Priority" --type select --options "High,Medium,Low"
        notion field add DB_ID "Notes" --type rich_text
        notion field add DB_ID "Due Date" --type date
        notion field add DB_ID "Completed" --type checkbox
        notion field add DB_ID "Score" --type number --number-format percent
        notion field add DB_ID "Related Tasks" --type relation --relation-database OTHER_DB_ID
    """
    client = get_client()

    # Validate type
    if prop_type not in SUPPORTED_TYPES:
        print_warning(f"Unsupported type: {prop_type}. Supported: {', '.join(SUPPORTED_TYPES)}")
        raise typer.Exit(1)

    # Parse options
    options_list = None
    if options:
        options_list = [o.strip() for o in options.split(",")]

    # Resolve the relation target to its data_source ID. The user may pass
    # either a database container ID or a data_source ID; the API needs the
    # target's data_source_id.
    relation_data_source_id = None
    if prop_type == "relation":
        if not relation_database:
            print_warning(
                "Relation type requires --relation-database "
                "(the target's database container ID or data_source ID)"
            )
            raise typer.Exit(1)
        relation_data_source_id = client.get_data_source_id(relation_database)

    # Build property schema
    try:
        schema = build_property_schema(
            prop_type=prop_type,
            options=options_list,
            formula_expression=formula_expression,
            relation_data_source_id=relation_data_source_id,
            relation_type=relation_type,
            number_format=number_format,
        )
    except ValueError as e:
        print_warning(str(e))
        raise typer.Exit(1)

    # Update database
    properties = {name: schema}
    updated_db = client.update_database(database_id, properties=properties)

    # Show the new field
    new_field = updated_db.get("properties", {}).get(name, {})
    print_json({
        "name": name,
        "type": new_field.get("type", prop_type),
        "id": new_field.get("id", ""),
    })
    print_success(f"Field '{name}' added successfully.")


@app.command("rename")
@command
def field_rename(
    database_id: str = typer.Argument(
        ...,
        help="The database ID",
    ),
    old_name: str = typer.Argument(
        ...,
        help="Current name of the field",
    ),
    new_name: str = typer.Argument(
        ...,
        help="New name for the field",
    ),
):
    """
    Rename a field (property) in a database.

    Examples:
        notion field rename DB_ID "Old Name" "New Name"
    """
    client = get_client()

    # Rename by setting the name property
    properties = {old_name: {"name": new_name}}
    updated_db = client.update_database(database_id, properties=properties)

    # Verify the rename
    new_field = updated_db.get("properties", {}).get(new_name, {})
    if new_field:
        print_json({
            "old_name": old_name,
            "new_name": new_name,
            "type": new_field.get("type", ""),
            "id": new_field.get("id", ""),
        })
        print_success(f"Field renamed from '{old_name}' to '{new_name}'.")
    else:
        print_warning(f"Field '{old_name}' not found or rename failed.")
        raise typer.Exit(1)


@app.command("delete")
@command
def field_delete(
    database_id: str = typer.Argument(
        ...,
        help="The database ID",
    ),
    name: str = typer.Argument(
        ...,
        help="Name of the field to delete",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-F",
        help="Skip confirmation prompt",
    ),
):
    """
    Delete a field (property) from a database.

    WARNING: This will delete all data in this field across all pages!

    Examples:
        notion field delete DB_ID "Field Name"
        notion field delete DB_ID "Field Name" --force
    """
    client = get_client()

    # Confirm unless force flag is set
    if not force:
        confirm = typer.confirm(
            f"Delete field '{name}'? This will remove all data in this field from all pages!"
        )
        if not confirm:
            typer.echo("Cancelled.")
            raise typer.Exit(0)

    # Delete by setting to None
    properties = {name: None}
    client.update_database(database_id, properties=properties)

    print_success(f"Field '{name}' deleted successfully.")


@option_app.command("add")
@command
def option_add(
    database_id: str = typer.Argument(
        ...,
        help="The database ID",
    ),
    field_name: str = typer.Argument(
        ...,
        help="Name of the select/multi_select/status field",
    ),
    option: str = typer.Argument(
        ...,
        help="Option value to add",
    ),
    color: Optional[str] = typer.Option(
        None,
        "--color",
        "-c",
        help="Color for the option (default, gray, brown, orange, yellow, green, blue, purple, pink, red)",
    ),
):
    """
    Add an option to a select, multi_select, or status field.

    Examples:
        notion field option add DB_ID "Priority" "Critical"
        notion field option add DB_ID "Status" "Blocked" --color red
    """
    client = get_client()

    # Get current database schema
    db = client.get_database(database_id)
    field_def = db.get("properties", {}).get(field_name)

    if not field_def:
        print_warning(f"Field '{field_name}' not found.")
        raise typer.Exit(1)

    field_type = field_def.get("type")
    if field_type not in ("select", "multi_select", "status"):
        print_warning(f"Field '{field_name}' is type '{field_type}'. Options only apply to select, multi_select, or status.")
        raise typer.Exit(1)

    # Get existing options
    existing_options = field_def.get(field_type, {}).get("options", [])

    # Check if option already exists
    existing_names = [o.get("name") for o in existing_options]
    if option in existing_names:
        print_warning(f"Option '{option}' already exists in field '{field_name}'.")
        raise typer.Exit(1)

    # Build new option
    new_option = {"name": option}
    if color:
        new_option["color"] = color

    # Add to options list
    updated_options = existing_options + [new_option]

    # Build update
    properties = {
        field_name: {
            field_type: {
                "options": updated_options
            }
        }
    }

    client.update_database(database_id, properties=properties)

    print_json({"field": field_name, "option_added": option, "color": color})
    print_success(f"Option '{option}' added to field '{field_name}'.")


@app.command("update")
@command
def field_update(
    database_id: str = typer.Argument(
        ...,
        help="The database ID",
    ),
    name: str = typer.Argument(
        ...,
        help="Name of the field to update",
    ),
    new_name: Optional[str] = typer.Option(
        None,
        "--name",
        "-n",
        help="New name for the field",
    ),
    options: Optional[str] = typer.Option(
        None,
        "--options",
        "-o",
        help="Replace options for select/multi_select/status (comma-separated)",
    ),
    number_format: Optional[str] = typer.Option(
        None,
        "--number-format",
        help="Format for number type",
    ),
    formula_expression: Optional[str] = typer.Option(
        None,
        "--formula-expression",
        help="Expression for formula type",
    ),
    relation_database: Optional[str] = typer.Option(
        None,
        "--relation-database",
        "--relation-data-source",
        help="For relation fields: the TARGET's database container ID OR "
        "data_source ID. Resolved to the target's data_source_id "
        "(API 2025-09-03).",
    ),
    relation_type: Optional[str] = typer.Option(
        None,
        "--relation-type",
        help="Relation type for relation fields (dual_property or single_property)",
    ),
):
    """
    Update a field's configuration.

    Examples:
        notion field update DB_ID "Priority" --name "Urgency"
        notion field update DB_ID "Score" --number-format percent
        notion field update DB_ID "Status" --options "Todo,In Progress,Done"
        notion field update DB_ID "Project" --relation-database TARGET_DB_ID
    """
    client = get_client()

    # Get current field definition
    db = client.get_database(database_id)
    field_def = db.get("properties", {}).get(name)

    if not field_def:
        print_warning(f"Field '{name}' not found.")
        raise typer.Exit(1)

    field_type = field_def.get("type")

    # Build update object
    update: dict = {}

    if new_name:
        update["name"] = new_name

    if options:
        if field_type not in ("select", "multi_select", "status"):
            print_warning(f"--options only applies to select, multi_select, or status fields.")
            raise typer.Exit(1)
        options_list = [{"name": o.strip()} for o in options.split(",")]
        update[field_type] = {"options": options_list}

    if number_format:
        if field_type != "number":
            print_warning(f"--number-format only applies to number fields.")
            raise typer.Exit(1)
        update["number"] = {"format": number_format}

    if formula_expression:
        if field_type != "formula":
            print_warning(f"--formula-expression only applies to formula fields.")
            raise typer.Exit(1)
        update["formula"] = {"expression": formula_expression}

    if relation_database or relation_type:
        if field_type != "relation":
            print_warning(
                "--relation-database/--relation-type only apply to relation fields."
            )
            raise typer.Exit(1)
        # Default to the existing relation type when only the target changes.
        resolved_type = relation_type or field_def.get("relation", {}).get(
            "type", "dual_property"
        )
        if resolved_type not in RELATION_TYPES:
            print_warning(
                f"--relation-type must be one of {', '.join(RELATION_TYPES)}"
            )
            raise typer.Exit(1)
        # Default to the existing target when only the type changes.
        if relation_database:
            relation_data_source_id = client.get_data_source_id(relation_database)
        else:
            relation_data_source_id = field_def.get("relation", {}).get(
                "data_source_id"
            )
            if not relation_data_source_id:
                print_warning(
                    "Cannot resolve the current relation target. "
                    "Pass --relation-database to set it explicitly."
                )
                raise typer.Exit(1)
        # API 2025-09-03 requires relation.data_source_id (NOT database_id).
        update["relation"] = {
            "data_source_id": relation_data_source_id,
            "type": resolved_type,
            resolved_type: {},
        }

    if not update:
        print_warning(
            "No updates specified. Use --name, --options, --number-format, "
            "--formula-expression, or --relation-database."
        )
        raise typer.Exit(1)

    # Apply update
    properties = {name: update}
    updated_db = client.update_database(database_id, properties=properties)

    # Get updated field (might have new name)
    result_name = new_name if new_name else name
    updated_field = updated_db.get("properties", {}).get(result_name, {})

    print_json({
        "name": result_name,
        "type": updated_field.get("type", field_type),
        "id": updated_field.get("id", ""),
    })
    print_success(f"Field '{name}' updated successfully.")


COMMAND_CREDENTIALS = {
    "add": [
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
    "option": [
        "custom"
    ],
    "rename": [
        "custom"
    ],
    "update": [
        "custom"
    ]
}
