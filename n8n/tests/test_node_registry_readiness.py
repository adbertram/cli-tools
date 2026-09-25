import requests

from n8n_cli.n8n_api import N8nApiClient


class _Response:
    def __init__(self, status_code: int):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


def test_wait_for_node_registry_does_not_accept_rest_only_readiness(monkeypatch):
    client = N8nApiClient(base_url="http://example.test/api/v1", api_key="test-key")
    client._get_session_cookie = lambda: "n8n-auth=test"
    statuses = iter([404, 200])
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return _Response(next(statuses))

    monkeypatch.setattr(requests, "get", fake_get)

    assert client.wait_for_node_registry(timeout=1, poll_interval=0) is True
    assert [url for url, _ in calls] == [
        "http://example.test/types/nodes.json",
        "http://example.test/types/nodes.json",
    ]
    assert all(call[1]["headers"] == {"cookie": "n8n-auth=test"} for call in calls)
