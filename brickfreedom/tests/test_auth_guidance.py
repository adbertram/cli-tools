from unittest.mock import MagicMock

import pytest

from brickfreedom_cli.client import BrickfreedomClient, ClientError


def test_unauthenticated_browser_guidance_uses_supported_login_command():
    """The single browser-session credential type does not expose ``-c``."""
    client = object.__new__(BrickfreedomClient)
    client._auth_checked = False
    client._browser = MagicMock()
    client._browser.is_authenticated.return_value = False

    with pytest.raises(ClientError, match="brickfreedom auth login") as error:
        client.get_page()

    assert "-c browser_session" not in str(error.value)
    client._browser.get_page.assert_not_called()
