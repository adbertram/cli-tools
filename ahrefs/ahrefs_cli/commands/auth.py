"""Authentication commands for Ahrefs CLI."""
from cli_tools_shared.auth_commands import create_auth_app
from ..config import get_config


def _test_handler(config):
    """Test browser session by checking authentication state."""
    browser = config.get_browser()
    try:
        result = browser.test_session()
        if result.get("authenticated"):
            return {"api_test": "passed"}
        return {"api_test": f"failed: session not authenticated"}
    except Exception as e:
        return {"api_test": f"failed: {e}"}
    finally:
        browser.close()


app = create_auth_app(get_config, tool_name="ahrefs", test_handler=_test_handler)
