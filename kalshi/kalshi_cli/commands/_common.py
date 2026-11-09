"""Shared option definitions, client construction and output helpers for command modules."""

import math
import threading
from typing import List, Optional

import typer
from cli_tools_shared.config import env_path_for_profile, get_runtime_profile_resolution
from cli_tools_shared.exceptions import ClientError, CredentialError
from cli_tools_shared.filters import FilterValidationError, apply_filters, apply_properties_filter, validate_filters
from cli_tools_shared.output import print_info, print_json, print_table

from ..client import KalshiClient, resolve_env
from ..config import get_config
from ..signing import Signer, decode_private_key

ENV_OPTION = typer.Option(None, "--env", "-e", help="Exchange environment: prod (default) or demo")
DEMO_OPTION = typer.Option(False, "--demo", help="Use the demo exchange (same as --env demo)")
TABLE_OPTION = typer.Option(False, "--table", "-t", help="Display as table")
LIMIT_OPTION = typer.Option(100, "--limit", "-l", min=1, max=10000, help="Maximum number of results (1-10000)")
FILTER_OPTION = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)")
PROPERTIES_OPTION = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include")


def _signer(env: str) -> Signer:
    """Load the key pair for an environment: demo uses the `demo` profile, prod the active or explicit profile."""
    runtime = get_runtime_profile_resolution()[0]
    if env == "demo":
        if runtime not in (None, "default", "demo"):
            raise ClientError(f"--profile {runtime} cannot be used with the demo exchange, which uses the 'demo' profile.")
        profile = "demo"
    else:
        if runtime == "demo":
            raise ClientError("Profile 'demo' holds demo credentials. Add --demo to use the demo exchange.")
        profile = runtime
    flag = f" --profile {profile}" if profile not in (None, "default") else ""
    if profile and not env_path_for_profile("kalshi", profile).exists():
        raise CredentialError(f"No Kalshi {env} credentials: profile '{profile}' does not exist. Run: kalshi auth login{flag}")
    config = get_config(profile=profile)
    if not config.key_id or not config.private_key:
        raise CredentialError(f"No Kalshi {env} credentials saved. Run: kalshi auth login{flag}")
    return Signer(config.key_id, decode_private_key(config.private_key))


def open_client(env: Optional[str], demo: bool, auth: bool = False) -> KalshiClient:
    """Build a client for the selected environment.

    With `auth`, the connection is opened in the background while the credentials load
    (the secret-manager read is the slowest local step), so the first signed call reuses it.
    """
    client = KalshiClient(env=resolve_env(env, demo), signer_factory=lambda: _signer(client.env))
    if auth:
        warm = threading.Thread(target=_prewarm, args=(client,), daemon=True)
        warm.start()
        client.signer
        warm.join()
    return client


def _prewarm(client: KalshiClient) -> None:
    try:
        client.prewarm()
    except ClientError:
        pass  # prewarm only opens the socket; the first real request reports any connection problem


def check_filters(filters: Optional[List[str]]) -> None:
    if not filters:
        return
    try:
        validate_filters(filters)
    except FilterValidationError as exc:
        raise typer.BadParameter(str(exc))


def emit_rows(rows: list, filters: Optional[List[str]], table: bool, properties: Optional[str], columns: list, empty: str) -> None:
    if filters:
        rows = apply_filters(rows, filters)
    fields = [field.strip() for field in properties.split(",") if field.strip()] if properties else None
    if fields:
        rows = apply_properties_filter(rows, properties)
    if not table:
        print_json(rows)
    elif not rows:
        print_info(empty)
    else:
        shown = fields or columns
        print_table(rows, shown, [name.replace("_", " ").title() for name in shown])


def emit_record(row: dict, table: bool, properties: Optional[str]) -> None:
    fields = [field.strip() for field in properties.split(",") if field.strip()] if properties else None
    if fields:
        row = apply_properties_filter([row], properties)[0]
    if table:
        print_table([{"field": key, "value": str(value)} for key, value in row.items()], ["field", "value"], ["Field", "Value"])
    else:
        print_json(row)


def finite(value: Optional[float], name: str) -> Optional[float]:
    """Reject NaN and infinity for a numeric option."""
    if value is not None and not math.isfinite(value):
        raise typer.BadParameter(f"{name} must be a finite number.")
    return value
