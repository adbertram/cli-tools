"""Offline SDK discovery and full RPC access."""
COMMAND_CREDENTIALS = {"versions": ["no_auth"], "services": ["no_auth"], "methods": ["no_auth"], "schema": ["no_auth"], "coverage": ["no_auth"], "call": ["no_auth"]}

import json
from pathlib import Path
from typing import Optional
import typer
from cli_tools_shared.activity_log import get_activity_logger
from cli_tools_shared.output import command, print_json
from cli_tools_shared.exceptions import ClientError
from ..client import get_client
from ..output import print_responses
from ..schema import DEFAULT_API_VERSION, SDK_VERSION, api_versions, catalog, coverage, method_info, message_schema, public_method

app = typer.Typer(help='Offline SDK discovery and full RPC access.', no_args_is_help=True)
logger = get_activity_logger("google-ads")


def reject_nonfinite_json(value):
    raise ValueError(f"Bare {value} is not valid JSON; protobuf special floats must be quoted strings.")


def read_body(body, body_file):
    if body is not None and body_file is not None:
        raise ClientError("Use only one of --body or --body-file.")
    try:
        if str(body_file) == "-":
            raw = typer.get_text_stream("stdin").read()
        else:
            raw = body_file.read_text() if body_file else body
        return json.loads(raw, parse_constant=reject_nonfinite_json) if raw is not None else {}
    except (OSError, ValueError) as exc:
        raise ClientError(f"Cannot read request JSON: {exc}") from exc


@app.command("versions")
@command
def versions():
    """Show versions available in the pinned SDK without authentication."""
    print_json({"sdk_version": SDK_VERSION, "default_api_version": DEFAULT_API_VERSION, "versions": api_versions()})


@app.command("services")
@command
def services(api_version: str = typer.Option(DEFAULT_API_VERSION, "--api-version", help="SDK API version")):
    """Show every generated service without authentication."""
    print_json([{"service": name, "rpc_count": len(entry["methods"])} for name, entry in catalog(api_version).items()])


@app.command("methods")
@command
def methods(service: str = typer.Argument(..., help="Exact SDK service name"),
            api_version: str = typer.Option(DEFAULT_API_VERSION, "--api-version", help="SDK API version")):
    """Show every method and request/response type for a service."""
    entries = catalog(api_version)
    if service not in entries:
        raise ClientError(f"Unknown service {service!r}; run 'google-ads api services'.")
    print_json([public_method(service, name, info) for name, info in entries[service]["methods"].items()])


@app.command("schema")
@command
def schema(service: str = typer.Argument(..., help="Exact SDK service name"),
           method: str = typer.Argument(..., help="Exact SDK snake_case RPC method"),
           api_version: str = typer.Option(DEFAULT_API_VERSION, "--api-version", help="SDK API version")):
    """Export complete request/response protobuf fields, nested types, enums and oneofs."""
    print_json(message_schema(service, method, api_version))


@app.command("coverage")
@command
def coverage_command(api_version: str = typer.Option(DEFAULT_API_VERSION, "--api-version", help="SDK API version")):
    """Export measured manifest of every reachable service/RPC."""
    print_json(coverage(api_version))


@app.command("call")
@command
def call(service: str = typer.Argument(..., help="Exact SDK service name"),
         method: str = typer.Argument(..., help="Exact SDK snake_case RPC method"),
         body: Optional[str] = typer.Option(None, "--body", help="Request protobuf JSON object"),
         body_file: Optional[Path] = typer.Option(None, "--body-file", help="JSON file, or - for stdin"),
         api_version: str = typer.Option(DEFAULT_API_VERSION, "--api-version", help="SDK API version"),
         yes: bool = typer.Option(False, "--yes", help="Explicitly permit mutation or unclassified RPC"),
         dry_run: bool = typer.Option(False, "--dry-run", help="Validate and print request locally without credentials"),
         validate_only: bool = typer.Option(False, "--validate-only", help="Ask server to validate without mutation; RPC must support it"),
         all_pages: bool = typer.Option(False, "--all-pages", help="Fetch every page, preserving full response envelopes"),
         timeout: float = typer.Option(60.0, "--timeout", min=0.001, help="Per-RPC timeout in seconds")):
    """Call any official SDK RPC. Streams print full batches as JSONL; other calls print JSON."""
    logger.info("Command api call %s.%s dry_run=%s", service, method, dry_run)
    result = get_client(api_version).call(service, method, read_body(body, body_file), yes=yes, dry_run=dry_run,
                                         validate_only=validate_only, all_pages=all_pages, timeout=timeout)
    print_responses(result, stream=method_info(service, method, api_version)["stream"] and not dry_run)


