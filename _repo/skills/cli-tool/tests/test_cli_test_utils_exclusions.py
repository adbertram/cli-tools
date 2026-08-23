"""Tests for CLI-scoped list/get pairing exclusions."""

import tomllib
from pathlib import Path

import pytest

from cli_test_utils import resolve_exclusions

CONFIG = {
    "exclusions": {
        "excluded_from_list_required": ["status", "summary"],
        "excluded_from_get_required": ["search"],
    },
    "cli_specific": {
        "ebay": {"excluded_from_list_required": ["listings", "time-away"]},
    },
}


def test_global_exclusions_apply_to_every_cli():
    assert resolve_exclusions(CONFIG, "notion", "excluded_from_list_required") == [
        "status",
        "summary",
    ]


def test_cli_specific_exclusions_widen_the_global_list():
    assert resolve_exclusions(CONFIG, "ebay", "excluded_from_list_required") == [
        "status",
        "summary",
        "listings",
        "time-away",
    ]


def test_cli_specific_exclusions_do_not_leak_to_other_clis():
    assert "listings" not in resolve_exclusions(
        CONFIG, "wordpress", "excluded_from_list_required"
    )


def test_cli_specific_section_without_the_key_is_ignored():
    assert resolve_exclusions(CONFIG, "ebay", "excluded_from_get_required") == ["search"]


def test_unknown_exclusion_key_fails_loudly():
    with pytest.raises(KeyError):
        resolve_exclusions(CONFIG, "ebay", "excluded_from_nothing")


def test_repo_config_scopes_ebay_exclusions_per_cli():
    """The real config must keep eBay's exemptions out of the global lists."""
    config_path = Path(__file__).parent / "cli_test_config.toml"
    config = tomllib.loads(config_path.read_text())

    global_list = config["exclusions"]["excluded_from_list_required"]
    assert "listings" not in global_list
    assert "time-away" not in global_list

    ebay = resolve_exclusions(config, "ebay", "excluded_from_list_required")
    assert "listings" in ebay
    assert "time-away" in ebay
