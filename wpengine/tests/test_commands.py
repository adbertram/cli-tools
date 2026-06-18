from __future__ import annotations

import json
from types import SimpleNamespace

from typer.testing import CliRunner

from wpengine_cli.commands import accounts, api, cache, sftp, ssh


runner = CliRunner()


class FakeClient:
    def __init__(self):
        self.calls = []

    def list_accounts(self, *, limit, filters=None):
        self.calls.append(("list_accounts", limit, filters))
        return [
            {"id": "acc-1", "name": "ATA", "extra": "kept"},
            {"id": "acc-2", "name": "Second", "extra": "kept"},
        ][:limit]

    def get_account(self, account_id):
        self.calls.append(("get_account", account_id))
        return {"id": account_id, "name": "ATA", "extra": {"kept": True}}

    def purge_cache(self, environment_id, cache_type):
        self.calls.append(("purge_cache", environment_id, cache_type))
        return {"accepted": True, "environment_id": environment_id, "type": cache_type}

    def list_ssh_keys(self, *, limit, filters=None):
        self.calls.append(("list_ssh_keys", limit, filters))
        return [{"id": "key-1", "fingerprint": "fp", "comment": "laptop"}]

    def get_ssh_key(self, ssh_key_id):
        self.calls.append(("get_ssh_key", ssh_key_id))
        return {"id": ssh_key_id, "fingerprint": "fp", "comment": "laptop"}

    def add_ssh_key(self, public_key):
        self.calls.append(("add_ssh_key", public_key))
        return {"id": "key-2", "public_key": public_key}

    def delete_ssh_key(self, ssh_key_id):
        self.calls.append(("delete_ssh_key", ssh_key_id))
        return {"deleted": True, "ssh_key_id": ssh_key_id}


def parse_json(output: str):
    return json.loads(output)


def test_api_status_outputs_public_status_without_auth(monkeypatch):
    class FakeStatusClient:
        def __init__(self, require_auth):
            self.require_auth = require_auth

        def get_api_status(self):
            return {"status": "ok", "message": "healthy"}

    monkeypatch.setattr(api, "WpengineClient", FakeStatusClient)

    result = runner.invoke(api.app, [])

    assert result.exit_code == 0
    assert parse_json(result.output) == {"status": "ok", "message": "healthy"}


def test_accounts_list_preserves_full_json_by_default(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(accounts, "get_client", lambda: fake)

    result = runner.invoke(accounts.app, ["list", "--limit", "1"])

    assert result.exit_code == 0
    assert parse_json(result.output) == [{"id": "acc-1", "name": "ATA", "extra": "kept"}]
    assert fake.calls == [("list_accounts", 1, None)]


def test_accounts_get_projects_only_requested_properties(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(accounts, "get_client", lambda: fake)

    result = runner.invoke(accounts.app, ["get", "acc-1", "--properties", "id,name"])

    assert result.exit_code == 0
    assert parse_json(result.output) == {"id": "acc-1", "name": "ATA"}


def test_cache_purge_validates_type_and_calls_client(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(cache, "get_client", lambda: fake)

    result = runner.invoke(cache.app, ["purge", "env-1", "--type", "cdn"])

    assert result.exit_code == 0
    assert parse_json(result.output) == {"accepted": True, "environment_id": "env-1", "type": "cdn"}
    assert fake.calls == [("purge_cache", "env-1", "cdn")]


def test_cache_purge_rejects_unknown_type(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(cache, "get_client", lambda: fake)

    result = runner.invoke(cache.app, ["purge", "env-1", "--type", "database"])

    assert result.exit_code == 1
    assert "--type must be one of: object, page, cdn, all" in result.output
    assert fake.calls == []


def test_cache_clear_removes_response_cache_files(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "one.json").write_text("abc")
    (cache_dir / "two.json").write_text("defg")
    (cache_dir / "nested").mkdir()

    monkeypatch.setattr(cache, "get_config", lambda: SimpleNamespace(storage_dir=tmp_path))

    result = runner.invoke(cache.app, ["clear"])

    assert result.exit_code == 0
    assert parse_json(result.output) == {"files_removed": 2, "bytes_freed": 7}
    assert not (cache_dir / "one.json").exists()
    assert not (cache_dir / "two.json").exists()
    assert (cache_dir / "nested").exists()


def test_cache_clear_reports_zero_when_cache_dir_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "get_config", lambda: SimpleNamespace(storage_dir=tmp_path))

    result = runner.invoke(cache.app, ["clear"])

    assert result.exit_code == 0
    assert parse_json(result.output) == {"files_removed": 0, "bytes_freed": 0}


def test_ssh_connection_get_outputs_documented_fields():
    result = runner.invoke(ssh.app, ["connection", "get", "ataprod"])

    assert result.exit_code == 0
    output = parse_json(result.output)
    assert output["host"] == "ataprod.ssh.wpengine.net"
    assert output["remote_host"] == "ataprod.ssh.wpengine.net"
    assert output["user"] == "ataprod"
    assert output["remote_root"] == "/sites/ataprod"
    assert output["command"] == "ssh ataprod@ataprod.ssh.wpengine.net"


def test_ssh_connection_list_outputs_template_row():
    result = runner.invoke(ssh.app, ["connection", "list", "--limit", "1"])

    assert result.exit_code == 0
    output = parse_json(result.output)
    assert output == [
        {
            "id": "ENVIRONMENT_NAME",
            "name": "ENVIRONMENT_NAME",
            "environment_name": "ENVIRONMENT_NAME",
            "host": "ENVIRONMENT_NAME.ssh.wpengine.net",
            "remote_host": "ENVIRONMENT_NAME.ssh.wpengine.net",
            "user": "ENVIRONMENT_NAME",
            "port": 22,
            "remote_root": "/sites/ENVIRONMENT_NAME",
            "command": "ssh ENVIRONMENT_NAME@ENVIRONMENT_NAME.ssh.wpengine.net",
        }
    ]


def test_ssh_config_get_outputs_config_text():
    result = runner.invoke(ssh.app, ["config", "get", "ataprod", "--properties", "alias,config"])

    assert result.exit_code == 0
    output = parse_json(result.output)
    assert output["alias"] == "ataprod-wpengine"
    assert "HostName ataprod.ssh.wpengine.net" in output["config"]
    assert "User ataprod" in output["config"]


def test_ssh_config_list_outputs_template_row():
    result = runner.invoke(ssh.app, ["config", "list", "--properties", "id,alias"])

    assert result.exit_code == 0
    output = parse_json(result.output)
    assert output == [{"id": "ENVIRONMENT_NAME", "alias": "ENVIRONMENT_NAME-wpengine"}]


def test_ssh_keys_get_calls_client(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(ssh, "get_client", lambda: fake)

    result = runner.invoke(ssh.app, ["keys", "get", "key-1"])

    assert result.exit_code == 0
    assert parse_json(result.output) == {"id": "key-1", "fingerprint": "fp", "comment": "laptop"}
    assert fake.calls == [("get_ssh_key", "key-1")]


def test_ssh_keys_delete_requires_yes_for_non_interactive(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(ssh, "get_client", lambda: fake)

    result = runner.invoke(ssh.app, ["keys", "delete", "key-1"])

    assert result.exit_code == 1
    assert "Refusing to delete WP Engine SSH key key-1 without confirmation" in result.output
    assert fake.calls == []


def test_ssh_keys_delete_with_yes_calls_client(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(ssh, "get_client", lambda: fake)

    result = runner.invoke(ssh.app, ["keys", "delete", "key-1", "--yes"])

    assert result.exit_code == 0
    assert parse_json(result.output) == {"deleted": True, "ssh_key_id": "key-1"}
    assert fake.calls == [("delete_ssh_key", "key-1")]


def test_sftp_connection_get_derives_documented_user_string():
    result = runner.invoke(sftp.app, ["connection", "get", "ataprod", "--username", "adam"])

    assert result.exit_code == 0
    output = parse_json(result.output)
    assert output["host"] == "ataprod.sftp.wpengine.com"
    assert output["remote_host"] == "ataprod.sftp.wpengine.com"
    assert output["port"] == 2222
    assert output["user"] == "ataprod-adam"
    assert output["username_pattern"] == "ataprod-<username>"
    assert output["command"] == "sftp -P 2222 ataprod-adam@ataprod.sftp.wpengine.com"


def test_sftp_connection_list_outputs_template_row():
    result = runner.invoke(sftp.app, ["connection", "list", "--properties", "id,host,port"])

    assert result.exit_code == 0
    output = parse_json(result.output)
    assert output == [
        {
            "id": "ENVIRONMENT_NAME",
            "host": "ENVIRONMENT_NAME.sftp.wpengine.com",
            "port": 2222,
        }
    ]
