"""Chrome Web Store commands."""
COMMAND_CREDENTIALS = {
    "list": ["custom"],
    "get": ["custom"],
    "package": ["custom"],
    "status": ["custom"],
    "upload": ["custom"],
    "upload-extension": ["custom"],
    "publish": ["custom"],
    "release": ["custom"],
    "cancel-submission": ["custom"],
    "rollout": ["custom"],
    "listing": ["no_auth"],
}

LISTING_COMMAND_CREDENTIALS = {
    "update": ["browser_session"],
}

import os
import sys
from pathlib import Path
from typing import Optional

import typer

from cli_tools_shared.command_registry import _check_credentials
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import handle_error, print_json, print_table

from ..browser import update_webstore_listing
from ..client import get_client as get_google_client
from ..models.webstore import WebStoreReleaseResult, WebStoreUploadExtensionResult
from ..config import get_config
from ..webstore_client import ChromeWebStoreClient
from ..webstore_listing import parse_listing_file
from ..webstore_package import create_extension_package


app = typer.Typer(help="Manage Chrome Web Store items", no_args_is_help=True)
listing_app = typer.Typer(help="Manage Developer Dashboard store listing metadata", no_args_is_help=True)


@listing_app.callback(invoke_without_command=True)
def listing_callback(ctx: typer.Context):
    """Gate browser-backed listing commands without blocking nested help."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()
    if "--help" in sys.argv or "-h" in sys.argv:
        return
    cred_types = LISTING_COMMAND_CREDENTIALS.get(ctx.invoked_subcommand)
    if cred_types:
        _check_credentials(get_config(), cred_types, "google")


def get_client(profile: Optional[str] = None) -> ChromeWebStoreClient:
    """Create a Chrome Web Store client from the active Google OAuth profile."""
    google_client = get_google_client(profile=profile)
    return ChromeWebStoreClient(credentials=google_client.creds)


def resolve_item_ids(
    publisher_id: Optional[str],
    item_id: Optional[str],
    profile: Optional[str] = None,
) -> tuple[str, str]:
    """Resolve Web Store item IDs from options or environment."""
    resolved_publisher_id = publisher_id
    if resolved_publisher_id is None:
        resolved_publisher_id = get_webstore_setting("CWS_PUBLISHER_ID", profile=profile)
    if resolved_publisher_id is None or len(resolved_publisher_id) == 0:
        raise ValueError("Chrome Web Store publisher ID required. Pass --publisher-id or set CWS_PUBLISHER_ID.")

    resolved_item_id = item_id
    if resolved_item_id is None:
        resolved_item_id = get_webstore_setting("CWS_EXTENSION_ID", profile=profile)
    if resolved_item_id is None or len(resolved_item_id) == 0:
        raise ValueError("Chrome Web Store item ID required. Pass --item-id or set CWS_EXTENSION_ID.")

    return resolved_publisher_id, resolved_item_id


def get_webstore_setting(name: str, profile: Optional[str] = None) -> Optional[str]:
    """Read a Web Store setting from environment or the active profile env."""
    if name in os.environ and len(os.environ[name]) > 0:
        return os.environ[name]

    return get_config(profile=profile)._get(name)


def package_extension(
    extension_dir: Path,
    output_dir: Path,
    verify_command: Optional[list[str]],
    exclude: Optional[list[str]],
):
    """Package an unpacked Chrome extension for Chrome Web Store upload."""
    verify_commands = []
    if verify_command is not None:
        verify_commands = verify_command

    exclude_patterns = []
    if exclude is not None:
        exclude_patterns = exclude

    return create_extension_package(
        extension_dir=extension_dir,
        output_dir=output_dir,
        verify_commands=verify_commands,
        exclude_patterns=exclude_patterns,
    )


def _parse_properties(properties: Optional[str]) -> Optional[list[str]]:
    if properties is None:
        return None
    parsed = [property_name.strip() for property_name in properties.split(",")]
    if any(property_name == "" for property_name in parsed):
        raise ValueError("Expected comma-separated property names")
    return parsed


def _select_properties(item: dict, properties: Optional[list[str]]) -> dict:
    if properties is None:
        return item
    return {property_name: item.get(property_name) for property_name in properties}


@app.command("package")
def package_command(
    extension_dir: Path = typer.Argument(Path("."), exists=True, file_okay=False, help="Unpacked extension directory"),
    output_dir: Path = typer.Option(Path("dist/chrome-webstore"), "--output-dir", help="Directory for the release ZIP"),
    verify_command: Optional[list[str]] = typer.Option(None, "--verify-command", help="Command to run before packaging; repeat for multiple commands"),
    exclude: Optional[list[str]] = typer.Option(None, "--exclude", help="Additional package-relative glob to exclude; repeat for multiple patterns"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Create a Chrome Web Store ZIP package for an unpacked extension."""
    try:
        result = package_extension(extension_dir, output_dir, verify_command, exclude)
        if table:
            print_table([result], ["zip_path", "manifest_version", "file_count"], ["ZIP Path", "Version", "Files"])
        else:
            print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("list")
def list_items(
    publisher_id: Optional[str] = typer.Option(None, "--publisher-id", help="Chrome Web Store publisher ID; defaults to CWS_PUBLISHER_ID"),
    item_id: Optional[str] = typer.Option(None, "--item-id", help="Chrome Web Store item or extension ID; defaults to CWS_EXTENSION_ID"),
    limit: int = typer.Option(1, "--limit", "-l", help="Maximum number of items to list"),
    filter: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated properties to include in output"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """List the configured Chrome Web Store item status."""
    try:
        if limit < 1:
            items = []
        else:
            resolved_publisher_id, resolved_item_id = resolve_item_ids(publisher_id, item_id, profile=profile)
            item = get_client(profile=profile).fetch_status(resolved_publisher_id, resolved_item_id)
            items = [item.model_dump(mode="json")]
        if filter:
            items = apply_filters(items, filter)
        selected_properties = _parse_properties(properties)
        items = [_select_properties(item, selected_properties) for item in items]
        if table:
            columns = selected_properties or ["item_id", "taken_down", "warned"]
            print_table(items, columns, columns)
        else:
            print_json(items)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("status")
def status(
    publisher_id: Optional[str] = typer.Option(None, "--publisher-id", help="Chrome Web Store publisher ID; defaults to CWS_PUBLISHER_ID"),
    item_id: Optional[str] = typer.Option(None, "--item-id", help="Chrome Web Store item or extension ID; defaults to CWS_EXTENSION_ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Fetch Chrome Web Store item status."""
    try:
        resolved_publisher_id, resolved_item_id = resolve_item_ids(publisher_id, item_id, profile=profile)
        result = get_client(profile=profile).fetch_status(resolved_publisher_id, resolved_item_id)
        if table:
            print_table([result], ["item_id", "taken_down", "warned"], ["Item ID", "Taken Down", "Warned"])
        else:
            print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def get(
    publisher_id: Optional[str] = typer.Option(None, "--publisher-id", help="Chrome Web Store publisher ID; defaults to CWS_PUBLISHER_ID"),
    item_id: Optional[str] = typer.Option(None, "--item-id", help="Chrome Web Store item or extension ID; defaults to CWS_EXTENSION_ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Fetch Chrome Web Store item status."""
    status(publisher_id=publisher_id, item_id=item_id, table=table, profile=profile)


@app.command("upload")
def upload(
    package: Path = typer.Argument(..., exists=True, dir_okay=False, help="Extension ZIP package"),
    publisher_id: Optional[str] = typer.Option(None, "--publisher-id", help="Chrome Web Store publisher ID; defaults to CWS_PUBLISHER_ID"),
    item_id: Optional[str] = typer.Option(None, "--item-id", help="Chrome Web Store item or extension ID; defaults to CWS_EXTENSION_ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Upload a package to an existing Chrome Web Store item."""
    try:
        resolved_publisher_id, resolved_item_id = resolve_item_ids(publisher_id, item_id, profile=profile)
        result = get_client(profile=profile).upload_package(resolved_publisher_id, resolved_item_id, package)
        if table:
            print_table([result], ["item_id", "crx_version", "upload_state"], ["Item ID", "CRX Version", "Upload State"])
        else:
            print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("upload-extension")
def upload_extension(
    extension_dir: Path = typer.Argument(Path("."), exists=True, file_okay=False, help="Unpacked extension directory"),
    publisher_id: Optional[str] = typer.Option(None, "--publisher-id", help="Chrome Web Store publisher ID; defaults to CWS_PUBLISHER_ID"),
    item_id: Optional[str] = typer.Option(None, "--item-id", help="Chrome Web Store item or extension ID; defaults to CWS_EXTENSION_ID"),
    output_dir: Path = typer.Option(Path("dist/chrome-webstore"), "--output-dir", help="Directory for the release ZIP"),
    verify_command: Optional[list[str]] = typer.Option(None, "--verify-command", help="Command to run before packaging; repeat for multiple commands"),
    exclude: Optional[list[str]] = typer.Option(None, "--exclude", help="Additional package-relative glob to exclude; repeat for multiple patterns"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Package and upload extension."""
    try:
        resolved_publisher_id, resolved_item_id = resolve_item_ids(publisher_id, item_id, profile=profile)
        package_result = package_extension(extension_dir, output_dir, verify_command, exclude)
        upload_result = get_client(profile=profile).upload_package(
            resolved_publisher_id,
            resolved_item_id,
            Path(package_result.zip_path),
        )
        result = WebStoreUploadExtensionResult(package=package_result, upload=upload_result)
        if table:
            print_table([result.upload], ["item_id", "crx_version", "upload_state"], ["Item ID", "CRX Version", "Upload State"])
        else:
            print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("publish")
def publish(
    publisher_id: Optional[str] = typer.Option(None, "--publisher-id", help="Chrome Web Store publisher ID; defaults to CWS_PUBLISHER_ID"),
    item_id: Optional[str] = typer.Option(None, "--item-id", help="Chrome Web Store item or extension ID; defaults to CWS_EXTENSION_ID"),
    publish_type: Optional[str] = typer.Option(
        "DEFAULT_PUBLISH",
        "--publish-type",
        help="Publish type: DEFAULT_PUBLISH or STAGED_PUBLISH",
    ),
    deploy_percentage: Optional[int] = typer.Option(None, "--deploy-percentage", help="Initial rollout percentage"),
    skip_review: bool = typer.Option(False, "--skip-review", help="Attempt to skip review when the item qualifies"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Submit a Chrome Web Store item for publishing."""
    try:
        resolved_publisher_id, resolved_item_id = resolve_item_ids(publisher_id, item_id, profile=profile)
        result = get_client(profile=profile).publish_item(
            resolved_publisher_id,
            resolved_item_id,
            publish_type,
            deploy_percentage,
            skip_review,
        )
        if table:
            print_table([result], ["item_id", "state"], ["Item ID", "State"])
        else:
            print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("release")
def release(
    extension_dir: Path = typer.Argument(Path("."), exists=True, file_okay=False, help="Unpacked extension directory"),
    publisher_id: Optional[str] = typer.Option(None, "--publisher-id", help="Chrome Web Store publisher ID; defaults to CWS_PUBLISHER_ID"),
    item_id: Optional[str] = typer.Option(None, "--item-id", help="Chrome Web Store item or extension ID; defaults to CWS_EXTENSION_ID"),
    output_dir: Path = typer.Option(Path("dist/chrome-webstore"), "--output-dir", help="Directory for the release ZIP"),
    verify_command: Optional[list[str]] = typer.Option(None, "--verify-command", help="Command to run before packaging; repeat for multiple commands"),
    exclude: Optional[list[str]] = typer.Option(None, "--exclude", help="Additional package-relative glob to exclude; repeat for multiple patterns"),
    publish_type: Optional[str] = typer.Option(
        "DEFAULT_PUBLISH",
        "--publish-type",
        help="Publish type: DEFAULT_PUBLISH or STAGED_PUBLISH",
    ),
    deploy_percentage: Optional[int] = typer.Option(None, "--deploy-percentage", help="Initial rollout percentage"),
    skip_review: bool = typer.Option(False, "--skip-review", help="Attempt to skip review when the item qualifies"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Package, upload, and publish extension."""
    try:
        resolved_publisher_id, resolved_item_id = resolve_item_ids(publisher_id, item_id, profile=profile)
        package_result = package_extension(extension_dir, output_dir, verify_command, exclude)
        client = get_client(profile=profile)
        upload_result = client.upload_package(
            resolved_publisher_id,
            resolved_item_id,
            Path(package_result.zip_path),
        )
        publish_result = client.publish_item(
            resolved_publisher_id,
            resolved_item_id,
            publish_type,
            deploy_percentage,
            skip_review,
        )
        result = WebStoreReleaseResult(
            package=package_result,
            upload=upload_result,
            publish=publish_result,
        )
        if table:
            print_table([result.publish], ["item_id", "state"], ["Item ID", "State"])
        else:
            print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@listing_app.command("update")
def update_listing(
    listing_file: Path = typer.Option(
        Path("store-assets/chrome-webstore-listing.md"),
        "--listing-file",
        exists=True,
        dir_okay=False,
        help="Chrome Web Store listing markdown file",
    ),
    publisher_id: Optional[str] = typer.Option(None, "--publisher-id", help="Chrome Web Store publisher ID; defaults to CWS_PUBLISHER_ID"),
    item_id: Optional[str] = typer.Option(None, "--item-id", help="Chrome Web Store item or extension ID; defaults to CWS_EXTENSION_ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Update Store Listing overview fields and image assets through the dashboard."""
    try:
        resolved_publisher_id, resolved_item_id = resolve_item_ids(publisher_id, item_id, profile=profile)
        listing = parse_listing_file(listing_file)
        browser = get_config(profile=profile).get_browser()
        try:
            result = update_webstore_listing(browser, resolved_publisher_id, resolved_item_id, listing)
        finally:
            browser.close()
        if table:
            print_table([result], ["item_id", "save_status"], ["Item ID", "Save Status"])
        else:
            print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("cancel-submission")
def cancel_submission(
    publisher_id: Optional[str] = typer.Option(None, "--publisher-id", help="Chrome Web Store publisher ID; defaults to CWS_PUBLISHER_ID"),
    item_id: Optional[str] = typer.Option(None, "--item-id", help="Chrome Web Store item or extension ID; defaults to CWS_EXTENSION_ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Cancel the active Chrome Web Store submission for an item."""
    try:
        resolved_publisher_id, resolved_item_id = resolve_item_ids(publisher_id, item_id, profile=profile)
        result = get_client(profile=profile).cancel_submission(resolved_publisher_id, resolved_item_id)
        if table:
            print_table([result], ["name", "action", "success"], ["Name", "Action", "Success"])
        else:
            print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("rollout")
def rollout(
    publisher_id: Optional[str] = typer.Option(None, "--publisher-id", help="Chrome Web Store publisher ID; defaults to CWS_PUBLISHER_ID"),
    item_id: Optional[str] = typer.Option(None, "--item-id", help="Chrome Web Store item or extension ID; defaults to CWS_EXTENSION_ID"),
    deploy_percentage: int = typer.Option(..., "--deploy-percentage", help="Higher target rollout percentage"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Set a higher target deploy percentage for the published revision."""
    try:
        resolved_publisher_id, resolved_item_id = resolve_item_ids(publisher_id, item_id, profile=profile)
        result = get_client(profile=profile).set_published_deploy_percentage(
            resolved_publisher_id,
            resolved_item_id,
            deploy_percentage,
        )
        if table:
            print_table([result], ["name", "action", "success"], ["Name", "Action", "Success"])
        else:
            print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))


app.add_typer(listing_app, name="listing", help="Manage Developer Dashboard store listing metadata")
