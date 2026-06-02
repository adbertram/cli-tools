"""Database commands for Notion CLI."""
import json
import typer
from typing import Optional, List, Dict

from ..client import get_client
from cli_tools_shared.filters import validate_filters, FilterValidationError, apply_filters
from cli_tools_shared import FilterMap
from ..output import (
    print_json,
    print_table,
    handle_error,
    format_page_for_display,
    print_success,
    print_warning,
    blocks_to_markdown,
    text_to_blocks,
)

app = typer.Typer(help="Query and manage databases")
page_app = typer.Typer(help="Get and update individual pages")
content_app = typer.Typer(help="Manage page content (blocks)")
template_app = typer.Typer(help="Manage database page templates")
app.add_typer(page_app, name="page")
app.add_typer(template_app, name="template")
page_app.add_typer(content_app, name="content")


# Note: Filter map could be used for more complex API translations in the future
_database_filter_map = FilterMap()


def build_filter_from_standard(
    filter_strings: Optional[List[str]] = None,
    schema: Optional[Dict[str, str]] = None,
) -> Optional[dict]:
    """
    Build Notion API filter object from standard field:op:value filter strings.

    Args:
        filter_strings: List of standard filter strings (e.g., ["Status:eq:Done", "Priority:eq:High"])
        schema: Optional dict mapping property names to their types (e.g., {"Phase": "status", "Priority": "select"})

    Returns:
        Notion API filter object or None
    """
    if not filter_strings:
        return None

    # Validate filters first
    validate_filters(filter_strings)

    from cli_tools_shared.filters import parse_filter_string

    schema = schema or {}

    def get_property_type(field_name: str) -> Optional[str]:
        """Get property type from schema, trying case-insensitive match."""
        # Try exact match first
        if field_name in schema:
            return schema[field_name]
        # Try case-insensitive match
        field_lower = field_name.lower()
        for prop_name, prop_type in schema.items():
            if prop_name.lower() == field_lower:
                return prop_type
        return None

    def build_equals_filter(field: str, value: str, prop_type: Optional[str]) -> dict:
        """Build an equals filter based on property type."""
        if prop_type == "status":
            return {"property": field, "status": {"equals": value}}
        elif prop_type == "select":
            return {"property": field, "select": {"equals": value}}
        elif prop_type == "multi_select":
            return {"property": field, "multi_select": {"contains": value}}
        elif prop_type == "checkbox":
            return {"property": field, "checkbox": {"equals": value.lower() in ('true', '1', 'yes')}}
        elif prop_type == "number":
            try:
                return {"property": field, "number": {"equals": float(value)}}
            except (ValueError, TypeError):
                return {"property": field, "rich_text": {"equals": value}}
        elif prop_type == "date":
            return {"property": field, "date": {"equals": value}}
        elif prop_type in ("url", "email", "phone_number"):
            return {"property": field, prop_type: {"equals": value}}
        else:
            # Default to rich_text
            return {"property": field, "rich_text": {"equals": value}}

    def build_not_equals_filter(field: str, value: str, prop_type: Optional[str]) -> dict:
        """Build a not-equals filter based on property type."""
        if prop_type == "status":
            return {"property": field, "status": {"does_not_equal": value}}
        elif prop_type == "select":
            return {"property": field, "select": {"does_not_equal": value}}
        elif prop_type == "multi_select":
            return {"property": field, "multi_select": {"does_not_contain": value}}
        elif prop_type == "checkbox":
            return {"property": field, "checkbox": {"equals": value.lower() not in ('true', '1', 'yes')}}
        elif prop_type == "number":
            try:
                return {"property": field, "number": {"does_not_equal": float(value)}}
            except (ValueError, TypeError):
                return {"property": field, "rich_text": {"does_not_equal": value}}
        elif prop_type == "date":
            return {"property": field, "date": {"does_not_equal": value}}
        elif prop_type in ("url", "email", "phone_number"):
            return {"property": field, prop_type: {"does_not_equal": value}}
        else:
            # Default to rich_text
            return {"property": field, "rich_text": {"does_not_equal": value}}

    # Parse all filter strings and build Notion filter conditions
    all_conditions = []

    for filter_str in filter_strings:
        conditions = parse_filter_string(filter_str)
        for field, op, value in conditions:
            # Get property type from schema
            prop_type = get_property_type(field)

            if op in ('null', 'notnull'):
                filter_obj = {
                    "property": field,
                    "is_empty": True if op == 'null' else False,
                }
            elif op in ('gt', 'gte', 'lt', 'lte'):
                # Comparison operators - number or date
                notion_op_map = {
                    'gt': 'greater_than',
                    'gte': 'greater_than_or_equal_to',
                    'lt': 'less_than',
                    'lte': 'less_than_or_equal_to',
                }
                if prop_type == "date":
                    filter_obj = {
                        "property": field,
                        "date": {notion_op_map[op]: value},
                    }
                else:
                    # Default to number
                    try:
                        num_val = float(value)
                        filter_obj = {
                            "property": field,
                            "number": {notion_op_map[op]: num_val},
                        }
                    except (ValueError, TypeError):
                        # Fall back to text contains
                        filter_obj = {
                            "property": field,
                            "rich_text": {"contains": value},
                        }
            elif op == 'like' or op == 'ilike':
                # Text contains (Notion doesn't distinguish case sensitivity in contains)
                filter_obj = {
                    "property": field,
                    "rich_text": {"contains": value.replace('%', '')},
                }
            elif op == 'eq':
                filter_obj = build_equals_filter(field, value, prop_type)
            elif op == 'ne':
                filter_obj = build_not_equals_filter(field, value, prop_type)
            elif op == 'in':
                # OR logic: field matches any of the values (pipe-separated)
                options = [v.strip() for v in value.split('|')]
                if len(options) == 1:
                    filter_obj = build_equals_filter(field, options[0], prop_type)
                else:
                    # Multiple values: wrap in OR
                    or_conditions = [build_equals_filter(field, opt, prop_type) for opt in options]
                    filter_obj = {"or": or_conditions}
            elif op == 'nin':
                # AND logic: field does not match any of the values (pipe-separated)
                options = [v.strip() for v in value.split('|')]
                if len(options) == 1:
                    filter_obj = build_not_equals_filter(field, options[0], prop_type)
                else:
                    # Multiple values: wrap in AND (must not equal any)
                    and_conditions = [build_not_equals_filter(field, opt, prop_type) for opt in options]
                    filter_obj = {"and": and_conditions}
            elif op == 'contains':
                # Contains operator - works for text and multi_select
                if prop_type == "multi_select":
                    filter_obj = {"property": field, "multi_select": {"contains": value}}
                else:
                    filter_obj = {"property": field, "rich_text": {"contains": value}}
            else:
                # Unsupported operator - skip
                continue

            all_conditions.append(filter_obj)

    if not all_conditions:
        return None

    if len(all_conditions) == 1:
        return all_conditions[0]

    # Multiple conditions: combine with AND
    return {"and": all_conditions}


@app.command("get")
def database_get(
    database_id: str = typer.Argument(
        ...,
        help="The database ID to retrieve",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display as formatted table",
    ),
    data_source: Optional[str] = typer.Option(
        None,
        "--data-source",
        help="Specific data_source ID to use when the database container holds multiple data sources",
    ),
):
    """
    Get database metadata and information.

    Examples:
        notion database get abc123
        notion database get abc123 --table
        notion database get abc123 --data-source ds_xyz
    """
    try:
        client = get_client()
        db = client.get_database(database_id, data_source_id=data_source)

        # Format for display
        formatted = {
            "id": db.get("id", ""),
            "title": "".join(t.get("plain_text", "") for t in db.get("title", [])),
            "created_time": db.get("created_time", ""),
            "last_edited_time": db.get("last_edited_time", ""),
            "url": db.get("url", ""),
            "archived": db.get("archived", False),
            "is_inline": db.get("is_inline", False),
            "parent_type": db.get("parent", {}).get("type", ""),
            "property_count": len(db.get("properties", {})),
        }
        # Surface data_sources for the container case (helps users discover
        # the data_source IDs they may need to pass via --data-source).
        if "data_sources" in db:
            formatted["data_sources"] = db["data_sources"]
        if "resolved_data_source_id" in db:
            formatted["resolved_data_source_id"] = db["resolved_data_source_id"]

        if table:
            rows = [{"field": k, "value": str(v)} for k, v in formatted.items()]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(formatted)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("schema")
def database_schema(
    database_id: str = typer.Argument(
        ...,
        help="The database ID to get schema for",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display as formatted table",
    ),
    data_source: Optional[str] = typer.Option(
        None,
        "--data-source",
        help="Specific data_source ID when the database container holds multiple data sources",
    ),
):
    """
    Get database schema (property definitions).

    Examples:
        notion database schema abc123
        notion database schema abc123 --table
        notion database schema abc123 --data-source ds_xyz
    """
    try:
        client = get_client()
        db = client.get_database(database_id, data_source_id=data_source)

        schema = {
            "id": db.get("id", ""),
            "title": "".join(t.get("plain_text", "") for t in db.get("title", [])),
            "properties": {}
        }

        for prop_name, prop_def in db.get("properties", {}).items():
            schema["properties"][prop_name] = {
                "type": prop_def.get("type", ""),
                "id": prop_def.get("id", ""),
            }

            # Include options for select/multi_select/status
            prop_type = prop_def.get("type", "")
            if prop_type == "select":
                options = prop_def.get("select", {}).get("options", [])
                schema["properties"][prop_name]["options"] = [o.get("name") for o in options]
            elif prop_type == "multi_select":
                options = prop_def.get("multi_select", {}).get("options", [])
                schema["properties"][prop_name]["options"] = [o.get("name") for o in options]
            elif prop_type == "status":
                options = prop_def.get("status", {}).get("options", [])
                schema["properties"][prop_name]["options"] = [o.get("name") for o in options]

        if table:
            rows = []
            for prop_name, prop_info in schema["properties"].items():
                row = {
                    "property": prop_name,
                    "type": prop_info["type"],
                    "options": ", ".join(prop_info.get("options", [])) if prop_info.get("options") else "",
                }
                rows.append(row)
            print_table(rows, ["property", "type", "options"], ["Property", "Type", "Options"])
        else:
            print_json(schema)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


def format_database_for_list(db: dict) -> dict:
    """
    Format a database search result for list display.

    Args:
        db: Raw database from Notion search API

    Returns:
        Simplified record for display
    """
    # Extract title
    title = ""
    title_arr = db.get("title", [])
    title = "".join(t.get("plain_text", "") for t in title_arr)

    # Get parent info
    parent = db.get("parent", {})
    parent_type = parent.get("type", "")
    parent_id = ""
    if parent_type == "page_id":
        parent_id = parent.get("page_id", "")
    elif parent_type == "workspace":
        parent_id = "workspace"

    return {
        "id": db.get("id", ""),
        "title": title,
        "parent_type": parent_type,
        "parent_id": parent_id,
        "url": db.get("url", ""),
        "last_edited": db.get("last_edited_time", ""),
    }


@app.command("list")
def database_list(
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display as formatted table",
    ),
    sort: Optional[str] = typer.Option(
        None,
        "--sort",
        help="Sort direction by last edited time (asc/desc)",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
        help="Maximum number of results to return",
    ),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter using field:op:value format (e.g., title:like:%project%). Client-side filtering.",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to display (id,title,parent_type,parent_id,url,last_edited)",
    ),
):
    """
    List all accessible databases.

    Examples:
        notion database list
        notion database list --table
        notion database list --sort desc --limit 20
        notion database list --filter "title:like:%project%"
        notion database list --properties "title,last_edited" --table

    Note: Filtering is performed client-side as the Notion search API has limited filter support.
    """
    from cli_tools_shared.filters import apply_filters

    try:
        client = get_client()

        # Validate filters
        if filter:
            try:
                validate_filters(filter)
            except FilterValidationError as e:
                print_warning(str(e))
                raise typer.Exit(1)

        # Parse sort direction
        sort_direction = None
        if sort:
            if sort.lower() in ("desc", "descending"):
                sort_direction = "descending"
            elif sort.lower() in ("asc", "ascending"):
                sort_direction = "ascending"
            else:
                print_warning(f"Invalid sort value: {sort}. Use 'asc' or 'desc'.")
                raise typer.Exit(1)

        # List all databases (search with filter_type=data_source)
        results = client.search_all(
            query=None,
            filter_type="data_source",
            sort_direction=sort_direction,
            limit=limit,
        )

        if not results:
            typer.echo("No databases found.")
            raise typer.Exit(0)

        # Format results
        formatted = [format_database_for_list(db) for db in results]

        # Apply client-side filter if provided
        if filter:
            formatted = apply_filters(formatted, filter)

        if not formatted:
            typer.echo("No databases found matching filter.")
            raise typer.Exit(0)

        # Parse properties option
        display_columns = None
        display_headers = None
        if properties:
            prop_list = [p.strip() for p in properties.split(",")]
            display_columns = prop_list
            display_headers = [p.replace("_", " ").title() for p in prop_list]

        if table:
            cols = display_columns or ["id", "title", "parent_type", "last_edited"]
            hdrs = display_headers or ["ID", "Title", "Parent Type", "Last Edited"]
            print_table(formatted, columns=cols, headers=hdrs)
        else:
            # Filter properties for JSON output
            if display_columns:
                formatted = [{k: v for k, v in r.items() if k in display_columns} for r in formatted]
            print_json(formatted)

        typer.echo(f"\n{len(formatted)} database(s) found.", err=True)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@page_app.command("list")
def page_list(
    database_id: str = typer.Option(
        ...,
        "--database-id",
        "-d",
        help="The database ID to query",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display as formatted table",
    ),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter using field:op:value format (e.g., Status:eq:Done, Priority:like:%High%). Can be used multiple times.",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of properties to include in output",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
        help="Maximum number of results to return",
    ),
    sort_by: Optional[str] = typer.Option(
        None,
        "--sort",
        help="Sort by property (format: 'property' or 'property:asc/desc')",
    ),
    data_source: Optional[str] = typer.Option(
        None,
        "--data-source",
        help="Specific data_source ID when the database container holds multiple data sources",
    ),
):
    """
    List pages in a database with optional filtering.

    Filter Examples:
        notion database page list DB_ID --filter "Status:eq:Done"
        notion database page list DB_ID --filter "Status:In progress"  # eq is default
        notion database page list DB_ID --filter "Priority:eq:High" --filter "Status:ne:Archived"
        notion database page list DB_ID --filter "Complete:true"
        notion database page list DB_ID --filter "Name:like:%project%"

    Output Examples:
        notion database page list DB_ID --table
        notion database page list DB_ID --properties "Title,Status,Due Date"
        notion database page list DB_ID --limit 10
    """
    try:
        client = get_client()

        # Fetch database schema to get property types for filter building
        schema: Dict[str, str] = {}
        if filter:
            db = client.get_database(database_id, data_source_id=data_source)
            for prop_name, prop_def in db.get("properties", {}).items():
                schema[prop_name] = prop_def.get("type", "")

        # Build filter
        filter_obj = None

        try:
            if filter:
                filter_obj = build_filter_from_standard(filter, schema=schema)
        except (FilterValidationError, ValueError) as e:
            print_warning(str(e))
            raise typer.Exit(1)

        # Build sorts
        sorts = None
        if sort_by:
            parts = sort_by.split(":", 1)
            prop_name = parts[0]
            direction = parts[1] if len(parts) > 1 else "ascending"
            if direction.lower() in ("desc", "descending"):
                direction = "descending"
            else:
                direction = "ascending"
            sorts = [{"property": prop_name, "direction": direction}]

        # Query database with limit passed to API
        pages = client.query_database_all(
            database_id=database_id,
            filter_obj=filter_obj,
            sorts=sorts,
            limit=limit,
            data_source_id=data_source,
        )

        if not pages:
            typer.echo("No pages found.")
            raise typer.Exit(0)

        # Parse properties list
        props_list = None
        if properties:
            props_list = [p.strip() for p in properties.split(",")]

        # Format pages
        formatted = [format_page_for_display(p, props_list) for p in pages]

        if table:
            # Determine columns from first page
            if formatted:
                # Default columns: id, Title (or Name), Excerpt, Status
                all_cols = list(formatted[0].keys())
                # Find title column (could be "Title" or "Name")
                title_col = next((c for c in all_cols if c.lower() in ("title", "name")), None)
                # Build default columns in priority order
                default_cols = ["id"]
                if title_col:
                    default_cols.append(title_col)
                if "Excerpt" in all_cols:
                    default_cols.append("Excerpt")
                if "Status" in all_cols:
                    default_cols.append("Status")
                # Use default columns, or fall back to first few if none found
                display_cols = [c for c in default_cols if c in all_cols]
                if not display_cols:
                    display_cols = all_cols[:4]
                print_table(formatted, display_cols, display_cols)
        else:
            print_json(formatted)

        typer.echo(f"\n{len(formatted)} page(s) found.", err=True)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@page_app.command("get")
def page_get(
    page_id: str = typer.Argument(
        ...,
        help="The page ID to retrieve",
    ),
    include_blocks: bool = typer.Option(
        False,
        "--include-blocks",
        "-b",
        help="Include page content blocks in output",
    ),
    markdown: bool = typer.Option(
        False,
        "--markdown",
        "-m",
        help="Output blocks as markdown (requires --include-blocks)",
    ),
    out_file: Optional[str] = typer.Option(
        None,
        "--out-file",
        "-o",
        help="Write markdown content to file (requires --include-blocks --markdown)",
    ),
):
    """
    Get a specific page by ID.

    Examples:
        notion database page get abc123-def456
        notion database page get abc123-def456 --include-blocks
        notion database page get abc123-def456 --include-blocks --markdown
        notion database page get abc123-def456 --include-blocks --markdown --out-file content.md
    """
    try:
        client = get_client()
        page = client.get_page(page_id)

        formatted = format_page_for_display(page)

        # Fetch and include blocks if requested
        if include_blocks:
            blocks = client.get_block_children_all(page_id, recursive=True)
            if markdown:
                markdown_content = blocks_to_markdown(blocks)
                formatted["content"] = markdown_content

                # Write to file if requested
                if out_file:
                    with open(out_file, 'w', encoding='utf-8') as f:
                        f.write(markdown_content)
                    print_success(f"Markdown content written to {out_file}")
                    return
            else:
                formatted["blocks"] = blocks

        print_json(formatted)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


def build_property_value(prop_type: str, value: str) -> dict:
    """Build a Notion property value object from type and value."""
    if prop_type == "status":
        return {"status": {"name": value}}
    elif prop_type == "select":
        return {"select": {"name": value}}
    elif prop_type == "multi_select":
        # Value can be comma-separated for multiple selections
        names = [n.strip() for n in value.split(",")]
        return {"multi_select": [{"name": n} for n in names]}
    elif prop_type == "checkbox":
        return {"checkbox": value.lower() in ("true", "1", "yes")}
    elif prop_type == "number":
        return {"number": float(value)}
    elif prop_type == "url":
        return {"url": value}
    elif prop_type == "email":
        return {"email": value}
    elif prop_type == "phone_number":
        return {"phone_number": value}
    elif prop_type == "rich_text":
        return {"rich_text": [{"type": "text", "text": {"content": value}}]}
    elif prop_type == "title":
        return {"title": [{"type": "text", "text": {"content": value}}]}
    else:
        raise ValueError(f"Unsupported property type: {prop_type}")


@page_app.command("update")
def page_update(
    page_id: str = typer.Argument(
        ...,
        help="The page ID to update",
    ),
    set_status: Optional[List[str]] = typer.Option(
        None,
        "--status",
        "-s",
        help="Set status property (format: 'value' or 'property:value'). Repeatable.",
    ),
    set_select: Optional[List[str]] = typer.Option(
        None,
        "--select",
        help="Set select property (format: 'property:value'). Repeatable.",
    ),
    set_text: Optional[List[str]] = typer.Option(
        None,
        "--text",
        help="Set rich_text property (format: 'property:value'). Repeatable.",
    ),
    set_checkbox: Optional[List[str]] = typer.Option(
        None,
        "--checkbox",
        help="Set checkbox property (format: 'property:true/false'). Repeatable.",
    ),
    set_number: Optional[List[str]] = typer.Option(
        None,
        "--number",
        help="Set number property (format: 'property:value'). Repeatable.",
    ),
    set_url: Optional[List[str]] = typer.Option(
        None,
        "--url",
        help="Set url property (format: 'property:value'). Repeatable.",
    ),
    properties_json: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Raw JSON properties object (Notion API format)",
    ),
    archive: Optional[bool] = typer.Option(
        None,
        "--archive/--restore",
        help="Archive or restore the page",
    ),
):
    """
    Update a page's properties.

    Property Examples:
        notion database page update PAGE_ID --status "Done"
        notion database page update PAGE_ID --status "Status:In progress"
        notion database page update PAGE_ID --select "Priority:High"
        notion database page update PAGE_ID --select "Client:Acme" --select "Contact:Jane Doe"
        notion database page update PAGE_ID --text "Notes:Updated content"
        notion database page update PAGE_ID --checkbox "Complete:true"
        notion database page update PAGE_ID --number "Score:95"

    Archive/Restore:
        notion database page update PAGE_ID --archive
        notion database page update PAGE_ID --restore

    Raw JSON (for complex updates):
        notion database page update PAGE_ID --properties '{"Status": {"status": {"name": "Done"}}}'
    """
    try:
        client = get_client()

        properties = {}

        # Parse raw JSON properties if provided
        if properties_json:
            try:
                properties = json.loads(properties_json)
            except json.JSONDecodeError as e:
                print_warning(f"Invalid JSON in --properties: {e}")
                raise typer.Exit(1)

        # Build properties from individual options (each flag is repeatable)
        for status_val in set_status or []:
            parts = status_val.split(":", 1)
            if len(parts) == 2:
                prop_name, value = parts
            else:
                prop_name, value = "Status", status_val
            properties[prop_name] = build_property_value("status", value)

        for select_val in set_select or []:
            parts = select_val.split(":", 1)
            if len(parts) != 2:
                print_warning("--select requires 'property:value' format")
                raise typer.Exit(1)
            prop_name, value = parts
            properties[prop_name] = build_property_value("select", value)

        for text_val in set_text or []:
            parts = text_val.split(":", 1)
            if len(parts) != 2:
                print_warning("--text requires 'property:value' format")
                raise typer.Exit(1)
            prop_name, value = parts
            properties[prop_name] = build_property_value("rich_text", value)

        for checkbox_val in set_checkbox or []:
            parts = checkbox_val.split(":", 1)
            if len(parts) != 2:
                print_warning("--checkbox requires 'property:true/false' format")
                raise typer.Exit(1)
            prop_name, value = parts
            properties[prop_name] = build_property_value("checkbox", value)

        for number_val in set_number or []:
            parts = number_val.split(":", 1)
            if len(parts) != 2:
                print_warning("--number requires 'property:value' format")
                raise typer.Exit(1)
            prop_name, value = parts
            properties[prop_name] = build_property_value("number", value)

        for url_val in set_url or []:
            parts = url_val.split(":", 1)
            if len(parts) != 2:
                print_warning("--url requires 'property:value' format")
                raise typer.Exit(1)
            prop_name, value = parts
            properties[prop_name] = build_property_value("url", value)

        # Validate we have something to update
        if not properties and archive is None:
            print_warning("No updates specified. Use --status, --select, --text, --properties, or --archive/--restore")
            raise typer.Exit(1)

        # Perform update
        updated_page = client.update_page(
            page_id=page_id,
            properties=properties if properties else None,
            archived=archive,
        )

        formatted = format_page_for_display(updated_page)
        print_json(formatted)
        print_success(f"Page {page_id} updated successfully.")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@page_app.command("create")
def page_create(
    database_id: str = typer.Argument(
        ...,
        help="The database ID to create the page in",
    ),
    title: str = typer.Option(
        ...,
        "--title",
        "-t",
        help="Page title (auto-detects the database's title property)",
    ),
    set_status: Optional[List[str]] = typer.Option(
        None,
        "--status",
        "-s",
        help="Set status property (format: 'value' or 'property:value'). Repeatable.",
    ),
    set_select: Optional[List[str]] = typer.Option(
        None,
        "--select",
        help="Set select property (format: 'property:value'). Repeatable.",
    ),
    content_file: Optional[str] = typer.Option(
        None,
        "--content-file",
        "-f",
        help="File containing markdown content for the page body",
    ),
    blocks_file: Optional[str] = typer.Option(
        None,
        "--blocks-file",
        help="File containing Notion JSON blocks (from 'export --format notion-json')",
    ),
    from_template: Optional[str] = typer.Option(
        None,
        "--from-template",
        help="Create page from template (use template ID or 'default' for default template)",
    ),
    properties_json: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Raw JSON properties object (Notion API format)",
    ),
):
    """
    Create a new page in a database.

    Examples:
        notion database page create DB_ID --title "My Page"
        notion database page create DB_ID --title "My Page" --status "In progress"
        notion database page create DB_ID --title "My Page" --select "Client:Acme Corp"
        notion database page create DB_ID --title "My Page" --content-file content.md
        notion database page create DB_ID --title "My Page" --blocks-file blocks.json
        notion database page create DB_ID --title "My Page" --from-template default
        notion database page create DB_ID --title "My Page" --from-template TEMPLATE_ID
        notion database page create DB_ID --title "My Page" --properties '{"Priority": {"select": {"name": "High"}}}'

    Template Usage:
        Use --from-template with either:
        - 'default' to use the database's default template
        - A specific template ID (use 'notion database template list' to find IDs)

    Blocks File:
        Use --blocks-file to import raw Notion blocks (preserving rich formatting like
        callouts, colors, columns) exported via 'notion pages export --format notion-json'.

    Note: --content-file, --blocks-file, and --from-template are mutually exclusive.
    """
    try:
        client = get_client()

        # Validate mutually exclusive content options
        content_sources = sum(1 for x in [content_file, blocks_file, from_template] if x is not None)
        if content_sources > 1:
            print_warning("Only one of --content-file, --blocks-file, or --from-template can be specified")
            raise typer.Exit(1)

        properties = {}

        # Parse raw JSON properties if provided
        if properties_json:
            try:
                properties = json.loads(properties_json)
            except json.JSONDecodeError as e:
                print_warning(f"Invalid JSON in --properties: {e}")
                raise typer.Exit(1)

        # Get the database schema to find the title property name
        db_info = client.get_database(database_id)
        db_properties = db_info.get("properties", {})

        # Find the property with type "title"
        title_prop_name = None
        for prop_name, prop_config in db_properties.items():
            if prop_config.get("type") == "title":
                title_prop_name = prop_name
                break

        if not title_prop_name:
            print_warning("Could not find title property in database schema")
            raise typer.Exit(1)

        # Set title using the actual property name from the schema
        properties[title_prop_name] = build_property_value("title", title)

        # Build properties from individual options (each flag is repeatable)
        for status_val in set_status or []:
            parts = status_val.split(":", 1)
            if len(parts) == 2:
                prop_name, value = parts
            else:
                prop_name, value = "Status", status_val
            properties[prop_name] = build_property_value("status", value)

        for select_val in set_select or []:
            parts = select_val.split(":", 1)
            if len(parts) != 2:
                print_warning("--select requires 'property:value' format")
                raise typer.Exit(1)
            prop_name, value = parts
            properties[prop_name] = build_property_value("select", value)

        # Create page - with template, blocks file, content file, or plain
        if from_template:
            # Create from template
            use_default = from_template.lower() == "default"
            template_id = None if use_default else from_template

            created_page = client.create_page_from_template(
                database_id=database_id,
                properties=properties,
                template_id=template_id,
                use_default_template=use_default,
            )
            template_msg = "default template" if use_default else f"template {template_id}"
            print_success(f"Page created from {template_msg} (content applied asynchronously)")

        elif blocks_file:
            # Create with Notion JSON blocks
            with open(blocks_file, 'r', encoding='utf-8') as f:
                blocks = json.load(f)

            if not isinstance(blocks, list):
                print_warning("Blocks file must contain a JSON array of block objects")
                raise typer.Exit(1)

            # Create page without children first (to handle nesting limits)
            created_page = client.create_page(
                database_id=database_id,
                properties=properties,
            )

            # Upload blocks with nesting handling
            if blocks:
                page_id = created_page["id"]

                def progress_cb(stage, message):
                    typer.echo(f"  [{stage}] {message}", err=True)

                typer.echo(f"Uploading {len(blocks)} blocks...", err=True)
                created_count, _ = client._upload_blocks_with_nesting(
                    page_id, blocks, progress_callback=progress_cb
                )
                print_success(f"Page created with {created_count} blocks: {created_page.get('url', created_page.get('id'))}")
            else:
                print_success(f"Page created successfully: {created_page.get('url', created_page.get('id'))}")

        else:
            # Create without template — optional markdown content
            children = None
            if content_file:
                with open(content_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                children = text_to_blocks(content)

            created_page = client.create_page(
                database_id=database_id,
                properties=properties,
                children=children,
            )
            print_success(f"Page created successfully: {created_page.get('url', created_page.get('id'))}")

        formatted = format_page_for_display(created_page)
        print_json(formatted)

    except FileNotFoundError as e:
        print_warning(f"File not found: {e.filename or content_file or blocks_file}")
        raise typer.Exit(1)
    except json.JSONDecodeError as e:
        print_warning(f"Invalid JSON in blocks file: {e}")
        raise typer.Exit(1)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@page_app.command("delete")
def page_delete(
    page_id: str = typer.Argument(
        ...,
        help="The page ID to delete (archive)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-F",
        help="Skip confirmation prompt",
    ),
):
    """
    Delete (archive) a page.

    Note: Notion doesn't truly delete pages - this archives them.
    Archived pages can be restored using 'notion database page update PAGE_ID --restore'.

    Examples:
        notion database page delete abc123-def456
        notion database page delete abc123-def456 --force
    """
    try:
        client = get_client()

        # Confirm unless force flag is set
        if not force:
            confirm = typer.confirm(f"Archive page {page_id}?")
            if not confirm:
                typer.echo("Cancelled.")
                raise typer.Exit(0)

        # Archive the page
        updated_page = client.update_page(
            page_id=page_id,
            archived=True,
        )

        formatted = format_page_for_display(updated_page)
        print_json(formatted)
        print_success(f"Page {page_id} archived successfully.")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


# Supported image file extensions for Notion uploads
SUPPORTED_IMAGE_EXTENSIONS = {
    '.gif', '.heic', '.jpeg', '.jpg', '.png', '.svg', '.tif', '.tiff', '.webp', '.ico'
}


def _process_markdown_images(
    content: str,
    source_file: Optional[str],
    client,
) -> dict:
    """
    Scan markdown content for local image references and upload them to Notion.

    Args:
        content: Markdown content to scan
        source_file: Path to the source file (for resolving relative paths).
                    If None, relative paths cannot be resolved.
        client: Notion client instance

    Returns:
        Dictionary mapping original image paths to Notion file_upload IDs
    """
    import re
    from pathlib import Path

    image_uploads = {}

    # Find all image references: ![alt](path)
    image_pattern = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')

    for match in image_pattern.finditer(content):
        image_path = match.group(2)

        # Skip URLs - they use external type
        if image_path.startswith(('http://', 'https://')):
            continue

        # Skip if already processed
        if image_path in image_uploads:
            continue

        # Resolve path relative to source file
        if source_file:
            source_dir = Path(source_file).parent
            resolved_path = source_dir / image_path
        else:
            resolved_path = Path(image_path)

        # Validate file exists
        if not resolved_path.exists():
            typer.echo(f"Warning: Image file not found: {resolved_path}", err=True)
            continue

        # Validate file extension
        ext = resolved_path.suffix.lower()
        if ext not in SUPPORTED_IMAGE_EXTENSIONS:
            typer.echo(
                f"Warning: Unsupported image type '{ext}' for: {resolved_path}. "
                f"Supported: {', '.join(sorted(SUPPORTED_IMAGE_EXTENSIONS))}",
                err=True
            )
            continue

        # Upload the file
        try:
            typer.echo(f"Uploading image: {resolved_path.name}...", err=True)
            file_upload_id = client.upload_file(str(resolved_path))
            image_uploads[image_path] = file_upload_id
        except Exception as e:
            typer.echo(f"Warning: Failed to upload {resolved_path}: {e}", err=True)
            continue

    return image_uploads


@content_app.command("append")
def content_append(
    page_id: str = typer.Argument(
        ...,
        help="The page ID to append content to",
    ),
    text: Optional[str] = typer.Option(
        None,
        "--text",
        "-t",
        help="Text/markdown content to append",
    ),
    file: Optional[str] = typer.Option(
        None,
        "--file",
        "-f",
        help="File containing text/markdown content to append",
    ),
    paragraph: Optional[str] = typer.Option(
        None,
        "--paragraph",
        "-p",
        help="Add a simple paragraph block",
    ),
):
    """
    Append content blocks to a page.

    Automatically handles content larger than Notion's 100-block limit
    by splitting into chunks and uploading sequentially.

    Examples:
        notion database page content append PAGE_ID --text "Hello world"
        notion database page content append PAGE_ID --text "# Heading\\n\\nParagraph text"
        notion database page content append PAGE_ID --file content.md
        notion database page content append PAGE_ID --paragraph "Simple paragraph"

    Markdown Support:
        - # Heading 1, ## Heading 2, ### Heading 3
        - Bullet lists with - or *
        - Numbered lists with 1. 2. etc
        - Code blocks with ```language
        - Blockquotes with >
        - Todo items with - [ ] or - [x]
        - Horizontal rules with ---
        - Tables with | col1 | col2 |
        - Inline: **bold**, *italic*, `code`, [links](url)
    """
    try:
        client = get_client()

        # Determine content source
        content = None
        if text:
            content = text
        elif file:
            with open(file, 'r', encoding='utf-8') as f:
                content = f.read()
        elif paragraph:
            content = paragraph

        if not content:
            print_warning("No content specified. Use --text, --file, or --paragraph")
            raise typer.Exit(1)

        # Process and upload any local images in the content
        image_uploads = _process_markdown_images(content, file, client)

        # Convert to blocks (with image upload mappings)
        blocks = text_to_blocks(content, image_uploads=image_uploads)

        if not blocks:
            print_warning("No valid content blocks generated from input")
            raise typer.Exit(1)

        # Define progress callback for nesting-aware upload
        def nesting_progress_cb(stage, message):
            typer.echo(f"  [{stage}] {message}", err=True)

        # Show info if content is large
        if len(blocks) > 100:
            typer.echo(f"Content has {len(blocks)} blocks, uploading...", err=True)

        # Append blocks using nesting-aware method (handles Notion's 2-level nesting limit)
        created_count, _ = client._upload_blocks_with_nesting(
            page_id, blocks, progress_callback=nesting_progress_cb
        )

        print_success(f"Appended {created_count} block(s) to page {page_id}")
        print_json({"blocks_created": created_count, "page_id": page_id})

    except FileNotFoundError:
        print_warning(f"File not found: {file}")
        raise typer.Exit(1)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@content_app.command("set")
def content_set(
    page_id: str = typer.Argument(
        ...,
        help="The page ID to set content for",
    ),
    text: Optional[str] = typer.Option(
        None,
        "--text",
        "-t",
        help="Text/markdown content to set (replaces existing)",
    ),
    file: Optional[str] = typer.Option(
        None,
        "--file",
        "-f",
        help="File containing text/markdown content to set",
    ),
    json_file: Optional[str] = typer.Option(
        None,
        "--json-file",
        help="File containing Notion JSON blocks to set (from 'export --format notion-json')",
    ),
):
    """
    Replace all page content with new content.

    This clears existing content and sets new content.
    Automatically handles content larger than Notion's 100-block limit
    by splitting into chunks and uploading sequentially.

    Use --json-file to import raw Notion blocks (preserving rich formatting like
    callouts, colors, columns) exported via 'notion pages export --format notion-json'.

    Examples:
        notion database page content set PAGE_ID --text "New content"
        notion database page content set PAGE_ID --file content.md
        notion database page content set PAGE_ID --json-file blocks.json

    Markdown Support:
        - # Heading 1, ## Heading 2, ### Heading 3
        - Bullet lists with - or *
        - Numbered lists with 1. 2. etc
        - Code blocks with ```language
        - Blockquotes with >
        - Todo items with - [ ] or - [x]
        - Horizontal rules with ---
        - Tables with | col1 | col2 |
        - Inline: **bold**, *italic*, `code`, [links](url)
    """
    try:
        client = get_client()

        # Validate mutually exclusive options
        sources = sum(1 for x in [text, file, json_file] if x is not None)
        if sources == 0:
            print_warning("No content specified. Use --text, --file, or --json-file")
            raise typer.Exit(1)
        if sources > 1:
            print_warning("Only one of --text, --file, or --json-file can be specified")
            raise typer.Exit(1)

        # Determine content source
        if json_file:
            with open(json_file, 'r', encoding='utf-8') as f:
                blocks = json.load(f)
            if not isinstance(blocks, list):
                print_warning("JSON file must contain an array of block objects")
                raise typer.Exit(1)
        else:
            content = None
            if text:
                content = text
            elif file:
                with open(file, 'r', encoding='utf-8') as f:
                    content = f.read()

            # Process and upload any local images in the content
            image_uploads = _process_markdown_images(content, file, client)

            # Convert to blocks (with image upload mappings)
            blocks = text_to_blocks(content, image_uploads=image_uploads)

        if not blocks:
            print_warning("No valid content blocks generated from input")
            raise typer.Exit(1)

        # Clear existing content (single API call using erase_content flag)
        client.clear_page_content(page_id)

        # Upload blocks using nesting-aware method (handles Notion's 2-level nesting limit)
        def nesting_progress_cb(stage, message):
            typer.echo(f"  [{stage}] {message}", err=True)

        if len(blocks) > 100:
            typer.echo(f"Uploading {len(blocks)} blocks...", err=True)

        created_count, _ = client._upload_blocks_with_nesting(
            page_id, blocks, progress_callback=nesting_progress_cb
        )

        print_success(f"Replaced content with {created_count} block(s)")
        print_json({
            "page_id": page_id,
            "blocks_created": created_count,
        })

    except FileNotFoundError as e:
        print_warning(f"File not found: {e.filename or json_file or file}")
        raise typer.Exit(1)
    except json.JSONDecodeError as e:
        print_warning(f"Invalid JSON: {e}")
        raise typer.Exit(1)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@content_app.command("clear")
def content_clear(
    page_id: str = typer.Argument(
        ...,
        help="The page ID to clear content from",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-F",
        help="Skip confirmation prompt",
    ),
):
    """
    Clear all content from a page.

    Examples:
        notion database page content clear PAGE_ID
        notion database page content clear PAGE_ID --force
    """
    try:
        client = get_client()

        # Confirm unless force flag is set
        if not force:
            confirm = typer.confirm(f"Clear all content from page {page_id}?")
            if not confirm:
                typer.echo("Cancelled.")
                raise typer.Exit(0)

        # Clear content (single API call using erase_content flag)
        client.clear_page_content(page_id)

        print_success(f"Cleared all content from page {page_id}")
        print_json({"page_id": page_id, "cleared": True})

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


# =============================================================================
# Template Commands
# =============================================================================


@template_app.command("list")
def template_list(
    database_id: str = typer.Option(
        ...,
        "--database-id",
        "-d",
        help="The database ID to list templates for",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display as formatted table",
    ),
    name: Optional[str] = typer.Option(
        None,
        "--name",
        "-n",
        help="Filter templates by name (case-insensitive substring match)",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
        help="Maximum number of templates to return",
    ),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., name:eq:MyTemplate, is_default:eq:true)",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include in output",
    ),
):
    """
    List available page templates for a database.

    Examples:
        notion database template list --database-id DB_ID
        notion database template list --database-id DB_ID --table
        notion database template list --database-id DB_ID --name "Bug"
    """
    try:
        client = get_client()
        templates = client.list_templates_all(
            database_id=database_id,
            name=name,
            limit=limit,
        )

        # Apply client-side filtering
        if filter:
            templates = apply_filters(templates, filter)

        # Filter to requested properties if specified
        if properties:
            props_list = [p.strip() for p in properties.split(",")]
            filtered_templates = []
            for t in templates:
                filtered = {prop: t.get(prop) for prop in props_list if prop in t}
                filtered_templates.append(filtered)
            templates = filtered_templates

        if not templates:
            typer.echo("No templates found.")
            raise typer.Exit(0)

        if table:
            columns = ["name", "id", "is_default"] if not properties else props_list
            print_table(
                templates,
                columns=columns,
            )
        else:
            print_json(templates)

        typer.echo(f"\n{len(templates)} template(s) found.", err=True)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@template_app.command("get")
def template_get(
    database_id: str = typer.Argument(
        ...,
        help="The database ID containing the template",
    ),
    template_id: str = typer.Argument(
        ...,
        help="The template ID to retrieve",
    ),
):
    """
    Get a specific template by ID.

    Examples:
        notion database template get DB_ID TEMPLATE_ID
    """
    try:
        client = get_client()
        # List all templates and find the matching one
        templates = client.list_templates_all(database_id=database_id)

        template = None
        for t in templates:
            if t.get("id") == template_id:
                template = t
                break

        if not template:
            print_warning(f"Template {template_id} not found in database {database_id}")
            raise typer.Exit(1)

        print_json(template)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


COMMAND_CREDENTIALS = {
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "page": [
        "custom"
    ],
    "schema": [
        "custom"
    ],
    "template": [
        "custom"
    ]
}
