"""Main entry point for the Venmo CLI."""

import os
import sys
from typing import List, Optional

import typer
from cli_tools_shared import create_app, read_cli_tool_secret, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import (
    command,
    print_error,
    print_info,
    print_json,
    print_success,
    print_table,
)
from cli_tools_shared.repo_paths import secret_manager_script

from . import __version__
from .client import get_client
from .config import get_config

# Curated columns for the --table view ONLY. The default JSON output is the
# raw Venmo API payload (every field Venmo returns) — the table view extracts
# a human-readable subset using dotted paths supported by the shared
# print_table helper / apply_properties_filter.
TRANSACTION_COLUMNS = [
    "payment_id",
    "date_created",
    "type",
    "payment.action",
    "payment.amount",
    "payment.status",
    "payment.actor.display_name",
    "payment.target.user.display_name",
    "note",
]

SECRETS_SCRIPT = str(secret_manager_script())

app = create_app(name="venmo", help="CLI interface for Venmo (transaction history)", version=__version__)
transactions_app = typer.Typer(help="Manage Venmo transactions", no_args_is_help=True)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _property_fields(properties: Optional[str]) -> Optional[List[str]]:
    if properties is None:
        return None
    fields = [field.strip() for field in properties.split(",") if field.strip()]
    return fields or None


def _validate(filters: Optional[List[str]]) -> None:
    if not filters:
        return
    try:
        validate_filters(filters)
    except FilterValidationError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


def _render(rows: List[dict], table: bool, properties: Optional[str], empty: str, columns: List[str]) -> None:
    """Render records to stdout.

    Default JSON output preserves the raw nested record shape. The table view
    is curated: nested values are extracted via dotted-path properties so the
    table stays readable. `--properties` (also dotted-path) overrides the
    default column set.
    """
    fields = _property_fields(properties)
    if not table:
        # JSON output: apply property whitelist if requested, otherwise pass
        # through the raw record shape unchanged.
        if fields:
            rows = apply_properties_filter(rows, properties)
        print_json(rows)
        return
    if not rows:
        print_info(empty)
        return
    cols = fields or columns
    # Table view: always flatten via apply_properties_filter so the dotted-path
    # columns resolve to top-level keys that print_table can read. (print_table
    # does not understand dotted paths on its own.)
    flat_rows = apply_properties_filter(rows, ",".join(cols))
    print_table(flat_rows, cols, [_header(c) for c in cols], max_columns=0)


# Friendly, disambiguated headers for the default --table view. Any dotted-path
# column not listed here falls back to a Title-Cased version of the last segment.
_TABLE_HEADERS = {
    "payment_id": "Payment Id",
    "date_created": "Date",
    "type": "Type",
    "payment.action": "Action",
    "payment.amount": "Amount",
    "payment.status": "Status",
    "payment.actor.display_name": "Actor",
    "payment.target.user.display_name": "Target",
    "note": "Note",
}


def _header(column: str) -> str:
    """Render a dotted-path column key as a human-readable header."""
    if column in _TABLE_HEADERS:
        return _TABLE_HEADERS[column]
    last = column.rsplit(".", 1)[-1]
    return last.replace("_", " ").title()


# ---------------------------------------------------------------------------
# Secret store helpers
# ---------------------------------------------------------------------------


def _get_secret(name: str) -> Optional[str]:
    """Read a secret from the CLI-tools keychain. Returns None if absent."""
    return read_cli_tool_secret(name)


def _require_secret(name: str) -> str:
    value = _get_secret(name)
    if not value:
        raise ClientError(
            f"Required secret '{name}' is not set in the CLI-tools keychain. "
            f"Store it via: {SECRETS_SCRIPT} set {name}"
        )
    return value


# ---------------------------------------------------------------------------
# Custom login handler: username/password -> OTP -> access_token
# ---------------------------------------------------------------------------


def venmo_login_handler(config, force: bool) -> None:
    """Authenticate against Venmo's private API using keychain credentials.

    Flow:
    1. Read venmo-username and venmo-password from the CLI-tools keychain.
    2. POST /oauth/access_token with the credentials. If Venmo returns a
       2-factor error (code 81109), capture the venmo-otp-secret header.
    3. Trigger an SMS OTP via /account/two-factor/token.
    4. Prompt the user for the 6-digit OTP, exchange it for an access_token.
    5. Mark the device trusted to avoid OTP on the next login.
    6. Persist ACCESS_TOKEN and DEVICE_ID to the per-profile .env.
    """
    if config.access_token and not force:
        print_info("Already authenticated. Use --force to re-authenticate.")
        return

    username = _require_secret("venmo-username")
    password = _require_secret("venmo-password")

    # Import lazily so import errors only surface when login is actually run.
    from venmo_api import ApiClient, AuthenticationApi, AuthenticationFailedError

    device_id = config.device_id  # reuse a previously trusted device id when present
    authn = AuthenticationApi(api_client=ApiClient(), device_id=device_id)
    effective_device_id = authn.get_device_id()

    print_info(f"Authenticating with Venmo as '{username}' (device-id: {effective_device_id})")

    try:
        response = authn.authenticate_using_username_password(username, password)
    except Exception as exc:  # noqa: BLE001 — surface Venmo error verbatim
        raise ClientError(f"Venmo username/password authentication failed: {exc}")

    body = response.get("body") or {}
    if body.get("error"):
        # Two-factor required.
        otp_secret = response.get("headers", {}).get("venmo-otp-secret")
        if not otp_secret:
            raise ClientError(
                "Venmo did not return an OTP secret. Check that the venmo-username "
                "and venmo-password secrets are correct."
            )
        print_info("Two-factor authentication required. Sending SMS OTP to your phone...")
        try:
            authn.send_text_otp(otp_secret=otp_secret)
        except AuthenticationFailedError as exc:
            raise ClientError(f"Failed to send Venmo OTP: {exc}")

        otp = _prompt_for_otp()
        try:
            access_token = authn.authenticate_using_otp(otp, otp_secret)
        except Exception as exc:  # noqa: BLE001
            raise ClientError(f"Venmo OTP exchange failed: {exc}")
        try:
            authn.set_access_token(access_token)
            authn.trust_this_device()
        except Exception as exc:  # noqa: BLE001
            # Trust-device is best-effort; do not fail the login over it.
            print_info(f"Note: could not mark device trusted ({exc}). You may be prompted for OTP next login.")
    else:
        access_token = body.get("access_token")
        if not access_token:
            raise ClientError(f"Venmo authentication returned no access token: {body}")

    config.save_credentials(ACCESS_TOKEN=access_token, DEVICE_ID=effective_device_id)
    print_success("Venmo authentication succeeded. Access token saved.")


def _prompt_for_otp() -> str:
    """Get the 6-digit OTP. Resolution order (single deterministic path):

    1. VENMO_OTP env var if set (the non-interactive automation channel).
    2. /dev/tty read if the process has a controlling terminal.
    3. Standard typer.prompt against stdin.

    Fails loudly with ClientError if none of these can produce a 6-digit value.
    """
    env_otp = os.environ.get("VENMO_OTP", "").strip()
    if env_otp:
        if len(env_otp) == 6 and env_otp.isdigit():
            return env_otp
        raise ClientError(
            f"VENMO_OTP is set but is not a 6-digit number (got '{env_otp}')."
        )

    # Try /dev/tty so the prompt works even when stdin is piped/closed.
    # Fall through to stdin only when /dev/tty is unavailable (CI / container).
    try:
        stream = open("/dev/tty", "r+")
        is_tty = True
    except OSError:
        stream = sys.stdin
        is_tty = False

    try:
        for _ in range(3):
            if is_tty:
                stream.write("Enter the 6-digit OTP Venmo sent to your phone: ")
                stream.flush()
            else:
                print_info("Enter the 6-digit OTP Venmo sent to your phone (or set VENMO_OTP env var):")
            line = stream.readline()
            if not line:
                break
            value = line.strip()
            if len(value) == 6 and value.isdigit():
                return value
            print_error("OTP must be exactly 6 digits. Try again.")
    finally:
        if is_tty:
            stream.close()

    raise ClientError(
        "Could not obtain Venmo OTP. Pass it via the VENMO_OTP environment variable, "
        "e.g. 'VENMO_OTP=123456 venmo auth login --force', or run from an interactive terminal."
    )


# ---------------------------------------------------------------------------
# transactions list / get
# ---------------------------------------------------------------------------


@transactions_app.command("list")
@command
def list_transactions(
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum number of transactions"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter results (field:op:value, repeatable)"
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
    before_id: Optional[str] = typer.Option(
        None, "--before-id", help="Return transactions older than this story id (pagination)"
    ),
    profile: Optional[str] = typer.Option(
        None, "--profile", help="Authentication profile to use"
    ),
):
    """List Venmo transactions visible to the authenticated account."""
    _validate(filter)
    rows = get_client(profile=profile).list_transactions(limit=limit, before_id=before_id)
    if filter:
        rows = apply_filters(rows, filter)
    _render(rows, table, properties, "No transactions found.", TRANSACTION_COLUMNS)


@transactions_app.command("get")
@command
def get_transaction(
    transaction_id: str = typer.Argument(..., help="Transaction (story) id"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
    profile: Optional[str] = typer.Option(
        None, "--profile", help="Authentication profile to use"
    ),
):
    """Look up a single transaction by payment id from recent history.

    Default output is the raw Venmo API payload (full nested shape, identical
    to one entry from `transactions list`). `--table` renders the curated
    columns; `--properties` (dotted paths) overrides the column set.
    """
    row = get_client(profile=profile).get_transaction(transaction_id)
    fields = _property_fields(properties)
    if table:
        cols = fields or TRANSACTION_COLUMNS
        flat = apply_properties_filter([row], ",".join(cols))
        print_table(flat, cols, [_header(c) for c in cols], max_columns=0)
        return
    # JSON output: preserve the historical single-dict envelope. `print_json`
    # merges dicts at the top level alongside `cache_hit`, so the final shape
    # is `{cache_hit: bool, <all raw payload keys>}` — easier to script than a
    # one-element results list.
    if fields:
        record = apply_properties_filter([row], properties)[0]
    else:
        record = row
    print_json(record)


# ---------------------------------------------------------------------------
# Wire up the app
# ---------------------------------------------------------------------------

def venmo_auth_test_handler(config) -> dict:
    """Live round-trip test: fetch the authenticated user's profile via venmo-api."""
    try:
        from venmo_api import Client as VenmoApiClient

        client = VenmoApiClient(access_token=config.access_token)
        profile = client.my_profile()
        if profile is None or getattr(profile, "id", None) is None:
            return {"api_test": "failed: no profile returned"}
        return {"api_test": "passed", "user_id": profile.id}
    except Exception as exc:  # noqa: BLE001
        return {"api_test": f"failed: {exc}"}


app.add_typer(transactions_app, name="transactions")
app.add_typer(
    create_auth_app(
        get_config,
        tool_name="venmo",
        login_handler=venmo_login_handler,
        test_handler=venmo_auth_test_handler,
    ),
    name="auth",
)
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
