from adobe_podcast_cli.client import AdobePodcastClient


class FakeConfig:
    access_token = "old-token"
    base_url = "https://example.test"

    def __init__(self):
        self.cleared = []

    def has_credentials(self):
        return True

    def _clear(self, name):
        self.cleared.append(name)
        if name == "ACCESS_TOKEN":
            self.access_token = None


class FakeResponse:
    headers = {}
    text = ""

    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body or {}

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._body


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.auth_headers = []
        self.responses = [
            FakeResponse(401, {"message": "Oauth token is not valid"}),
            FakeResponse(200, {"ok": True}),
        ]

    def request(self, method, url, **kwargs):
        self.auth_headers.append(self.headers.get("Authorization"))
        return self.responses.pop(0)


def test_request_refreshes_cached_access_token_once_after_401(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr("adobe_podcast_cli.client.requests.Session", lambda: session)

    config = FakeConfig()
    client = AdobePodcastClient(config=config)
    monkeypatch.setattr(client, "_extract_token_from_browser", lambda: "fresh-token")

    response = client._request("POST", "https://example.test/rails/active_storage/direct_uploads")

    assert response.status_code == 200
    assert config.cleared == ["ACCESS_TOKEN"]
    assert session.auth_headers == ["Bearer old-token", "Bearer fresh-token"]
