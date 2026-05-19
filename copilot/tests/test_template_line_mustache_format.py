"""
Regression tests for the Mustache template-format opt-in on TemplateLine fields
(`instructions` and `responseInstructions`) in the Custom GPT botcomponent YAML.

THE BUG
-------
`responseInstructions` (and `instructions`) are TemplateLine fields whose
default template format is Power Fx (per the Copilot Studio botcomponent
schema: `TemplateEngineOptions.format` defaults to `PowerFx`). At publish
time, PvaPublish parses these values as Power Fx templates. In a Power Fx
template, `{ ... }` delimits a record / expression literal — so a bare `{`
in user content triggers expression parsing on the rest of the field, and a
quoted JSON key like `"summary_markdown"` then fails because Power Fx record
literals require unquoted keys.

Concretely, the CLI used to emit `responseInstructions` as a plain YAML
literal block scalar, which made every agent whose response-format file
contained a `{ ... }` JSON example fail to publish with:

    Unexpected character in expression '
      "summary_markdown": "..."
      ...

THE FIX
-------
Per-component, set `template.format: Mustache` on the GptComponentMetadata
when content contains `{`. Mustache uses `{{ ... }}` (double braces) for
expressions, so a single `{` is plain literal text — no escaping or
quote-doubling required, and the multi-line content round-trips as a YAML
literal block scalar. This is the per-component opt-in defined in the
Copilot Studio schema (foundry.schema.yaml.cli.json: TemplateFormat oneOf
{PowerFxOptionalKind, Mustache}).
"""

from __future__ import annotations

import yaml

from copilot_cli.client import (
    DataverseClient,
    _needs_mustache_template_format,
)


def _make_client() -> DataverseClient:
    return DataverseClient.__new__(DataverseClient)


# ---------------------------------------------------------------------------
# Helper-level tests
# ---------------------------------------------------------------------------


def test_needs_mustache_true_for_text_with_brace():
    assert _needs_mustache_template_format("Use this shape: { foo: 1 }") is True


def test_needs_mustache_false_for_plain_text():
    assert _needs_mustache_template_format("plain markdown content") is False
    assert _needs_mustache_template_format("") is False
    assert _needs_mustache_template_format(None) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# build_gpt_component_yaml integration
# ---------------------------------------------------------------------------


# Sample mirrors response-format files in the Progress Content Automation repo
# (ansible/roles/agents/files/response-formats/developmental-reviewer.md).
RESPONSE_INSTRUCTIONS_WITH_JSON = (
    "Return only valid JSON. Do not include markdown fences, greetings, "
    "pleasantries, explanatory prose, or keys outside the required object.\n\n"
    "Use this exact object shape:\n"
    "{\n"
    '  "summary_markdown": "Structured Markdown review report.",\n'
    '  "comments": [\n'
    "    {\n"
    '      "paragraph_id": "P0001",\n'
    '      "anchor_text": "exact text from the paragraph",\n'
    '      "review_type": "developmental",\n'
    '      "severity": "low|medium|high",\n'
    '      "comment": "Actionable comment for the Word document.",\n'
    '      "suggested_replacement": "Replacement text or empty string."\n'
    "    }\n"
    "  ]\n"
    "}\n"
)


def test_response_instructions_with_json_emits_template_mustache():
    """
    When `responseInstructions` content contains `{`, the YAML must include
    `template: { kind: TemplateEngineOptions, format: Mustache }`. This is the
    actual fix for the publish-blocking bug.
    """
    client = _make_client()
    out = client.build_gpt_component_yaml(
        instructions="Be helpful.",
        response_instructions=RESPONSE_INSTRUCTIONS_WITH_JSON,
        model_hint="GPT5Chat",
    )
    parsed = yaml.safe_load(out)
    assert parsed.get("template") == {
        "kind": "TemplateEngineOptions",
        "format": "Mustache",
    }
    # The text content must be unchanged — no Power Fx wrapping or escaping.
    assert parsed["responseInstructions"] == RESPONSE_INSTRUCTIONS_WITH_JSON


def test_response_instructions_without_brace_leaves_template_default():
    """
    Content with no `{` does NOT need Mustache. The YAML must NOT emit a
    `template` block — the default Power Fx parser handles plain text fine,
    and matching Microsoft's canonical agent.mcs.yml shape (no template:
    field) keeps the change surface minimal.
    """
    client = _make_client()
    plain = "Talk in a professional manner. Use bullet points when possible."
    out = client.build_gpt_component_yaml(
        response_instructions=plain,
        model_hint="GPT5Chat",
    )
    parsed = yaml.safe_load(out)
    assert "template" not in parsed
    assert parsed["responseInstructions"] == plain


def test_instructions_with_brace_also_triggers_mustache():
    """
    `instructions` is the same TemplateLine type as `responseInstructions`, so
    the same publish-blocking failure can occur if a system prompt contains
    `{`. The Mustache opt-in MUST cover both fields together.
    """
    client = _make_client()
    instr = "When user mentions { schema }, respond carefully."
    out = client.build_gpt_component_yaml(
        instructions=instr,
        model_hint="GPT5Chat",
    )
    parsed = yaml.safe_load(out)
    assert parsed.get("template") == {
        "kind": "TemplateEngineOptions",
        "format": "Mustache",
    }
    assert parsed["instructions"] == instr


def test_yaml_round_trip_through_parse():
    """
    Full build → parse round-trip via the public client APIs. This is the
    contract the update_response_instructions / update_gpt_instructions paths
    rely on when they read existing settings before re-emitting YAML — the
    text content must come back byte-identical.
    """
    client = _make_client()
    out = client.build_gpt_component_yaml(
        instructions="System prompt without braces.",
        response_instructions=RESPONSE_INSTRUCTIONS_WITH_JSON,
        model_hint="GPT5Chat",
        web_browsing=True,
    )
    parsed = client.parse_gpt_component_yaml(out)
    assert parsed["instructions"] == "System prompt without braces."
    assert parsed["response_instructions"] == RESPONSE_INSTRUCTIONS_WITH_JSON
    assert parsed["model_hint"] == "GPT5Chat"
    assert parsed["web_browsing"] is True


def test_template_block_uses_quoted_string_format_value():
    """
    Smoke check: the Mustache literal must be emitted as a plain string value
    in the YAML, matching the schema's PowerFxOptionalKind/Mustache oneOf.
    A YAML mapping with `format: Mustache` (string scalar) is the simplest
    encoding.
    """
    client = _make_client()
    out = client.build_gpt_component_yaml(
        response_instructions=RESPONSE_INSTRUCTIONS_WITH_JSON,
        model_hint="GPT5Chat",
    )
    assert "format: Mustache" in out
    assert "kind: TemplateEngineOptions" in out


def test_published_yaml_contains_no_powerfx_wrap_artifacts():
    """
    The earlier attempted fix wrapped content as `="..."` (Power Fx string
    literal). That approach is deliberately abandoned because the publisher
    parser still rejects it. Guard against accidental regression by asserting
    no `="` appears anywhere in the emitted YAML for plain JSON-bearing
    response instructions.
    """
    client = _make_client()
    out = client.build_gpt_component_yaml(
        response_instructions=RESPONSE_INSTRUCTIONS_WITH_JSON,
        model_hint="GPT5Chat",
    )
    assert '="' not in out
