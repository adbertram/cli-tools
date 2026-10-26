"""Exercise the CLI boundary and credential isolation, not remote mutations."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from typer.testing import CliRunner
from gumroad_cli import main, client

runner = CliRunner()


def test_all_worker_capabilities_exposed():
    worker_keys = {
        "listGumroadProducts", "inspectGumroadProduct", "planGumroadRelease",
        "createGumroadDraft", "updateGumroadBook", "publishGumroadBook",
        "inspectGumroadBuild", "buildGumroadBook", "smokeTestGumroadUpload",
        "createGumroadSmokeDraft", "updateGumroadSmokeDraft", "buildGumroadEpub",
        "planGumroadFormats", "updateGumroadFormats",
    }
    assert set(main.CONTRACTS) == worker_keys
    for key in worker_keys:
        result = runner.invoke(main.app, ["schema", "get", key])
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["schema"]["additionalProperties"] is False


@pytest.mark.parametrize("payload", [{}, [], {"bookPageUrl": "x", "mode": "guess"}, {"bookPageUrl": "x", "mode": "proof", "extra": True}])
def test_bad_input_never_reaches_network(monkeypatch, tmp_path, payload):
    monkeypatch.setattr(main, "run_operation", lambda *a: pytest.fail("API called"))
    path = tmp_path / "input.json"
    path.write_text(json.dumps(payload))
    result = runner.invoke(main.app, ["uploads", "smoke-test", "--input-file", str(path)])
    assert result.exit_code != 0


def test_list_filters_before_limit_and_json(monkeypatch):
    rows = [{"id": str(i), "name": name} for i, name in enumerate(["other", "match", "match"])]
    monkeypatch.setattr(main, "run_operation", lambda *a: {"products": rows})
    result = runner.invoke(main.app, ["products", "list", "-f", "name:eq:match", "-l", "1", "-p", "id"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [{"id": "1"}]


def test_product_does_not_read_notion_secret(monkeypatch):
    monkeypatch.setattr(client, "get_config", lambda profile: SimpleNamespace(personal_access_token="test-token"))
    monkeypatch.setattr(client, "read_cli_tool_secret", lambda *a: pytest.fail("Notion credential read"))
    def run(args, **kwargs):
        assert kwargs["env"]["GUMROAD_ACCESS_TOKEN"] == "test-token"
        assert "test-token" not in json.dumps(args) + kwargs["input"]
        return SimpleNamespace(returncode=0, stdout='{"products":[]}')
    monkeypatch.setattr(client.subprocess, "run", run)
    assert client.run_operation("listGumroadProducts", {}) == {"products": []}


def test_book_does_not_require_gumroad(monkeypatch):
    monkeypatch.setattr(client, "get_config", lambda *a: pytest.fail("Gumroad credential read"))
    monkeypatch.setattr(client, "read_cli_tool_secret", lambda name: "notion-test" if name == "notion-api-token" else None)
    monkeypatch.setattr(client.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout='{"ready":true}'))
    assert client.run_operation("inspectGumroadBuild", {"bookPageUrl": "x", "mode": "proof"}) == {"ready": True}


def test_ambiguous_process_failure_is_not_retried(monkeypatch):
    monkeypatch.setattr(client, "get_config", lambda profile: SimpleNamespace(personal_access_token="test-token"))
    monkeypatch.setattr(client, "read_cli_tool_secret", lambda *a: "notion-test")
    calls = []
    def fail(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=1, stdout="")
    monkeypatch.setattr(client.subprocess, "run", fail)
    with pytest.raises(Exception, match="do not automatically repeat writes"):
        client.run_operation("updateGumroadBook", {})
    assert len(calls) == 1


@pytest.mark.parametrize("data", [[], None, "not-an-object", {}, {"success": True, "products": {}}])
def test_auth_response_contract(monkeypatch, data):
    from gumroad_cli.config import Config
    import gumroad_cli.config as config_module
    monkeypatch.setattr(config_module.requests, "get", lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: data))
    config = SimpleNamespace(DEFAULT_BASE_URL=Config.DEFAULT_BASE_URL, personal_access_token="test")
    assert Config.test_connection(config)["api_test"].startswith("failed:")
