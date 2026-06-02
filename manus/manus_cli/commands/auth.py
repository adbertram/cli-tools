"""Authentication commands for Manus CLI."""
import requests
from cli_tools_shared.auth_commands import create_auth_app
from ..config import get_config


def _test_auth(config):
    """Test authentication by making a lightweight API call."""
    try:
        response = requests.get(
            f"{config.base_url}/v2/task.list",
            headers={
                "x-manus-api-key": config.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            params={"limit": 1},
            timeout=10,
        )
        if response.status_code == 200:
            return {"api_test": "passed"}
        else:
            return {"api_test": f"failed: HTTP {response.status_code}"}
    except Exception as e:
        return {"api_test": f"failed: {e}"}


app = create_auth_app(
    get_config_fn=get_config,
    tool_name="manus",
    test_handler=_test_auth,
)
