"""Regression tests for eBay command credential mappings."""

import ast
from pathlib import Path


COMMANDS_DIR = Path(__file__).resolve().parents[1] / "ebay_cli" / "commands"


def _load_constant(module_path: Path, constant_name: str) -> dict[str, list[str]]:
    tree = ast.parse(module_path.read_text(), filename=str(module_path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == constant_name:
                return ast.literal_eval(node.value)
    raise AssertionError(f"{constant_name} not found in {module_path}")


def _load_command_credentials(module_name: str) -> dict[str, list[str]]:
    return _load_constant(COMMANDS_DIR / f"{module_name}.py", "COMMAND_CREDENTIALS")


def test_seller_group_commands_are_oauth_only():
    """Seller group commands use OAuth so live compliance tests have one auth path."""
    credentials = _load_command_credentials("seller")

    oauth_only_groups = {
        "get",
        "images",
        "inventory",
        "list",
        "listings",
        "locations",
        "messages",
        "orders",
        "payment-policies",
        "policies",
        "return-policies",
        "shipping-labels",
        "shipping-quote",
        "store",
        "templates",
    }
    for group in oauth_only_groups:
        assert credentials[group] == ["oauth_authorization_code"]


def test_seller_listings_commands_are_oauth_only():
    """Seller listings commands use OAuth; marketplace search is public."""
    credentials = _load_command_credentials("listings")

    for command_name in (
        "create",
        "delete",
        "get",
        "list",
        "preview",
        "publish",
        "unpublish",
        "update",
    ):
        assert credentials[command_name] == ["oauth_authorization_code"]

    assert credentials["search"] == ["no_auth"]


def test_marketplace_listing_search_requires_no_auth():
    """Top-level marketplace search uses a browser, but not a logged-in session."""
    assert _load_command_credentials("search") == {"search": ["no_auth"]}
