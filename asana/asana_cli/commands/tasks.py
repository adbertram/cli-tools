"""Task commands for Asana CLI."""
import typer
from typing import Optional, List
from ..client import get_client
from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
from cli_tools_shared.output import print_json, print_table, handle_error, print_success

app = typer.Typer(help="Manage Asana tasks")


def extract_field(data, field_path: str):
    """Extract a field value using dot notation (e.g., 'assignee.name')."""
    parts = field_path.split(".")
    value = data
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit():
            idx = int(part)
            value = value[idx] if idx < len(value) else None
        else:
            return None
        if value is None:
            return None
    return value


@app.command("list")
def task_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    assignee: Optional[str] = typer.Option(None, "--assignee", "-a", help="Assignee ID or 'me'"),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="Workspace ID"),
    limit: Optional[int] = typer.Option(100, "--limit", "-l", help="Limit number of results"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output single field (e.g., 'gid', 'name', 'assignee.name')"),
    filter_: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
):
    """List tasks. Requires either project, assignee, or workspace."""
    try:
        # Validate filters first
        if filter_:
            try:
                validate_filters(filter_)
            except FilterValidationError as e:
                typer.echo(f"Filter error: {e}", err=True)
                raise typer.Exit(1)

        client = get_client()
        tasks = client.list_tasks(
            project_id=project,
            assignee=assignee,
            workspace_id=workspace,
            limit=limit
        )

        # Apply filters if provided
        if filter_:
            tasks = apply_filters(tasks, filter_)

        if output:
            # Output just the specified field from each task
            for task in tasks:
                value = extract_field(task, output)
                if value is not None:
                    print(value)
        elif table:
            print_table(
                tasks,
                ["gid", "name", "completed"],
                ["ID", "Name", "Completed"]
            )
        else:
            print_json(tasks)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("search")
def task_search(
    query: str = typer.Argument(..., help="Search query (supports wildcards: * for any chars, ? for single char)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="Workspace ID"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Limit number of results"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output single field (e.g., 'gid', 'name')"),
):
    """Search tasks with wildcard query. Searches name, notes, and assignee."""
    try:
        client = get_client()
        tasks = client.search_tasks(
            query=query,
            project_id=project,
            workspace_id=workspace,
            limit=limit
        )

        if output:
            for task in tasks:
                value = extract_field(task, output)
                if value is not None:
                    print(value)
        elif table:
            print_table(
                tasks,
                ["gid", "name", "completed"],
                ["ID", "Name", "Completed"]
            )
        else:
            print_json(tasks)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def task_get(
    task_id: str = typer.Argument(..., help="Task ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output single field (e.g., 'gid', 'name', 'assignee.name', 'custom_fields.0.display_value')"),
):
    """Get task details."""
    try:
        client = get_client()
        task = client.get_task(task_id)

        if output:
            value = extract_field(task, output)
            if value is not None:
                print(value)
        elif table:
            # Flatten for table display
            data = {
                "gid": task.get("gid"),
                "name": task.get("name"),
                "completed": task.get("completed"),
                "assignee": (task.get("assignee") or {}).get("name", "Unassigned"),
                "due_on": task.get("due_on", ""),
            }
            print_table([data], list(data.keys()), ["ID", "Name", "Completed", "Assignee", "Due"])
        else:
            print_json(task)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def task_create(
    name: str = typer.Argument(..., help="Task name"),
    project: Optional[List[str]] = typer.Option(None, "--project", "-p", help="Project ID (can repeat)"),
    assignee: Optional[str] = typer.Option(None, "--assignee", "-a", help="Assignee ID"),
    notes: Optional[str] = typer.Option(None, "--notes", "-n", help="Task notes"),
    due_on: Optional[str] = typer.Option(None, "--due", "-d", help="Due date (YYYY-MM-DD)"),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="Workspace ID"),
):
    """Create a new task."""
    try:
        client = get_client()
        task = client.create_task(
            name=name,
            workspace_id=workspace,
            projects=list(project) if project else None,
            assignee=assignee,
            notes=notes,
            due_on=due_on,
        )

        print_success(f"Task created: {task['gid']}")
        print_json(task)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def task_update(
    task_id: str = typer.Argument(..., help="Task ID"),
    name: Optional[str] = typer.Option(None, "--name", help="Task name"),
    notes: Optional[str] = typer.Option(None, "--notes", "-n", help="Task notes"),
    assignee: Optional[str] = typer.Option(None, "--assignee", "-a", help="Assignee ID"),
    due_on: Optional[str] = typer.Option(None, "--due", "-d", help="Due date (YYYY-MM-DD)"),
    completed: Optional[bool] = typer.Option(None, "--completed", help="Mark as completed"),
):
    """Update a task."""
    try:
        client = get_client()

        # Build update data from provided options
        updates = {}
        if name is not None:
            updates["name"] = name
        if notes is not None:
            updates["notes"] = notes
        if assignee is not None:
            updates["assignee"] = assignee
        if due_on is not None:
            updates["due_on"] = due_on
        if completed is not None:
            updates["completed"] = completed

        if not updates:
            print_success("No updates provided")
            raise typer.Exit(0)

        task = client.update_task(task_id, **updates)

        print_success(f"Task updated: {task_id}")
        print_json(task)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("complete")
def task_complete(
    task_id: str = typer.Argument(..., help="Task ID"),
):
    """Mark task as complete."""
    try:
        client = get_client()
        task = client.complete_task(task_id)

        print_success(f"Task completed: {task_id}")
        print_json(task)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def task_delete(
    task_id: str = typer.Argument(..., help="Task ID"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Delete a task."""
    try:
        if not force:
            # Get task name for confirmation
            client = get_client()
            task = client.get_task(task_id)
            task_name = task.get("name", "Unknown")
            confirm = typer.confirm(f"Delete task '{task_name}' ({task_id})?")
            if not confirm:
                print_success("Cancelled")
                raise typer.Exit(0)

        client = get_client()
        client.delete_task(task_id)

        print_success(f"Task deleted: {task_id}")
    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "complete": [
        "custom"
    ],
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
    "search": [
        "custom"
    ],
    "update": [
        "custom"
    ]
}
