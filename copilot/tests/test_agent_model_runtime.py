import json

from copilot_cli.client import DataverseClient
from copilot_cli.commands import agent as agent_commands


def test_get_bot_runtime_model_reads_configuration():
    client = DataverseClient("https://example.crm.dynamics.com", "token")

    bot = {
        "configuration": json.dumps(
            {
                "aISettings": {
                    "$kind": "AISettings",
                    "optInUseLatestModels": True,
                    "model": {
                        "$kind": "CurrentModels",
                        "kind": "ReasoningPreviewModels",
                        "modelNameHint": "GPT5Reasoning",
                    },
                }
            }
        )
    }

    result = client.get_bot_runtime_model(bot)

    assert result == {
        "model_kind": "ReasoningPreviewModels",
        "model_hint": "GPT5Reasoning",
        "opt_in_use_latest_models": True,
    }


def test_update_bot_model_patches_runtime_configuration_and_disables_latest(monkeypatch):
    client = DataverseClient("https://example.crm.dynamics.com", "token")
    patch_calls = []

    monkeypatch.setattr(
        client,
        "get_bot",
        lambda bot_id: {
            "configuration": json.dumps(
                {
                    "aISettings": {
                        "$kind": "AISettings",
                        "optInUseLatestModels": True,
                        "model": {
                            "$kind": "CurrentModels",
                            "kind": "ReasoningPreviewModels",
                            "modelNameHint": "GPT5Reasoning",
                        },
                    }
                }
            )
        },
    )
    monkeypatch.setattr(client, "patch", lambda path, payload: patch_calls.append((path, payload)))

    changed = client.update_bot_model(
        "agent-123",
        model_kind="DefaultModels",
        model_hint="GPT5Chat",
        opt_in_use_latest_models=False,
    )

    assert changed is True
    assert len(patch_calls) == 1
    path, payload = patch_calls[0]
    assert path == "bots(agent-123)"

    configuration = json.loads(payload["configuration"])
    assert configuration["aISettings"]["optInUseLatestModels"] is False
    assert configuration["aISettings"]["model"] == {
        "$kind": "CurrentModels",
        "kind": "DefaultModels",
        "modelNameHint": "GPT5Chat",
    }


def test_model_get_prefers_runtime_model_and_reports_mismatch(monkeypatch):
    class FakeClient:
        def get_bot(self, agent_id):
            return {"name": "Example Agent"}

        def get_bot_runtime_model(self, bot):
            return {
                "model_kind": "ReasoningPreviewModels",
                "model_hint": "GPT5Reasoning",
                "opt_in_use_latest_models": True,
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
    assert result["modelKind"] == "ReasoningPreviewModels"
    assert result["modelNameHint"] == "GPT5Reasoning"
    assert result["runtimeModelKind"] == "ReasoningPreviewModels"
    assert result["componentModelKind"] == "DefaultModels"
    assert result["mismatch"] is True


def test_model_set_updates_runtime_config_and_component(monkeypatch):
    class FakeClient:
        def __init__(self):
            self.update_bot_model_calls = []
            self.patch_calls = []
            self.published = False

        def get_bot(self, agent_id):
            return {"name": "Example Agent"}

        def get_bot_runtime_model(self, bot):
            return {
                "model_kind": "ReasoningPreviewModels",
                "model_hint": "GPT5Reasoning",
                "opt_in_use_latest_models": True,
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
                "model_hint": "GPT5Reasoning",
                "instructions": "Keep these instructions",
                "response_instructions": "Keep this response shape",
                "web_browsing": True,
            }

        def build_gpt_component_yaml(
            self,
            instructions=None,
            response_instructions=None,
            model_kind=None,
            model_hint=None,
            web_browsing=None,
        ):
            return f"{instructions}|{response_instructions}|{model_kind}|{model_hint}|{web_browsing}"

        def patch(self, path, payload):
            self.patch_calls.append((path, payload))

        def publish_bot(self, agent_id):
            self.published = True

    fake_client = FakeClient()
    monkeypatch.setattr(agent_commands, "get_client", lambda: fake_client)
    monkeypatch.setattr(agent_commands, "print_success", lambda message: None)
    monkeypatch.setattr(agent_commands, "print_warning", lambda message: None)

    agent_commands.model_set("agent-123", "ChatPreviewModels:GPT5Chat", publish=False)

    assert fake_client.update_bot_model_calls == [
        ("agent-123", "ChatPreviewModels", "GPT5Chat", False)
    ]
    assert fake_client.patch_calls == [
        (
            "botcomponents(component-123)",
            {"data": "Keep these instructions|Keep this response shape|ChatPreviewModels|GPT5Chat|True"},
        )
    ]
    assert fake_client.published is False
