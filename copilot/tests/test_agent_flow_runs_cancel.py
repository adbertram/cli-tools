"""Tests for `copilot agent-flow runs cancel` subcommand."""
import pytest
from typer.testing import CliRunner

from copilot_cli.commands import agent_flow


def test_runs_cancel_success_with_yes_flag(monkeypatch):
    """`runs cancel --yes` skips confirmation and calls cancel_flow_run on the client."""
    captured = {}

    class FakeClient:
        def cancel_flow_run(self, workflow_id, run_id):
            captured["workflow_id"] = workflow_id
            captured["run_id"] = run_id
            return {"status_code": 200}

    monkeypatch.setattr(agent_flow, "get_client", lambda: FakeClient())

    runner = CliRunner()
    result = runner.invoke(
        agent_flow.app,
        ["runs", "cancel", "flow-abc", "run-xyz", "--yes"],
    )

    assert result.exit_code == 0, result.output
    assert captured == {"workflow_id": "flow-abc", "run_id": "run-xyz"}


def test_runs_cancel_aborts_when_user_declines_confirmation(monkeypatch):
    """Without --yes, declining the prompt aborts without calling the client."""
    call_count = {"n": 0}

    class FakeClient:
        def cancel_flow_run(self, workflow_id, run_id):
            call_count["n"] += 1
            return {"status_code": 200}

    monkeypatch.setattr(agent_flow, "get_client", lambda: FakeClient())

    runner = CliRunner()
    result = runner.invoke(
        agent_flow.app,
        ["runs", "cancel", "flow-abc", "run-xyz"],
        input="n\n",
    )

    assert result.exit_code == 0
    assert call_count["n"] == 0
    assert "aborted" in result.stdout.lower()


def test_runs_cancel_propagates_client_errors(monkeypatch):
    """Cancel surfaces ClientError (e.g. 4xx for already-completed run) as non-zero exit."""

    class FakeClient:
        def cancel_flow_run(self, workflow_id, run_id):
            from copilot_cli.client import ClientError
            raise ClientError(
                "Failed to cancel flow run: HTTP 400: WorkflowRunCanNotBeCancelled"
            )

    monkeypatch.setattr(agent_flow, "get_client", lambda: FakeClient())

    runner = CliRunner()
    result = runner.invoke(
        agent_flow.app,
        ["runs", "cancel", "flow-abc", "run-xyz", "--yes"],
    )

    assert result.exit_code != 0
