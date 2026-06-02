"""Reward commands for PartnerStack CLI."""
COMMAND_CREDENTIALS = {
    "list": ["api_key"],
    "get": ["api_key"],
}

import typer
from typing import Any, List, Optional

from pydantic import BaseModel

from ..client import get_client
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import handle_error, print_json, print_table


app = typer.Typer(help="List PartnerStack rewards", no_args_is_help=True)


def model_to_dict(item: Any) -> dict:
    """Convert a Pydantic model or dict to a dict for field extraction."""
    if isinstance(item, BaseModel):
        return item.model_dump(mode="json")
    if isinstance(item, dict):
        return item
    raise ClientError(f"Expected model or dict, got {type(item).__name__}")


def extract_field(item: Any, field: str) -> Any:
    """Extract a dot-notation field from a model or dict."""
    value: Any = model_to_dict(item)
    for part in field.split("."):
        if not isinstance(value, dict):
            raise ClientError(f"Field path '{field}' cannot descend into non-object value")
        if part not in value:
            raise ClientError(f"Field path '{field}' was not found")
        value = value[part]
    return value


def extract_fields(items: list, fields: list) -> list:
    """Extract selected dot-notation fields from each item."""
    return [{field: extract_field(item, field) for field in fields} for item in items]


def parse_properties(properties: str) -> List[str]:
    """Parse a comma-separated property list."""
    fields = [field.strip() for field in properties.split(",")]
    if not all(fields):
        raise ClientError("Properties must be a comma-separated list of field names")
    return fields


@app.command("list")
def rewards_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=250, help="Maximum rewards to return"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="API filter, e.g. payment_status:eq:withdrawn or created_at:gte:1711034344078",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include, with dot-notation support",
    ),
    starting_after: Optional[str] = typer.Option(None, "--starting-after", help="Pagination cursor"),
    ending_before: Optional[str] = typer.Option(None, "--ending-before", help="Pagination cursor"),
):
    """List rewards from the PartnerStack Partner API."""
    try:
        client = get_client()
        rewards = client.list_rewards(
            limit=limit,
            filters=filter,
            starting_after=starting_after,
            ending_before=ending_before,
        )

        if properties:
            fields = parse_properties(properties)
            rewards = extract_fields(rewards, fields)

        if table:
            if properties:
                columns = parse_properties(properties)
                print_table(rewards, columns, columns)
            else:
                columns = [
                    "key",
                    "company.name",
                    "amount",
                    "currency",
                    "payment_status",
                    "reward_status",
                    "description",
                ]
                table_rows = extract_fields(rewards, columns)
                print_table(
                    table_rows,
                    columns,
                    [
                        "Key",
                        "Company",
                        "Amount",
                        "Currency",
                        "Payment",
                        "Reward",
                        "Description",
                    ],
                )
        else:
            print_json(rewards)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def rewards_get(
    reward_key: str = typer.Argument(..., help="Reward key"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include, with dot-notation support",
    ),
):
    """Get one reward by reward key."""
    try:
        client = get_client()
        reward = client.get_reward(reward_key)

        if properties:
            fields = parse_properties(properties)
            reward_output = extract_fields([reward], fields)[0]
        else:
            reward_output = reward

        if table:
            if properties:
                columns = parse_properties(properties)
                print_table([reward_output], columns, columns)
            else:
                reward_dict = model_to_dict(reward_output)
                rows = [{"field": key, "value": value} for key, value in reward_dict.items()]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(reward_output)
    except Exception as e:
        raise typer.Exit(handle_error(e))
