import json

from typer.testing import CliRunner

from claude_code_sessions_cli.commands import sessions as sessions_cmd


runner = CliRunner()


class FakeClient:
    def __init__(self):
        self.calls = []

    def search_sessions(self, **kwargs):
        self.calls.append(kwargs)
        return []


def test_sessions_search_defaults_to_all_projects(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(sessions_cmd, "get_client", lambda: fake)

    result = runner.invoke(sessions_cmd.app, ["search", "Multi-topic submissions plan", "--limit", "20"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == []
    assert fake.calls == [
        {
            "query": "Multi-topic submissions plan",
            "project": None,
            "limit": 20,
            "since": None,
        }
    ]
