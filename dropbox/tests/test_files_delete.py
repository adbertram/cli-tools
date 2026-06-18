import signal

from typer.testing import CliRunner

from dropbox_cli.commands import files
from dropbox_cli.main import app


class FakeClient:
    def __init__(self, metadata=None, error=None):
        self.metadata = metadata or {"path_display": "/Temp"}
        self.error = error
        self.timeout = None
        self.deleted_path = None

    def set_timeout(self, timeout):
        self.timeout = timeout

    def delete(self, path):
        self.deleted_path = path
        if self.error:
            raise self.error
        return self.metadata


def test_files_rm_should_apply_wall_clock_timeout_and_restore_alarm(monkeypatch):
    client = FakeClient()
    alarms = []
    handlers = []

    def fake_signal(signum, handler):
        handlers.append((signum, handler))
        return signal.SIG_DFL

    monkeypatch.setattr(files, "get_client", lambda: client)
    monkeypatch.setattr(files.signal, "signal", fake_signal)
    monkeypatch.setattr(files.signal, "alarm", lambda seconds: alarms.append(seconds))

    result = CliRunner().invoke(app, ["files", "rm", "/Temp", "--force", "--timeout", "7"])

    assert result.exit_code == 0
    assert client.timeout == 7
    assert client.deleted_path == "/Temp"
    assert alarms == [7, 0]
    assert handlers[0][0] == signal.SIGALRM
    assert handlers[1] == (signal.SIGALRM, signal.SIG_DFL)


def test_files_rm_should_fail_clearly_when_delete_times_out(monkeypatch):
    client = FakeClient(error=TimeoutError("Delete timed out after 3 seconds: /Temp"))
    alarms = []

    monkeypatch.setattr(files, "get_client", lambda: client)
    monkeypatch.setattr(files.signal, "signal", lambda signum, handler: signal.SIG_DFL)
    monkeypatch.setattr(files.signal, "alarm", lambda seconds: alarms.append(seconds))

    result = CliRunner().invoke(app, ["files", "rm", "/Temp", "--force", "--timeout", "3"])

    assert result.exit_code == 1
    assert "Delete timed out after 3 seconds: /Temp" in result.stderr
    assert alarms == [3, 0]


def test_files_rm_should_reject_non_positive_timeout(monkeypatch):
    monkeypatch.setattr(files, "get_client", lambda: FakeClient())

    result = CliRunner().invoke(app, ["files", "rm", "/Temp", "--force", "--timeout", "0"])

    assert result.exit_code == 1
    assert "--timeout must be greater than 0" in result.stderr
