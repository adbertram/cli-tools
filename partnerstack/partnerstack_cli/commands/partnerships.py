"""Partnership (post-approval) commands for PartnerStack CLI."""
COMMAND_CREDENTIALS = {
    "list": ["api_key"],
    "get": ["api_key"],
}

from typing import List, Optional

import typer

from ..client import get_client
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import handle_error, print_json, print_table

from ._common import extract_fields, model_to_dict, parse_properties


app = typer.Typer(help="List PartnerStack partnerships (post-approval relationships)", no_args_is_help=True)


@app.command("list")
def partnerships_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(10, "--limit", "-l", min=1, max=250, help="Maximum partnerships to return"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help=(
            "API filter. Supported: order_by:eq:<value>, has_sub_id:eq:<true|false|null>, "
            "include_offers:eq:<true|false>, include_archived:eq:<true|false>"
        ),
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
    """List partnerships (already-joined programs)."""
    try:
        client = get_client()
        partnerships = client.list_partnerships(
            limit=limit,
            filters=filter,
            starting_after=starting_after,
            ending_before=ending_before,
        )

        if properties:
            fields = parse_properties(properties)
            partnerships = extract_fields(partnerships, fields)

        if table:
            if properties:
                columns = parse_properties(properties)
                print_table(partnerships, columns, columns)
            else:
                columns = ["key", "company.name", "company.key", "status", "is_archived"]
                rows = extract_fields(partnerships, columns)
                print_table(
                    rows,
                    columns,
                    ["Key", "Company", "Company Key", "Status", "Archived"],
                )
        else:
            print_json(partnerships)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def partnerships_get(
    partnership_key: str = typer.Argument(..., help="Partnership key (or value of the model's `id`)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include, with dot-notation support",
    ),
):
    """Get one partnership by key.

    PartnerStack does not document a `GET /partnerships/{key}` endpoint; this
    command pages through `GET /api/v2/partnerships` (the documented partner
    endpoint) and returns the partnership whose `key` matches.
    """
    try:
        client = get_client()
        # Page through up to several batches to find the requested partnership.
        cursor: Optional[str] = None
        match = None
        for _ in range(20):  # bounded to avoid runaway pagination
            page = client.list_partnerships(limit=250, starting_after=cursor)
            if not page:
                break
            for partnership in page:
                if partnership.key == partnership_key:
                    match = partnership
                    break
            if match is not None:
                break
            if len(page) < 250:
                break
            cursor = page[-1].key

        if match is None:
            raise ClientError(f"No partnership found with key '{partnership_key}'")

        if properties:
            fields = parse_properties(properties)
            output = extract_fields([match], fields)[0]
        else:
            output = match

        if table:
            if properties:
                columns = parse_properties(properties)
                print_table([output], columns, columns)
            else:
                data = model_to_dict(output)
                rows = [{"field": k, "value": v} for k, v in data.items()]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(output)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


