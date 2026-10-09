"""One airtable invocation builds its config once and reads the PAT secret once.

The command registry builds the config with the resolved active profile name
for its credential check, then the API client asks ``get_config()`` with no
profile. Both calls must return the same instance, so the secret manager runs
once. The shared per-process secret memo is disabled here so the count reflects
real config builds rather than the memo hiding a second one.
"""

import json
import subprocess

import pytest
from typer.testing import CliRunner

import airtable_cli.client as client_module
import airtable_cli.config as airtable_config
import cli_tools_shared.config as shared_config
from airtable_cli.main import app

SECRET_NAME = "airtable-personal-access-token"


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
        return {"bases": [{"id": "appTEST", "name": "Test", "permissionLevel": "read"}]}


@pytest.fixture
def secret_gets(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data-home"))
    env = shared_config.get_profiles_base_dir("airtable") / "default" / ".env"
    env.parent.mkdir(parents=True)
    env.write_text(f"ACTIVE=true\nPERSONAL_ACCESS_TOKEN=secret://{SECRET_NAME}\n")

    gets = []

    def counting_secret_manager(command, secret_name, *, secret_value=None):
        assert command == "get", f"unexpected secret-manager command: {command}"
        gets.append(secret_name)
        return subprocess.CompletedProcess([], 0, stdout="patTEST", stderr="")

    monkeypatch.setattr(shared_config, "_run_secret_manager", counting_secret_manager)
    monkeypatch.setattr(shared_config, "_resolved_secret_cache", _NonStoringMemo())
    monkeypatch.setattr(airtable_config, "_configs", {})
    monkeypatch.setattr(client_module, "_client", None)
    monkeypatch.setattr(client_module.requests, "request", lambda **_: _FakeResponse())
    return gets


@pytest.mark.parametrize("profile_args", [[], ["--profile", "default"]])
def test_bases_list_reads_the_secret_once(secret_gets, profile_args):
    result = CliRunner().invoke(app, ["bases", "list", *profile_args])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)[0]["id"] == "appTEST"
    assert secret_gets == [SECRET_NAME]
