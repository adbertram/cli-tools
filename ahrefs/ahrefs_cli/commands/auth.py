"""Authentication commands for Ahrefs CLI."""
from cli_tools_shared.auth_commands import create_auth_app
from ..config import get_config

AUTH_TEST_PROJECT_ID = 2185593


def _test_handler(config):
    """Test browser session by exercising the Ahrefs API used by commands."""
    from ..client import AhrefsClient

    client = AhrefsClient()
    try:
        client.list_crawls(AUTH_TEST_PROJECT_ID)
        return {"api_test": "passed", "project_id": AUTH_TEST_PROJECT_ID}
    except Exception as e:
        return {"api_test": f"failed: {e}"}
    finally:
        client.close()


app = create_auth_app(get_config, tool_name="ahrefs", test_handler=_test_handler)
