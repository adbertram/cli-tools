import json

from typer.testing import CliRunner

from claude_code_sessions_cli.commands import search as search_cmd


runner = CliRunner()


class FakeClient:
    def search_all(self, **kwargs):
        return []


def test_search_run_no_results_emits_json_array(monkeypatch):
    monkeypatch.setattr(search_cmd, "get_client", lambda: FakeClient())

    result = runner.invoke(search_cmd.app, ["missing query"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == []
