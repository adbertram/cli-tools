"""Authentication commands for Raptive CLI."""
from cli_tools_shared.auth_commands import create_auth_app
from ..config import get_config


def _test_handler(config):
    """Test by making API call with JWT from saved session."""
    from ..client import RaptiveClient
    client = RaptiveClient(config)
    try:
        client.get_date_bounds()
        return {"api_test": "passed"}
    except Exception as e:
        return {"api_test": f"failed: {e}"}
    finally:
        client.close()


app = create_auth_app(get_config, tool_name="raptive", test_handler=_test_handler)
