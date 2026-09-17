"""Tests for the monarch auth login MFA flow (agent-issues #669).

Adam wants to type a one-time MFA code interactively at login time without
storing a persistent TOTP secret. The handler must:
- prompt for a code and retry when MFA is required and stdin is a TTY, and
- fail clearly (never hang) when MFA is required and stdin is not a TTY.
Existing headless callers where MFA is not required must keep working.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from monarch_cli.client import ClientError
from monarch_cli.commands import auth


def _config():
    return SimpleNamespace(
        username="adam@example.com",
        password="hunter2",
        clear_session=MagicMock(),
    )


def _patch_client(login_returns):
    """Patch MonarchClient so client.login returns/raises the given sequence."""
    client = MagicMock()
    client.login.side_effect = login_returns
    factory = patch.object(auth, "MonarchClient", return_value=client)
    return factory, client


def test_prompts_for_mfa_code_and_retries_on_tty():
    config = _config()
    factory, client = _patch_client(
        [
            {"success": False, "mfa_required": True},
            {"success": True, "mfa_required": False},
        ]
    )
    with factory, patch.object(auth.sys.stdin, "isatty", return_value=True), patch.object(
        auth.typer, "prompt", return_value="123456"
    ) as prompt:
        auth._login_handler(config, force=False)

    prompt.assert_called_once()
    assert client.login.call_count == 2
    # The retry passes the interactively-typed code.
    assert client.login.call_args_list[1].kwargs["mfa_code"] == "123456"


def test_fails_clearly_without_tty_and_does_not_prompt():
    config = _config()
    factory, client = _patch_client([{"success": False, "mfa_required": True}])
    with factory, patch.object(auth.sys.stdin, "isatty", return_value=False), patch.object(
        auth.typer, "prompt"
    ) as prompt:
        with pytest.raises(ClientError) as excinfo:
            auth._login_handler(config, force=False)

    prompt.assert_not_called()
    assert client.login.call_count == 1  # no hang, no retry
    assert "interactive terminal" in str(excinfo.value)


def test_headless_login_without_mfa_does_not_prompt():
    config = _config()
    factory, client = _patch_client([{"success": True, "mfa_required": False}])
    # Non-TTY (headless) caller: no MFA required -> must succeed with no prompt.
    with factory, patch.object(auth.sys.stdin, "isatty", return_value=False), patch.object(
        auth.typer, "prompt"
    ) as prompt:
        auth._login_handler(config, force=False)

    prompt.assert_not_called()
    assert client.login.call_count == 1


def test_force_clears_session_before_login():
    config = _config()
    factory, client = _patch_client([{"success": True, "mfa_required": False}])
    with factory, patch.object(auth.sys.stdin, "isatty", return_value=True):
        auth._login_handler(config, force=True)

    config.clear_session.assert_called_once()
