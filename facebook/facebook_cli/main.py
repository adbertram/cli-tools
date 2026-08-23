"""Main entry point for Facebook CLI."""
import json
import sys
from typing import Optional


def create_facebook_app():
    """Build the full Typer application."""
    from . import __version__
    from cli_tools_shared import create_app
    from cli_tools_shared.auth_commands import create_auth_app
    from cli_tools_shared.cache_commands import create_cache_app
    from cli_tools_shared.command_registry import register_commands

    from .config import get_config
    from .commands import groups, marketplace, messenger

    app = create_app(
        name="facebook",
        help="Facebook CLI - Marketplace, Messenger, and more via browser automation",
        version=__version__,
    )
    register_commands(app, get_config, groups, name="groups", help="Manage Facebook Groups")
    register_commands(app, get_config, marketplace, name="marketplace", help="Search and browse Facebook Marketplace")
    register_commands(app, get_config, messenger, name="messenger", help="Facebook Messenger conversations and messages")
    app.add_typer(create_auth_app(get_config, tool_name="facebook"), name="auth", help="Manage Facebook authentication")
    app.add_typer(create_cache_app(get_config), name="cache")
    return app


def _parse_fast_groups_get(argv: list[str]):
    """Parse the hot `groups get` path without building the full Typer app."""
    if len(argv) < 3:
        return None
    if argv[0] != "groups" or argv[1] != "get":
        return None
    if "--help" in argv or "-h" in argv:
        return None

    group_id = None
    table = False
    properties = None
    index = 2
    while index < len(argv):
        arg = argv[index]
        if arg in ("--table", "-t"):
            table = True
            index += 1
        elif arg in ("--properties", "-p"):
            if index + 1 >= len(argv):
                return None
            properties = argv[index + 1]
            index += 2
        elif arg.startswith("-"):
            return None
        elif group_id is None:
            group_id = arg
            index += 1
        else:
            return None

    if group_id is None:
        return None
    return group_id, table, properties


def _parse_fast_groups_posts_list(argv: list[str]):
    """Parse the hot `groups posts list` path without building the full Typer app."""
    if len(argv) < 4:
        return None
    if argv[0] != "groups" or argv[1] != "posts" or argv[2] != "list":
        return None
    if "--help" in argv or "-h" in argv:
        return None

    group_id = None
    table = False
    limit = 20
    full_threads = False
    filters: list[str] = []
    properties = None
    index = 3
    while index < len(argv):
        arg = argv[index]
        if arg in ("--table", "-t"):
            table = True
            index += 1
        elif arg in ("--limit", "-l"):
            if index + 1 >= len(argv):
                return None
            limit = int(argv[index + 1])
            index += 2
        elif arg.startswith("--limit="):
            limit = int(arg.split("=", 1)[1])
            index += 1
        elif arg == "--full-threads":
            full_threads = True
            index += 1
        elif arg in ("--filter", "-f"):
            if index + 1 >= len(argv):
                return None
            filters.append(argv[index + 1])
            index += 2
        elif arg.startswith("--filter="):
            filters.append(arg.split("=", 1)[1])
            index += 1
        elif arg in ("--properties", "-p"):
            if index + 1 >= len(argv):
                return None
            properties = argv[index + 1]
            index += 2
        elif arg.startswith("--properties="):
            properties = arg.split("=", 1)[1]
            index += 1
        elif arg.startswith("-"):
            return None
        elif group_id is None:
            group_id = arg
            index += 1
        else:
            return None

    if group_id is None:
        return None
    if limit < 1 or limit > 25:
        return None
    return group_id, table, limit, full_threads, filters or None, properties


def _parse_fast_groups_posts_get(argv: list[str]):
    """Parse the hot `groups posts get` path without building the full Typer app."""
    if len(argv) < 4:
        return None
    if argv[0] != "groups" or argv[1] != "posts" or argv[2] != "get":
        return None
    if "--help" in argv or "-h" in argv:
        return None

    post_ref = None
    table = False
    properties = None
    index = 3
    while index < len(argv):
        arg = argv[index]
        if arg in ("--table", "-t"):
            table = True
            index += 1
        elif arg in ("--properties", "-p"):
            if index + 1 >= len(argv):
                return None
            properties = argv[index + 1]
            index += 2
        elif arg.startswith("--properties="):
            properties = arg.split("=", 1)[1]
            index += 1
        elif arg.startswith("-"):
            return None
        elif post_ref is None:
            post_ref = arg
            index += 1
        else:
            return None

    if post_ref is None:
        return None
    return post_ref, table, properties


def _apply_properties(data: dict, properties: str) -> dict:
    fields = [field.strip() for field in properties.split(",")]
    return {field: data[field] for field in fields if field in data}


def _fast_groups_get(argv: list[str]) -> Optional[int]:
    parsed = _parse_fast_groups_get(argv)
    if parsed is None:
        return None

    group_id, table, properties = parsed
    from .client import ClientError, get_client

    client = get_client()
    try:
        data = client.get_group(group_id).model_dump()
    except ClientError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    finally:
        client.close()

    if properties is not None:
        data = _apply_properties(data, properties)

    if table:
        from cli_tools_shared.output import print_table
        columns = list(data.keys())
        print_table([data], columns, columns)
    else:
        print(json.dumps(data, indent=2))
    return 0


def _fast_groups_posts_get(argv: list[str]) -> Optional[int]:
    parsed = _parse_fast_groups_posts_get(argv)
    if parsed is None:
        return None

    post_ref, table, properties = parsed
    from .client import ClientError, get_client

    client = get_client()
    try:
        post = client.get_group_post(post_ref)
    except ClientError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    finally:
        client.close()

    from ._helpers import output_single
    output_single(post.model_dump(), table=table, properties=properties)
    return 0


def _fast_groups_posts_list(argv: list[str]) -> Optional[int]:
    parsed = _parse_fast_groups_posts_list(argv)
    if parsed is None:
        return None

    group_id, table, limit, full_threads, filters, properties = parsed
    from .client import ClientError, get_client

    client = get_client()
    try:
        posts = client.list_group_posts(group_id, limit=limit, full_threads=full_threads)
    except ClientError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    finally:
        client.close()

    from ._helpers import output_list
    items = [post.model_dump() for post in posts]
    output_list(
        items,
        table=table,
        filter=filters,
        properties=properties,
        limit=limit,
        default_columns=["post_id", "author", "text", "timestamp"],
        default_headers=["Post ID", "Author", "Text", "Timestamp"],
        noun="post",
    )
    return 0


def main():
    """Main entry point."""
    fast_status = _fast_groups_get(sys.argv[1:])
    if fast_status is not None:
        return fast_status
    fast_status = _fast_groups_posts_list(sys.argv[1:])
    if fast_status is not None:
        return fast_status
    fast_status = _fast_groups_posts_get(sys.argv[1:])
    if fast_status is not None:
        return fast_status

    from cli_tools_shared import run_app
    from .client import ClientError

    app = create_facebook_app()
    run_app(app, error_types=ClientError)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
