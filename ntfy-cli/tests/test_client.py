from pathlib import Path

import pytest

from ntfy_cli_cli.client import ClientError, NtfyClient


class FakeConfig:
    def __init__(self, path: Path):
        self.path = str(path)

    def get_cli_executable(self):
        return self.path


def test_poll_parses_ndjson(monkeypatch, tmp_path):
    executable = tmp_path / "ntfy"
    executable.write_text('#!/bin/sh\nprintf \'{"id":"one"}\\n{"id":"two"}\\n\'\n')
    executable.chmod(0o755)
    client = NtfyClient.__new__(NtfyClient)
    client.config = FakeConfig(executable)
    assert client.poll(("topic",)) == [{"id": "one"}, {"id": "two"}]


def test_poll_rejects_bad_ndjson(tmp_path):
    executable = tmp_path / "ntfy"
    executable.write_text("#!/bin/sh\nprintf 'broken\\n'\n")
    executable.chmod(0o755)
    client = NtfyClient.__new__(NtfyClient)
    client.config = FakeConfig(executable)
    with pytest.raises(ClientError, match="malformed"):
        client.poll(("topic",))
