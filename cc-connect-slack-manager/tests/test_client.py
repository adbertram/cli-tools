import json
import subprocess
from pathlib import Path
from urllib.error import URLError

import pytest

from cc_connect_slack_manager_cli.client import CcConnectSlackManagerClient, ClientError
from cc_connect_slack_manager_cli.models import SlackUserStatus


def write_cody_config(home: Path, app_id: str = "A_TEST_APP", include_runtime_sections: bool = True) -> Path:
    config_path = home / ".codex" / "cody" / "configuration.json"
    config_path.parent.mkdir(parents=True)
    data = {
        "version": 1,
        "identity": {"name": "Cody", "email": "cody@example.com"},
        "paths": {
            "cc_connect_config": str(home / ".cc-connect" / "cody.config.toml"),
            "cc_connect_runner": str(home / ".cc-connect" / "run-cody.sh"),
            "cc_connect_data_dir": str(home / ".cc-connect" / "cody-data"),
            "cc_connect_logs_dir": str(home / ".cc-connect" / "logs"),
        },
        "secrets": {
            "keychain_path": str(home / ".codex" / "cody.keychain-db"),
            "slack_bot_token": {
                "service": "BOT_TOKEN_SERVICE",
                "account": "cody-keychain-account",
            },
            "slack_app_token": {
                "service": "APP_TOKEN_SERVICE",
                "account": "cody-keychain-account",
            },
            "email_password": {
                "service": "EMAIL_SERVICE",
                "account": "cody@example.com",
            },
        },
        "channels": {
            "slack": {
                "enabled": True,
                "session_key_prefix": "slack:",
                "app_id": app_id,
                "bot_user_id": "U_TEST_BOT",
                "default_user_id": "U_TEST_USER",
                "default_dm_channel_id": "D_TEST_DM",
                "bridge": {"label": "com.test.cody"},
            }
        },
    }
    if include_runtime_sections:
        data["sessions"] = {"readable_sources": []}
        data["channels"]["email"] = {
            "enabled": True,
            "session_key_prefix": "email:",
            "headers": {
                "channel": "X-Cody-Channel",
                "session_key": "X-Cody-Session-Key",
            },
        }
    config_path.write_text(json.dumps(data))
    return config_path


def test_client_rejects_config_missing_runtime_required_sections(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    write_cody_config(tmp_path, include_runtime_sections=False)

    with pytest.raises(ClientError, match="Cody configuration key 'sessions' must be an object"):
        CcConnectSlackManagerClient()


@pytest.mark.parametrize(
    ("path", "match"),
    [
        (("paths", "cc_connect_runner"), "cc_connect_runner"),
        (("secrets", "slack_bot_token", "service"), "service"),
        (("secrets", "slack_app_token", "account"), "account"),
        (("channels", "slack", "app_id"), "app_id"),
        (("channels", "slack", "bridge", "label"), "label"),
        (("channels", "email", "headers", "session_key"), "session_key"),
    ],
)
def test_client_rejects_required_runtime_config_fields(tmp_path, monkeypatch, path, match):
    monkeypatch.setenv("HOME", str(tmp_path))
    config_path = write_cody_config(tmp_path)
    data = json.loads(config_path.read_text())
    target = data
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]
    config_path.write_text(json.dumps(data))

    with pytest.raises(ClientError, match=match):
        CcConnectSlackManagerClient()


def test_config_status_reads_cody_runtime_config(client):
    status = client.config_status()

    assert status.app_id == "A_TEST_APP"
    assert status.bot_user_id == "U_TEST_BOT"
    assert status.dm_channel_id == "D_TEST_DM"
    assert status.adam_user_id == "U_TEST_USER"
    assert status.launch_agent_plist_path.endswith("com.test.cody.plist")


def test_token_status_reads_keychain_services_and_account(client, monkeypatch):
    calls = []

    def fake_run(args, check=True):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="token\n", stderr="")

    monkeypatch.setattr(client, "_run", fake_run)

    statuses = client.token_status()

    assert [item.service for item in statuses] == ["BOT_TOKEN_SERVICE", "APP_TOKEN_SERVICE"]
    assert [item.account for item in statuses] == ["cody-keychain-account", "cody-keychain-account"]
    assert calls == [
        [
            "security",
            "find-generic-password",
            "-a",
            "cody-keychain-account",
            "-s",
            "BOT_TOKEN_SERVICE",
            "-w",
            str(Path.home() / ".codex" / "cody.keychain-db"),
        ],
        [
            "security",
            "find-generic-password",
            "-a",
            "cody-keychain-account",
            "-s",
            "APP_TOKEN_SERVICE",
            "-w",
            str(Path.home() / ".codex" / "cody.keychain-db"),
        ],
    ]


def test_slack_verify_accepts_configured_bot_app(client, monkeypatch):
    monkeypatch.setattr(
        client,
        "_slack_user",
        lambda user_id: SlackUserStatus(
            id=user_id,
            name="cody",
            deleted=False,
            is_bot=True,
            is_app_user=True,
            api_app_id="A_TEST_APP",
            bot_id="B_TEST_BOT",
            image_512=None,
        ),
    )

    result = client.slack_verify()

    assert result.app_id == "A_TEST_APP"
    assert result.dm_channel_id == "D_TEST_DM"
    assert result.bot_user.id == "U_TEST_BOT"
    assert result.bot_user.api_app_id == "A_TEST_APP"
    assert result.bot_user.bot_id == "B_TEST_BOT"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    write_cody_config(tmp_path)
    return CcConnectSlackManagerClient()


def test_slack_verify_rejects_bot_from_wrong_app(client, monkeypatch):
    monkeypatch.setattr(
        client,
        "_slack_user",
        lambda user_id: SlackUserStatus(
            id=user_id,
            name="cody",
            deleted=False,
            is_bot=True,
            is_app_user=True,
            api_app_id="A_WRONG_APP",
            bot_id=None,
            image_512=None,
        ),
    )

    with pytest.raises(ClientError, match="belongs to Slack app A_WRONG_APP"):
        client.slack_verify()


def test_send_test_message_posts_to_configured_dm_channel(client, monkeypatch):
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps({"ok": True, "ts": "123.456"}).encode()

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr(client, "_keychain_token", lambda token_config: "xoxb-test")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = client.send_test_message("Bridge test")

    request, timeout = requests[0]
    assert timeout == 15
    assert request.full_url == "https://slack.com/api/chat.postMessage"
    assert request.data == b"channel=D_TEST_DM&text=Bridge+test"
    assert request.headers["Authorization"] == "Bearer xoxb-test"
    assert result.message == "Sent message to D_TEST_DM at 123.456"


def test_send_test_message_rejects_slack_api_failure(client, monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps({"ok": False, "error": "channel_not_found"}).encode()

    monkeypatch.setattr(client, "_keychain_token", lambda token_config: "xoxb-test")
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: Response())

    with pytest.raises(ClientError, match="channel_not_found"):
        client.send_test_message("Bridge test")
