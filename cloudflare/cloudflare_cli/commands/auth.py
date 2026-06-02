"""Authentication commands for Cloudflare CLI."""
from cli_tools_shared.auth_commands import create_auth_app
from ..config import get_config
from . import profiles


def _test_handler(config):
    """Test Cloudflare API credentials by making a lightweight API call."""
    import requests

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"

    response = requests.get(
        f"{config.base_url}/zones",
        headers=headers,
        params={"per_page": 1},
        timeout=10,
    )
    response.raise_for_status()
    resp_data = response.json()
    if not resp_data.get("success"):
        errors = resp_data.get("errors", [])
        error_msg = errors[0].get("message", "Unknown error") if errors else "Token invalid"
        raise Exception(f"Credentials invalid: {error_msg}")
    return {"api_test": "passed", "method": "api_key"}


app = create_auth_app(
    get_config,
    tool_name="cloudflare",
    test_handler=_test_handler,
    profiles_app=profiles.app,
)
