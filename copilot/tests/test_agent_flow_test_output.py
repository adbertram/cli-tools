import json

from typer.testing import CliRunner

from copilot_cli.commands import agent_flow


def test_agent_flow_test_result_output_is_json_only(capsys):
    result = {
        "run_id": "08584251617487991053779448410CU05",
        "status": "Succeeded",
        "duration": "4.86s",
        "body": {
            "success": True,
            "response": "Hello! How can I assist you today?",
        },
    }

    agent_flow._print_flow_test_result(result)

    captured = capsys.readouterr()
    assert json.loads(captured.out) == result
    assert captured.err == ""
    assert captured.out.strip().startswith("{")
    assert "=== Run Result ===" not in captured.out
    assert "Invoking flow" not in captured.out


def test_agent_flow_test_manual_wait_command_returns_only_json(monkeypatch):
    run_result = {
        "run_id": "run-123",
        "status": "Succeeded",
        "duration": "1.25s",
        "body": {
            "success": True,
            "response": "Hello! How can I assist you today?",
        },
    }

    class FakeClient:
        def get_flow_callback_url(self, workflow_id):
            assert workflow_id == "flow-123"
            return {"response": {"value": "https://example.invalid/callback"}}

        def invoke_flow_manual(self, callback_url, body_data):
            assert callback_url == "https://example.invalid/callback"
            assert body_data == {"prompt": "hi"}
            return {"accepted": True}

        def list_flow_runs(self, workflow_id, top):
            assert workflow_id == "flow-123"
            assert top == 1
            return [{"name": "run-123"}]

    monkeypatch.setattr(agent_flow, "get_client", lambda: FakeClient())
    monkeypatch.setattr(agent_flow.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        agent_flow,
        "_wait_for_run",
        lambda client, workflow_id, run_id, timeout: run_result,
    )

    runner = CliRunner()
    result = runner.invoke(
        agent_flow.app,
        [
            "test",
            "flow-123",
            "--trigger",
            "manual",
            "--body",
            '{"prompt": "hi"}',
            "--wait",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == run_result
    assert result.stderr == ""
    assert "Getting callback URL" not in result.output
    assert "Invoking flow" not in result.output
    assert "=== Run Result ===" not in result.output


def test_agent_flow_test_history_returns_json_even_with_table_flag(monkeypatch):
    histories = [
        {
            "id": "history-123",
            "status": "Succeeded",
        }
    ]

    class FakeClient:
        def get_flow_trigger_histories(self, workflow_id):
            assert workflow_id == "flow-123"
            return histories

    monkeypatch.setattr(agent_flow, "get_client", lambda: FakeClient())
    monkeypatch.setattr(agent_flow, "format_trigger_history_for_display", lambda history: history)

    runner = CliRunner()
    result = runner.invoke(
        agent_flow.app,
        [
            "test",
            "flow-123",
            "--history",
            "--table",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == histories
    assert result.stderr == ""
