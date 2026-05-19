from wordpress_cli.client import WordPressClient
from wordpress_cli.commands.plugins import requires_update_status
from wordpress_cli.models import create_plugin


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
