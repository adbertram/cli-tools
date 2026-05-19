"""Unit tests for the command-registry credential gate.

After the persistent-profile refactor, the BROWSER_SESSION gate uses ONLY
``config.has_saved_session()`` — the single source of truth shared with
``auth status``. The previous ``AUTH_STORAGE_KEY`` / ``AUTH_COOKIE_PATTERNS``
offline checks operated on the deleted ``auth-state.json`` snapshot and
have been removed. CLIs that need a stricter live check perform it at the
point of use, not in the gate.
"""

from unittest.mock import MagicMock, patch

import pytest
import typer

from cli_tools_shared.command_registry import _check_credentials


def _config_with_session(has_session: bool) -> MagicMock:
    """Build a mock config whose ``has_saved_session()`` returns ``has_session``."""
    config = MagicMock()
    config.has_saved_session.return_value = has_session
    config.get_browser.return_value = MagicMock()
    return config


def test_static_oauth_gate_uses_required_fields_without_token_refresh():
    config = MagicMock()
    config.OAUTH_TOKEN_EXPIRES = False
    config.OAUTH_STATIC_REQUIRED_FIELDS = ("CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN", "REFRESH_TOKEN")
    config._get.side_effect = lambda field: {
        "CLIENT_ID": "consumer-key",
        "CLIENT_SECRET": "consumer-secret",
        "ACCESS_TOKEN": "token-value",
        "REFRESH_TOKEN": "token-secret",
    }.get(field)

    with patch("cli_tools_shared.token_manager.TokenManager") as MockTM:
        _check_credentials(config, ["oauth"], "tool")

    MockTM.assert_not_called()


def test_static_oauth_gate_fails_when_required_field_missing():
    config = MagicMock()
    config.OAUTH_TOKEN_EXPIRES = False
    config.OAUTH_STATIC_REQUIRED_FIELDS = ("CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN", "REFRESH_TOKEN")
    config._get.side_effect = lambda field: {
        "CLIENT_ID": "consumer-key",
        "CLIENT_SECRET": "consumer-secret",
        "ACCESS_TOKEN": "token-value",
        "REFRESH_TOKEN": "",
    }.get(field)

    with pytest.raises(typer.Exit):
        _check_credentials(config, ["oauth"], "tool")


def test_browser_session_gate_passes_when_config_has_saved_session():
    """``config.has_saved_session()`` is the only signal the gate consults."""
    config = _config_with_session(True)

    _check_credentials(config, ["browser_session"], "tool")

    config.has_saved_session.assert_called_once_with()


def test_browser_session_gate_fails_when_config_has_no_saved_session():
    config = _config_with_session(False)

    with pytest.raises(typer.Exit):
        _check_credentials(config, ["browser_session"], "tool")

    config.has_saved_session.assert_called_once_with()


def test_browser_session_gate_does_not_call_live_is_authenticated():
    """The gate must NEVER do a live browser navigation. That's the bug the
    refactor fixed: ``auth status`` (filesystem-only) disagreeing with the
    gate (which used to live-navigate).
    """
    config = _config_with_session(True)
    browser = config.get_browser.return_value

    _check_credentials(config, ["browser_session"], "tool")

    browser.is_authenticated.assert_not_called()
    browser.has_session.assert_not_called()


def test_browser_session_gate_does_not_consider_browser_class_attributes():
    """Old contract: gate looked at ``AUTH_STORAGE_KEY`` / ``AUTH_COOKIE_PATTERNS``
    on the browser subclass to do an offline disk check against
    ``auth-state.json``. New contract: those class attrs no longer affect
    the gate — only the persistent profile on disk does.
    """
    config = _config_with_session(False)
    browser = config.get_browser.return_value
    # Declare BOTH hooks — these used to bypass ``has_saved_session()``.
    browser.AUTH_STORAGE_KEY = "token"
    browser.AUTH_COOKIE_PATTERNS = [r"^session$"]

    # Even though the browser subclass declares both hooks, the gate fails
    # because ``has_saved_session()`` is False. The hooks have no effect.
    with pytest.raises(typer.Exit):
        _check_credentials(config, ["browser_session"], "tool")
