"""Project commands for Things CLI."""
import typer
from typing import Optional, List

from pydantic import BaseModel

from cli_tools_shared.filters import apply_filters
from ..client import get_client
from cli_tools_shared.output import print_json, print_table, print_info, handle_error


app = typer.Typer(help="Manage projects", no_args_is_help=True)


def model_to_dict(item):
    """Convert model or dict to dict for field extraction."""
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


def extract_field(item, field: str):
    """Extract a field value, supporting dot-notation for nested fields."""
    data = model_to_dict(item)
    parts = field.split(".")
    value = data
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def extract_fields(items: list, fields: list) -> list:
    """Extract specified fields from items, supporting dot-notation."""
    result = []
    for item in items:
        extracted = {}
        for field in fields:
            value = extract_field(item, field)
            extracted[field] = value
        result.append(extracted)
    return result


@app.command("list")
def projects_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of items"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
    area: Optional[str] = typer.Option(None, "--area", help="Filter by area UUID"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status: incomplete, completed"),
    exclude_tag: Optional[List[str]] = typer.Option(None, "--exclude-tag", help="Drop projects tagged with this tag (case-sensitive, repeatable; union exclusion)"),
):
    """
    List projects.

    Examples:
        things projects list
        things projects list --area AREA_UUID
        things projects list --status incomplete
        things projects list --properties "uuid,title,status"
        things projects list --table
        things projects list --exclude-tag WF
        things projects list --exclude-tag WF --exclude-tag SomeOther
    """
    try:
        client = get_client()
        projects = client.list_projects(
            area=area,
            status=status,
            limit=limit,
        )

        # Drop items tagged with any of the excluded tags (case-sensitive)
        if exclude_tag:
            excluded = set(exclude_tag)
            projects = [p for p in projects if not (set(model_to_dict(p).get("tags") or []) & excluded)]

        # Apply client-side filters if provided
        if filter:
            projects_dicts = [model_to_dict(p) for p in projects]
            projects = apply_filters(projects_dicts, filter)

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            projects = extract_fields(projects, fields)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(projects, fields, fields)
            else:
                print_table(
                    projects,
                    ["uuid", "title", "status", "start", "deadline"],
                    ["UUID", "Title", "Status", "When", "Deadline"],
                )
        else:
            print_json(projects)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def projects_get(
    uuid: str = typer.Argument(..., help="The project UUID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """
    Get a specific project by UUID.

    Examples:
        things projects get UUID
        things projects get UUID --table
        things projects get UUID --properties "title,notes"
    """
    try:
        client = get_client()
        project = client.get_project(uuid)

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            project = extract_fields([project], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([project], fields, fields)
            else:
                item_dict = model_to_dict(project)
                rows = [{"field": k, "value": str(v)} for k, v in item_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(project)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def projects_create(
    title: str = typer.Argument(..., help="Project title"),
    notes: Optional[str] = typer.Option(None, "--notes", "-n", help="Project notes"),
    area: Optional[str] = typer.Option(None, "--area", help="Area UUID"),
    when: Optional[str] = typer.Option(None, "--when", "-w", help="When: anytime, someday"),
):
    """
    Create a new project.

    Examples:
        things projects create "Home Renovation"
        things projects create "Q1 Goals" --area AREA_UUID
        things projects create "Backlog Project" --when someday
    """
    try:
        client = get_client()
        project = client.create_project(
            title=title,
            notes=notes,
            area=area,
            when=when,
        )

        print_info(f"Created project: {project.uuid}")
        print_json(project)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("complete")
def projects_complete(
    uuid: str = typer.Argument(..., help="The project UUID"),
):
    """
    Mark a project as completed.

    Example:
        things projects complete UUID
    """
    try:
        client = get_client()
        project = client.complete_project(uuid)

        print_info(f"Completed: {project.title}")
        print_json(project)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def projects_delete(
    uuid: str = typer.Argument(..., help="The project UUID"),
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """
    Delete a project (move to trash).

    Example:
        things projects delete UUID
        things projects delete UUID --yes
    """
    try:
        client = get_client()

        if not confirm:
            project = client.get_project(uuid)
            if not typer.confirm(f"Delete project '{project.title}'?"):
                print_info("Cancelled")
                raise typer.Exit(0)

        result = client.delete_project(uuid)
        print_info(f"Deleted: {result['title']}")
        print_json(result)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def projects_update(
    uuid: str = typer.Argument(..., help="The project UUID"),
    title: Optional[str] = typer.Option(None, "--title", help="New title"),
    notes: Optional[str] = typer.Option(None, "--notes", "-n", help="New notes"),
    area: Optional[str] = typer.Option(None, "--area", help="Area UUID, or empty string to remove from area"),
    when: Optional[str] = typer.Option(None, "--when", "-w", help="When: anytime, someday"),
    deadline: Optional[str] = typer.Option(None, "--deadline", "-d", help="Deadline (ISO date), or empty string to clear"),
    tags: Optional[str] = typer.Option(None, "--tags", help="Comma-separated tag titles (replaces existing)"),
):
    """
    Update a project.

    Examples:
        things projects update UUID --title "New title"
        things projects update UUID --notes "Updated notes"
        things projects update UUID --area AREA_UUID
        things projects update UUID --area ""  # Remove from area
        things projects update UUID --when someday
        things projects update UUID --deadline 2024-12-31
        things projects update UUID --tags "work,Q1"
    """
    try:
        client = get_client()
        tag_list = [t.strip() for t in tags.split(",")] if tags else None

        project = client.update_project(
            uuid=uuid,
            title=title,
            notes=notes,
            area=area,
            when=when,
            deadline=deadline,
            tags=tag_list,
        )

        print_info(f"Updated: {project.title}")
        print_json(project)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("search")
def projects_search(
    query: str = typer.Argument(..., help="Search query (matches title)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """
    Search projects by title.

    Examples:
        things projects search "home"
        things projects search "work" --table
    """
    try:
        client = get_client()
        projects = client.list_projects(limit=limit)

        # Filter by title OR area name containing query (case-insensitive)
        query_lower = query.lower()
        projects = [
            p for p in projects
            if query_lower in p.title.lower()
            or (p.area is not None and query_lower in p.area.lower())
        ]

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            projects = extract_fields(projects, fields)

        if table:
            if projects:
                if properties:
                    columns = [f.strip() for f in properties.split(",")]
                else:
                    columns = ["uuid", "title", "status", "start"]
                print_table(projects, columns, columns)
            else:
                print_info("No projects found matching the search query.")
        else:
            print_json(projects)

    except Exception as e:
        raise typer.Exit(handle_error(e))
