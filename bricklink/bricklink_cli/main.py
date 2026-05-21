"""Main entry point for Bricklink CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

from .config import get_config
from .commands import auth, catalog, coupon, inventory, member, messages, notification, order, refund

app = create_app(
    name="bricklink",
    help="CLI interface for Bricklink API",
    version=__version__,
)

# Register command modules.
#
# NOTE on invoice removal (2026-05-16):
# The legacy `invoice` command group depended on the browser-scraped page
# `https://www.bricklink.com/v3/billing/invoice.page`. Bricklink removed
# that page (and every adjacent `/v3/billing/*` and `/v2/*billing*` URL —
# all 302 to `/v3/error/404_not_found.page` or `/v2/error_404.page`) when
# they folded billing into the LEGO Identity portal at
# `identity.lego.com`. The Bricklink OAuth REST API has never exposed an
# invoice/billing endpoint (see client.py — there are no list_invoices /
# get_invoice methods to wire up). With both the scrape target and any
# programmatic alternative gone, the `invoice` commands have no working
# path and were silently returning fake all-null records via a fallback
# pattern that violated Fail-Fast. Deprecating the commands removes the
# lie. Restore them once Bricklink ships a real invoice endpoint we can
# call — at that point reintroduce `commands/invoice.py` and the
# `COMMAND_GROUPS` entry below.
COMMAND_GROUPS = (
    (order, "order", "Manage orders"),
    (inventory, "inventory", "Manage store inventory"),
    (catalog, "catalog", "Browse catalog data"),
    (member, "member", "Member information"),
    (coupon, "coupon", "Manage coupons"),
    (messages, "messages", "Manage messages (browser)"),
    (refund, "refund", "Manage refunds (browser)"),
    (notification, "notification", "Manage notifications (browser)"),
)

for module, name, help_text in COMMAND_GROUPS:
    register_commands(app, get_config, module, name=name, help=help_text)

# Register shared auth + cache apps
app.add_typer(auth.app, name="auth")
app.add_typer(create_cache_app(get_config), name="cache")

# Top-level browser commands (backward compatibility)
@app.command("send-wanted-list-notification", hidden=True)
def send_wanted_list_notification_cmd():
    """Send wanted list notification to matching stores (browser)."""
    notification.send_wanted_list_notification()


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
