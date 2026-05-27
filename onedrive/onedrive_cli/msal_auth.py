"""Authentication for OneDrive CLI with multiple auth methods.

Supports two auth methods based on the active profile's AUTH_METHOD:
- az_cli: Gets Graph API tokens via Azure CLI
- msal_device_code: Uses MSAL device code flow with cached tokens

The az_cli method requires Azure CLI to be logged in.
The msal_device_code method uses Microsoft's well-known Graph Command Line Tools app.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import msal
import requests

from .config import get_config

# Microsoft Graph PowerShell public client application.
CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"

# Scopes required for OneDrive operations
# Note: offline_access is automatically requested by MSAL for refresh tokens
SCOPES = [
    "Files.ReadWrite.All",  # Full access to user's files
    "User.Read",            # Basic profile
]


def _get_az_cmd() -> str:
    """Resolve the full path to the Azure CLI executable.

    Uses shutil.which to find az, which correctly resolves .cmd/.exe
    extensions on Windows where subprocess.run(["az", ...]) fails.

    Returns:
        Full path to the az executable

    Raises:
        RuntimeError: If az is not found on PATH
    """
    az_path = shutil.which("az")
    if not az_path:
        raise RuntimeError(
            "Azure CLI ('az') not found. Install it: https://aka.ms/installazurecli"
        )
    return az_path


# ==================== Token Cache (MSAL) ====================

def _get_cache_path(config=None) -> Path:
    """Get the per-profile token cache file path."""
    active_config = config or get_config()
    return active_config.get_profile_data_dir() / "token_cache.json"


def _load_cache(config=None) -> msal.SerializableTokenCache:
    """Load token cache from disk."""
    cache = msal.SerializableTokenCache()
    cache_path = _get_cache_path(config)
    if cache_path.exists():
        cache.deserialize(cache_path.read_text())
    return cache


def _save_cache(cache: msal.SerializableTokenCache, config=None) -> None:
    """Save token cache to disk."""
    if cache.has_state_changed:
        cache_path = _get_cache_path(config)
        cache_path.write_text(cache.serialize())
        # Secure the file (readable only by owner)
        cache_path.chmod(0o600)


def _get_app(
    config=None,
    cache: Optional[msal.SerializableTokenCache] = None,
) -> msal.PublicClientApplication:
    """Get MSAL public client application."""
    if cache is None:
        cache = _load_cache(config)

    return msal.PublicClientApplication(
        client_id=CLIENT_ID,
        authority="https://login.microsoftonline.com/common",
        token_cache=cache,
    )


# ==================== Azure CLI Auth ====================

def _get_az_cli_token() -> str:
    """Get access token from Azure CLI.

    Runs: az account get-access-token --resource https://graph.microsoft.com

    Returns:
        Access token string

    Raises:
        RuntimeError: If az CLI is not installed, not logged in, or command fails
    """
    result = subprocess.run(
        [_get_az_cmd(), "account", "get-access-token", "--resource", "https://graph.microsoft.com"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(
            f"Azure CLI token acquisition failed (exit {result.returncode}): {stderr}\n"
            "Make sure Azure CLI is installed and you are logged in (run 'az login')."
        )
    data = json.loads(result.stdout)
    token = data.get("accessToken")
    if not token:
        raise RuntimeError("Azure CLI returned no accessToken in response.")
    return token


def _verify_drive_access(token: str) -> None:
    """Verify the token can access the OneDrive API surface this CLI uses."""
    response = requests.get(
        "https://graph.microsoft.com/v1.0/me/drives",
        params={"$top": 1},
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=30,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Microsoft Graph drive access failed ({response.status_code}): {response.text}"
        )


def _get_az_cli_status() -> dict:
    """Check Azure CLI authentication status.

    Returns:
        Dict with authentication status and account info
    """
    try:
        az_cmd = _get_az_cmd()
    except RuntimeError:
        return {"authenticated": False, "error": "Azure CLI ('az') not found."}

    result = subprocess.run(
        [az_cmd, "account", "show"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {"authenticated": False, "error": "Azure CLI not logged in. Run 'az login'."}

    data = json.loads(result.stdout)
    user = data.get("user", {})

    if user.get("type") != "user":
        return {
            "authenticated": False,
            "error": (
                "Azure CLI is logged in as a service principal. "
                "OneDrive commands use delegated Microsoft Graph /me endpoints. "
                "Run 'az login' with a user account or switch to an "
                "'msal_device_code' profile."
            ),
        }

    try:
        _verify_drive_access(_get_az_cli_token())
    except RuntimeError as exc:
        return {"authenticated": False, "error": str(exc)}

    return {
        "authenticated": True,
        "user": data.get("user", {}).get("name", "Unknown"),
        "name": data.get("user", {}).get("name", "Unknown"),
        "tenant": data.get("tenantId", "Unknown"),
    }


# ==================== MSAL Device Code Auth ====================

def _get_msal_token(config=None) -> str:
    """Get access token from MSAL cache.

    Returns:
        Access token string

    Raises:
        RuntimeError: If not authenticated
    """
    cache = _load_cache(config)
    app = _get_app(config=config, cache=cache)

    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            _save_cache(cache, config)
            return result["access_token"]

    raise RuntimeError(
        "Not authenticated. Run 'onedrive auth login' to authenticate."
    )


def _get_msal_status(config=None) -> dict:
    """Get MSAL authentication status.

    Returns:
        Dict with authentication status and user info
    """
    cache = _load_cache(config)
    app = _get_app(config=config, cache=cache)

    accounts = app.get_accounts()
    if not accounts:
        return {"authenticated": False}

    account = accounts[0]

    result = app.acquire_token_silent(SCOPES, account=account)

    if result and "access_token" in result:
        try:
            _verify_drive_access(result["access_token"])
        except RuntimeError as exc:
            return {"authenticated": False, "error": str(exc)}
        _save_cache(cache, config)
        return {
            "authenticated": True,
            "user": account.get("username", "Unknown"),
            "name": account.get("name", "Unknown"),
            "tenant": account.get("home_account_id", "").split(".")[1] if "." in account.get("home_account_id", "") else "Unknown",
        }

    return {"authenticated": False, "error": "Token expired or invalid"}


# ==================== Public API (routes by auth_method) ====================

def get_access_token() -> str:
    """Get an access token for Microsoft Graph API.

    Routes based on the active config's AUTH_METHOD:
    - az_cli: Gets token via Azure CLI
    - msal_device_code: Gets token from MSAL cache

    Returns:
        Access token string

    Raises:
        RuntimeError: If authentication fails or AUTH_METHOD is not set
    """
    config = get_config()
    method = config.auth_method

    if method == "az_cli":
        return _get_az_cli_token()
    elif method == "msal_device_code":
        return _get_msal_token(config)
    else:
        raise RuntimeError(
            f"Unknown or missing AUTH_METHOD: {method!r}. "
            "Set AUTH_METHOD to 'az_cli' or 'msal_device_code' in your profile."
        )


def login_handler(config, force: bool) -> None:
    """Login handler for create_auth_app integration.

    Routes based on config's AUTH_METHOD:
    - az_cli: Verifies Azure CLI is authenticated
    - msal_device_code: Performs interactive device code flow

    Args:
        config: Config instance
        force: If True, clear cached tokens before re-authenticating
    """
    from cli_tools_shared.output import print_info, print_success

    method = config.auth_method

    if not method:
        raise RuntimeError("AUTH_METHOD not set in profile. Set it to 'az_cli' or 'msal_device_code'.")

    if method == "az_cli":
        print_info("Auth method: Azure CLI")
        print_info("Verifying Azure CLI authentication...")
        status = _get_az_cli_status()
        if not status.get("authenticated"):
            raise RuntimeError(status.get("error") or "Azure CLI is not authenticated. Run 'az login' first.")
        print_success(f"Azure CLI authenticated as {status.get('user', 'Unknown')}")

    elif method == "msal_device_code":
        if force:
            cache_path = _get_cache_path(config)
            if cache_path.exists():
                cache_path.unlink()
            print_info("Cleared cached MSAL tokens.")

        print_info("Auth method: MSAL device code flow")
        print_info("Starting device code authentication...")
        print_info("You will need to open a browser and enter a code.\n")

        cache = _load_cache(config)
        app = _get_app(config=config, cache=cache)

        flow = app.initiate_device_flow(scopes=SCOPES)

        if "user_code" not in flow:
            raise RuntimeError(f"Failed to initiate device flow: {flow.get('error_description', 'Unknown error')}")

        print(flow["message"])
        sys.stdout.flush()

        result = app.acquire_token_by_device_flow(flow)

        if "access_token" not in result:
            error = result.get("error_description", result.get("error", "Unknown error"))
            raise RuntimeError(f"Authentication failed: {error}")

        _save_cache(cache, config)
        user = result.get("id_token_claims", {}).get("preferred_username", "Unknown")
        print_success(f"Authenticated as {user}")

    else:
        raise RuntimeError(
            f"Unknown AUTH_METHOD: {method!r}. "
            "Set AUTH_METHOD to 'az_cli' or 'msal_device_code' in your profile."
        )


def test_handler(config) -> dict:
    """Test handler for create_auth_app integration.

    Attempts to get an access token to verify auth is working.

    Args:
        config: Config instance

    Returns:
        Dict with api_test result
    """
    method = config.auth_method
    if not method:
        return {"api_test": "failed: AUTH_METHOD not set"}

    try:
        if method == "az_cli":
            status = _get_az_cli_status()
            if not status.get("authenticated"):
                return {"api_test": f"failed: {status.get('error', 'Azure CLI is not authenticated.')}"}
            token = _get_az_cli_token()
        elif method == "msal_device_code":
            token = _get_msal_token(config)
        else:
            return {"api_test": f"failed: unknown AUTH_METHOD {method!r}"}
        _verify_drive_access(token)
        return {"api_test": "passed", "auth_method": method}
    except Exception as e:
        return {"api_test": f"failed: {e}"}


def logout() -> None:
    """Clear cached tokens / session.

    For az_cli: instructs user to run az logout.
    For msal_device_code: clears MSAL token cache.
    """
    config = get_config()
    method = config.auth_method

    if method == "az_cli":
        print("Azure CLI auth — run 'az logout' to clear Azure CLI session.")
    elif method == "msal_device_code":
        cache_path = _get_cache_path(config)
        if cache_path.exists():
            cache_path.unlink()
    else:
        raise RuntimeError(
            f"Unknown or missing AUTH_METHOD: {method!r}."
        )


def get_auth_status() -> dict:
    """Get current authentication status.

    Routes based on the active config's AUTH_METHOD.

    Returns:
        Dict with authentication status, user info, profile name, and auth method
    """
    config = get_config()
    method = config.auth_method
    profile_name = config.get_active_profile_name()

    if method == "az_cli":
        status = _get_az_cli_status()
    elif method == "msal_device_code":
        status = _get_msal_status(config)
    else:
        status = {"authenticated": False, "error": f"Unknown AUTH_METHOD: {method!r}"}

    status["profile"] = profile_name
    status["auth_method"] = method
    return status
