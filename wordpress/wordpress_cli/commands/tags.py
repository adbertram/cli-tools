"""Tags commands for WordPress CLI."""
import typer
from typing import Optional, List

from cli_tools_shared.output import print_json, print_table, handle_error, print_success, print_info
from ..filter_map import wordpress_filter_map
from . import model_to_dict, extract_fields, apply_client_side_filters


app = typer.Typer(help="Manage WordPress tags")

COMMAND_CREDENTIALS = {
    "create": [
        "username_password"
    ],
    "delete": [
        "username_password"
    ],
    "get": [
        "username_password"
    ],
    "list": [
        "username_password"
    ],
    "update": [
        "username_password"
    ]
}


def get_client():
    from ..client import get_client as _get_client
    return _get_client()


@app.command("list")
def tags_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of tags to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
):
    """List WordPress tags."""
    try:
        client = get_client()

        filters = wordpress_filter_map.to_api_params(filter) if filter else {}
        tags = client.list_tags(limit=limit, filters=filters)

        # Apply client-side filtering for fields without API translators
        tags = apply_client_side_filters(tags, filter)

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            tags = extract_fields(tags, fields)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(tags, fields, fields)
            else:
                print_table(
                    tags,
                    ["id", "name", "slug", "count"],
                    ["ID", "Name", "Slug", "Count"],
                )
        else:
            print_json(tags)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def tags_get(
    tag_id: int = typer.Argument(..., help="The tag ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
):
    """Get details for a specific WordPress tag."""
    try:
        client = get_client()
        tag = client.get_tag(tag_id)

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            tag = extract_fields([tag], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([tag], fields, fields)
            else:
                tag_dict = model_to_dict(tag)
                rows = [{"field": k, "value": str(v)} for k, v in tag_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(tag)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def tags_create(
    name: str = typer.Option(..., "--name", "-n", help="Tag name"),
    slug: Optional[str] = typer.Option(None, "--slug", "-s", help="URL slug for the tag"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Tag description"),
):
    """Create a new WordPress tag. Returns existing tag if name already exists."""
    try:
        client = get_client()

        # Get existing tags to detect duplicates
        existing_tags = client.list_tags(limit=100, filters={"search": name})
        existing_tag = None
        for tag in existing_tags:
            if tag.name.lower() == name.lower():
                existing_tag = tag
                break

        print_info(f"Creating tag: {name}")
        tag = client.create_tag(
            name=name,
            slug=slug,
            description=description,
        )

        if existing_tag and tag.id == existing_tag.id:
            print_success(f"Tag already exists (ID: {tag.id})")
        else:
            print_success(f"Tag created successfully (ID: {tag.id})")
        print_json(tag)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def tags_update(
    tag_id: int = typer.Argument(..., help="The tag ID to update"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="New tag name"),
    slug: Optional[str] = typer.Option(None, "--slug", "-s", help="New URL slug"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="New description"),
):
    """Update an existing WordPress tag."""
    try:
        client = get_client()

        fields = {}
        if name is not None:
            fields["name"] = name
        if slug is not None:
            fields["slug"] = slug
        if description is not None:
            fields["description"] = description

        if not fields:
            raise ValueError("Must provide at least one field to update (--name, --slug, or --description)")

        print_info(f"Updating tag {tag_id}")
        tag = client.update_tag(tag_id, fields)

        print_success(f"Tag {tag_id} updated successfully")
        print_json(tag)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def tags_delete(
    tag_id: int = typer.Argument(..., help="The tag ID to delete"),
):
    """Delete a WordPress tag."""
    try:
        client = get_client()

        print_info(f"Permanently deleting tag {tag_id}")

        result = client.delete_tag(tag_id)

        print_success(f"Tag {tag_id} permanently deleted")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))
