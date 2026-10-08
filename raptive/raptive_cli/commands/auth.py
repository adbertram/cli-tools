"""Authentication commands for Raptive CLI."""
from cli_tools_shared.auth_commands import create_auth_app
from ..config import get_config


def _test_handler(config):
    """Test with a live (never cached) publisher-API call from the saved session."""
    from ..client import RaptiveClient
    try:
        RaptiveClient.get_date_bounds.__wrapped__(RaptiveClient(config))
        return {"api_test": "passed"}
    except Exception as e:
        return {"api_test": f"failed: {e}"}


app = create_auth_app(get_config, tool_name="raptive", test_handler=_test_handler)
