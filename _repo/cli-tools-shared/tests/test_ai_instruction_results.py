import json

import pytest
from pydantic import ValidationError

from cli_tools_shared import AIInstruction
from cli_tools_shared.output import print_ai_instruction


def make_instruction(**overrides):
    data = {
        "tool": "example",
        "command": "messages triage",
        "action_id": "triage_message",
        "objective": "Decide how to handle the customer message.",
        "structured_context": {
            "message_id": "msg_123",
            "message": "Can you help with my order?",
        },
        "narrative_context": "A customer is asking for help with an order.",
        "allowed_tools": ["cli", "browser", "file", "web"],
        "constraints": ["Do not invent order details."],
        "success_criteria": ["The customer receives a specific response."],
    }
    data.update(overrides)
    return AIInstruction(**data)


def test_ai_instruction_serializes_required_contract():
    instruction = make_instruction()

    serialized = instruction.model_dump(mode="json", exclude_none=True)

    assert serialized == {
        "type": "ai_instruction",
        "schema_version": "1.0",
        "tool": "example",
        "command": "messages triage",
        "action_id": "triage_message",
        "objective": "Decide how to handle the customer message.",
        "structured_context": {
            "message_id": "msg_123",
            "message": "Can you help with my order?",
        },
        "narrative_context": "A customer is asking for help with an order.",
        "allowed_tools": ["cli", "browser", "file", "web"],
        "constraints": ["Do not invent order details."],
        "success_criteria": ["The customer receives a specific response."],
    }


def test_ai_instruction_allows_post_completion_commands():
    instruction = make_instruction(
        verification_commands=["example messages get msg_123"],
        follow_up_commands=["example messages list --limit 5"],
    )

    serialized = instruction.model_dump(mode="json", exclude_none=True)

    assert serialized["verification_commands"] == ["example messages get msg_123"]
    assert serialized["follow_up_commands"] == ["example messages list --limit 5"]


def test_ai_instruction_rejects_required_commands_field():
    with pytest.raises(ValidationError):
        make_instruction(required_commands=["example messages reply msg_123"])


def test_print_ai_instruction_outputs_json(capsys):
    instruction = make_instruction()

    print_ai_instruction(instruction)

    captured = capsys.readouterr()
    assert captured.err == ""
    parsed = json.loads(captured.out)
    assert parsed["type"] == "ai_instruction"
    assert "narrative_context" in parsed
    assert "required_commands" not in parsed


def test_print_ai_instruction_rejects_other_models():
    with pytest.raises(TypeError, match="Expected AIInstruction"):
        print_ai_instruction({"type": "ai_instruction"})
