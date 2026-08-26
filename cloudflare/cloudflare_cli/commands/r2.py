"""Cloudflare R2 bucket and object operations."""
from __future__ import annotations

import hashlib
import mimetypes
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import BinaryIO, Optional
from urllib.parse import quote

import boto3
import requests
import typer
from botocore.exceptions import ClientError as BotoClientError

from ..client import R2_ENABLEMENT_MESSAGE, SECRETS_MANAGER, build_forbidden_error, get_client
from cli_tools_shared.config import read_cli_tool_secret
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import apply_filters, apply_properties_filter
from cli_tools_shared.output import (
    command,
    print_json,
    print_success,
    print_table,
    print_warning,
)


app = typer.Typer(help="Manage R2 buckets and objects", no_args_is_help=True)
buckets_app = typer.Typer(help="Manage R2 buckets", no_args_is_help=True)
objects_app = typer.Typer(help="Manage R2 objects", no_args_is_help=True)
SYNC_WORKERS = 16
REST_EDGE_CHALLENGE_TITLE = "<title>Attention Required! | Cloudflare</title>"

# CLI-tools secret manager entries for the R2 S3-compatible API. These are
# separate from the Cloudflare REST API token (cloudflare-api-key): the REST
# API authenticates with a Bearer token, the R2 S3-compatible API authenticates
# with an R2-scoped access key ID / secret access key pair (SigV4).
R2_ACCESS_KEY_ID_SECRET = "cloudflare-r2-access-key-id"
R2_SECRET_ACCESS_KEY_SECRET = "cloudflare-r2-secret-access-key"


def _account_id(client, account: Optional[str]) -> str:
    return client.resolve_account_id(account) if account else client.default_account_id()


def _s3_secret(name: str) -> str:
    value = read_cli_tool_secret(name)
    if not value:
        raise ClientError(
            f"Missing CLI-tools secret '{name}' required for the R2 "
            f"S3-compatible API. Store it with: {SECRETS_MANAGER} set {name}"
        )
    return value


def _s3_client(account_id: str):
    """Build a boto3 S3 client scoped to this account's R2 endpoint.

    The R2 S3-compatible API authenticates with an R2-scoped access key ID /
    secret access key pair, not the Cloudflare REST API's Bearer token. Use
    this client (via `objects put-s3` / `objects head-s3`) for object keys the
    REST API's edge WAF blocks with a 403 HTML challenge, such as keys
    containing '..'.
    """
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=_s3_secret(R2_ACCESS_KEY_ID_SECRET),
        aws_secret_access_key=_s3_secret(R2_SECRET_ACCESS_KEY_SECRET),
        region_name="auto",
    )


def _headers(jurisdiction: str) -> dict[str, str]:
    return {} if jurisdiction == "default" else {"cf-r2-jurisdiction": jurisdiction}


def _object_endpoint(account_id: str, bucket: str, key: Optional[str] = None) -> str:
    endpoint = f"/accounts/{account_id}/r2/buckets/{quote(bucket, safe='')}/objects"
    return endpoint if key is None else f"{endpoint}/{quote(key, safe='/')}"


def _response_error(
    response: requests.Response,
    method: str,
    endpoint: str,
    *,
    attempts: int = 1,
) -> ClientError:
    content_type = response.headers.get("Content-Type", "").lower()
    if (
        response.status_code == 403
        and "text/html" in content_type
        and REST_EDGE_CHALLENGE_TITLE in response.text
    ):
        key_guidance = ""
        if ".." in endpoint:
            key_guidance = (
                " The object key contains '..'; Cloudflare's edge rejects that "
                "substring even when the dots are percent-encoded."
            )
        return ClientError(
            "Cloudflare blocked the R2 REST object path before R2 processed it "
            f"(403 HTML Attention Required): {method} {endpoint}.{key_guidance} "
            "This is not an API-token permission failure, and percent-encoding "
            "the dots does not bypass the edge rule. For sync, rerun with "
            "--skip-rest-edge-blocked to upload every representable key and "
            "report the omitted keys explicitly. Exact blocked keys require an "
            "R2 S3-compatible client or an invoked Worker with an R2 binding."
        )
    try:
        payload = response.json()
        errors = payload.get("errors") or []
        message = errors[0].get("message", "Request failed") if errors else "Request failed"
    except ValueError:
        message = response.text or "Request failed"
    if response.status_code == 403 and message == R2_ENABLEMENT_MESSAGE:
        # Cloudflare returns this exact message for every token, including
        # one with full R2 permission scopes, when the account has no active
        # R2 subscription. It is not a permission or credential problem, so
        # skip the generic permission-group/token-rotation guidance entirely.
        return ClientError(
            f"API request failed (403): {message}\n\n"
            "R2 has not been enabled for this Cloudflare account. Enable it "
            "once in the dashboard, then retry:\n"
            "  Dashboard > Storage & databases > R2 > Overview\n"
            "Complete the R2 subscription checkout (R2 has a free tier; no "
            "charge until usage exceeds it)."
        )
    if response.status_code == 403:
        return ClientError(build_forbidden_error(method, endpoint, message))
    if attempts > 1:
        return ClientError(
            f"API request failed after {attempts} attempts "
            f"({response.status_code}): {message}"
        )
    return ClientError(f"API request failed ({response.status_code}): {message}")


def _request_object(
    client,
    method: str,
    endpoint: str,
    *,
    jurisdiction: str,
    content_type: Optional[str] = None,
    body: Optional[BinaryIO] = None,
    stream: bool = False,
) -> requests.Response:
    headers = dict(client.headers)
    headers.update(_headers(jurisdiction))
    if content_type:
        headers["Content-Type"] = content_type
    elif method == "GET":
        headers.pop("Content-Type", None)
    retry_status = method == "PUT"
    max_attempts = client.max_retries + 1
    body_position = body.tell() if body is not None else None

    for attempt in range(max_attempts):
        if body_position is not None:
            body.seek(body_position)
        try:
            response = requests.request(
                method,
                f"{client.base_url}{endpoint}",
                headers=headers,
                data=body,
                stream=stream,
            )
        except requests.exceptions.RequestException as exc:
            # A transport-level failure carries no response, so no R2 state
            # change is in doubt for any method and the request can be retried
            # as-is (a PUT body is re-seeked at the top of the loop). Delegate
            # the transient/permanent decision to the same client predicate the
            # rest of the CLI uses, so both request paths agree on what
            # "transient" means. Concurrent `uv tool install` runs rebuild this
            # tool's site-packages, which unlinks and recreates certifi's
            # cacert.pem; a request that opens the CA bundle inside that window
            # raises SSLError(FileNotFoundError(2, ...)), which is transient.
            if client._is_retryable(None, exc) and attempt < client.max_retries:
                delay = client._calculate_retry_delay(attempt)
                print_warning(
                    f"Transient transport failure on {method} {endpoint} "
                    f"(attempt {attempt + 1}/{max_attempts}); retrying in "
                    f"{delay:.1f}s: {exc!r}"
                )
                time.sleep(delay)
                continue
            raise
        if response.ok:
            return response

        retryable = response.status_code == 429 or 500 <= response.status_code < 600
        if retry_status and retryable and attempt < client.max_retries:
            retry_after = client._get_retry_after(response)
            delay = client._calculate_retry_delay(attempt, retry_after)
            response.close()
            time.sleep(delay)
            continue

        error = _response_error(
            response,
            method,
            endpoint,
            attempts=attempt + 1,
        )
        response.close()
        raise error

    raise AssertionError("R2 object request retry loop exited without a response")


def _single(result: dict, table: bool, properties: Optional[str]) -> None:
    if properties:
        result = apply_properties_filter([result], properties)[0]
    if table:
        print_table(
            [{"field": key, "value": str(value)} for key, value in result.items()],
            ["field", "value"],
            ["Field", "Value"],
        )
    else:
        print_json(result)


def _md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sync_file(
    client,
    account_id: str,
    bucket: str,
    directory: Path,
    path: Path,
    normalized_prefix: str,
    remote: dict[str, dict],
    jurisdiction: str,
) -> bool:
    """Upload one changed file and return whether an upload occurred."""
    key = normalized_prefix + path.relative_to(directory).as_posix()
    existing = remote.get(key)
    size = path.stat().st_size
    if (
        existing
        and existing.get("size") == size
        and str(existing.get("etag", "")).strip('"') == _md5(path)
    ):
        return False

    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    try:
        with path.open("rb") as handle:
            response = _request_object(
                client,
                "PUT",
                _object_endpoint(account_id, bucket, key),
                jurisdiction=jurisdiction,
                content_type=mime,
                body=handle,
            )
        response.close()
    except Exception as exc:
        raise ClientError(f"Failed to upload R2 object {key}: {exc}") from exc
    return True


def _list_all_objects(
    client,
    account_id: str,
    bucket: str,
    prefix: str,
    jurisdiction: str,
    limit: Optional[int] = None,
) -> list[dict]:
    rows: list[dict] = []
    cursor: Optional[str] = None
    endpoint = _object_endpoint(account_id, bucket)
    while True:
        per_page = 1000 if limit is None else min(1000, limit - len(rows))
        params = {"per_page": per_page, "prefix": prefix}
        if cursor:
            params["cursor"] = cursor
        response = client._make_request("GET", endpoint, params=params, headers=_headers(jurisdiction))
        rows.extend(response.get("result", []))
        info = response.get("result_info") or {}
        if (limit is not None and len(rows) >= limit) or not info.get("is_truncated"):
            return rows
        cursor = info.get("cursor")
        if not cursor:
            raise ClientError("R2 object list was truncated without a continuation cursor")


@buckets_app.command("list")
@command
def list_buckets(
    account: Optional[str] = typer.Argument(None, help="Account name or ID"),
    table: bool = typer.Option(False, "--table", "-t"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000),
    filter_str: Optional[list[str]] = typer.Option(None, "--filter", "-f"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p"),
    jurisdiction: str = typer.Option("default", "--jurisdiction"),
):
    """List R2 buckets."""
    client = get_client()
    response = client._make_request(
        "GET", f"/accounts/{_account_id(client, account)}/r2/buckets",
        params={"per_page": limit}, headers=_headers(jurisdiction),
    )
    rows = (response.get("result") or {}).get("buckets", [])
    if filter_str:
        rows = apply_filters(rows, filter_str)
    if properties:
        rows = apply_properties_filter(rows, properties)
    if table:
        print_table(rows, ["name", "location", "storage_class", "creation_date"], ["Name", "Location", "Storage Class", "Created"])
    else:
        print_json(rows)


@buckets_app.command("get")
@command
def get_bucket(
    bucket: str = typer.Argument(...),
    account: Optional[str] = typer.Argument(None, help="Account name or ID"),
    table: bool = typer.Option(False, "--table", "-t"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p"),
    jurisdiction: str = typer.Option("default", "--jurisdiction"),
):
    """Get one R2 bucket."""
    client = get_client()
    endpoint = f"/accounts/{_account_id(client, account)}/r2/buckets/{quote(bucket, safe='')}"
    result = client._make_request("GET", endpoint, headers=_headers(jurisdiction)).get("result", {})
    _single(result, table, properties)


@buckets_app.command("create")
@command
def create_bucket(
    bucket: str = typer.Argument(...),
    account: Optional[str] = typer.Argument(None, help="Account name or ID"),
    location: Optional[str] = typer.Option(None, "--location", help="Location hint: apac, eeur, enam, weur, wnam, or oc"),
    storage_class: str = typer.Option("Standard", "--storage-class"),
    jurisdiction: str = typer.Option("default", "--jurisdiction"),
):
    """Create an R2 bucket."""
    client = get_client()
    data = {"name": bucket, "storageClass": storage_class}
    if location:
        data["locationHint"] = location
    endpoint = f"/accounts/{_account_id(client, account)}/r2/buckets"
    result = client._make_request("POST", endpoint, data=data, headers=_headers(jurisdiction)).get("result", {})
    print_json(result)
    print_success(f"Created R2 bucket {bucket}")


@buckets_app.command("inspect")
@command
def inspect_bucket(
    bucket: str = typer.Argument(...),
    account: Optional[str] = typer.Argument(None, help="Account name or ID"),
    table: bool = typer.Option(False, "--table", "-t"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p"),
    jurisdiction: str = typer.Option("default", "--jurisdiction"),
):
    """Inspect bucket properties and public-domain access."""
    client = get_client()
    base = f"/accounts/{_account_id(client, account)}/r2/buckets/{quote(bucket, safe='')}"
    result = {
        "bucket": client._make_request("GET", base, headers=_headers(jurisdiction)).get("result", {}),
        "managed_domain": client._make_request("GET", f"{base}/domains/managed", headers=_headers(jurisdiction)).get("result", {}),
        "custom_domains": (client._make_request("GET", f"{base}/domains/custom", headers=_headers(jurisdiction)).get("result", {}) or {}).get("domains", []),
    }
    _single(result, table, properties)


@objects_app.command("list")
@command
def list_objects(
    bucket: str = typer.Argument(...),
    account: Optional[str] = typer.Argument(None, help="Account name or ID"),
    prefix: str = typer.Option("", "--prefix"),
    table: bool = typer.Option(False, "--table", "-t"),
    limit: int = typer.Option(100, "--limit", "-l", min=1),
    filter_str: Optional[list[str]] = typer.Option(None, "--filter", "-f"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p"),
    jurisdiction: str = typer.Option("default", "--jurisdiction"),
):
    """List objects in an R2 bucket."""
    client = get_client()
    rows = _list_all_objects(
        client,
        _account_id(client, account),
        bucket,
        prefix,
        jurisdiction,
        limit,
    )[:limit]
    if filter_str:
        rows = apply_filters(rows, filter_str)
    if properties:
        rows = apply_properties_filter(rows, properties)
    if table:
        print_table(rows, ["key", "size", "etag", "last_modified"], ["Key", "Size", "ETag", "Modified"])
    else:
        print_json(rows)


@objects_app.command("get")
@command
def get_object(
    bucket: str = typer.Argument(...),
    key: str = typer.Argument(...),
    output: Path = typer.Option(..., "--output", "-o"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID"),
    jurisdiction: str = typer.Option("default", "--jurisdiction"),
):
    """Download an R2 object to a file."""
    client = get_client()
    response = _request_object(client, "GET", _object_endpoint(_account_id(client, account), bucket, key), jurisdiction=jurisdiction, stream=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as handle:
        for chunk in response.iter_content(1024 * 1024):
            handle.write(chunk)
    response.close()
    print_json({"bucket": bucket, "key": key, "output": str(output), "size": output.stat().st_size})


@objects_app.command("head")
@command
def head_object(
    bucket: str = typer.Argument(...),
    key: str = typer.Argument(...),
    account: Optional[str] = typer.Argument(None, help="Account name or ID"),
    table: bool = typer.Option(False, "--table", "-t"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p"),
    jurisdiction: str = typer.Option("default", "--jurisdiction"),
):
    """Read R2 object metadata without downloading its body."""
    client = get_client()
    response = _request_object(client, "GET", _object_endpoint(_account_id(client, account), bucket, key), jurisdiction=jurisdiction, stream=True)
    result = {"key": key, "size": int(response.headers.get("Content-Length", 0)), "etag": response.headers.get("ETag", "").strip('"'), "content_type": response.headers.get("Content-Type"), "last_modified": response.headers.get("Last-Modified")}
    response.close()
    _single(result, table, properties)


@objects_app.command("put")
@command
def put_object(
    bucket: str = typer.Argument(...),
    key: str = typer.Argument(...),
    file: Path = typer.Option(..., "--file", exists=True, file_okay=True, dir_okay=False, readable=True),
    content_type: Optional[str] = typer.Option(None, "--content-type"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID"),
    jurisdiction: str = typer.Option("default", "--jurisdiction"),
):
    """Upload one file to an R2 object key."""
    client = get_client()
    mime = content_type or mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    endpoint = _object_endpoint(_account_id(client, account), bucket, key)
    with file.open("rb") as handle:
        response = _request_object(client, "PUT", endpoint, jurisdiction=jurisdiction, content_type=mime, body=handle)
    result = response.json().get("result", {})
    response.close()
    print_json(result)
    print_success(f"Uploaded {key}")


@objects_app.command("put-s3")
@command
def put_object_s3(
    bucket: str = typer.Argument(...),
    key: str = typer.Argument(...),
    file: Path = typer.Option(..., "--file", exists=True, file_okay=True, dir_okay=False, readable=True),
    content_type: Optional[str] = typer.Option(None, "--content-type"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID"),
):
    """Upload one file to an R2 object key via the S3-compatible API.

    Use this instead of `objects put` for object keys the REST API's edge
    rejects with a 403 HTML "Attention Required" challenge, such as keys
    containing '..'. This is not a permissions difference; it authenticates
    with the R2 S3-compatible access key pair instead of the REST API token.
    """
    client = get_client()
    account_id = _account_id(client, account)
    mime = content_type or mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    s3 = _s3_client(account_id)
    try:
        with file.open("rb") as handle:
            s3.put_object(Bucket=bucket, Key=key, Body=handle, ContentType=mime)
    except BotoClientError as exc:
        raise ClientError(f"S3 upload failed for R2 object {key}: {exc}") from exc
    result = {"bucket": bucket, "key": key, "size": file.stat().st_size, "content_type": mime}
    print_json(result)
    print_success(f"Uploaded {key} via R2 S3 API")


@objects_app.command("head-s3")
@command
def head_object_s3(
    bucket: str = typer.Argument(...),
    key: str = typer.Argument(...),
    account: Optional[str] = typer.Argument(None, help="Account name or ID"),
    table: bool = typer.Option(False, "--table", "-t"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p"),
):
    """Read R2 object metadata via the S3-compatible API.

    Use this instead of `objects head` for object keys the REST API's edge
    blocks with a 403 HTML challenge, such as keys containing '..'.
    """
    client = get_client()
    account_id = _account_id(client, account)
    s3 = _s3_client(account_id)
    try:
        response = s3.head_object(Bucket=bucket, Key=key)
    except BotoClientError as exc:
        raise ClientError(f"S3 head failed for R2 object {key}: {exc}") from exc
    last_modified = response.get("LastModified")
    result = {
        "key": key,
        "size": response["ContentLength"],
        "etag": response.get("ETag", "").strip('"'),
        "content_type": response.get("ContentType"),
        "last_modified": last_modified.isoformat() if last_modified else None,
    }
    _single(result, table, properties)


@objects_app.command("sync")
@command
def sync_objects(
    bucket: str = typer.Argument(...),
    directory: Path = typer.Argument(..., exists=True, file_okay=False, readable=True),
    prefix: str = typer.Option("wp-content/uploads/", "--prefix", help="Destination key prefix"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID"),
    jurisdiction: str = typer.Option("default", "--jurisdiction"),
    skip_rest_edge_blocked: bool = typer.Option(
        False,
        "--skip-rest-edge-blocked",
        help=(
            "Upload representable keys and explicitly report keys containing "
            "'..' that Cloudflare's REST edge cannot address"
        ),
    ),
):
    """Synchronize a directory, skipping objects verified by size and MD5 ETag."""
    client = get_client()
    account_id = _account_id(client, account)
    normalized_prefix = prefix.strip("/")
    normalized_prefix = f"{normalized_prefix}/" if normalized_prefix else ""
    all_paths = sorted(candidate for candidate in directory.rglob("*") if candidate.is_file())
    blocked_paths = [
        path
        for path in all_paths
        if ".." in (normalized_prefix + path.relative_to(directory).as_posix())
    ]
    blocked_keys = [
        normalized_prefix + path.relative_to(directory).as_posix()
        for path in blocked_paths
    ]
    if blocked_keys and not skip_rest_edge_blocked:
        raise ClientError(
            f"Cloudflare's R2 REST edge cannot address {len(blocked_keys)} "
            "object key(s) containing '..'. No uploads were attempted. "
            "Rerun with --skip-rest-edge-blocked to upload every representable "
            "key and report the omitted keys explicitly. Exact blocked keys "
            "require an R2 S3-compatible client or an invoked Worker with an "
            "R2 binding. First blocked key: "
            f"{blocked_keys[0]}"
        )
    blocked_set = set(blocked_paths)
    paths = [path for path in all_paths if path not in blocked_set]
    remote = {
        row["key"]: row
        for row in _list_all_objects(
            client, account_id, bucket, normalized_prefix, jurisdiction
        )
    }
    uploaded = 0
    with ThreadPoolExecutor(max_workers=SYNC_WORKERS) as executor:
        for offset in range(0, len(paths), SYNC_WORKERS):
            uploaded += sum(executor.map(
                lambda path: _sync_file(
                    client,
                    account_id,
                    bucket,
                    directory,
                    path,
                    normalized_prefix,
                    remote,
                    jurisdiction,
                ),
                paths[offset:offset + SYNC_WORKERS],
            ))
    skipped = len(paths) - uploaded
    print_json({
        "bucket": bucket,
        "directory": str(directory),
        "prefix": normalized_prefix,
        "uploaded": uploaded,
        "skipped_verified": skipped,
        "skipped_rest_edge_blocked": len(blocked_keys),
        "rest_edge_blocked_keys": blocked_keys,
        "total": len(all_paths),
    })


app.add_typer(buckets_app, name="buckets")
app.add_typer(objects_app, name="objects")


COMMAND_CREDENTIALS = {
    "buckets": ["api_key"],
    "objects": ["api_key"],
}
