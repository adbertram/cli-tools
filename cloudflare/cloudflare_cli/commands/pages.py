"""Pages commands for Cloudflare CLI.

Account-level Cloudflare Pages management:
  projects     - Create/update/delete Pages projects (+ build cache, upload token)
  deployments  - List/get/create deployments, retry, rollback, delete
  domains      - Manage custom domains attached to a project

Endpoints verified against https://developers.cloudflare.com/api/resources/pages/
Direct-upload asset flow mirrored from wrangler 4.125.0 (see pages_assets.py).
"""
import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import typer

from ..client import get_client
from .. import pages_assets
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import (
    apply_filters,
    apply_properties_filter,
)
from cli_tools_shared.output import (
    print_json,
    print_table,
    print_warning,
    command,
    print_success,
    confirm_destructive_action,
)


class DeploymentEnvironment(str, Enum):
    """Cloudflare Pages deployment environments."""

    PRODUCTION = "production"
    PREVIEW = "preview"


app = typer.Typer(help="Manage Cloudflare Pages projects, deployments, and domains", no_args_is_help=True)

projects_app = typer.Typer(help="Manage Pages projects", no_args_is_help=True)
deployments_app = typer.Typer(help="Manage Pages deployments", no_args_is_help=True)
domains_app = typer.Typer(help="Manage custom domains for a Pages project", no_args_is_help=True)


def _resolve_account(client, account: Optional[str]) -> str:
    """Resolve the optional account argument to an account ID."""
    if account:
        return client.resolve_account_id(account)
    return client.default_account_id()


def _format_local_timestamp(value) -> str:
    """Render an API ISO timestamp in the local timezone for table display."""
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M")


def _parse_json_object(raw: Optional[str], flag_name: str) -> Optional[Dict]:
    """Parse an optional JSON object argument, raising ClientError on bad input."""
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ClientError(f"Invalid {flag_name} JSON: {e}")
    if not isinstance(parsed, dict):
        raise ClientError(f"{flag_name} must be a JSON object")
    return parsed


def _project_row(project: Dict) -> Dict:
    """Flatten a project dict into table columns."""
    return {
        "id": project.get("id"),
        "name": project.get("name"),
        "production_branch": project.get("production_branch"),
        "created_on": _format_local_timestamp(project.get("created_on")),
    }


def _deployment_row(deployment: Dict) -> Dict:
    """Flatten a deployment dict into table columns."""
    trigger_metadata = (deployment.get("deployment_trigger") or {}).get("metadata") or {}
    latest_stage = deployment.get("latest_stage") or {}
    return {
        "id": deployment.get("id"),
        "env": deployment.get("env"),
        "branch": trigger_metadata.get("branch", ""),
        "status": latest_stage.get("status", ""),
        "created_on": _format_local_timestamp(deployment.get("created_on")),
    }


def _domain_row(domain: Dict) -> Dict:
    """Flatten a domain dict into table columns."""
    return {
        "name": domain.get("name"),
        "status": domain.get("status"),
        "created_on": _format_local_timestamp(domain.get("creation_date")),
        "modified_on": _format_local_timestamp(domain.get("modified_date")),
    }


def _print_single_result(result: Dict, table: bool, properties: Optional[str]) -> None:
    """Apply optional property selection, then print one record as JSON or key-value table."""
    if properties:
        result = apply_properties_filter([result], properties)[0]

    if table:
        rows = [{"field": k, "value": str(v)} for k, v in result.items() if v is not None]
        print_table(rows, ["field", "value"], ["Field", "Value"])
    else:
        print_json(result)


# ==================== Projects ====================


@projects_app.command("list")
@command
def list_projects(
    account: Optional[str] = typer.Argument(None, help="Account name or ID (defaults to the single visible account)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of projects to return"),
    filter_str: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:contains:blog)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
):
    """
    List Pages projects for an account.

    Examples:
        cloudflare pages projects list
        cloudflare pages projects list ACCOUNT_NAME --table
        cloudflare pages projects list --filter "name:contains:docs" --properties "name,production_branch"
    """
    client = get_client()
    account_id = _resolve_account(client, account)
    projects = client.list_pages_projects(account_id=account_id, limit=limit)

    if filter_str:
        projects = apply_filters(projects, filter_str)

    if properties:
        projects = apply_properties_filter(projects, properties)

    if table:
        print_table(
            [_project_row(p) for p in projects],
            ["id", "name", "production_branch", "created_on"],
            ["ID", "Name", "Production Branch", "Created"],
        )
    else:
        print_json(projects)


@projects_app.command("get")
@command
def get_project(
    project: str = typer.Argument(..., help="The Pages project name"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID (defaults to the single visible account)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
):
    """
    Get details for a single Pages project.

    Examples:
        cloudflare pages projects get my-site
        cloudflare pages projects get my-site ACCOUNT_NAME --table
        cloudflare pages projects get my-site --properties "name,production_branch"
    """
    client = get_client()
    account_id = _resolve_account(client, account)
    result = client.get_pages_project(account_id=account_id, project_name=project)
    _print_single_result(result, table, properties)


@projects_app.command("create")
@command
def create_project(
    name: str = typer.Argument(..., help="The new project name"),
    production_branch: str = typer.Option(..., "--production-branch", "-b", help="Branch that identifies production deployments"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID (defaults to the single visible account)"),
    config: Optional[str] = typer.Option(None, "--config", help='Extra JSON body fields (e.g. \'{"build_config":{"build_command":"npm run build"}}\')'),
):
    """
    Create a Pages project.

    Examples:
        cloudflare pages projects create my-site --production-branch main
        cloudflare pages projects create my-site -b main --config '{"build_config":{"build_command":"npm run build"}}'
    """
    client = get_client()
    account_id = _resolve_account(client, account)
    extra = _parse_json_object(config, "--config")

    result = client.create_pages_project(
        account_id=account_id,
        name=name,
        production_branch=production_branch,
        config=extra,
    )

    print_json(result)
    print_success(f"Created Pages project {result.get('name', name)}")


@projects_app.command("update")
@command
def update_project(
    project: str = typer.Argument(..., help="The Pages project name"),
    production_branch: Optional[str] = typer.Option(None, "--production-branch", "-b", help="New production branch"),
    build_command: Optional[str] = typer.Option(None, "--build-command", help="New build command"),
    destination_dir: Optional[str] = typer.Option(None, "--destination-dir", help="New build output directory"),
    root_dir: Optional[str] = typer.Option(None, "--root-dir", help="Directory to run the build command in"),
    build_caching: Optional[bool] = typer.Option(None, "--build-caching", help="Enable/disable build caching"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID (defaults to the single visible account)"),
    config: Optional[str] = typer.Option(None, "--config", help='Extra JSON body fields merged last (e.g. \'{"deployment_configs":{...}}\')'),
):
    """
    Update a Pages project via the PATCH edit endpoint.

    At least one setting must be specified.

    Examples:
        cloudflare pages projects update my-site --production-branch develop
        cloudflare pages projects update my-site --build-command "npm run build" --destination-dir dist
        cloudflare pages projects update my-site --config '{"deployment_configs":{"preview":{"env_vars":{"API_URL":null}}}}'
    """
    body: Dict = {}
    build_config: Dict = {}
    if build_command is not None:
        build_config["build_command"] = build_command
    if destination_dir is not None:
        build_config["destination_dir"] = destination_dir
    if root_dir is not None:
        build_config["root_dir"] = root_dir
    if build_caching is not None:
        build_config["build_caching"] = build_caching
    if build_config:
        body["build_config"] = build_config
    if production_branch is not None:
        body["production_branch"] = production_branch

    extra = _parse_json_object(config, "--config")
    if extra:
        body.update(extra)

    if not body:
        typer.echo("Error: At least one setting must be specified", err=True)
        raise typer.Exit(1)

    client = get_client()
    account_id = _resolve_account(client, account)
    result = client.patch_pages_project(account_id=account_id, project_name=project, data=body)

    print_json(result)
    updated = ", ".join(sorted(body.keys()))
    print_success(f"Updated Pages project {project}: {updated}")


@projects_app.command("delete")
@command
def delete_project(
    project: str = typer.Argument(..., help="The Pages project name"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID (defaults to the single visible account)"),
    force: bool = typer.Option(False, "--force", "-F", help="Skip confirmation prompt"),
):
    """
    Delete a Pages project.

    Examples:
        cloudflare pages projects delete my-site --force
    """
    client = get_client()
    account_id = _resolve_account(client, account)

    confirm_destructive_action(
        f"Are you sure you want to delete Pages project {project}?",
        assume_yes=force,
        action_description=f"delete Pages project {project}",
        skip_flag_hint="--force",
    )

    client.delete_pages_project(account_id=account_id, project_name=project)
    print_success(f"Deleted Pages project {project}")


@projects_app.command("purge-build-cache")
@command
def purge_build_cache(
    project: str = typer.Argument(..., help="The Pages project name"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID (defaults to the single visible account)"),
    force: bool = typer.Option(False, "--force", "-F", help="Skip confirmation prompt"),
):
    """
    Purge all cached build artifacts for a Pages project.

    Examples:
        cloudflare pages projects purge-build-cache my-site --force
    """
    client = get_client()
    account_id = _resolve_account(client, account)

    confirm_destructive_action(
        f"Are you sure you want to purge build cache for {project}?",
        assume_yes=force,
        action_description=f"purge build cache for Pages project {project}",
        skip_flag_hint="--force",
    )

    client.purge_pages_build_cache(account_id=account_id, project_name=project)
    print_success(f"Purged build cache for Pages project {project}")


@projects_app.command("get-upload-token")
@command
def get_upload_token(
    project: str = typer.Argument(..., help="The Pages project name"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID (defaults to the single visible account)"),
):
    """
    Get the direct-upload token for a Pages project.

    Examples:
        cloudflare pages projects get-upload-token my-site
    """
    client = get_client()
    account_id = _resolve_account(client, account)
    result = client.get_pages_upload_token(account_id=account_id, project_name=project)
    print_json(result)


# ==================== Deployments ====================


@deployments_app.command("list")
@command
def list_deployments(
    project: str = typer.Argument(..., help="The Pages project name"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID (defaults to the single visible account)"),
    env: Optional[DeploymentEnvironment] = typer.Option(None, "--env", "-e", help="Filter by environment (production or preview)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of deployments to return"),
    filter_str: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., status:eq:success)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
):
    """
    List deployments for a Pages project.

    Examples:
        cloudflare pages deployments list my-site
        cloudflare pages deployments list my-site --env production --table
        cloudflare pages deployments list my-site --filter "branch:eq:main" --properties "id,status"
    """
    client = get_client()
    account_id = _resolve_account(client, account)
    deployments = client.list_pages_deployments(
        account_id=account_id,
        project_name=project,
        limit=limit,
        env=env.value if env else None,
    )

    if filter_str:
        deployments = apply_filters(deployments, filter_str)

    if properties:
        deployments = apply_properties_filter(deployments, properties)

    if table:
        print_table(
            [_deployment_row(d) for d in deployments],
            ["id", "env", "branch", "status", "created_on"],
            ["ID", "Env", "Branch", "Status", "Created"],
        )
    else:
        print_json(deployments)


@deployments_app.command("get")
@command
def get_deployment(
    project: str = typer.Argument(..., help="The Pages project name"),
    deployment_id: str = typer.Argument(..., help="The deployment ID"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID (defaults to the single visible account)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
):
    """
    Get a single deployment.

    Examples:
        cloudflare pages deployments get my-site DEPLOYMENT_ID
        cloudflare pages deployments get my-site DEPLOYMENT_ID --table
    """
    client = get_client()
    account_id = _resolve_account(client, account)
    result = client.get_pages_deployment(account_id=account_id, project_name=project, deployment_id=deployment_id)
    _print_single_result(result, table, properties)


# wrangler truncates commit_message metadata to 384 UTF-8 bytes
# (MAX_COMMIT_MESSAGE_BYTES in src/api/pages/deploy.ts).
MAX_COMMIT_MESSAGE_BYTES = 384


def _truncate_utf8_bytes(text: Optional[str], limit: int = MAX_COMMIT_MESSAGE_BYTES) -> Optional[str]:
    """Truncate a string to at most `limit` UTF-8 bytes without splitting a char."""
    if text is None:
        return None
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode("utf-8", errors="ignore")


def _upload_directory_assets(
    client,
    account_id: str,
    project_name: str,
    site_dir: Path,
    skip_caching: bool,
) -> Tuple[str, int, int, Optional[str], Optional[str]]:
    """
    Run the direct-upload asset flow for one local directory.

    Mirrors wrangler's pages deploy sequence: hash every file, fetch the
    project upload token, check which hashes Cloudflare is missing, upload
    the rest in bounded batches, record all hashes, and read _headers /
    _redirects from the directory root for the deployment create call.

    Returns:
        (manifest_json, uploaded_count, total_files, headers_text, redirects_text)
    """
    assets = pages_assets.collect_files(site_dir)
    hashes = [asset["hash"] for asset in assets]
    typer.echo(f"Hashed {len(assets)} files in {site_dir}", err=True)

    token_result = client.get_pages_upload_token(account_id=account_id, project_name=project_name)
    jwt = token_result.get("jwt") if isinstance(token_result, dict) else None
    if not jwt:
        raise ClientError("Cloudflare did not return an upload token JWT for this project")

    if skip_caching:
        missing_hashes = list(hashes)
    else:
        known = set(hashes)
        missing_hashes = [h for h in client.check_missing_page_assets(jwt, hashes) if h in known]

    by_hash = {asset["hash"]: asset for asset in assets}
    to_upload = [by_hash[h] for h in missing_hashes]
    buckets = pages_assets.bucket_files(to_upload)

    uploaded = 0
    for index, bucket in enumerate(buckets, start=1):
        typer.echo(
            f"Uploading asset batch {index}/{len(buckets)} ({uploaded + len(bucket)}/{len(to_upload)} files)...",
            err=True,
        )
        client.upload_page_assets(jwt, pages_assets.build_upload_payload(bucket))
        uploaded += len(bucket)

    try:
        client.upsert_page_asset_hashes(jwt, hashes)
    except ClientError as e:
        print_warning(
            f"Could not record asset hashes for future deploys ({e}); "
            "the deployment itself is unaffected"
        )

    headers_path = site_dir / "_headers"
    redirects_path = site_dir / "_redirects"
    headers_text = headers_path.read_text(encoding="utf-8") if headers_path.is_file() else None
    redirects_text = redirects_path.read_text(encoding="utf-8") if redirects_path.is_file() else None

    return json.dumps(pages_assets.build_manifest(assets)), uploaded, len(assets), headers_text, redirects_text


@deployments_app.command("create")
@command
def create_deployment(
    project: str = typer.Argument(..., help="The Pages project name"),
    branch: Optional[str] = typer.Option(None, "--branch", "-b", help="Branch to build from (git-connected projects; defaults to production branch). With --directory it selects production vs preview"),
    commit_message: Optional[str] = typer.Option(None, "--commit-message", help="Commit message metadata"),
    commit_hash: Optional[str] = typer.Option(None, "--commit-hash", help="Commit SHA metadata"),
    commit_dirty: Optional[bool] = typer.Option(None, "--commit-dirty", help="Mark the source as having uncommitted changes"),
    directory: Optional[str] = typer.Option(None, "--directory", "-d", help="Local directory of static assets to deploy via direct upload: hashes the tree, uploads missing assets, then creates the deployment (wrangler pages deploy equivalent)"),
    skip_caching: bool = typer.Option(False, "--skip-caching", help="With --directory: re-upload every file even if Cloudflare already stores its content hash"),
    manifest: Optional[str] = typer.Option(None, "--manifest", help='Advanced/manual use: direct-upload manifest JSON string mapping "/path" keys to content hashes (assets must already be uploaded out-of-band)'),
    account: Optional[str] = typer.Argument(None, help="Account name or ID (defaults to the single visible account)"),
):
    """
    Start a new deployment.

    Git-connected projects: pass --branch to build the branch HEAD.
    Direct-upload projects: pass --directory to ship a local folder in one
    command — files are hashed (blake3), missing assets are uploaded via the
    Pages asset endpoints, and the deployment goes live once every hash lands.
    Pass --branch to target a preview branch; production deploys need no flag.
    Advanced/manual use only: --manifest creates a deployment from an existing
    manifest without uploading anything.

    Examples:
        cloudflare pages deployments create my-site --branch main
        cloudflare pages deployments create my-site --directory ./dist
        cloudflare pages deployments create my-site -d ./dist --branch preview --commit-message "docs update"
        cloudflare pages deployments create my-site --manifest '{"/index.html":"<content-hash>"}'
    """
    client = get_client()
    account_id = _resolve_account(client, account)
    manifest_json = _parse_json_object(manifest, "--manifest")

    if directory is not None and manifest_json is not None:
        raise ClientError("--directory and --manifest are mutually exclusive; pass one of them")

    manifest_str = json.dumps(manifest_json) if manifest_json is not None else None
    headers_text: Optional[str] = None
    redirects_text: Optional[str] = None
    upload_note = ""
    if directory is not None:
        site_dir = Path(directory).expanduser()
        if not site_dir.is_dir():
            raise ClientError(f"Deployment directory does not exist or is not a directory: {site_dir}")
        manifest_str, uploaded, total, headers_text, redirects_text = _upload_directory_assets(
            client, account_id, project, site_dir, skip_caching=skip_caching
        )
        upload_note = f" (uploaded {uploaded}/{total} assets)"

    result = client.create_pages_deployment(
        account_id=account_id,
        project_name=project,
        branch=branch,
        commit_message=_truncate_utf8_bytes(commit_message),
        commit_hash=commit_hash,
        commit_dirty=commit_dirty,
        manifest=manifest_str,
        headers_text=headers_text,
        redirects_text=redirects_text,
    )

    print_json(result)
    print_success(
        f"Created deployment for Pages project {project}: {result.get('id', '')}{upload_note}"
    )


@deployments_app.command("retry")
@command
def retry_deployment(
    project: str = typer.Argument(..., help="The Pages project name"),
    deployment_id: str = typer.Argument(..., help="The deployment ID to retry"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID (defaults to the single visible account)"),
):
    """
    Retry a failed deployment build.

    Examples:
        cloudflare pages deployments retry my-site DEPLOYMENT_ID
    """
    client = get_client()
    account_id = _resolve_account(client, account)
    result = client.retry_pages_deployment(account_id=account_id, project_name=project, deployment_id=deployment_id)
    print_json(result)
    print_success(f"Retried deployment {deployment_id}")


@deployments_app.command("rollback")
@command
def rollback_deployment(
    project: str = typer.Argument(..., help="The Pages project name"),
    deployment_id: str = typer.Argument(..., help="Target deployment ID (must be a successful production deployment)"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID (defaults to the single visible account)"),
    force: bool = typer.Option(False, "--force", "-F", help="Skip confirmation prompt"),
):
    """
    Roll production back to a previous successful production deployment.

    Examples:
        cloudflare pages deployments rollback my-site DEPLOYMENT_ID --force
    """
    client = get_client()
    account_id = _resolve_account(client, account)

    confirm_destructive_action(
        f"Are you sure you want to roll production back to deployment {deployment_id}?",
        assume_yes=force,
        action_description=f"roll production back to deployment {deployment_id}",
        skip_flag_hint="--force",
    )

    result = client.rollback_pages_deployment(account_id=account_id, project_name=project, deployment_id=deployment_id)
    print_json(result)
    print_success(f"Rolled production back to deployment {deployment_id}")


@deployments_app.command("delete")
@command
def delete_deployment(
    project: str = typer.Argument(..., help="The Pages project name"),
    deployment_id: str = typer.Argument(..., help="The deployment ID to delete"),
    allow_aliased: bool = typer.Option(False, "--allow-aliased", help="Allow deleting aliased non-production deployments (sends force=true to the API)"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID (defaults to the single visible account)"),
    force: bool = typer.Option(False, "--force", "-F", help="Skip confirmation prompt"),
):
    """
    Delete a deployment.

    The Cloudflare API does not support bulk deployment deletion; delete
    deployments one at a time.

    Examples:
        cloudflare pages deployments delete my-site DEPLOYMENT_ID --force
        cloudflare pages deployments delete my-site DEPLOYMENT_ID --allow-aliased --force
    """
    client = get_client()
    account_id = _resolve_account(client, account)

    confirm_destructive_action(
        f"Are you sure you want to delete deployment {deployment_id}?",
        assume_yes=force,
        action_description=f"delete deployment {deployment_id}",
        skip_flag_hint="--force",
    )

    client.delete_pages_deployment(
        account_id=account_id,
        project_name=project,
        deployment_id=deployment_id,
        allow_aliased=allow_aliased,
    )
    print_success(f"Deleted deployment {deployment_id}")


# ==================== Domains ====================


@domains_app.command("list")
@command
def list_domains(
    project: str = typer.Argument(..., help="The Pages project name"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID (defaults to the single visible account)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of domains to show (applied client-side; this endpoint returns all domains in one response)"),
    filter_str: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., status:eq:pending)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
):
    """
    List custom domains attached to a Pages project.

    The domains endpoint returns all domains in one response; --limit is
    applied client-side after filtering.

    Examples:
        cloudflare pages domains list my-site
        cloudflare pages domains list my-site --table
        cloudflare pages domains list my-site --filter "status:eq:active"
    """
    client = get_client()
    account_id = _resolve_account(client, account)
    domains = client.list_pages_domains(account_id=account_id, project_name=project)

    if filter_str:
        domains = apply_filters(domains, filter_str)

    domains = domains[:limit]

    if properties:
        domains = apply_properties_filter(domains, properties)

    if table:
        print_table(
            [_domain_row(d) for d in domains],
            ["name", "status", "created_on", "modified_on"],
            ["Domain", "Status", "Created", "Modified"],
        )
    else:
        print_json(domains)


@domains_app.command("get")
@command
def get_domain(
    project: str = typer.Argument(..., help="The Pages project name"),
    domain: str = typer.Argument(..., help="The domain name"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID (defaults to the single visible account)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
):
    """
    Get a single custom domain.

    Examples:
        cloudflare pages domains get my-site docs.example.com
        cloudflare pages domains get my-site docs.example.com --table
    """
    client = get_client()
    account_id = _resolve_account(client, account)
    result = client.get_pages_domain(account_id=account_id, project_name=project, domain_name=domain)
    _print_single_result(result, table, properties)


@domains_app.command("create")
@command
def create_domain(
    project: str = typer.Argument(..., help="The Pages project name"),
    domain: str = typer.Argument(..., help="Custom domain name to add"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID (defaults to the single visible account)"),
):
    """
    Add a custom domain to a Pages project.

    Examples:
        cloudflare pages domains create my-site docs.example.com
    """
    client = get_client()
    account_id = _resolve_account(client, account)
    result = client.add_pages_domain(account_id=account_id, project_name=project, domain_name=domain)
    print_json(result)
    print_success(f"Added domain {result.get('name', domain)} to Pages project {project}")


@domains_app.command("update")
@command
def update_domain(
    project: str = typer.Argument(..., help="The Pages project name"),
    domain: str = typer.Argument(..., help="The domain name"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID (defaults to the single visible account)"),
):
    """
    Retry validation for a custom domain (reprovision via the PATCH edit endpoint).

    Examples:
        cloudflare pages domains update my-site docs.example.com
    """
    client = get_client()
    account_id = _resolve_account(client, account)
    result = client.revalidate_pages_domain(account_id=account_id, project_name=project, domain_name=domain)
    print_json(result)
    print_success(f"Revalidated domain {domain}")


@domains_app.command("delete")
@command
def delete_domain(
    project: str = typer.Argument(..., help="The Pages project name"),
    domain: str = typer.Argument(..., help="The domain name"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID (defaults to the single visible account)"),
    force: bool = typer.Option(False, "--force", "-F", help="Skip confirmation prompt"),
):
    """
    Remove a custom domain from a Pages project.

    Examples:
        cloudflare pages domains delete my-site docs.example.com --force
    """
    client = get_client()
    account_id = _resolve_account(client, account)

    confirm_destructive_action(
        f"Are you sure you want to delete domain {domain}?",
        assume_yes=force,
        action_description=f"delete Pages domain {domain}",
        skip_flag_hint="--force",
    )

    client.delete_pages_domain(account_id=account_id, project_name=project, domain_name=domain)
    print_success(f"Deleted domain {domain}")


app.add_typer(projects_app, name="projects")
app.add_typer(deployments_app, name="deployments")
app.add_typer(domains_app, name="domains")


COMMAND_CREDENTIALS = {
    "projects": [
        "api_key"
    ],
    "deployments": [
        "api_key"
    ],
    "domains": [
        "api_key"
    ]
}
