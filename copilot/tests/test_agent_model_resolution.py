import pytest

from copilot_cli.commands import agent as agent_commands


def test_resolve_stored_model_exact_pair():
    result = agent_commands._resolve_stored_model("ChatPreviewModels", "GPT5Chat")

    assert result["modelId"] == "gpt-5-chat"
    assert result["modelName"] == "GPT-5 Chat"
    assert result["resolution"] == "exact"
    assert result["isKnownPair"] is True
    assert result["issues"] == []


def test_resolve_stored_model_invalid_default_pair_resolves_to_current_default():
    result = agent_commands._resolve_stored_model("DefaultModels", "GPT5Chat")

    assert result["modelId"] == "gpt-4.1"
    assert result["modelName"] == "GPT-4.1"
    assert result["resolution"] == "default-category"
    assert result["isKnownPair"] is False
    assert "not a recognized model mapping" in result["issues"][0]


def test_parse_requested_model_accepts_model_id():
    result = agent_commands._parse_requested_model("gpt-5-chat")

    assert result == {
        "modelId": "gpt-5-chat",
        "modelName": "GPT-5 Chat",
        "kind": "ChatPreviewModels",
        "modelNameHint": "GPT5Chat",
    }


def test_parse_requested_model_rejects_invalid_raw_pair():
    with pytest.raises(ValueError, match="Unknown or invalid model pair"):
        agent_commands._parse_requested_model("DefaultModels:GPT5Chat")


def test_model_get_reports_resolved_model_for_invalid_default_pair(monkeypatch):
    class FakeClient:
        def get_bot(self, agent_id):
            return {
                "name": "Example Agent",
                "synchronizationstatus": {
                    "lastFinishedPublishOperation": {"status": "Failed"},
                    "lastPublishedOnUtc": "2026-03-19T15:11:26.2537588Z",
                    "currentSynchronizationState": {"state": "Synchronizing"},
                },
            }

        def get_bot_runtime_model(self, bot):
            return {
                "model_kind": "DefaultModels",
                "model_hint": "GPT5Chat",
                "opt_in_use_latest_models": False,
            }

        def get_custom_gpt_component(self, agent_id):
            return {
                "botcomponentid": "component-123",
                "name": "Custom GPT",
                "data": "unused",
            }

        def parse_gpt_component_yaml(self, yaml_data):
            return {
                "model_kind": "DefaultModels",
                "model_hint": "GPT5Chat",
            }

    captured = {}
    monkeypatch.setattr(agent_commands, "get_client", lambda: FakeClient())
    monkeypatch.setattr(agent_commands, "print_json", lambda payload: captured.setdefault("payload", payload))

    agent_commands.model_get("agent-123")

    result = captured["payload"]
    assert result["modelKind"] == "DefaultModels"
    assert result["modelNameHint"] == "GPT5Chat"
    assert result["resolvedModelId"] == "gpt-4.1"
    assert result["resolvedModelName"] == "GPT-4.1"
    assert result["resolvedBy"] == "default-category"
    assert result["runtimeResolution"] == "default-category"
    assert result["lastPublishOperationStatus"] == "Failed"
    assert any("live published model may not match" in issue for issue in result["issues"])


def test_model_set_writes_canonical_pair_for_model_id(monkeypatch):
    class FakeClient:
        def __init__(self):
            self.update_bot_model_calls = []
            self.patch_calls = []
            self.published = False

        def get_bot(self, agent_id):
            return {"name": "Example Agent"}

        def get_bot_runtime_model(self, bot):
            return {
                "model_kind": "DefaultModels",
                "model_hint": "GPT4.1",
                "opt_in_use_latest_models": False,
            }

        def update_bot_model(self, agent_id, model_kind, model_hint, opt_in_use_latest_models=False):
            self.update_bot_model_calls.append(
                (agent_id, model_kind, model_hint, opt_in_use_latest_models)
            )
            return True

        def get_custom_gpt_component(self, agent_id):
            return {
                "botcomponentid": "component-123",
                "data": "old-yaml",
            }

        def parse_gpt_component_yaml(self, yaml_data):
            return {
                "model_hint": "GPT4.1",
                "instructions": "Keep these instructions",
            }

        def build_gpt_component_yaml(self, instructions=None, model_kind=None, model_hint=None):
            return f"{instructions}|{model_kind}|{model_hint}"

        def patch(self, path, payload):
            self.patch_calls.append((path, payload))

        def publish_bot(self, agent_id):
            self.published = True

    fake_client = FakeClient()
    monkeypatch.setattr(agent_commands, "get_client", lambda: fake_client)
    monkeypatch.setattr(agent_commands, "print_success", lambda message: None)
    monkeypatch.setattr(agent_commands, "print_warning", lambda message: None)

    agent_commands.model_set("agent-123", "gpt-5-chat", publish=False)

    assert fake_client.update_bot_model_calls == [
        ("agent-123", "ChatPreviewModels", "GPT5Chat", False)
    ]
    assert fake_client.patch_calls == [
        ("botcomponents(component-123)", {"data": "Keep these instructions|ChatPreviewModels|GPT5Chat"})
    ]
    assert fake_client.published is False
