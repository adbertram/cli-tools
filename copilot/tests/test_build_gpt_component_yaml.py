"""
Regression tests for DataverseClient.build_gpt_component_yaml.

The CLI used to emit a `kind:` field under `aISettings.model` (e.g. "DefaultModels"
or "ChatPreviewModels"). Neither of those model kinds is in the current Copilot
Studio YAML schema's AgentModelType union, so every PvaPublish call rejected the
botcomponent with "Node is unknown to the system" and every agent in the
tenant stopped publishing for ~3 weeks while the CLI's publish command falsely
reported success.

The schema accepts the `CurrentModelsNoKind` variant — a `model:` block that has
only `modelNameHint:` and no `kind:`. Microsoft's canonical template at
microsoft/skills-for-copilot-studio/templates/agents/agent.mcs.yml writes exactly
that structure. These tests pin the fix in place.
"""

from __future__ import annotations

import yaml

from copilot_cli.client import DataverseClient


def _make_client() -> DataverseClient:
    return DataverseClient.__new__(DataverseClient)


def test_yaml_omits_kind_field_under_model():
    """The bug: CLI used to write `kind: DefaultModels` under aISettings.model,
    which the Copilot Studio schema rejects. Assert the field is gone."""
    client = _make_client()
    out = client.build_gpt_component_yaml(
        instructions="Be helpful.",
        model_kind="DefaultModels",
        model_hint="GPT5Chat",
    )
    parsed = yaml.safe_load(out)

    assert parsed["kind"] == "GptComponentMetadata"
    assert "aISettings" in parsed
    model = parsed["aISettings"]["model"]
    assert model == {"modelNameHint": "GPT5Chat"}
    assert "kind" not in model


def test_yaml_ignores_legacy_model_kind_parameter():
    """Even when callers still pass model_kind='ChatPreviewModels' (the old
    pseudo-canonical pair for GPT5Chat), the builder must drop it."""
    client = _make_client()
    out = client.build_gpt_component_yaml(
        instructions=None,
        model_kind="ChatPreviewModels",
        model_hint="GPT5Chat",
    )
    assert "kind: ChatPreviewModels" not in out
    assert "kind: DefaultModels" not in out
    parsed = yaml.safe_load(out)
    assert parsed["aISettings"]["model"] == {"modelNameHint": "GPT5Chat"}


def test_yaml_omits_aisettings_when_no_model_hint():
    """If no model_hint is passed, the builder must not emit an aISettings block
    at all. An empty or bare aISettings would be a different schema violation."""
    client = _make_client()
    out = client.build_gpt_component_yaml(
        instructions="Be helpful.",
        model_kind="DefaultModels",
        model_hint=None,
    )
    parsed = yaml.safe_load(out)
    assert "aISettings" not in parsed


def test_yaml_preserves_instructions_as_literal_block_scalar():
    """Instructions must be emitted with YAML's literal block scalar (|) so
    multi-line system prompts aren't wrapped or double-quoted. The Copilot Studio
    UI cannot parse the double-quoted form with \\-line-continuations."""
    client = _make_client()
    out = client.build_gpt_component_yaml(
        instructions="Line one.\nLine two.\nLine three.",
        model_kind=None,
        model_hint="GPT5Chat",
    )
    assert "instructions: |" in out
    assert "Line one." in out
    assert "Line two." in out
    assert "Line three." in out


def test_yaml_matches_microsoft_template_shape():
    """
    Shape-check: the builder output must match the top-level structure of
    microsoft/skills-for-copilot-studio/templates/agents/agent.mcs.yml:
        kind: GptComponentMetadata
        instructions: |
          ...
        aISettings:
          model:
            modelNameHint: GPT5Chat
    """
    client = _make_client()
    out = client.build_gpt_component_yaml(
        instructions="You are a helpful assistant.",
        model_kind="DefaultModels",  # legacy, must be ignored
        model_hint="GPT5Chat",
    )
    parsed = yaml.safe_load(out)
    assert set(parsed.keys()) == {"kind", "instructions", "aISettings"}
    assert parsed["kind"] == "GptComponentMetadata"
    assert parsed["aISettings"] == {"model": {"modelNameHint": "GPT5Chat"}}
