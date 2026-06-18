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


class WpcomConfig:
    def __init__(self, *, wpcom_access_token="token", wpcom_site="example.com", missing=None):
        self.wpcom_access_token = wpcom_access_token
        self.wpcom_site = wpcom_site
        self.clear_count = 0
        self._missing = list(missing or [])

    def clear_wpcom_access_token(self):
        self.clear_count += 1
        self.wpcom_access_token = None

    def get_missing_wpcom_credentials(self):
        return list(self._missing)


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


def test_get_plugin_resolves_slug_from_installed_plugin_list():
    client = WordPressClient.__new__(WordPressClient)
    installed = create_plugin(
        {
            "plugin": "seo-by-rank-math/rank-math",
            "name": "Rank Math SEO",
            "status": "active",
            "version": "1.0.272",
            "textdomain": "seo-by-rank-math",
        }
    )
    client.list_plugins = MagicMock(return_value=[installed])
    client._make_request = MagicMock(
        return_value={
            "plugin": "seo-by-rank-math/rank-math",
            "name": "Rank Math SEO",
            "status": "active",
            "version": "1.0.272",
            "textdomain": "seo-by-rank-math",
        }
    )

    result = client.get_plugin("seo-by-rank-math")

    assert result.plugin == "seo-by-rank-math/rank-math"
    client._make_request.assert_called_once_with("GET", "/plugins/seo-by-rank-math/rank-math")


def test_resolve_plugin_identifier_accepts_exact_name_and_textdomain():
    client = WordPressClient.__new__(WordPressClient)
    installed = create_plugin(
        {
            "plugin": "seo-by-rank-math-pro/rank-math-pro",
            "name": "Rank Math SEO PRO",
            "status": "active",
            "version": "3.0.68",
            "textdomain": "rank-math-pro",
        }
    )
    client.list_plugins = MagicMock(return_value=[installed])

    assert client.resolve_plugin_identifier("Rank Math SEO PRO") == "seo-by-rank-math-pro/rank-math-pro"
    assert client.resolve_plugin_identifier("rank-math-pro") == "seo-by-rank-math-pro/rank-math-pro"


def test_resolve_plugin_identifier_fails_clearly_when_not_installed():
    client = WordPressClient.__new__(WordPressClient)
    client.list_plugins = MagicMock(return_value=[])

    with pytest.raises(ClientError, match="Plugin not found: missing"):
        client.resolve_plugin_identifier("missing")


def test_resolve_plugin_identifier_fails_clearly_when_ambiguous():
    client = WordPressClient.__new__(WordPressClient)
    client.list_plugins = MagicMock(
        return_value=[
            create_plugin({"plugin": "one/plugin", "name": "Sample", "status": "active", "version": "1.0"}),
            create_plugin({"plugin": "two/plugin", "name": "Sample", "status": "active", "version": "1.0"}),
        ]
    )

    with pytest.raises(ClientError, match="Plugin identifier is ambiguous: Sample"):
        client.resolve_plugin_identifier("Sample")


def test_upgrade_plugin_uses_native_update_without_delete_or_reinstall():
    client = WordPressClient.__new__(WordPressClient)
    client.config = WpcomConfig()

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
    client.config = WpcomConfig()
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
    client.config = WpcomConfig()

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
    client.config = WpcomConfig(wpcom_access_token=None)

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
    client.config = WpcomConfig(wpcom_access_token="stale-token")
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
    client.config = WpcomConfig(wpcom_access_token="stale-token")
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
    client.config = WpcomConfig(wpcom_access_token="stale-token")
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
    client.config = WpcomConfig(
        wpcom_access_token=None,
        missing=["WPCOM_CLIENT_ID"],
    )

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


def test_upgrade_plugin_requires_wpcom_credentials_before_plugin_lookup():
    client = WordPressClient.__new__(WordPressClient)
    client.config = WpcomConfig(
        wpcom_access_token=None,
        wpcom_site=None,
        missing=["WPCOM_CLIENT_ID", "WPCOM_SITE"],
    )
    client.get_plugin = MagicMock()
    client._assert_jetpack_plugin_management_connected = MagicMock()
    client._make_wpcom_request = MagicMock()

    with pytest.raises(ClientError, match="Missing WordPress.com credentials: WPCOM_CLIENT_ID, WPCOM_SITE"):
        client.upgrade_plugin("sample/sample")

    client.get_plugin.assert_not_called()
    client._assert_jetpack_plugin_management_connected.assert_not_called()
    client._make_wpcom_request.assert_not_called()


def test_upgrade_plugin_fails_before_wpcom_request_when_jetpack_user_is_not_connected():
    client = WordPressClient.__new__(WordPressClient)
    client.config = WpcomConfig()
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


def test_upgrade_plugin_proceeds_when_connected_user_can_manage_configured_site_plugins():
    client = WordPressClient.__new__(WordPressClient)
    client.config = WpcomConfig()
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
            [{"plugin": "sample/sample"}],
            {"id": "sample/sample", "version": "1.1"},
        ]
    )

    result = client.upgrade_plugin("sample/sample")

    assert result.version == "1.1"
    assert client._make_wpcom_request.call_args_list == [
        call("GET", "/sites/example.com/plugins", retry_on_forbidden=True),
        call("POST", "/sites/example.com/plugins/sample%2Fsample/update/"),
    ]


def test_upgrade_plugin_fails_before_wpcom_request_when_jetpack_user_cannot_manage_plugins_locally():
    client = WordPressClient.__new__(WordPressClient)
    client.config = WpcomConfig()
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


def test_upgrade_plugin_fails_before_update_request_when_wpcom_plugin_endpoint_is_denied():
    client = WordPressClient.__new__(WordPressClient)
    client.config = WpcomConfig()
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
        side_effect=ClientError(WPCOM_PLUGIN_AUTHORIZATION_ERROR)
    )

    with pytest.raises(ClientError, match=WPCOM_PLUGIN_AUTHORIZATION_ERROR):
        client.upgrade_plugin("sample/sample")

    client._make_wpcom_request.assert_called_once_with(
        "GET",
        "/sites/example.com/plugins",
        retry_on_forbidden=True,
    )


def test_vulnerability_affects_version_with_max_and_min_ranges():
    assert WordPressClient.vulnerability_affects_version(
        "1.2.0",
        {
            "operator": {
                "min_operator": "gte",
                "min_version": "1.0.0",
                "max_operator": "lt",
                "max_version": "1.3.0",
                "unfixed": "0",
            }
        },
    ) is True
    assert WordPressClient.vulnerability_affects_version(
        "1.3.0",
        {
            "operator": {
                "min_operator": "gte",
                "min_version": "1.0.0",
                "max_operator": "lt",
                "max_version": "1.3.0",
                "unfixed": "0",
            }
        },
    ) is False


def test_security_scan_returns_only_installed_version_affected_vulnerabilities():
    client = WordPressClient.__new__(WordPressClient)
    client.list_plugins = MagicMock(
        return_value=[
            create_plugin(
                {
                    "plugin": "sample/sample",
                    "name": "Sample",
                    "status": "active",
                    "version": "1.2.0",
                    "update_status": "current",
                    "latest_version": "1.2.0",
                }
            )
        ]
    )
    client.list_themes = MagicMock(return_value=[])
    client.get_site_settings = MagicMock(return_value={"title": "Example", "url": "https://example.com"})
    client.get_wpvulnerability_record = MagicMock(
        return_value={
            "error": 0,
            "message": None,
            "updated": 1700000000,
            "data": {
                "plugin": "sample",
                "vulnerability": [
                    {
                        "uuid": "affected",
                        "name": "Sample < 1.3.0",
                        "operator": {"max_operator": "lt", "max_version": "1.3.0", "unfixed": "0"},
                        "impact": {"cvss3": {"severity": "high", "score": "8.1"}},
                        "source": [{"id": "CVE-1"}],
                    },
                    {
                        "uuid": "fixed",
                        "name": "Sample < 1.1.0",
                        "operator": {"max_operator": "lt", "max_version": "1.1.0", "unfixed": "0"},
                        "impact": {"cvss3": {"severity": "medium", "score": "5.1"}},
                        "source": [{"id": "CVE-2"}],
                    },
                ],
            },
        }
    )

    result = client.security_scan()

    assert result["summary"]["affected_component_count"] == 1
    assert result["summary"]["affected_vulnerability_count"] == 1
    affected = result["affected_components"][0]
    assert affected["slug"] == "sample"
    assert affected["vulnerabilities"] == [
        {
            "uuid": "affected",
            "name": "Sample < 1.3.0",
            "severity": "high",
            "score": "8.1",
            "source_ids": ["CVE-1"],
        }
    ]


def test_health_report_summarizes_plugins_and_themes():
    client = WordPressClient.__new__(WordPressClient)
    client.list_plugins = MagicMock(
        return_value=[
            create_plugin(
                {
                    "plugin": "sample/sample",
                    "name": "Sample",
                    "status": "active",
                    "version": "1.0",
                    "update_status": "available",
                    "latest_version": "1.1",
                    "update_version": "1.1",
                }
            ),
            create_plugin(
                {
                    "plugin": "closed/closed",
                    "name": "Closed",
                    "status": "inactive",
                    "version": "2.0",
                    "update_status": "closed",
                }
            ),
        ]
    )
    client.list_themes = MagicMock(
        return_value=[
            {"theme": "active-theme", "name": "Active Theme", "version": "1.0", "status": "active"},
            {"theme": "old-theme", "name": "Old Theme", "version": "0.9", "status": "inactive"},
        ]
    )
    client.get_site_settings = MagicMock(
        return_value={
            "title": "Example",
            "url": "https://example.com",
            "description": "Example site",
            "timezone": "America/Chicago",
        }
    )

    result = client.health_report()

    assert result["plugins"]["count"] == 2
    assert result["plugins"]["active_count"] == 1
    assert result["plugins"]["inactive_count"] == 1
    assert result["plugins"]["updates_available_count"] == 1
    assert result["plugins"]["closed_count"] == 1
    assert result["themes"]["active"][0]["theme"] == "active-theme"
    assert result["wordpress"]["status"] == "unavailable"
