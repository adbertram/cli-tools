"""Customer commands for FreshBooks CLI."""
import typer
from typing import Optional, List

from cli_tools_shared.output import print_json, print_table, handle_error, print_success

from ..client import get_client
from ..formatters import format_client_for_display
from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError

app = typer.Typer(help="Manage FreshBooks customers/clients")


@app.command("list")
def customer_list(
    filter_: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter results (field:op:value, e.g., organization:like:acme)",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
        help="Maximum number of customers to return (default: 100)",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of properties to display (e.g., 'id,organization,email')",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display output as a formatted table instead of JSON",
    ),
):
    """
    List all customers/clients.

    Shows all customers in your FreshBooks account.

    Examples:
        freshbooks customer list
        freshbooks customer list --table
        freshbooks customer list --filter organization:like:acme --table
        freshbooks customer list --filter email:eq:john@acme.com
        freshbooks customer list --limit 10
        freshbooks customer list --properties id,organization,email
    """
    try:
        # Validate filters first
        if filter_:
            try:
                validate_filters(filter_)
            except FilterValidationError as e:
                typer.echo(f"Filter error: {e}", err=True)
                raise typer.Exit(1)

        client = get_client()
        customers = client.get_clients(per_page=limit)

        if not customers:
            if table:
                print_table([], columns=["id", "organization", "name", "email"],
                            headers=["ID", "Organization", "Contact", "Email"])
            else:
                print_json([])
            return

        # Format customers
        formatted = [format_client_for_display(c) for c in customers]

        # Apply filters if provided (client-side filtering)
        if filter_:
            formatted = apply_filters(formatted, filter_)

        if not formatted:
            if table:
                print_table([], columns=["id", "organization", "name", "email"],
                            headers=["ID", "Organization", "Contact", "Email"])
            else:
                print_json([])
            return

        # Sort by organization name
        formatted.sort(key=lambda x: x["organization"].lower() if x["organization"] else x["name"].lower())

        # Apply property selection
        if properties:
            prop_list = [p.strip() for p in properties.split(",")]
            formatted = [{k: v for k, v in c.items() if k in prop_list} for c in formatted]

        if table:
            if properties:
                prop_list = [p.strip() for p in properties.split(",")]
                print_table(formatted, columns=prop_list, headers=prop_list)
            else:
                print_table(
                    formatted,
                    columns=["id", "organization", "name", "email"],
                    headers=["ID", "Organization", "Contact", "Email"],
                )
        else:
            print_json(formatted)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("get")
def customer_get(
    customer_id: str = typer.Argument(
        ...,
        help="The customer ID to retrieve",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display output as a formatted table instead of JSON",
    ),
):
    """
    Get details for a specific customer.

    Examples:
        freshbooks customer get 12345
        freshbooks customer get 12345 --table
    """
    try:
        client = get_client()
        customer = client.get_client(customer_id)

        if not customer:
            typer.echo(f"Customer {customer_id} not found.")
            raise typer.Exit(1)

        if table:
            formatted = format_client_for_display(customer)
            print_table(
                [formatted],
                columns=["id", "organization", "name", "email"],
                headers=["ID", "Organization", "Contact", "Email"],
            )
        else:
            print_json(customer)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("find")
def customer_find(
    email: str = typer.Argument(
        ...,
        help="Email address to search for",
    ),
):
    """
    Find a customer by email address.

    Examples:
        freshbooks customer find client@example.com
    """
    try:
        client = get_client()
        customer = client.get_client_by_email(email)

        if not customer:
            typer.echo(f"No customer found with email: {email}")
            raise typer.Exit(1)

        print_json(customer)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("create")
def customer_create(
    email: str = typer.Option(
        ...,
        "--email",
        "-e",
        help="Customer email address",
    ),
    first_name: str = typer.Option(
        ...,
        "--first-name",
        "-f",
        help="Contact first name",
    ),
    last_name: str = typer.Option(
        ...,
        "--last-name",
        "-l",
        help="Contact last name",
    ),
    organization: str = typer.Option(
        ...,
        "--organization",
        "-o",
        help="Organization/company name",
    ),
):
    """
    Create a new customer.

    Examples:
        freshbooks customer create -e john@acme.com -f John -l Doe -o "Acme Corp"
    """
    try:
        client = get_client()

        # Check if customer already exists
        existing = client.get_client_by_email(email)
        if existing:
            typer.echo(f"Customer with email {email} already exists (ID: {existing.get('id')})")
            raise typer.Exit(1)

        customer = client.create_client(
            email=email,
            first_name=first_name,
            last_name=last_name,
            organization=organization
        )

        print_success(f"Customer '{organization}' created (ID: {customer.get('id')})")
        print_json(format_client_for_display(customer))

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("update")
def customer_update(
    customer_id: str = typer.Argument(
        ...,
        help="The customer ID to update",
    ),
    email: Optional[str] = typer.Option(
        None,
        "--email",
        "-e",
        help="New email address",
    ),
    first_name: Optional[str] = typer.Option(
        None,
        "--first-name",
        "-f",
        help="New first name",
    ),
    last_name: Optional[str] = typer.Option(
        None,
        "--last-name",
        "-l",
        help="New last name",
    ),
    organization: Optional[str] = typer.Option(
        None,
        "--organization",
        "-o",
        help="New organization name",
    ),
):
    """
    Update an existing customer.

    Examples:
        freshbooks customer update 12345 --email newemail@acme.com
        freshbooks customer update 12345 -o "New Company Name"
    """
    try:
        client = get_client()

        # Build update data
        update_data = {}
        if email:
            update_data["email"] = email
        if first_name:
            update_data["fname"] = first_name
        if last_name:
            update_data["lname"] = last_name
        if organization:
            update_data["organization"] = organization

        if not update_data:
            typer.echo("No updates specified. Use --help to see available options.")
            raise typer.Exit(1)

        customer = client.update_client(customer_id, **update_data)

        print_success(f"Customer {customer_id} updated.")
        print_json(format_client_for_display(customer))

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


COMMAND_CREDENTIALS = {
    "create": [
        "oauth"
    ],
    "find": [
        "oauth"
    ],
    "get": [
        "oauth"
    ],
    "list": [
        "oauth"
    ],
    "update": [
        "oauth"
    ]
}
