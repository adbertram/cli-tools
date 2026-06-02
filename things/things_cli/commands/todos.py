"""Todo commands for Things CLI."""
import typer
from typing import Optional, List

from pydantic import BaseModel

from cli_tools_shared.filters import apply_filters
from ..client import get_client
from cli_tools_shared.output import print_json, print_table, print_info, handle_error


app = typer.Typer(help="Manage todos", no_args_is_help=True)


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


# Human-readable mappings for table display
STATUS_LABELS = {0: "Incomplete", 3: "Completed"}
START_LABELS = {0: "Inbox", 1: "Anytime", 2: "Someday"}


def format_for_table(todos: list) -> list:
    """Format todos for human-readable table display."""
    result = []
    for todo in todos:
        data = model_to_dict(todo)
        # Convert status to label
        status_val = data.get('status')
        if isinstance(status_val, int):
            data['status'] = STATUS_LABELS.get(status_val, str(status_val))
        # Convert start to label
        start_val = data.get('start')
        if isinstance(start_val, int):
            data['start'] = START_LABELS.get(start_val, str(start_val))
        result.append(data)
    return result


@app.command("list")
def todos_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of items"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
    when: Optional[str] = typer.Option(None, "--when", "-w", help="Filter by when: inbox, anytime, someday, today, upcoming"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status: incomplete, completed"),
    tag: Optional[str] = typer.Option(None, "--tag", help="Filter by tag title"),
    exclude_tag: Optional[List[str]] = typer.Option(None, "--exclude-tag", help="Drop todos tagged with this tag (case-sensitive, repeatable; union exclusion)"),
    area: Optional[str] = typer.Option(None, "--area", help="Filter by area UUID"),
    project: Optional[str] = typer.Option(None, "--project", help="Filter by project UUID"),
    next_actions: bool = typer.Option(False, "--next-actions", "-n", help="Show only actionable todos (no tags, in project, no WF task ahead)"),
    include_trashed: bool = typer.Option(False, "--include-trashed", help="Include todos from trashed projects"),
):
    """
    List todos.

    Examples:
        things todos list
        things todos list --when today
        things todos list --when anytime --limit 10
        things todos list --status completed
        things todos list --project PROJECT_UUID
        things todos list --properties "uuid,title,status"
        things todos list --table
        things todos list --exclude-tag WF
        things todos list --exclude-tag WF --exclude-tag SomeOther
        things todos list --tag work --exclude-tag WF
    """
    try:
        client = get_client()

        if next_actions:
            # Use specialized next actions query
            todos = client.list_next_actions(limit=limit)
        else:
            todos = client.list_todos(
                when=when,
                status=status,
                tag=tag,
                area=area,
                project=project,
                limit=limit,
                include_trashed=include_trashed,
            )

        # Drop items tagged with any of the excluded tags (case-sensitive)
        if exclude_tag:
            excluded = set(exclude_tag)
            todos = [t for t in todos if not (set(model_to_dict(t).get("tags") or []) & excluded)]

        # Apply client-side filters if provided
        if filter:
            todos_dicts = [model_to_dict(t) for t in todos]
            todos = apply_filters(todos_dicts, filter)

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            todos = extract_fields(todos, fields)

        if table:
            formatted = format_for_table(todos)
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(formatted, fields, fields)
            else:
                print_table(
                    formatted,
                    ["title", "project", "area", "status", "deadline"],
                    ["Title", "Project", "Area", "Status", "Deadline"],
                )
        else:
            print_json(todos)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def todos_get(
    uuid: str = typer.Argument(..., help="The todo UUID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """
    Get a specific todo by UUID.

    Examples:
        things todos get UUID
        things todos get UUID --table
        things todos get UUID --properties "title,notes,deadline"
    """
    try:
        client = get_client()
        todo = client.get_todo(uuid)

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            todo = extract_fields([todo], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([todo], fields, fields)
            else:
                item_dict = model_to_dict(todo)
                rows = [{"field": k, "value": str(v)} for k, v in item_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(todo)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def todos_create(
    title: str = typer.Argument(..., help="Todo title"),
    notes: Optional[str] = typer.Option(None, "--notes", "-n", help="Todo notes"),
    when: Optional[str] = typer.Option(None, "--when", "-w", help="When: inbox, anytime, someday, or ISO date"),
    deadline: Optional[str] = typer.Option(None, "--deadline", "-d", help="Deadline (ISO date)"),
    tags: Optional[str] = typer.Option(None, "--tags", help="Comma-separated tag titles"),
    project: Optional[str] = typer.Option(None, "--project", help="Project UUID"),
    area: Optional[str] = typer.Option(None, "--area", help="Area UUID (places todo directly in an area, without a project)"),
):
    """
    Create a new todo.

    Examples:
        things todos create "Buy groceries"
        things todos create "Review document" --when today
        things todos create "Call John" --deadline 2024-12-31
        things todos create "Task" --project PROJECT_UUID --tags "work,urgent"
        things todos create "Some task" --area AREA_UUID --tags "WF"
    """
    try:
        client = get_client()
        tag_list = [t.strip() for t in tags.split(",")] if tags else None

        todo = client.create_todo(
            title=title,
            notes=notes,
            when=when,
            deadline=deadline,
            tags=tag_list,
            project=project,
            area=area,
        )

        print_info(f"Created todo: {todo.uuid}")
        print_json(todo)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("complete")
def todos_complete(
    uuid: str = typer.Argument(..., help="The todo UUID"),
):
    """
    Mark a todo as completed.

    Example:
        things todos complete UUID
    """
    try:
        client = get_client()
        todo = client.complete_todo(uuid)

        print_info(f"Completed: {todo.title}")
        print_json(todo)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("uncomplete")
def todos_uncomplete(
    uuid: str = typer.Argument(..., help="The todo UUID"),
):
    """
    Mark a completed todo as incomplete.

    Example:
        things todos uncomplete UUID
    """
    try:
        client = get_client()
        todo = client.uncomplete_todo(uuid)

        print_info(f"Uncompleted: {todo.title}")
        print_json(todo)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def todos_delete(
    uuid: str = typer.Argument(..., help="The todo UUID"),
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """
    Delete a todo (move to trash).

    Example:
        things todos delete UUID
        things todos delete UUID --yes
    """
    try:
        client = get_client()

        if not confirm:
            todo = client.get_todo(uuid)
            if not typer.confirm(f"Delete todo '{todo.title}'?"):
                print_info("Cancelled")
                raise typer.Exit(0)

        result = client.delete_todo(uuid)
        print_info(f"Deleted: {result['title']}")
        print_json(result)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def todos_update(
    uuid: str = typer.Argument(..., help="The todo UUID"),
    title: Optional[str] = typer.Option(None, "--title", help="New title"),
    notes: Optional[str] = typer.Option(None, "--notes", "-n", help="New notes"),
    when: Optional[str] = typer.Option(None, "--when", "-w", help="When: inbox, today, tomorrow, evening, anytime, someday, or ISO date"),
    deadline: Optional[str] = typer.Option(None, "--deadline", "-d", help="Deadline (ISO date), or empty string to clear"),
    tags: Optional[str] = typer.Option(None, "--tags", help="Comma-separated tag titles (replaces existing)"),
    project: Optional[str] = typer.Option(None, "--project", help="Move todo to project UUID. Mutually exclusive with --area."),
    area: Optional[str] = typer.Option(None, "--area", help="Move todo to area UUID (detaches from any project). Mutually exclusive with --project."),
):
    """
    Update a todo.

    Examples:
        things todos update UUID --title "New title"
        things todos update UUID --notes "Updated notes"
        things todos update UUID --when today
        things todos update UUID --deadline 2024-12-31
        things todos update UUID --deadline ""  # Clear deadline
        things todos update UUID --tags "work,urgent"
        things todos update UUID --project PROJECT_UUID
        things todos update UUID --area AREA_UUID
    """
    try:
        if project is not None and area is not None:
            typer.echo("Pass only one of --project or --area, not both.", err=True)
            raise typer.Exit(2)

        client = get_client()
        tag_list = [t.strip() for t in tags.split(",")] if tags else None

        todo = client.update_todo(
            uuid=uuid,
            title=title,
            notes=notes,
            when=when,
            deadline=deadline,
            tags=tag_list,
            project=project,
            area=area,
        )

        print_info(f"Updated: {todo.title}")
        print_json(todo)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("search")
def todos_search(
    query: str = typer.Argument(..., help="Search query (matches title)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """
    Search todos by title.

    Examples:
        things todos search "groceries"
        things todos search "meeting" --table
    """
    try:
        client = get_client()
        # Use list with a filter pattern - we'll implement a basic search
        todos = client.list_todos(limit=limit)

        # Filter by title containing query (case-insensitive)
        query_lower = query.lower()
        todos = [t for t in todos if query_lower in t.title.lower()]

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            todos = extract_fields(todos, fields)

        if table:
            if todos:
                if properties:
                    columns = [f.strip() for f in properties.split(",")]
                else:
                    columns = ["uuid", "title", "status", "start"]
                print_table(todos, columns, columns)
            else:
                print_info("No todos found matching the search query.")
        else:
            print_json(todos)

    except Exception as e:
        raise typer.Exit(handle_error(e))
