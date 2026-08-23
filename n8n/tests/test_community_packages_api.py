from n8n_cli.n8n_api import N8nApiClient


def test_list_community_packages_uses_public_api_endpoint():
    client = N8nApiClient(base_url="http://example.test/api/v1", api_key="test-key")
    recorded = {}

    def fake_request(method, endpoint, **kwargs):
        recorded["method"] = method
        recorded["endpoint"] = endpoint
        recorded["kwargs"] = kwargs
        return {"data": [{"name": "n8n-nodes-cody"}]}

    def fail_rest_request(*args, **kwargs):
        raise AssertionError("community package list should not use the internal /rest API")

    client._request = fake_request
    client._rest_request = fail_rest_request

    assert client.list_community_packages() == [{"name": "n8n-nodes-cody"}]
    assert recorded == {
        "method": "GET",
        "endpoint": "/community-packages",
        "kwargs": {},
    }


def test_install_community_package_uses_public_api_endpoint():
    client = N8nApiClient(base_url="http://example.test/api/v1", api_key="test-key")
    recorded = {}

    def fake_request(method, endpoint, **kwargs):
        recorded["method"] = method
        recorded["endpoint"] = endpoint
        recorded["kwargs"] = kwargs
        return {"data": {"packageName": "n8n-nodes-cody"}}

    def fail_rest_request(*args, **kwargs):
        raise AssertionError("community package install should not use the internal /rest API")

    client._request = fake_request
    client._rest_request = fail_rest_request

    result = client.install_community_package(
        "n8n-nodes-cody",
        version="1.2.3",
        verify=True,
    )

    assert result == {"packageName": "n8n-nodes-cody"}
    assert recorded == {
        "method": "POST",
        "endpoint": "/community-packages",
        "kwargs": {
            "json": {
                "name": "n8n-nodes-cody",
                "version": "1.2.3",
                "verify": True,
            },
            "timeout": 300,
        },
    }


def test_uninstall_community_package_uses_public_api_endpoint_and_encodes_scoped_name():
    client = N8nApiClient(base_url="http://example.test/api/v1", api_key="test-key")
    recorded = {}

    def fake_request(method, endpoint, **kwargs):
        recorded["method"] = method
        recorded["endpoint"] = endpoint
        recorded["kwargs"] = kwargs
        return None

    def fail_rest_request(*args, **kwargs):
        raise AssertionError("community package uninstall should not use the internal /rest API")

    client._request = fake_request
    client._rest_request = fail_rest_request

    client.uninstall_community_package("@scope/n8n-nodes-example")

    assert recorded == {
        "method": "DELETE",
        "endpoint": "/community-packages/%40scope%2Fn8n-nodes-example",
        "kwargs": {"timeout": 300},
    }
