"""One manus invocation builds its config once and reads the API key secret once.

The command registry builds the config with the resolved active profile name
for its credential check, then the API client asks ``get_config()`` with no
profile. ``cli_tools_shared.config.config_for`` keys both calls on the resolved
profile, so the secret manager runs once. The shared per-process secret memo is
disabled here so the count reflects real config builds.
"""

import json
import subprocess

import pytest
from typer.testing import CliRunner

import cli_tools_shared.config as shared_config
import manus_cli.client as client_module
import manus_cli.config as manus_config
from manus_cli.main import app

SECRET_NAME = "manus-api-key"


class _NonStoringMemo(dict):
    def __contains__(self, key):
        return False

    def __setitem__(self, key, value):
        pass


class _FakeResponse:
    status_code = 200
    ok = True
    headers = {}
    text = ""

    def json(self):
        return {"total_credits": 42}


@pytest.fixture
def secret_gets(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data-home"))
    env = shared_config.get_profiles_base_dir("manus") / "default" / ".env"
    env.parent.mkdir(parents=True)
    env.write_text(f"ACTIVE=true\nAPI_KEY=secret://{SECRET_NAME}\n")

    gets = []

    def counting_secret_manager(command, secret_name, *, secret_value=None):
        assert command == "get", f"unexpected secret-manager command: {command}"
        gets.append(secret_name)
        return subprocess.CompletedProcess([], 0, stdout="manus-test-key", stderr="")

    monkeypatch.setattr(shared_config, "_run_secret_manager", counting_secret_manager)
    monkeypatch.setattr(shared_config, "_resolved_secret_cache", _NonStoringMemo())
    monkeypatch.setattr(manus_config, "_configs", {})
    monkeypatch.setattr(client_module, "_client", None)
    monkeypatch.setattr(client_module.requests, "request", lambda *_, **__: _FakeResponse())
    return gets


@pytest.mark.parametrize("profile_args", [[], ["--profile", "default"]])
def test_available_credits_reads_the_secret_once(secret_gets, profile_args):
    result = CliRunner().invoke(app, ["usage", "available-credits", *profile_args])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["total_credits"] == 42
    assert secret_gets == [SECRET_NAME]
