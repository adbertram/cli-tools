import json
import subprocess
from dataclasses import dataclass

import pytest

from ntfy_cli_cli.client import ClientError, Result


@dataclass
class FakeReadinessConfig:
    available: bool = True

    def is_cli_available(self) -> bool:
        return self.available


class FakeClient:
    """Command-level fake that records every upstream boundary call."""

    def __init__(self) -> None:
        self.config = FakeReadinessConfig()
        self.calls: list[tuple] = []
        self.server_error: ClientError | None = None
        self.run_result: Result | None = None
        self.publish_result = {
            "id": "msg-1",
            "time": 1,
            "topic": "alerts",
            "message": "hello",
        }
        self.poll_result = [
            {"id": "msg-1", "time": 1, "topic": "alerts", "message": "first"},
            {"id": "msg-2", "time": 2, "topic": "alerts", "message": "second"},
        ]

    @property
    def executable(self) -> str:
        return "/fake/ntfy"

    def require_server(self) -> None:
        self.calls.append(("require_server",))
        if self.server_error is not None:
            raise self.server_error

    def run(self, args, *, stdin=None, timeout=60, check=True) -> Result:
        args = tuple(args)
        self.calls.append(("run", args, stdin, timeout, check))
        if self.run_result is not None:
            if check and self.run_result.returncode:
                raise ClientError(self.run_result.stderr.strip() or self.run_result.stdout.strip() or "ntfy command failed")
            return self.run_result

        if args == ("--version",):
            return Result("ntfy version 2.28.0\n", "", 0)

        if args[:2] == ("user", "list"):
            return Result("user role\nalice user\nroot admin\n", "", 0)
        elif args[:1] == ("access",):
            return Result("user topic access\nalice alerts rw\nroot * rw\n", "", 0)
        elif args[:2] == ("token", "list"):
            return Result("token user expires label\ntk_existing alice never phone\ntk_admin root never admin\n", "", 0)
        elif args[:2] == ("token", "add"):
            payload = {"username": args[-1], "token": "tk_created_once", "label": "phone"}
        elif args[:2] == ("token", "generate"):
            payload = {"token": "tk_generated_once"}
        else:
            payload = {"ok": True}
        return Result(json.dumps(payload) + "\n", "", 0)

    def publish(self, args, body):
        self.calls.append(("publish", tuple(args), body))
        return self.publish_result

    def poll(self, args):
        self.calls.append(("poll", tuple(args)))
        return list(self.poll_result)

    def passthrough(self, args):
        self.calls.append(("passthrough", tuple(args)))
        try:
            return subprocess.Popen([self.executable, *args]).wait()
        except OSError as exc:
            raise ClientError(f"Unable to run ntfy: {exc}") from exc


@pytest.fixture
def fake_client(monkeypatch):
    import ntfy_cli_cli.main as main
    import ntfy_cli_cli.commands.auth as auth
    import ntfy_cli_cli.commands.messages as messages

    client = FakeClient()
    monkeypatch.setattr(main, "get_client", lambda: client)
    monkeypatch.setattr(auth, "get_client", lambda: client)
    monkeypatch.setattr(messages, "get_client", lambda: client)
    return client
