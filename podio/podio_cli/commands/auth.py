"""Authentication commands for Podio CLI."""
from cli_tools_shared.auth_commands import create_auth_app
from ..config import get_config


def _test_handler(config):
    """Test Podio API credentials by making a lightweight API call."""
    from ..client import get_client
    client = get_client()
    user = client.User.current()
    return {
        "api_test": "passed",
        "user_id": user.get("user_id"),
        "email": user.get("mail"),
    }


app = create_auth_app(get_config, tool_name="podio", test_handler=_test_handler)
