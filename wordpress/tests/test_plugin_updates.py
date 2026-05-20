from unittest.mock import MagicMock, call

import pytest

from cli_tools_shared.exceptions import ClientError
from wordpress_cli.client import (
    JETPACK_PLUGIN_MANAGEMENT_ERROR,
    WPCOM_API_BASE_URL,
    WPCOM_PLUGIN_AUTHORIZATION_ERROR,
    WordPressClient,
)
from wordpress_cli.commands.plugins import requires_update_status
from wordpress_cli.models import create_plugin


class DummyResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.ok = 200 <= status_code < 300
        self.text = str(payload)

    def json(self):
        return self._payload


def make_client(update_count, plugin_info):
    client = WordPressClient.__new__(WordPressClient)
    client.get_plugin_update_count = lambda: update_count
    client.get_wordpress_org_plugin_info = lambda slug: plugin_info[slug]
    return client


def test_enrich_plugins_with_public_latest_versions_and_closed_status():
    plugins = [
        create_plugin({"plugin": "akismet/akismet", "name": "Akismet", "status": "active", "version": "5.7"}),
        create_plugin({"plugin": "advanced-custom-fields/acf", "name": "ACF", "status": "active", "version": "6.3.12"}),
        create_plugin({"plugin": "acf-to-rest-api/class-acf-to-rest-api", "name": "ACF REST", "status": "active", "version": "3.3.4"}),
        create_plugin({"plugin": "facetwp/index", "name": "FacetWP", "status": "active", "version": "4.5"}),
    ]
    client = make_client(
        0,
        {
            "akismet": {"status": "found", "slug": "akismet", "version": "5.7"},
            "advanced-custom-fields": {"status": "found", "slug": "advanced-custom-fields", "version": "6.8.1"},
            "acf-to-rest-api": {"status": "closed", "slug": "acf-to-rest-api"},
            "facetwp": {"status": "not_found", "slug": "facetwp"},
        },
    )

    results = {plugin.plugin: plugin for plugin in client.enrich_plugins_with_update_status(plugins)}

    assert results["akismet/akismet"].update_status == "current"
    assert results["akismet/akismet"].latest_version == "5.7"
    assert results["advanced-custom-fields/acf"].update_status == "available"
    assert results["advanced-custom-fields/acf"].latest_version == "6.8.1"
    assert results["acf-to-rest-api/class-acf-to-rest-api"].update_status == "closed"
    assert results["acf-to-rest-api/class-acf-to-rest-api"].latest_version is None
    assert results["facetwp/index"].update_status == "current"
    assert results["facetwp/index"].latest_version == "4.5"
    assert results["facetwp/index"].latest_version_source == "site_update_check"


def test_enrich_plugins_marks_private_plugins_unverified_when_update_count_is_unresolved():
    plugins = [
        create_plugin({"plugin": "akismet/akismet", "name": "Akismet", "status": "active", "version": "5.6"}),
        create_plugin({"plugin": "facetwp/index", "name": "FacetWP", "status": "active", "version": "4.5"}),
    ]
    client = make_client(
        2,
        {
            "akismet": {"status": "found", "slug": "akismet", "version": "5.7"},
            "facetwp": {"status": "not_found", "slug": "facetwp"},
        },
    )

    results = {plugin.plugin: plugin for plugin in client.enrich_plugins_with_update_status(plugins)}

    assert results["akismet/akismet"].update_status == "available"
    assert results["akismet/akismet"].latest_version == "5.7"
    assert results["facetwp/index"].update_status == "unverified"
    assert results["facetwp/index"].latest_version is None


def test_requires_update_status_only_when_latest_version_fields_are_requested():
    assert requires_update_status("name,status,version") is False
    assert requires_update_status("name,status,version,latest_version") is True
    assert requires_update_status("name,status,version,update_status") is True


def test_upgrade_plugin_uses_native_update_without_delete_or_reinstall():
    client = WordPressClient.__new__(WordPressClient)
    client.config = type(
        "Config",
        (),
        {
            "wpcom_access_token": "token",
            "wpcom_site": "example.com",
        },
    )()

    current = create_plugin(
        {
            "plugin": "sample/sample",
            "name": "Sample",
            "status": "active",
            "version": "1.0",
            "update_status": "available",
            "latest_version": "1.1",
            "update_version": "1.1",
            "latest_version_source": "wordpress.org",
        }
    )
    upgraded = create_plugin(
        {
            "plugin": "sample/sample",
            "name": "Sample",
            "status": "active",
            "version": "1.1",
            "update_status": "current",
            "latest_version": "1.1",
            "update_version": "1.1",
            "latest_version_source": "wordpress.org",
        }
    )

    plugin_reads = [current, upgraded]

    def get_plugin(plugin, include_update_status=False):
        assert plugin == "sample/sample"
        assert include_update_status is True
        return plugin_reads.pop(0)

    client.get_plugin = get_plugin
    client._assert_jetpack_plugin_management_connected = MagicMock()
    client._make_wpcom_request = MagicMock(return_value={"id": "sample/sample", "version": "1.1"})
    client.update_plugin = MagicMock()
    client.delete_plugin = MagicMock()
    client.install_plugin = MagicMock()

    result = client.upgrade_plugin("sample/sample")

    assert result.version == "1.1"
    client._make_wpcom_request.assert_called_once_with(
        "POST",
        "/sites/example.com/plugins/sample%2Fsample/update/",
    )
    client._assert_jetpack_plugin_management_connected.assert_called_once_with()
    client.update_plugin.assert_not_called()
    client.delete_plugin.assert_not_called()
    client.install_plugin.assert_not_called()


def test_upgrade_plugin_rejects_plugins_without_available_update():
    client = WordPressClient.__new__(WordPressClient)
    client.get_plugin = MagicMock(
        return_value=create_plugin(
            {
                "plugin": "sample/sample",
                "name": "Sample",
                "status": "active",
                "version": "1.1",
                "update_status": "current",
                "latest_version": "1.1",
            }
        )
    )
    client._make_wpcom_request = MagicMock()

    with pytest.raises(ClientError, match="does not have an available update"):
        client.upgrade_plugin("sample/sample")

    client._make_wpcom_request.assert_not_called()


def test_upgrade_plugin_fails_when_readback_is_not_current():
    client = WordPressClient.__new__(WordPressClient)
    client.config = type(
        "Config",
        (),
        {
            "wpcom_access_token": "token",
            "wpcom_site": "example.com",
        },
    )()

    current = create_plugin(
        {
            "plugin": "sample/sample",
            "name": "Sample",
            "status": "active",
            "version": "1.0",
            "update_status": "available",
            "latest_version": "1.1",
        }
    )
    still_outdated = create_plugin(
        {
            "plugin": "sample/sample",
            "name": "Sample",
            "status": "active",
            "version": "1.0",
            "update_status": "available",
            "latest_version": "1.1",
        }
    )
    plugin_reads = [current, still_outdated]
    client.get_plugin = MagicMock(side_effect=lambda plugin, include_update_status=False: plugin_reads.pop(0))
    client._assert_jetpack_plugin_management_connected = MagicMock()
    client._make_wpcom_request = MagicMock(return_value={"id": "sample/sample"})

    with pytest.raises(ClientError, match="update did not complete"):
        client.upgrade_plugin("sample/sample")


def test_upgrade_plugin_auto_acquires_missing_wpcom_token(monkeypatch):
    client = WordPressClient.__new__(WordPressClient)

    class Config:
        def __init__(self):
            self.wpcom_access_token = None
            self.wpcom_site = "example.com"

        def clear_wpcom_access_token(self):
            self.wpcom_access_token = None

    client.config = Config()

    current = create_plugin(
        {
            "plugin": "sample/sample",
            "name": "Sample",
            "status": "active",
            "version": "1.0",
            "update_status": "available",
            "latest_version": "1.1",
            "update_version": "1.1",
            "latest_version_source": "wordpress.org",
        }
    )
    upgraded = create_plugin(
        {
            "plugin": "sample/sample",
            "name": "Sample",
            "status": "active",
            "version": "1.1",
            "update_status": "current",
            "latest_version": "1.1",
            "update_version": "1.1",
            "latest_version_source": "wordpress.org",
        }
    )
    plugin_reads = [current, upgraded]
    client.get_plugin = MagicMock(side_effect=lambda plugin, include_update_status=False: plugin_reads.pop(0))
    client._assert_jetpack_plugin_management_connected = MagicMock()
    client._dispatch_wpcom_request = MagicMock(return_value=DummyResponse(200, {"id": "sample/sample"}))

    def fake_acquire(config):
        config.wpcom_access_token = "fresh-token"
        return {"site": config.wpcom_site, "token_saved": True}

    monkeypatch.setattr("wordpress_cli.client.acquire_wpcom_access_token", fake_acquire)

    result = client.upgrade_plugin("sample/sample")

    assert result.version == "1.1"
    client._dispatch_wpcom_request.assert_called_once_with(
        "POST",
        f"{WPCOM_API_BASE_URL}/sites/example.com/plugins/sample%2Fsample/update/",
        "fresh-token",
        None,
    )


def test_make_wpcom_request_reacquires_on_invalid_token_once(monkeypatch):
    client = WordPressClient.__new__(WordPressClient)

    class Config:
        def __init__(self):
            self.wpcom_access_token = "stale-token"
            self.wpcom_site = "example.com"
            self.clear_count = 0

        def clear_wpcom_access_token(self):
            self.clear_count += 1
            self.wpcom_access_token = None

    client.config = Config()
    client._dispatch_wpcom_request = MagicMock(
        side_effect=[
            DummyResponse(401, {"error": "invalid_token"}),
            DummyResponse(200, {"id": "sample/sample"}),
        ]
    )

    def fake_acquire(config):
        config.wpcom_access_token = "fresh-token"
        return {"site": config.wpcom_site, "token_saved": True}

    acquire = MagicMock(side_effect=fake_acquire)
    monkeypatch.setattr("wordpress_cli.client.acquire_wpcom_access_token", acquire)

    result = client._make_wpcom_request("POST", "/sites/example.com/plugins/sample%2Fsample/update/")

    assert result == {"id": "sample/sample"}
    assert client.config.clear_count == 1
    assert acquire.call_count == 1
    assert client._dispatch_wpcom_request.call_args_list == [
        call(
            "POST",
            f"{WPCOM_API_BASE_URL}/sites/example.com/plugins/sample%2Fsample/update/",
            "stale-token",
            None,
        ),
        call(
            "POST",
            f"{WPCOM_API_BASE_URL}/sites/example.com/plugins/sample%2Fsample/update/",
            "fresh-token",
            None,
        ),
    ]


def test_make_wpcom_request_reacquires_on_plugin_forbidden_once(monkeypatch):
    client = WordPressClient.__new__(WordPressClient)

    class Config:
        def __init__(self):
            self.wpcom_access_token = "stale-token"
            self.wpcom_site = "example.com"
            self.clear_count = 0

        def clear_wpcom_access_token(self):
            self.clear_count += 1
            self.wpcom_access_token = None

    client.config = Config()
    client._dispatch_wpcom_request = MagicMock(
        side_effect=[
            DummyResponse(403, {"error": "authorization_required"}),
            DummyResponse(200, [{"plugin": "sample/sample"}]),
        ]
    )

    def fake_acquire(config):
        config.wpcom_access_token = "fresh-token"
        return {"site": config.wpcom_site, "token_saved": True}

    acquire = MagicMock(side_effect=fake_acquire)
    monkeypatch.setattr("wordpress_cli.client.acquire_wpcom_access_token", acquire)

    result = client._make_wpcom_request(
        "GET",
        "/sites/example.com/plugins",
        retry_on_forbidden=True,
    )

    assert result == [{"plugin": "sample/sample"}]
    assert client.config.clear_count == 1
    assert acquire.call_count == 1
    assert client._dispatch_wpcom_request.call_args_list == [
        call(
            "GET",
            f"{WPCOM_API_BASE_URL}/sites/example.com/plugins",
            "stale-token",
            None,
        ),
        call(
            "GET",
            f"{WPCOM_API_BASE_URL}/sites/example.com/plugins",
            "fresh-token",
            None,
        ),
    ]


def test_make_wpcom_request_fails_clearly_when_plugin_access_stays_forbidden(monkeypatch):
    client = WordPressClient.__new__(WordPressClient)

    class Config:
        def __init__(self):
            self.wpcom_access_token = "stale-token"
            self.wpcom_site = "example.com"

        def clear_wpcom_access_token(self):
            self.wpcom_access_token = None

    client.config = Config()
    client._dispatch_wpcom_request = MagicMock(
        side_effect=[
            DummyResponse(403, {"error": "authorization_required"}),
            DummyResponse(403, {"error": "authorization_required"}),
        ]
    )

    def fake_acquire(config):
        config.wpcom_access_token = "fresh-token"
        return {"site": config.wpcom_site, "token_saved": True}

    monkeypatch.setattr("wordpress_cli.client.acquire_wpcom_access_token", MagicMock(side_effect=fake_acquire))

    with pytest.raises(ClientError, match=WPCOM_PLUGIN_AUTHORIZATION_ERROR):
        client._make_wpcom_request(
            "GET",
            "/sites/example.com/plugins",
            retry_on_forbidden=True,
        )


def test_upgrade_plugin_fails_clearly_when_wpcom_credentials_are_missing(monkeypatch):
    client = WordPressClient.__new__(WordPressClient)

    class Config:
        wpcom_access_token = None
        wpcom_site = "example.com"

        def clear_wpcom_access_token(self):
            self.wpcom_access_token = None

    client.config = Config()

    current = create_plugin(
        {
            "plugin": "sample/sample",
            "name": "Sample",
            "status": "active",
            "version": "1.0",
            "update_status": "available",
            "latest_version": "1.1",
            "update_version": "1.1",
            "latest_version_source": "wordpress.org",
        }
    )
    client.get_plugin = MagicMock(side_effect=[current])
    client._assert_jetpack_plugin_management_connected = MagicMock()
    client.update_plugin = MagicMock()
    client.delete_plugin = MagicMock()
    client.install_plugin = MagicMock()

    monkeypatch.setattr(
        "wordpress_cli.client.acquire_wpcom_access_token",
        MagicMock(
            side_effect=ClientError(
                "Missing WordPress.com credentials: WPCOM_CLIENT_ID. "
                "Run `wordpress org token save-credential --client-id ... --client-secret ... "
                "--site ... --redirect-uri ...` to save the full WordPress.com credential bundle."
            )
        ),
    )

    with pytest.raises(ClientError, match="Missing WordPress.com credentials: WPCOM_CLIENT_ID"):
        client.upgrade_plugin("sample/sample")

    client.update_plugin.assert_not_called()
    client.delete_plugin.assert_not_called()
    client.install_plugin.assert_not_called()


def test_upgrade_plugin_fails_before_wpcom_request_when_jetpack_user_is_not_connected():
    client = WordPressClient.__new__(WordPressClient)
    client.config = type("Config", (), {"wpcom_site": "example.com"})()
    client.get_plugin = MagicMock(
        return_value=create_plugin(
            {
                "plugin": "sample/sample",
                "name": "Sample",
                "status": "active",
                "version": "1.0",
                "update_status": "available",
                "latest_version": "1.1",
                "update_version": "1.1",
                "latest_version_source": "wordpress.org",
            }
        )
    )
    client._get_jetpack_connection_data = MagicMock(
        return_value={"currentUser": {"isConnected": False}}
    )
    client._make_wpcom_request = MagicMock()

    with pytest.raises(ClientError, match=JETPACK_PLUGIN_MANAGEMENT_ERROR):
        client.upgrade_plugin("sample/sample")

    client._make_wpcom_request.assert_not_called()


def test_upgrade_plugin_proceeds_when_connected_user_can_manage_plugins_and_wpcom_site_is_visible():
    client = WordPressClient.__new__(WordPressClient)
    client.config = type(
        "Config",
        (),
        {
            "wpcom_site": "example.com",
            "wpcom_access_token": "token",
        },
    )()
    current = create_plugin(
        {
            "plugin": "sample/sample",
            "name": "Sample",
            "status": "active",
            "version": "1.0",
            "update_status": "available",
            "latest_version": "1.1",
            "update_version": "1.1",
            "latest_version_source": "wordpress.org",
        }
    )
    upgraded = create_plugin(
        {
            "plugin": "sample/sample",
            "name": "Sample",
            "status": "active",
            "version": "1.1",
            "update_status": "current",
            "latest_version": "1.1",
            "update_version": "1.1",
            "latest_version_source": "wordpress.org",
        }
    )
    plugin_reads = [current, upgraded]
    client.get_plugin = MagicMock(side_effect=lambda plugin, include_update_status=False: plugin_reads.pop(0))
    client._get_jetpack_connection_data = MagicMock(
        return_value={
            "currentUser": {
                "isConnected": True,
                "permissions": {
                    "manage_plugins": True,
                },
            }
        }
    )
    client._make_wpcom_request = MagicMock(
        side_effect=[
            {
                "sites": [
                    {
                        "URL": "https://example.com",
                        "capabilities": {
                            "update_plugins": True,
                            "manage_options": True,
                        },
                    }
                ]
            },
            [{"plugin": "sample/sample"}],
            {"id": "sample/sample", "version": "1.1"},
        ]
    )

    result = client.upgrade_plugin("sample/sample")

    assert result.version == "1.1"
    assert client._make_wpcom_request.call_args_list == [
        call("GET", "/me/sites"),
        call("GET", "/sites/example.com/plugins", retry_on_forbidden=True),
        call("POST", "/sites/example.com/plugins/sample%2Fsample/update/"),
    ]


def test_upgrade_plugin_fails_before_wpcom_request_when_jetpack_user_cannot_manage_plugins_locally():
    client = WordPressClient.__new__(WordPressClient)
    client.config = type("Config", (), {"wpcom_site": "example.com"})()
    client.get_plugin = MagicMock(
        return_value=create_plugin(
            {
                "plugin": "sample/sample",
                "name": "Sample",
                "status": "active",
                "version": "1.0",
                "update_status": "available",
                "latest_version": "1.1",
                "update_version": "1.1",
                "latest_version_source": "wordpress.org",
            }
        )
    )
    client._get_jetpack_connection_data = MagicMock(
        return_value={
            "currentUser": {
                "isConnected": True,
                "permissions": {
                    "manage_plugins": False,
                },
            }
        }
    )
    client._make_wpcom_request = MagicMock()

    with pytest.raises(ClientError, match=JETPACK_PLUGIN_MANAGEMENT_ERROR):
        client.upgrade_plugin("sample/sample")

    client._make_wpcom_request.assert_not_called()


def test_upgrade_plugin_fails_before_update_request_when_wpcom_site_has_no_management_capability():
    client = WordPressClient.__new__(WordPressClient)
    client.config = type(
        "Config",
        (),
        {
            "wpcom_site": "example.com",
            "wpcom_access_token": "token",
        },
    )()
    client.get_plugin = MagicMock(
        return_value=create_plugin(
            {
                "plugin": "sample/sample",
                "name": "Sample",
                "status": "active",
                "version": "1.0",
                "update_status": "available",
                "latest_version": "1.1",
                "update_version": "1.1",
                "latest_version_source": "wordpress.org",
            }
        )
    )
    client._get_jetpack_connection_data = MagicMock(
        return_value={
            "currentUser": {
                "isConnected": True,
                "permissions": {
                    "manage_plugins": True,
                },
            }
        }
    )
    client._make_wpcom_request = MagicMock(
        return_value={
            "sites": [
                {
                    "URL": "https://example.com",
                    "capabilities": {
                        "update_plugins": False,
                        "manage_options": False,
                    },
                }
            ]
        }
    )

    with pytest.raises(ClientError, match=JETPACK_PLUGIN_MANAGEMENT_ERROR):
        client.upgrade_plugin("sample/sample")

    client._make_wpcom_request.assert_called_once_with("GET", "/me/sites")
