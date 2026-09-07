"""Run the real remote source-note command against disposable local databases."""
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from legoscout_cli.deploy import config, source_notes, ssh
from legoscout_cli.ledger import db
from legoscout_cli.main import app
from legoscout_cli.sources import registry


@pytest.fixture
def remote_registry(tmp_path, monkeypatch):
    server = str(tmp_path / "server.db")
    baseline = str(tmp_path / "baseline.db")
    db.init(server).close()
    conn = registry._connect(server)
    with conn:
        conn.execute("INSERT INTO sources (namespace, payload) VALUES (?, ?)",
                     ("ebay", json.dumps({"name": "eBay", "aliases": []})))
    conn.close()
    db.snapshot(server, baseline, baseline=True)
    monkeypatch.setenv("LEGOSCOUT_DB_PATH", baseline)
    monkeypatch.setattr(config, "REMOTE_SHARED_DB", server)
    monkeypatch.setattr(config, "REMOTE_TOOL_PYTHON", sys.executable)
    calls = []

    def local_remote(argv, input=None):
        assert argv[:2] == ["ssh", config.REMOTE_HOST]
        command = shlex.split(argv[2])
        assert command[:2] == ["env", "LEGOSCOUT_DB_PATH=" + server]
        calls.append({"argv": argv, "input": input})
        result = subprocess.run(command, input=input, text=True, capture_output=True,
                                env=os.environ.copy())
        if result.returncode:
            raise ssh.DeployError(result.stderr)
        return result.stdout

    monkeypatch.setattr(ssh, "run_local", local_remote)
    return server, baseline, calls


def test_run_note_persists_only_on_server_with_literal_content(remote_registry):
    server, baseline, calls = remote_registry
    baseline_bytes = Path(baseline).read_bytes()
    before = db.query("SELECT * FROM source_notes", path=baseline)
    text = "Quoted 'note' with $() and `literal`\nsecond line"
    result = CliRunner().invoke(app, ["deploy", "source-note", "ebay|123",
                                    "--text", text, "--date", "2026-09-07"])
    assert result.exit_code == 0, result.output
    note = json.loads(result.stdout)
    assert note == {"id": "ebay-2026-09-07-1", "date": "2026-09-07",
                    "text": text, "supersedes": None}
    assert db.query("SELECT text FROM source_notes", path=server) == [{"text": text}]
    assert db.query("SELECT * FROM source_notes", path=baseline) == before == []
    assert len(calls) == 1
    assert text not in calls[0]["argv"][2]
    assert json.loads(calls[0]["input"])["text"] == text
    second = source_notes.add("eBay", "second note", "2026-09-07")
    assert second["id"] == "ebay-2026-09-07-2"
    assert db.query("SELECT text FROM source_notes ORDER BY rowid", path=server) == [
        {"text": text}, {"text": "second note"}]
    assert Path(baseline).read_bytes() == baseline_bytes


def test_unknown_source_fails_without_writing_or_retrying(remote_registry):
    server, baseline, calls = remote_registry
    with pytest.raises(ssh.DeployError, match="not a registered source"):
        source_notes.add("unregistered-source", "note", "2026-09-07")
    assert len(calls) == 1
    assert db.query("SELECT * FROM source_notes", path=server) == []
    assert db.query("SELECT * FROM source_notes", path=baseline) == []


def test_missing_server_database_is_not_created(remote_registry, monkeypatch, tmp_path):
    _, baseline, _ = remote_registry
    missing = tmp_path / "missing.db"
    monkeypatch.setattr(config, "REMOTE_SHARED_DB", str(missing))
    # Execute the same generated command while retaining the selected baseline.
    def local_remote(argv, input=None):
        result = subprocess.run(shlex.split(argv[2]), input=input, text=True,
                                capture_output=True, env=os.environ.copy())
        if result.returncode:
            raise ssh.DeployError(result.stderr)
        return result.stdout
    monkeypatch.setattr(ssh, "run_local", local_remote)
    with pytest.raises(ssh.DeployError, match="Ledger database missing"):
        source_notes.add("ebay", "note", "2026-09-07")
    assert not missing.exists()
    assert db.query("SELECT * FROM source_notes", path=baseline) == []


def test_invalid_receipt_fails_without_retry(monkeypatch):
    calls = []
    def remote(argv, input=None):
        calls.append(argv)
        return json.dumps({"id": "ebay-1", "date": "2026-09-07",
                           "text": "wrong note", "supersedes": None})
    monkeypatch.setattr(ssh, "run_local", remote)
    with pytest.raises(ValueError, match="invalid source-note receipt"):
        source_notes.add("ebay", "note", "2026-09-07")
    assert len(calls) == 1
