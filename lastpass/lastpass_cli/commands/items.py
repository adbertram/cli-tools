"""Vault commands for LastPass CLI wrapper.

Manage vault entries (passwords, notes, etc.)
"""
import typer
from typing import Optional, List

from ..client import get_client, ClientError, MultipleMatchesError
from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
from cli_tools_shared.output import print_json, print_table, handle_error, print_success

# Exit code for an ambiguous lookup. Distinct from the generic error code (1)
# so a caller can tell "multiple matches" apart from a real failure, while the
# JSON payload on stdout lets it disambiguate by ID.
MULTIPLE_MATCHES_EXIT_CODE = 3


def _emit_multiple_matches(error: MultipleMatchesError) -> int:
    """Print the ambiguous-match candidates as JSON on stdout and return the exit code.

    The payload is parseable by `jq` so automation can pick an entry by ID and
    re-run the lookup with that exact ID.
    """
    print_json({
        "error": "multiple_matches",
        "query": error.query,
        "matches": error.matches,
    })
    return MULTIPLE_MATCHES_EXIT_CODE

COMMAND_CREDENTIALS = {
    "create": [
        "custom"
    ],
    "delete": [
        "custom"
    ],
    "generate": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "password": [
        "custom"
    ],
    "update": [
        "custom"
    ],
    "username": [
        "custom"
    ]
}

app = typer.Typer(help="Manage LastPass vault entries")

# `items list` is metadata-only: `lpass ls` yields just these fields per entry
# (see LastpassClient._parse_lpass_ls). Filtering can therefore only ever work
# on these. Declaring them lets the shared filter layer raise a clear error for
# a non-filterable field (e.g. Username, URL) instead of silently returning an
# empty result, which reads as a false "not found". To filter on a secret-bearing
# field such as username or url, fetch the entry with `items get`/`items username`.
LIST_FILTERABLE_FIELDS = ("id", "name", "group", "full_path")


@app.command("list")
def vault_list(
    group: Optional[str] = typer.Argument(None, help="Folder/group to list (e.g., 'Work' or 'Work/Servers')"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum entries to return (default 50; use 0 for unlimited). A truncation notice is printed to stderr when results are capped."),
    category: Optional[str] = typer.Option(None, "--category", "-c", help="Filter already-narrowed entries by LastPass category/note type; broad category scans over 50 candidates are refused"),
    filters: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value. Only metadata fields are filterable (id, name, group, full_path); name:like/ilike is case-insensitive. An unsupported field (e.g. Username, URL) errors instead of returning empty. E.g. name:like:%github%, group:eq:Home."),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of properties to include (supports dot notation)"),
):
    """
    List vault entries.

    Only metadata fields are returned, so --filter only supports:
    id, name, group, full_path. The `name:like:`/`ilike:` wildcard match is
    case-insensitive, so `name:like:%google%` also matches an entry named
    "Google". Filtering on a non-metadata field such as Username or URL is an
    error (those values require fetching the entry with `items get`).

    The default limit is 50; pass `--limit 0` for unlimited. When results are
    truncated a notice is printed to stderr.

    Category filtering checks each remaining candidate's NoteType and refuses
    more than 50 candidates. Pass a group argument or metadata --filter before
    --category; do not run category-only scans with --limit 0.

    Examples:
        lastpass items list
        lastpass items list --table
        lastpass items list Work --table
        lastpass items list --filter "name:like:%hsa%" --category "Payment Cards" --table
        lastpass items list --filter "name:like:%github%"
        lastpass items list --filter "name:like:%google%" --limit 0
    """
    try:
        # Validate filters if provided. Pass the metadata-only filterable fields
        # so an unsupported field (e.g. Username, URL) raises a clear error
        # instead of silently matching nothing.
        if filters:
            try:
                validate_filters(filters, allowed_fields=LIST_FILTERABLE_FIELDS)
            except FilterValidationError as e:
                from cli_tools_shared.output import print_error
                print_error(str(e))
                raise typer.Exit(1)

        client = get_client()
        items = client.list_items(group=group)

        # Apply client-side filters
        if filters and isinstance(items, list):
            items = apply_filters(items, filters, allowed_fields=LIST_FILTERABLE_FIELDS)

        # Filter out folder entries for cleaner output
        items = [item for item in items if not item.get("is_folder")]

        if category:
            items = client.filter_items_by_category(items, category)

        # Apply limit after filtering. `--limit 0` (or negative) means unlimited.
        # When a positive limit actually truncates results, warn on stderr so the
        # caller never mistakes a capped list for the complete set.
        if limit and limit > 0 and len(items) > limit:
            from cli_tools_shared.output import print_warning
            total = len(items)
            items = items[:limit]
            print_warning(
                f"Showing {limit} of {total} matching entries (truncated by "
                f"--limit {limit}). Pass --limit 0 for all, or raise --limit."
            )

        # Apply property selection
        if properties:
            prop_list = [p.strip() for p in properties.split(",")]
            items = [{k: v for k, v in item.items() if k in prop_list} for item in items]

        if table:
            if not items:
                print("No entries found.")
                return

            print_table(
                items,
                ["id", "name", "group", "category"] if category else ["id", "name", "group"],
                ["ID", "Name", "Group", "Category"] if category else ["ID", "Name", "Group"],
            )
        else:
            print_json(items)

    except typer.Exit:
        raise
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def vault_get(
    item_id: str = typer.Argument(..., help="Entry ID or unique name"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    show_password: bool = typer.Option(False, "--show-password", "-p", help="Show password (default: masked)"),
):
    """
    Get details of a vault entry.

    Examples:
        lastpass items get 1234567890
        lastpass items get "Work/GitHub" --table
        lastpass items get github.com --show-password
    """
    try:
        client = get_client()
        item = client.get_item(item_id, show_password=show_password)

        if table:
            rows = [{"field": k, "value": str(v)[:60]} for k, v in item.items()]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(item)

    except MultipleMatchesError as e:
        raise typer.Exit(_emit_multiple_matches(e))
    except typer.Exit:
        raise
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("password")
def vault_password(
    item_id: str = typer.Argument(..., help="Entry ID or unique name"),
    clip: bool = typer.Option(False, "--clip", "-c", help="Copy password to clipboard"),
):
    """
    Get just the password for an entry.

    Examples:
        lastpass items password github.com
        lastpass items password 1234567890 --clip
    """
    try:
        client = get_client()
        password = client.get_password(item_id)

        if clip:
            # Copy to clipboard only. Never fall back to printing the secret to
            # stdout: --clip exists specifically to keep the password off the
            # output stream, so a pbcopy failure must surface loudly.
            import subprocess
            subprocess.run(["pbcopy"], input=password.encode(), check=True)
            print_success("Password copied to clipboard")
        else:
            print(password)

    except MultipleMatchesError as e:
        raise typer.Exit(_emit_multiple_matches(e))
    except typer.Exit:
        raise
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("username")
def vault_username(
    item_id: str = typer.Argument(..., help="Entry ID or unique name"),
):
    """
    Get just the username for an entry.

    Examples:
        lastpass items username github.com
        lastpass items username 1234567890
    """
    try:
        client = get_client()
        username = client.get_username(item_id)
        print(username)

    except MultipleMatchesError as e:
        raise typer.Exit(_emit_multiple_matches(e))
    except typer.Exit:
        raise
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def vault_create(
    name: str = typer.Argument(..., help="Entry name"),
    username: Optional[str] = typer.Option(None, "--username", "-u", help="Username/email"),
    password: Optional[str] = typer.Option(None, "--password", "-P", help="Password"),
    url: Optional[str] = typer.Option(None, "--url", help="URL"),
    notes: Optional[str] = typer.Option(None, "--notes", "-n", help="Notes"),
    group: Optional[str] = typer.Option(None, "--group", "-g", help="Folder/group"),
):
    """
    Create a new vault entry.

    Examples:
        lastpass items create "My Site" --username me@email.com --password secret123 --url https://mysite.com
        lastpass items create "Work/VPN" --username admin --password hunter2 --group Work
    """
    try:
        client = get_client()
        result = client.create_item(
            name=name, username=username, password=password,
            url=url, notes=notes, group=group,
        )
        print_success(result["message"])
    except typer.Exit:
        raise
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def vault_update(
    item_id: str = typer.Argument(..., help="Entry ID or unique name"),
    username: Optional[str] = typer.Option(None, "--username", "-u", help="New username"),
    password: Optional[str] = typer.Option(None, "--password", "-P", help="New password"),
    url: Optional[str] = typer.Option(None, "--url", help="New URL"),
    notes: Optional[str] = typer.Option(None, "--notes", "-n", help="New notes"),
    name: Optional[str] = typer.Option(None, "--name", help="New name"),
):
    """
    Update an existing vault entry.

    Examples:
        lastpass items update "Amazon.com" --password newpassword123
        lastpass items update 1234567890 --username newuser@email.com --url https://new.example.com
    """
    try:
        client = get_client()
        result = client.update_item(
            item_id=item_id, username=username, password=password,
            url=url, notes=notes, name=name,
        )
        if result["success"]:
            print_success(result["message"])
        else:
            from cli_tools_shared.output import print_error
            print_error(result["message"])
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def vault_delete(
    item_id: str = typer.Argument(..., help="Entry ID or unique name"),
    force: bool = typer.Option(False, "--force", "-F", help="Skip confirmation"),
):
    """
    Delete a vault entry.

    Examples:
        lastpass items delete "Old Entry"
        lastpass items delete 1234567890 --force
    """
    try:
        if not force:
            confirm = typer.confirm(f"Delete entry '{item_id}'?")
            if not confirm:
                raise typer.Abort()

        client = get_client()
        result = client.delete_item(item_id)
        print_success(result["message"])
    except typer.Abort:
        print("Cancelled.")
    except typer.Exit:
        raise
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("generate")
def vault_generate(
    name: str = typer.Argument(..., help="Entry name or ID"),
    length: int = typer.Option(20, "--length", "-L", help="Password length"),
    username: Optional[str] = typer.Option(None, "--username", "-u", help="Username for the entry"),
    url: Optional[str] = typer.Option(None, "--url", help="URL for the entry"),
    no_symbols: bool = typer.Option(False, "--no-symbols", help="Omit symbols from password"),
    clip: bool = typer.Option(False, "--clip", "-c", help="Copy generated password to clipboard"),
):
    """
    Generate a random password for a new or existing entry.

    Examples:
        lastpass items generate "New Site" --length 30
        lastpass items generate "Work/API Key" --username admin --no-symbols --clip
    """
    try:
        client = get_client()
        result = client.generate_password(
            name=name, length=length, username=username,
            url=url, no_symbols=no_symbols,
        )
        if clip:
            # Copy to clipboard only; surface a pbcopy failure loudly rather
            # than silently dumping the generated secret to stdout.
            import subprocess
            subprocess.run(["pbcopy"], input=result["password"].encode(), check=True)
            print_success(f"{result['message']} (copied to clipboard)")
        else:
            print_json(result)
    except typer.Exit:
        raise
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))
