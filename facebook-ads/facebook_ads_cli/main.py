"""Facebook Ads command contract, including complete SDK dispatch."""

import json
from pathlib import Path
import sys
from typing import List, Optional

import typer
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.filters import apply_filters, apply_properties_filter, validate_filters
from cli_tools_shared.output import command, print_json, print_table, prompt_secret
from cli_tools_shared.exceptions import ClientError

from . import __version__
from .catalog import catalog, operation, schema, SDK_VERSION, API_VERSION
from .client import get_client, validate_json_numbers
from .config import get_config
from .commands import auth

app = create_app(name="facebook-ads", help="Meta Marketing API and pinned Business SDK", version=__version__)
app.add_typer(auth.app, name="auth")
app.add_typer(create_cache_app(get_config), name="cache")
sdk_app = typer.Typer(help="All generated API operations in the pinned SDK", no_args_is_help=True)
resources_app = typer.Typer(help="Discover SDK resources", no_args_is_help=True)
methods_app = typer.Typer(help="Discover SDK operations", no_args_is_help=True)
graph_app = typer.Typer(help="Versioned Graph API requests, uploads and batches", no_args_is_help=True)
insights_app = typer.Typer(help="Reporting and asynchronous jobs", no_args_is_help=True)
app.add_typer(sdk_app, name="sdk")
sdk_app.add_typer(resources_app, name="resources")
sdk_app.add_typer(methods_app, name="methods")
app.add_typer(graph_app, name="graph")
app.add_typer(insights_app, name="insights")


def read_json(value, expected=dict):
    """Read inline JSON, @file, or stdin without guessing missing values."""
    try:
        text = sys.stdin.read() if value == "-" else Path(value[1:]).read_text() if value.startswith("@") else value
        data = json.loads(text)
    except (OSError, ValueError) as exc:
        raise ClientError(f"Invalid JSON input: {exc}") from None
    validate_json_numbers(data)
    if not isinstance(data, expected):
        raise ClientError(f"JSON input must be a {expected.__name__}.")
    return data


def file_map(values):
    result = {}
    for value in values or []:
        key, separator, path = value.partition("=")
        if not separator or not key or not Path(path).is_file():
            raise ClientError("--file requires FIELD=existing-file-path.")
        if key in result:
            raise ClientError(f"Duplicate upload field '{key}'.")
        result[key] = path
    return result


def render(data, table=False, properties=None):
    rows = data if isinstance(data, list) else [data]
    if properties:
        rows = apply_properties_filter(rows, properties)
        data = rows if isinstance(data, list) else rows[0]
    if not table:
        print_json(data)
    elif isinstance(data, list):
        print_table(rows, max_columns=0)
    else:
        print_table([{"field": key, "value": value} for key, value in data.items()], ["field", "value"], ["Field", "Value"])


def discovery(rows, limit, filters, properties, table):
    validate_filters(filters or [])
    rows = apply_filters(rows, filters) if filters else rows
    render(rows[:limit], table, properties)


@resources_app.command("list")
@command
def resource_list(
    limit: int = typer.Option(10000, "--limit", "-l", min=1, help="Maximum local resources"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Local field:operator:value filter"),
    table: bool = typer.Option(False, "--table", "-t", help="Display table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Output fields"),
):
    """List every generated SDK resource/schema (local, no token)."""
    discovery([{"name": name, "module": entry["module"], "operation_count": len(entry["methods"])}
               for name, entry in catalog().items()], limit, filter, properties, table)


@methods_app.command("list")
@command
def method_list(
    resource: str = typer.Argument(..., help="SDK resource class, for example AdAccount"),
    limit: int = typer.Option(1000, "--limit", "-l", min=1, help="Maximum local operations"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Local field:operator:value filter"),
    table: bool = typer.Option(False, "--table", "-t", help="Display table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Output fields"),
):
    """List generated API methods for a resource (local, no token)."""
    data = schema(resource)
    discovery([{"name": name, **entry} for name, entry in data["methods"].items()], limit, filter, properties, table)


@resources_app.command("get")
@command
def resource_get(resource: str = typer.Argument(..., help="SDK resource class"),
                 table: bool = typer.Option(False, "--table", "-t", help="Display table"),
                 properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Output fields")):
    """Get one resource schema without network access."""
    render(schema(resource), table, properties)


@methods_app.command("get")
@command
def method_get(resource: str = typer.Argument(..., help="SDK resource class"),
               method: str = typer.Argument(..., help="Generated API operation"),
               table: bool = typer.Option(False, "--table", "-t", help="Display table"),
               properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Output fields")):
    """Get one generated method parameter/enum schema without network access."""
    render(schema(resource, method)["operation"], table, properties)


@sdk_app.command("schema")
@command
def sdk_schema(resource: str = typer.Argument(..., help="SDK resource class"),
               method: Optional[str] = typer.Option(None, "--method", help="Include request parameter and enum schema"),
               table: bool = typer.Option(False, "--table", "-t", help="Display table")):
    """Inspect fields, methods, parameters and enums without network access."""
    render(schema(resource, method), table)


@sdk_app.command("coverage")
@command
def coverage(table: bool = typer.Option(False, "--table", "-t", help="Display table")):
    """Report pinned SDK dispatch coverage; this is not live endpoint verification."""
    data = catalog()
    render({"sdk_version": SDK_VERSION, "api_version": API_VERSION, "resources": len(data),
            "resources_with_operations": sum(bool(v["methods"]) for v in data.values()),
            "generated_operations": sum(len(v["methods"]) for v in data.values()),
            "scope": "Generated FacebookRequest methods in official adobjects; inherited generic helpers use graph request.",
            "live_endpoint_coverage": "Not implied by catalog discovery or mocked tests."}, table)


@sdk_app.command("call")
@command
def sdk_call(
    resource: str = typer.Argument(..., help="SDK resource class"),
    method: str = typer.Argument(..., help="Generated API operation"),
    object_id: str = typer.Argument(..., help="Graph node ID, such as act_123"),
    params: str = typer.Option("{}", "--params", help="JSON object, @file, or - for stdin"),
    fields: Optional[str] = typer.Option(None, "--fields", help="Comma-separated API fields"),
    file: Optional[List[str]] = typer.Option(None, "--file", help="Upload FIELD=path; repeatable"),
    all_pages: bool = typer.Option(False, "--all-pages", help="Follow cursor pages up to --limit"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, help="Maximum records across pages"),
    yes: bool = typer.Option(False, "--yes", help="Execute mutation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Build request without sending"),
    table: bool = typer.Option(False, "--table", "-t", help="Display table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Output fields"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Authentication profile"),
):
    """Invoke any generated SDK API operation with its complete parameter schema."""
    operation(resource, method)
    payload = read_json(params)
    client = get_client(profile, dry_run)
    render(client.call(resource, method, object_id, payload, fields.split(",") if fields else None,
                       file_map(file), all_pages, limit, yes, dry_run), table, properties)


@graph_app.command("request")
@command
def graph_request(
    method: str = typer.Argument(..., help="GET, POST, DELETE, PUT, PATCH"),
    path: str = typer.Argument(..., help="Relative Graph node/edge path"),
    params: str = typer.Option("{}", "--params", help="JSON object, @file, or stdin -"),
    file: Optional[List[str]] = typer.Option(None, "--file", help="Multipart FIELD=path"),
    video_host: bool = typer.Option(False, "--video-host", help="Use official graph-video.facebook.com upload host"),
    yes: bool = typer.Option(False, "--yes", help="Execute mutation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Build request without sending"),
    table: bool = typer.Option(False, "--table", "-t", help="Display table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Authentication profile"),
):
    """Send a complete versioned Graph request, including multipart uploads."""
    payload, uploads = read_json(params), file_map(file)
    render(get_client(profile, dry_run).graph(method, path, payload, uploads, yes, dry_run, video_host), table)


@graph_app.command("batch")
@command
def graph_batch(
    operations: str = typer.Argument(..., help="JSON operation array, @file, or stdin -"),
    file: Optional[List[str]] = typer.Option(None, "--file", help="Batch attachment FIELD=path"),
    yes: bool = typer.Option(False, "--yes", help="Execute mutating subrequests"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Build batch without sending"),
    table: bool = typer.Option(False, "--table", "-t", help="Display table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Authentication profile"),
):
    """Execute up to 50 batch calls; print individual failures and exit nonzero."""
    payload, uploads = read_json(operations, list), file_map(file)
    result, failed = get_client(profile, dry_run).batch(payload, uploads, yes, dry_run)
    render(result, table)
    if failed:
        raise typer.Exit(1)


def resource_commands(name, edge):
    """Build common commands from the canonical resource mapping."""
    group = typer.Typer(help=f"Manage {name}", no_args_is_help=True)

    @group.command("list")
    @command
    def list_resources(
        parent: str = typer.Option("me" if name == "accounts" else ..., "--parent", help="Parent ID; usually act_123"),
        limit: int = typer.Option(100, "--limit", "-l", min=1, help="Maximum records; passed to API"),
        filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Native field:operator:value filter"),
        fields: Optional[str] = typer.Option(None, "--fields", help="API fields to request"),
        params: str = typer.Option("{}", "--params", help="Extra API parameters JSON/@file/-"),
        table: bool = typer.Option(False, "--table", "-t", help="Display table"),
        properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Output fields"),
        profile: Optional[str] = typer.Option(None, "--profile", help="Authentication profile"),
    ):
        """List resources with server paging, filters, and complete returned fields."""
        render(get_client(profile).list_edge(parent, edge, limit, filter, fields, read_json(params)), table, properties)

    @group.command("get")
    @command
    def get_resource(
        object_id: str = typer.Argument(..., help="Graph resource ID"),
        fields: Optional[str] = typer.Option(None, "--fields", help="API fields to request"),
        table: bool = typer.Option(False, "--table", "-t", help="Display table"),
        properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Output fields"),
        profile: Optional[str] = typer.Option(None, "--profile", help="Authentication profile"),
    ):
        """Get a resource, preserving every returned field."""
        render(get_client(profile).graph("GET", object_id, {"fields": fields} if fields else {}), table, properties)

    if name != "accounts":
        for action, http_method in (("create", "POST"), ("update", "POST"), ("delete", "DELETE")):
            def build_mutation(action, http_method):
                @command
                def mutate(
                    object_id: str = typer.Argument(..., help="Parent ad account for create; resource ID for update/delete"),
                    params: str = typer.Option("{}", "--params", help="Complete mutation parameters JSON/@file/-"),
                    yes: bool = typer.Option(False, "--yes", help="Execute mutation"),
                    dry_run: bool = typer.Option(False, "--dry-run", help="Build request without sending"),
                    table: bool = typer.Option(False, "--table", "-t", help="Display table"),
                    profile: Optional[str] = typer.Option(None, "--profile", help="Authentication profile"),
                ):
                    """Create, update or delete using the full API parameter object."""
                    path = f"{object_id}/{edge}" if action == "create" else object_id
                    render(get_client(profile, dry_run).graph(http_method, path, read_json(params), yes=yes, dry_run=dry_run), table)
                return mutate
            group.command(action)(build_mutation(action, http_method))
    app.add_typer(group, name=name)


for name, edge in (("accounts", "adaccounts"), ("campaigns", "campaigns"),
                   ("adsets", "adsets"), ("ads", "ads"), ("creatives", "adcreatives")):
    resource_commands(name, edge)


@insights_app.command("list")
@command
def insights_list(
    object_id: str = typer.Argument(..., help="Ad account, campaign, adset, or ad ID"),
    params: str = typer.Option("{}", "--params", help="Insights parameters JSON/@file/-"),
    fields: Optional[str] = typer.Option(None, "--fields", help="Metrics and dimensions"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, help="Maximum rows"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Native field:operator:value filter"),
    table: bool = typer.Option(False, "--table", "-t", help="Display table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Output fields"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Authentication profile"),
):
    """Read synchronous insights with native API parameters and cursor paging."""
    render(get_client(profile).list_edge(object_id, "insights", limit, filter, fields, read_json(params)), table, properties)


@insights_app.command("start")
@command
def insights_start(object_id: str = typer.Argument(..., help="Ad account, campaign, adset or ad ID"),
                   params: str = typer.Option("{}", "--params", help="Insights parameters JSON/@file/-"),
                   table: bool = typer.Option(False, "--table", "-t", help="Display table"),
                   profile: Optional[str] = typer.Option(None, "--profile", help="Authentication profile")):
    """Start an asynchronous reporting job (no advertising change or spend)."""
    render(get_client(profile).graph("POST", f"{object_id}/insights", read_json(params), yes=True), table)


@insights_app.command("get")
@insights_app.command("status")
@command
def insights_status(report_id: str = typer.Argument(..., help="Async report run ID"),
                    table: bool = typer.Option(False, "--table", "-t", help="Display table"),
                    profile: Optional[str] = typer.Option(None, "--profile", help="Authentication profile")):
    """Read asynchronous report state."""
    render(get_client(profile).report_status(report_id), table)


@insights_app.command("wait")
@command
def insights_wait(report_id: str = typer.Argument(..., help="Async report run ID"),
                  timeout: float = typer.Option(600, "--timeout", min=0.01, help="Maximum wait seconds"),
                  interval: float = typer.Option(5, "--interval", min=0.01, help="Poll interval seconds"),
                  table: bool = typer.Option(False, "--table", "-t", help="Display table"),
                  profile: Optional[str] = typer.Option(None, "--profile", help="Authentication profile")):
    """Wait until an insights report completes, fails, or times out."""
    render(get_client(profile).wait_report(report_id, timeout, interval), table)


@insights_app.command("results")
@command
def insights_results(report_id: str = typer.Argument(..., help="Completed async report run ID"),
                     limit: int = typer.Option(100, "--limit", "-l", min=1, help="Maximum report rows"),
                     table: bool = typer.Option(False, "--table", "-t", help="Display table"),
                     profile: Optional[str] = typer.Option(None, "--profile", help="Authentication profile")):
    """Fetch completed asynchronous report rows with cursor paging."""
    render(get_client(profile).list_edge(report_id, "insights", limit), table)


@app.command("app-secret")
@command
def app_secret(profile: Optional[str] = typer.Option(None, "--profile", help="Authentication profile")):
    """Save optional app secret through the shared secret manager for proof."""
    value = prompt_secret("Meta app secret")
    get_config(profile).save_credentials(APP_SECRET=value)
    print_json({"saved": True})


def main():
    run_app(app)


if __name__ == "__main__":
    main()
