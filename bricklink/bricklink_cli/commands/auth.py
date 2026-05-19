"""Authentication commands for Bricklink CLI."""
import typer
from cli_tools_shared.activity_log import get_activity_logger
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.output import print_success, print_info

from ..config import get_config

activity = get_activity_logger("bricklink")


def _test_handler(config):
    """Test Bricklink API credentials by making a lightweight API call.

    Browser session check is handled automatically by the common package
    via config.get_browser().
    """
    activity.info("auth test: verifying OAuth1 API credentials")
    from ..client import BricklinkClient
    client = BricklinkClient()
    client.test_connection()
    activity.info("auth test: API credentials verified successfully")
    return {"api_test": "passed", "method": "oauth1_api"}


app = create_auth_app(get_config, tool_name="bricklink", test_handler=_test_handler)


@app.command("confirm")
def auth_confirm():
    """Clear the legacy pending-confirmation flag from older Bricklink builds.

    Current browser commands do not store confirmation codes locally. If
    BrickLink redirects to ``confirmation_code_required``, the command fails
    immediately and tells the user to check email and retry.
    """
    activity.info("auth confirm: checking for pending confirmation")
    config = get_config()
    browser = config.get_browser()

    if not browser.confirmation.is_pending():
        activity.info("auth confirm: no pending confirmation found")
        print_info("No pending confirmation. All browser commands are available.")
        browser.close()
        raise typer.Exit(0)

    info = browser.confirmation.get()
    operation = info.get("operation", "unknown") if info else "unknown"
    order_id = info.get("order_id") if info else None
    timestamp = info.get("timestamp", "") if info else ""

    activity.info("auth confirm: clearing confirmation for operation=%s order_id=%s", operation, order_id)
    print_info(f"Pending confirmation for: {operation}")
    if order_id:
        print_info(f"Order ID: {order_id}")
    if timestamp:
        print_info(f"Since: {timestamp}")

    browser.confirmation.clear()
    activity.info("auth confirm: confirmation flag cleared")
    print_success("Confirmation flag cleared. Browser commands are available again.")
    browser.close()
