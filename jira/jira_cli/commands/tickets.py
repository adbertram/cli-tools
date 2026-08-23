"""Ticket commands for Jira CLI."""

from typing import List, Optional

import typer
from cli_tools_shared.filters import FilterValidationError, validate_filters
from cli_tools_shared.output import command, print_error, print_json, print_table

from ..client import get_client
from ..config import OAUTH_3LO_AUTH_TYPE

COMMAND_CREDENTIALS = {
    "list": [OAUTH_3LO_AUTH_TYPE, "custom"],
    "get": [OAUTH_3LO_AUTH_TYPE, "custom"],
    "create": [OAUTH_3LO_AUTH_TYPE, "custom"],
    "update": [OAUTH_3LO_AUTH_TYPE, "custom"],
    "delete": [OAUTH_3LO_AUTH_TYPE, "custom"],
    "comment": [OAUTH_3LO_AUTH_TYPE, "custom"],
    "transitions": [OAUTH_3LO_AUTH_TYPE, "custom"],
    "transition": [OAUTH_3LO_AUTH_TYPE, "custom"],
}

LIST_COLUMNS = ["key", "summary", "status", "issue_type", "project", "assignee", "updated"]

app = typer.Typer(help="Manage Jira tickets", no_args_is_help=True)


def _properties(value: Optional[str]) -> Optional[List[str]]:
    if value is None:
        return None
    fields = [field.strip() for field in value.split(",") if field.strip()]
    return fields or None


def _select_fields(rows: List[dict], properties: Optional[str]) -> List[dict]:
    fields = _properties(properties)
    if fields is None:
        return rows
    return [{field: row.get(field) for field in fields} for row in rows]


def _print_rows(rows: List[dict], *, table: bool, properties: Optional[str], columns: List[str]) -> None:
    rows = _select_fields(rows, properties)
    if table:
        selected_columns = _properties(properties) or columns
        print_table(rows, selected_columns, [column.replace("_", " ").title() for column in selected_columns])
        return
    print_json(rows)


def _validate_filters(filters: Optional[List[str]]) -> None:
    if not filters:
        return
    try:
        validate_filters(filters)
    except FilterValidationError as exc:
        print_error(str(exc))
        raise typer.Exit(1) from exc


def _labels(values: Optional[List[str]]) -> Optional[List[str]]:
    if not values:
        return None
    labels: List[str] = []
    for value in values:
        labels.extend(label.strip() for label in value.split(",") if label.strip())
    return labels or None


@app.command("list")
@command
def list_tickets(
    limit: int = typer.Option(100, "--limit", "-l", min=1, help="Maximum number of tickets"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter tickets (field:op:value)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    jql: Optional[str] = typer.Option(None, "--jql", help="Raw Jira JQL to use before structured filters"),
    next_page_token: Optional[str] = typer.Option(None, "--next-page-token", help="Jira search pagination token"),
):
    """List Jira tickets."""
    _validate_filters(filter)
    rows = get_client().list_tickets(
        limit=limit,
        jql=jql,
        filters=filter,
        next_page_token=next_page_token,
    )
    _print_rows(rows, table=table, properties=properties, columns=LIST_COLUMNS)


@app.command("get")
@command
def get_ticket(
    issue_id_or_key: str = typer.Argument(..., help="Jira issue id or key"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get a Jira ticket."""
    row = get_client().get_ticket(issue_id_or_key)
    if table and properties is None:
        print_table(
            [{"field": key, "value": value} for key, value in row.items()],
            ["field", "value"],
            ["Field", "Value"],
        )
        return
    if not table and properties is None:
        print_json(row)
        return
    _print_rows([row], table=table, properties=properties, columns=LIST_COLUMNS)


@app.command("create")
@command
def create_ticket(
    project: str = typer.Option(..., "--project", "-P", help="Jira project key"),
    summary: str = typer.Option(..., "--summary", "-s", help="Ticket summary"),
    issue_type: str = typer.Option("Task", "--issue-type", "-i", help="Jira issue type name"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Plain-text ticket description"),
    assignee: Optional[str] = typer.Option(None, "--assignee", "-a", help="Assignee account id"),
    priority: Optional[str] = typer.Option(None, "--priority", help="Priority name"),
    label: Optional[List[str]] = typer.Option(None, "--label", help="Label to add; repeat or comma-separate"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Create a Jira ticket."""
    row = get_client().create_ticket(
        project=project,
        issue_type=issue_type,
        summary=summary,
        description=description,
        assignee=assignee,
        priority=priority,
        labels=_labels(label),
    )
    _print_rows([row], table=table, properties=properties, columns=LIST_COLUMNS)


@app.command("update")
@command
def update_ticket(
    issue_id_or_key: str = typer.Argument(..., help="Jira issue id or key"),
    summary: Optional[str] = typer.Option(None, "--summary", "-s", help="Ticket summary"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Plain-text ticket description"),
    assignee: Optional[str] = typer.Option(None, "--assignee", "-a", help="Assignee account id"),
    priority: Optional[str] = typer.Option(None, "--priority", help="Priority name"),
    label: Optional[List[str]] = typer.Option(None, "--label", help="Replacement label; repeat or comma-separate"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Update a Jira ticket."""
    row = get_client().update_ticket(
        issue_id_or_key,
        summary=summary,
        description=description,
        assignee=assignee,
        priority=priority,
        labels=_labels(label),
    )
    _print_rows([row], table=table, properties=properties, columns=LIST_COLUMNS)


@app.command("delete")
@command
def delete_ticket(
    issue_id_or_key: str = typer.Argument(..., help="Jira issue id or key"),
    delete_subtasks: bool = typer.Option(False, "--delete-subtasks", help="Delete the issue's subtasks too"),
):
    """Delete a Jira ticket."""
    print_json(get_client().delete_ticket(issue_id_or_key, delete_subtasks=delete_subtasks))


@app.command("comment")
@command
def comment_ticket(
    issue_id_or_key: str = typer.Argument(..., help="Jira issue id or key"),
    body: str = typer.Option(..., "--body", "-b", help="Plain-text comment body"),
):
    """Add a comment to a Jira ticket."""
    print_json(get_client().add_comment(issue_id_or_key, body))


@app.command("transitions")
@command
def list_transitions(
    issue_id_or_key: str = typer.Argument(..., help="Jira issue id or key"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """List available transitions for a Jira ticket."""
    rows = get_client().list_transitions(issue_id_or_key)
    _print_rows(rows, table=table, properties=properties, columns=["id", "name", "to_name", "status_category"])


@app.command("transition")
@command
def transition_ticket(
    issue_id_or_key: str = typer.Argument(..., help="Jira issue id or key"),
    transition_id: str = typer.Option(..., "--transition-id", "-i", help="Transition id from tickets transitions"),
    comment: Optional[str] = typer.Option(None, "--comment", "-c", help="Plain-text comment to add during transition"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Transition a Jira ticket."""
    row = get_client().transition_ticket(issue_id_or_key, transition_id, comment=comment)
    _print_rows([row], table=table, properties=properties, columns=LIST_COLUMNS)
