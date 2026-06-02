"""Main entry point for LinkedIn CLI."""

from typing import List, Optional

import typer
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import command, print_error, print_info, print_json, print_table
from cli_tools_shared.profiles import list_profiles

from . import __version__
from .client import LinkedInClient, get_client
from .config import get_config

POST_COLUMNS = [
    "id",
    "author",
    "commentary",
    "visibility",
    "lifecycle_state",
    "published_at",
]

PERSON_URN_PREFIX = "urn:li:person:"
ORGANIZATION_URN_PREFIXES = ("urn:li:organization:", "urn:li:organizationBrand:")

COMMAND_CREDENTIALS = {
    "user posts list": ["oauth_authorization_code"],
    "user posts get": ["oauth_authorization_code"],
    "user posts create": ["oauth_authorization_code"],
    "user posts update": ["oauth_authorization_code"],
    "user posts delete": ["oauth_authorization_code"],
    "user posts search": ["oauth_authorization_code"],
    "page posts list": ["oauth_authorization_code"],
    "page posts get": ["oauth_authorization_code"],
    "page posts create": ["oauth_authorization_code"],
    "page posts update": ["oauth_authorization_code"],
    "page posts delete": ["oauth_authorization_code"],
    "page posts search": ["oauth_authorization_code"],
}

app = create_app(
    name="linkedin",
    help="Create and manage LinkedIn member and page posts",
    version=__version__,
)
user_app = typer.Typer(help="Manage authenticated-member LinkedIn resources", no_args_is_help=True)
page_app = typer.Typer(help="Manage LinkedIn page resources", no_args_is_help=True)
user_posts_app = typer.Typer(help="Manage LinkedIn member posts", no_args_is_help=True)
page_posts_app = typer.Typer(help="Manage LinkedIn page posts", no_args_is_help=True)
auth_app = create_auth_app(get_config, tool_name="linkedin")

POST_CAPABILITIES = [
    {
        "command": "user posts create/update/delete",
        "commands": ["user posts create", "user posts update", "user posts delete"],
        "required_scopes": ["w_member_social"],
        "author_field": "linkedin_person_urn",
        "author_default": "authenticated member",
    },
    {
        "command": "user posts list/get/search",
        "commands": ["user posts list", "user posts get", "user posts search"],
        "required_scopes": ["r_member_social"],
        "author_field": "linkedin_person_urn",
        "author_default": "authenticated member",
    },
    {
        "command": "page posts create/update/delete",
        "commands": ["page posts create", "page posts update", "page posts delete"],
        "required_scopes": ["w_organization_social"],
        "author_field": "linkedin_page_urn",
        "author_default": "pass --page or set LINKEDIN_PAGE_URN",
    },
    {
        "command": "page posts list/get/search",
        "commands": ["page posts list", "page posts get", "page posts search"],
        "required_scopes": ["r_organization_social"],
        "author_field": "linkedin_page_urn",
        "author_default": "pass --page or set LINKEDIN_PAGE_URN",
    },
]


def _property_fields(properties: Optional[str]) -> Optional[List[str]]:
    if properties is None:
        return None
    fields = [field.strip() for field in properties.split(",") if field.strip()]
    return fields or None


def _validate_filters(filters: Optional[List[str]]) -> None:
    if not filters:
        return
    try:
        validate_filters(filters)
    except FilterValidationError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


def _render_list(rows: List[dict], table: bool, properties: Optional[str], empty: str) -> None:
    fields = _property_fields(properties)
    if fields:
        rows = apply_properties_filter(rows, properties)
    if not table:
        print_json(rows)
        return
    if not rows:
        print_info(empty)
        return
    columns = fields or POST_COLUMNS
    print_table(rows, columns, [column.replace("_", " ").title() for column in columns])


def _render_single(row: dict, table: bool, properties: Optional[str]) -> None:
    fields = _property_fields(properties)
    if fields:
        row = apply_properties_filter([row], properties)[0]
    if not table:
        print_json(row)
        return
    if fields:
        print_table([row], fields, [field.replace("_", " ").title() for field in fields])
        return
    print_table(
        [{"field": key, "value": str(value)} for key, value in row.items()],
        ["field", "value"],
        ["Field", "Value"],
    )


def _profile_names(profile: Optional[str]) -> List[str]:
    if profile:
        return [profile]
    names = [entry["name"] for entry in list_profiles(get_config())]
    if not names:
        return [get_config().get_active_profile_name()]
    return names


def _post_readiness(profile: Optional[str]) -> dict:
    config = get_config(profile=profile)
    connection = config.test_connection()
    api_authenticated = connection.get("api_test") == "passed"
    scopes = connection.get("scopes") or []
    scope_set = set(scopes)
    missing_api_credentials = (
        config.get_missing_api_credentials() if not config.has_api_credentials() else []
    )

    checks = []
    for capability in POST_CAPABILITIES:
        required_scopes = capability["required_scopes"]
        missing_scopes = [scope for scope in required_scopes if scope not in scope_set]
        configured_author = getattr(config, capability["author_field"])
        blocked_by = []
        if missing_api_credentials:
            blocked_by.append(f"missing credentials: {', '.join(missing_api_credentials)}")
        elif not api_authenticated:
            blocked_by.append(connection["api_test"])
        if missing_scopes:
            blocked_by.append(f"missing scopes: {', '.join(missing_scopes)}")
        checks.append(
            {
                "command": capability["command"],
                "commands": capability["commands"],
                "ready": not blocked_by,
                "credential": "oauth",
                "required_scopes": required_scopes,
                "scopes_present": [scope for scope in required_scopes if scope in scope_set],
                "scopes_missing": missing_scopes,
                "default_author": configured_author or capability["author_default"],
                "blocked_by": blocked_by,
            }
        )

    return {
        "profile": config.get_active_profile_name(),
        "authenticated": api_authenticated,
        "api_authenticated": api_authenticated,
        "api_test": connection["api_test"],
        "token_status": connection.get("token_status"),
        "scopes": scopes,
        "checks": checks,
    }


def _readiness_rows(readiness: List[dict]) -> List[dict]:
    rows = []
    for profile in readiness:
        for check in profile["checks"]:
            rows.append(
                {
                    "profile": profile["profile"],
                    "command": check["command"],
                    "ready": check["ready"],
                    "missing": ", ".join(check["scopes_missing"]),
                    "blocked_by": "; ".join(check["blocked_by"]),
                }
            )
    return rows


@auth_app.command("readiness")
@command
def auth_readiness(
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        "-p",
        help="Profile name to check. Defaults to all profiles.",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Show LinkedIn post command readiness by profile and scope."""
    readiness = [_post_readiness(name) for name in _profile_names(profile)]
    if table:
        print_table(
            _readiness_rows(readiness),
            ["profile", "command", "ready", "missing", "blocked_by"],
            ["Profile", "Command", "Ready", "Missing", "Blocked By"],
            max_columns=0,
        )
        return
    print_json({"profiles": readiness})


def _require_person_urn(person_urn: str) -> str:
    if not person_urn.startswith(PERSON_URN_PREFIX):
        raise ClientError("Expected a LinkedIn person URN: urn:li:person:<id>.")
    return person_urn


def _require_page_urn(page_urn: str) -> str:
    if page_urn.startswith(ORGANIZATION_URN_PREFIXES):
        return page_urn
    raise ClientError(
        "Expected --page to be a LinkedIn organization URN: "
        "urn:li:organization:<id> or urn:li:organizationBrand:<id>."
    )


def _resolve_user_author(client: LinkedInClient, person: Optional[str]) -> str:
    if person:
        return _require_person_urn(person)
    configured_person_urn = client.config.linkedin_person_urn
    if configured_person_urn:
        return _require_person_urn(configured_person_urn)
    return client.get_current_member_urn()


def _resolve_page_author(client: LinkedInClient, page: Optional[str]) -> str:
    return _resolve_page_author_from_config(client.config, page)


def _resolve_page_author_from_config(config, page: Optional[str]) -> str:
    page_urn = page or config.linkedin_page_urn
    if not page_urn:
        raise ClientError(
            "Page URN is required. Pass --page urn:li:organization:<id> or set LINKEDIN_PAGE_URN."
        )
    return _require_page_urn(page_urn)


def _list_posts(
    client: LinkedInClient,
    author: str,
    *,
    start: int,
    sort_by: str,
    limit: int,
    filters: Optional[List[str]],
    table: bool,
    properties: Optional[str],
) -> None:
    _validate_filters(filters)
    rows = client.list_posts(
        author=author,
        limit=limit,
        start=start,
        sort_by=sort_by,
    )
    if filters:
        rows = apply_filters(rows, filters)
    _render_list(rows, table, properties, "No posts found.")


def _search_posts(
    client: LinkedInClient,
    author: str,
    *,
    query: str,
    limit: int,
    filters: Optional[List[str]],
    table: bool,
    properties: Optional[str],
) -> None:
    _validate_filters(filters)
    rows = client.search_posts(query=query, author=author, limit=limit)
    if filters:
        rows = apply_filters(rows, filters)
    _render_list(rows, table, properties, "No posts found.")


@user_posts_app.command("list")
@command
def list_user_posts(
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        help="Auth profile name. Defaults to the active profile.",
    ),
    person: Optional[str] = typer.Option(
        None,
        "--person",
        help="Member author URN. Defaults to LINKEDIN_PERSON_URN, then the authenticated member when identity lookup is available.",
    ),
    start: int = typer.Option(0, "--start", help="Zero-based paging offset"),
    sort_by: str = typer.Option(
        "LAST_MODIFIED",
        "--sort-by",
        help="Sort order accepted by LinkedIn (for example LAST_MODIFIED).",
    ),
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum number of posts"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter results (field:op:value)",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include",
    ),
):
    """List LinkedIn posts for a member author."""
    client = get_client(profile=profile)
    _list_posts(
        client,
        _resolve_user_author(client, person),
        start=start,
        sort_by=sort_by,
        limit=limit,
        filters=filter,
        table=table,
        properties=properties,
    )


@user_posts_app.command("get")
@command
def get_user_post(
    post_urn: str = typer.Argument(..., help="LinkedIn post URN"),
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        help="Auth profile name. Defaults to the active profile.",
    ),
    person: Optional[str] = typer.Option(
        None,
        "--person",
        help="Member author URN. Defaults to LINKEDIN_PERSON_URN, then the authenticated member when identity lookup is available.",
    ),
    view_context: str = typer.Option(
        "AUTHOR",
        "--view-context",
        help="LinkedIn view context (AUTHOR or READER).",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include",
    ),
):
    """Get a single member post by URN."""
    client = get_client(profile=profile)
    author = _resolve_user_author(client, person)
    _render_single(
        client.get_post(
            post_urn=post_urn,
            view_context=view_context,
            permission_author=author,
        ),
        table,
        properties,
    )


@user_posts_app.command("create")
@command
def create_user_post(
    commentary: str = typer.Argument(..., help="Text content for the post"),
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        help="Auth profile name. Defaults to the active profile.",
    ),
    person: Optional[str] = typer.Option(
        None,
        "--person",
        help="Member author URN. Defaults to LINKEDIN_PERSON_URN, then the authenticated member when LinkedIn identity lookup is available.",
    ),
    visibility: str = typer.Option(
        "PUBLIC",
        "--visibility",
        help="LinkedIn visibility value.",
    ),
    feed_distribution: str = typer.Option(
        "MAIN_FEED",
        "--feed-distribution",
        help="LinkedIn distribution feed value.",
    ),
    disable_reshare: bool = typer.Option(
        False,
        "--disable-reshare",
        help="Prevent resharing the post.",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Create a text-only LinkedIn member post."""
    client = get_client(profile=profile)
    _render_single(
        client.create_post(
            commentary=commentary,
            author=_resolve_user_author(client, person),
            visibility=visibility,
            feed_distribution=feed_distribution,
            disable_reshare=disable_reshare,
        ),
        table,
        None,
    )


@user_posts_app.command("update")
@command
def update_user_post(
    post_urn: str = typer.Argument(..., help="LinkedIn post URN"),
    commentary: str = typer.Argument(..., help="Updated text content"),
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        help="Auth profile name. Defaults to the active profile.",
    ),
    person: Optional[str] = typer.Option(
        None,
        "--person",
        help="Member author URN. Defaults to LINKEDIN_PERSON_URN, then the authenticated member when identity lookup is available.",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Update the commentary for an existing member post."""
    client = get_client(profile=profile)
    _render_single(
        client.update_post(
            post_urn=post_urn,
            commentary=commentary,
            permission_author=_resolve_user_author(client, person),
        ),
        table,
        None,
    )


@user_posts_app.command("delete")
@command
def delete_user_post(
    post_urn: str = typer.Argument(..., help="LinkedIn post URN"),
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        help="Auth profile name. Defaults to the active profile.",
    ),
    person: Optional[str] = typer.Option(
        None,
        "--person",
        help="Member author URN. Defaults to LINKEDIN_PERSON_URN, then the authenticated member when identity lookup is available.",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Delete a member post."""
    client = get_client(profile=profile)
    _render_single(
        client.delete_post(
            post_urn=post_urn,
            permission_author=_resolve_user_author(client, person),
        ),
        table,
        None,
    )


@user_posts_app.command("search")
@command
def search_user_posts(
    query: str = typer.Argument(..., help="Search query (supports * wildcards)"),
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        help="Auth profile name. Defaults to the active profile.",
    ),
    person: Optional[str] = typer.Option(
        None,
        "--person",
        help="Member author URN. Defaults to LINKEDIN_PERSON_URN, then the authenticated member when identity lookup is available.",
    ),
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum number of posts"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter results (field:op:value)",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include",
    ),
):
    """Search member posts with client-side wildcard matching."""
    client = get_client(profile=profile)
    _search_posts(
        client,
        _resolve_user_author(client, person),
        query=query,
        limit=limit,
        filters=filter,
        table=table,
        properties=properties,
    )


@page_posts_app.command("list")
@command
def list_page_posts(
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        help="Auth profile name. Defaults to the active profile.",
    ),
    page: Optional[str] = typer.Option(
        None,
        "--page",
        help="Page author URN. Defaults to LINKEDIN_PAGE_URN when set.",
    ),
    start: int = typer.Option(0, "--start", help="Zero-based paging offset"),
    sort_by: str = typer.Option(
        "LAST_MODIFIED",
        "--sort-by",
        help="Sort order accepted by LinkedIn (for example LAST_MODIFIED).",
    ),
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum number of posts"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter results (field:op:value)",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include",
    ),
):
    """List LinkedIn posts for an organization or showcase page."""
    client = get_client(profile=profile)
    _list_posts(
        client,
        _resolve_page_author(client, page),
        start=start,
        sort_by=sort_by,
        limit=limit,
        filters=filter,
        table=table,
        properties=properties,
    )


@page_posts_app.command("get")
@command
def get_page_post(
    post_urn: str = typer.Argument(..., help="LinkedIn post URN"),
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        help="Auth profile name. Defaults to the active profile.",
    ),
    page: Optional[str] = typer.Option(
        None,
        "--page",
        help="Page author URN. Defaults to LINKEDIN_PAGE_URN when set.",
    ),
    view_context: str = typer.Option(
        "AUTHOR",
        "--view-context",
        help="LinkedIn view context (AUTHOR or READER).",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include",
    ),
):
    """Get a single page post by URN."""
    client = get_client(profile=profile)
    page_urn = _resolve_page_author(client, page)
    _render_single(
        client.get_post(
            post_urn=post_urn,
            view_context=view_context,
            permission_author=page_urn,
        ),
        table,
        properties,
    )


@page_posts_app.command("create")
@command
def create_page_post(
    commentary: str = typer.Argument(..., help="Text content for the post"),
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        help="Auth profile name. Defaults to the active profile.",
    ),
    page: Optional[str] = typer.Option(
        None,
        "--page",
        help="Page author URN. Defaults to LINKEDIN_PAGE_URN when set.",
    ),
    visibility: str = typer.Option(
        "PUBLIC",
        "--visibility",
        help="LinkedIn visibility value.",
    ),
    feed_distribution: str = typer.Option(
        "MAIN_FEED",
        "--feed-distribution",
        help="LinkedIn distribution feed value.",
    ),
    disable_reshare: bool = typer.Option(
        False,
        "--disable-reshare",
        help="Prevent resharing the post.",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Create a text-only LinkedIn page post."""
    client = get_client(profile=profile)
    _render_single(
        client.create_post(
            commentary=commentary,
            author=_resolve_page_author(client, page),
            visibility=visibility,
            feed_distribution=feed_distribution,
            disable_reshare=disable_reshare,
        ),
        table,
        None,
    )


@page_posts_app.command("update")
@command
def update_page_post(
    post_urn: str = typer.Argument(..., help="LinkedIn post URN"),
    commentary: str = typer.Argument(..., help="Updated text content"),
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        help="Auth profile name. Defaults to the active profile.",
    ),
    page: Optional[str] = typer.Option(
        None,
        "--page",
        help="Page author URN. Defaults to LINKEDIN_PAGE_URN when set.",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Update the commentary for an existing page post."""
    client = get_client(profile=profile)
    _render_single(
        client.update_post(
            post_urn=post_urn,
            commentary=commentary,
            permission_author=_resolve_page_author(client, page),
        ),
        table,
        None,
    )


@page_posts_app.command("delete")
@command
def delete_page_post(
    post_urn: str = typer.Argument(..., help="LinkedIn post URN"),
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        help="Auth profile name. Defaults to the active profile.",
    ),
    page: Optional[str] = typer.Option(
        None,
        "--page",
        help="Page author URN. Defaults to LINKEDIN_PAGE_URN when set.",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Delete a page post."""
    client = get_client(profile=profile)
    _render_single(
        client.delete_post(
            post_urn=post_urn,
            permission_author=_resolve_page_author(client, page),
        ),
        table,
        None,
    )


@page_posts_app.command("search")
@command
def search_page_posts(
    query: str = typer.Argument(..., help="Search query (supports * wildcards)"),
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        help="Auth profile name. Defaults to the active profile.",
    ),
    page: Optional[str] = typer.Option(
        None,
        "--page",
        help="Page author URN. Defaults to LINKEDIN_PAGE_URN when set.",
    ),
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum number of posts"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter results (field:op:value)",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include",
    ),
):
    """Search page posts with client-side wildcard matching."""
    client = get_client(profile=profile)
    _search_posts(
        client,
        _resolve_page_author(client, page),
        query=query,
        limit=limit,
        filters=filter,
        table=table,
        properties=properties,
    )


user_app.add_typer(user_posts_app, name="posts")
page_app.add_typer(page_posts_app, name="posts")

app.add_typer(user_app, name="user")
app.add_typer(page_app, name="page")
app.add_typer(auth_app, name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main() -> None:
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
