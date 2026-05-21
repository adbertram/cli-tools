# Data Shape Standards

The CLI's external command contract matters more than its internal data
representation. Command names, options, stdout JSON/table shape, auth behavior,
cache behavior, and exit codes are the product surface.

## Representation Decision

| Situation | Representation |
|-----------|----------------|
| Parsed/API data already matches output fields | Plain dict records |
| Command output needs small derived fields | Plain dict records built by parsers/client |
| Runtime validation materially catches bad upstream data | Pydantic model |
| Polymorphic child objects need controlled serialization | Pydantic model with `SerializeAsAny` |
| Command returns an AI handoff payload | Shared `AIInstruction` model |

Rules:
- Do not create `models/`, `filters.py`, `output.py`, or helper modules just to satisfy an old template.
- Do not keep a direct `pydantic` dependency unless runtime package code imports `pydantic` or `cli_tools_shared.models`.
- Do not convert dicts into models and back into dicts when the command only needs to print the same fields.
- Keep parser/client records stable enough for command contract tests to assert exact output.
- Preserve fail-fast behavior: missing required upstream fields should fail at the parser or model boundary, not be hidden with fallback values.

## AI Instruction Model

`AIInstruction` from `cli_tools_shared.models` is the standard model for CLI-to-agent handoffs. Use it when a command can identify the next objective and context but the actual action requires AI judgment.

Rules:
- Import and return the shared `AIInstruction`; do not define a local schema.
- Keep `type` as `ai_instruction` and `schema_version` as `1.0`.
- Include `tool`, `command`, `action_id`, `objective`, `structured_context`, `allowed_tools`, `constraints`, and `success_criteria`.
- Add `narrative_context` when prose context helps the agent act correctly.
- Add `verification_commands` or `follow_up_commands` only for post-completion checks or continuation.
- Never add `required_commands`; the CLI must not pretend the non-deterministic action has a deterministic command path.

## Printing Output

Use shared output helpers directly from `cli_tools_shared.output`. Do not add a
local `output.py` re-export module.

```python
from cli_tools_shared.output import print_json, print_table

print_json(records)
print_table(records, columns=["id", "name"], headers=["ID", "Name"])
```

`print_json()` and `print_table()` handle plain dicts, lists, and Pydantic
models. Pick the smallest representation that preserves the documented output.

## When Pydantic Earns Its Cost

Use local Pydantic models when they remove real complexity:

```python
from cli_tools_shared.models import CLIModel


class Item(CLIModel):
    id: str
    name: str
```

Required fields must have no default value. Let validation fail when required
data is missing.

```python
# WRONG - hides malformed upstream data
name = data.get("name") or "Unknown"

# CORRECT - fail at the boundary that knows the required shape
class Item(CLIModel):
    name: str
```

## Factory Functions for Polymorphism

Use factory functions when a single action type maps to different models:

```python
def create_step(action_type: str, params: dict) -> AnyStep:
    if "variable" in action_type.lower():
        return VariableStep(**params)
    if "http" in action_type.lower():
        return HttpStep(**params)
    raise ValueError(f"Unknown action type: {action_type}")
```

## SerializeAsAny for Polymorphic Child Lists

When a parent model contains a list of polymorphic child models, use
`SerializeAsAny` so subclass fields are serialized.

```python
from pydantic import SerializeAsAny
from typing import List, Optional

from .step import Step


class Flow(CLIModel):
    id: str
    name: str
    steps: Optional[List[SerializeAsAny[Step]]] = None
```

Without `SerializeAsAny`, Pydantic serializes only fields from the declared base
type and drops subclass-specific fields.
