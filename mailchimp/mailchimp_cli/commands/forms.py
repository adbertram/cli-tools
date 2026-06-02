"""Signup form commands for Mailchimp CLI."""
import typer
from typing import List, Optional

from cli_tools_shared.filters import apply_filters, apply_limit, apply_properties_filter

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error, print_success

app = typer.Typer(help="Manage list signup forms")

COMMAND_CREDENTIALS = {
    "create": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ]
}


@app.command("list")
def forms_list(
    list_id: Optional[str] = typer.Argument(None, help="The list/audience ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Max forms to return"),
    filters: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include in output",
    ),
):
    """
    List signup forms for an audience/list.

    Examples:
        mailchimp forms list LIST_ID
        mailchimp forms list LIST_ID --table
    """
    try:
        client = get_client()
        if list_id is None:
            forms = client.list_all_signup_forms(count=limit)
        else:
            forms = client.list_signup_forms(list_id)

        forms = apply_filters(forms, filters)
        forms = apply_limit(forms, limit)
        forms = apply_properties_filter(forms, properties)

        if table:
            print_table(
                forms,
                ["list_id", "signup_form_url"],
                ["List ID", "Signup Form URL"],
            )
        else:
            print_json(forms)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def forms_get(
    list_id: str = typer.Argument(..., help="The list/audience ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get the default signup form for an audience/list.

    Examples:
        mailchimp forms get LIST_ID
        mailchimp forms get LIST_ID --table
    """
    try:
        client = get_client()
        form = client.get_signup_form(list_id)

        if table:
            print_table(
                [form],
                ["list_id", "signup_form_url"],
                ["List ID", "Signup Form URL"],
            )
        else:
            print_json(form)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def forms_create(
    list_id: str = typer.Argument(..., help="The list/audience ID"),
    header_text: str = typer.Option(..., "--header-text", help="Signup form header text"),
    signup_message: str = typer.Option(..., "--signup-message", help="Signup form message"),
    signup_thank_you_title: str = typer.Option(
        ...,
        "--thank-you-title",
        help="Signup form thank-you title",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Create or update the default signup form for an audience/list.

    Examples:
        mailchimp forms create LIST_ID --header-text "Example beta" \\
            --signup-message "Join the beta tester list." \\
            --thank-you-title "You are on the list"
    """
    try:
        client = get_client()
        form = client.customize_signup_form(
            list_id=list_id,
            header_text=header_text,
            signup_message=signup_message,
            signup_thank_you_title=signup_thank_you_title,
        )

        print_success(f"Created signup form for audience: {list_id}")

        if table:
            print_table(
                [form],
                ["list_id", "signup_form_url"],
                ["List ID", "Signup Form URL"],
            )
        else:
            print_json(form)

    except Exception as e:
        raise typer.Exit(handle_error(e))
