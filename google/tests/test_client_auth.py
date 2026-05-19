import pytest
from google.oauth2.credentials import Credentials

from google_cli.client import ClientError, GoogleClient, SCOPES


class ConfigWithToken:
    def __init__(self, token_path):
        self.token_path = str(token_path)
        self.credentials_path = str(token_path)

    def get_missing_credentials(self):
        return []


def test_client_rejects_stored_token_missing_required_scopes(tmp_path):
    token_path = tmp_path / "token.json"
    creds = Credentials(
        token="access-token",
        refresh_token="refresh-token",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="client-id",
        client_secret="client-secret",
        scopes=SCOPES[:-1],
    )
    token_path.write_text(creds.to_json())

    with pytest.raises(ClientError, match="missing required OAuth scopes"):
        GoogleClient(ConfigWithToken(token_path))
