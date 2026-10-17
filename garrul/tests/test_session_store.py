"""The stored session cookie: what the CLI keeps, and when it stops trusting it.

`garrul auth login` mints the session in the shared Chromium profile, which any
other browser-backed CLI can empty. These tests pin the replacement behaviour:
the cookie the Worker issued is kept in the tool's own profile directory, admin
requests use it without touching a browser, and a store written for one
instance is never sent to another.
"""

import json
import stat

import pytest
from cli_tools_shared.exceptions import ClientError, CredentialError
from cli_tools_shared.http_session import BrowserAuthState, BrowserCookie

from garrul_cli import client as client_module
from garrul_cli import session_store
from garrul_cli.client import GarrulClient

INSTANCE = "https://comments.example.test"
SID = "a" * 64


class FakeConfig:
    def __init__(self, base_dir, instance=INSTANCE):
        self._base_dir = base_dir
        self.instance_origin = instance
        self.embed_origin = "https://blog.example.test"

    def get_profile_data_dir(self):
        return self._base_dir


@pytest.fixture
def config(tmp_path):
    return FakeConfig(tmp_path)


def test_store_and_load_round_trip(config):
    path = session_store.save(config, [{"name": "__Host-garrul_sess", "value": SID, "domain": "comments.example.test"}])

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert session_store.load(config) == [
        {
            "name": "__Host-garrul_sess",
            "value": SID,
            "domain": "comments.example.test",
            "path": "/",
            "expires": -1,
        }
    ]


def test_store_refuses_an_empty_cookie_set(config):
    with pytest.raises(ClientError, match="empty session cookie"):
        session_store.save(config, [])


def test_load_ignores_a_store_written_for_another_instance(config, tmp_path):
    session_store.save(config, [{"name": "__Host-garrul_sess", "value": SID, "domain": "comments.example.test"}])

    other = FakeConfig(tmp_path, instance="https://comments.other.test")

    assert session_store.load(other) is None


def test_load_drops_a_corrupt_store(config):
    path = session_store.store_path(config)
    path.write_text("{not json", encoding="utf-8")

    assert session_store.load(config) is None
    assert not path.exists()


def test_clear_removes_the_store(config):
    session_store.save(config, [{"name": "__Host-garrul_sess", "value": SID, "domain": "comments.example.test"}])

    session_store.clear(config)

    assert session_store.load(config) is None


def test_admin_requests_use_the_stored_cookie_without_a_browser(config, monkeypatch):
    session_store.save(config, [{"name": "__Host-garrul_sess", "value": SID, "domain": "comments.example.test"}])

    def explode(_config):
        raise AssertionError("the browser profile must not be read when a stored cookie exists")

    monkeypatch.setattr(client_module.BrowserAuthState, "from_config", staticmethod(explode))

    assert GarrulClient(config=config)._session_cookie() == f"__Host-garrul_sess={SID}"


def test_admin_requests_fall_back_to_the_browser_cookie(config, monkeypatch):
    state = BrowserAuthState(
        cookies=(BrowserCookie(name="__Host-garrul_sess", value=SID, domain="comments.example.test", path="/", expires=0),)
    )
    monkeypatch.setattr(client_module.BrowserAuthState, "from_config", staticmethod(lambda _config: state))

    assert GarrulClient(config=config)._session_cookie() == f"__Host-garrul_sess={SID}"


def test_missing_cookie_everywhere_names_the_login_command(config, monkeypatch):
    monkeypatch.setattr(
        client_module.BrowserAuthState,
        "from_config",
        staticmethod(lambda _config: BrowserAuthState(cookies=())),
    )

    with pytest.raises(CredentialError, match="garrul auth login"):
        GarrulClient(config=config)._session_cookie()


def test_stored_cookie_excludes_foreign_names(config):
    session_store.save(
        config,
        [
            {"name": "some_other_cookie", "value": "x", "domain": "comments.example.test"},
            {"name": "__Host-garrul_sess", "value": SID, "domain": "comments.example.test"},
        ],
    )

    assert GarrulClient(config=config)._session_cookie() == f"__Host-garrul_sess={SID}"


def test_saved_file_is_readable_json(config):
    path = session_store.save(config, [{"name": "__Host-garrul_sess", "value": SID, "domain": "comments.example.test"}])

    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["instance"] == INSTANCE
    assert payload["cookies"][0]["name"] == "__Host-garrul_sess"
