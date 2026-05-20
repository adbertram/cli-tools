"""The cli-tool guidance must reflect the lean CLI contract."""

from __future__ import annotations

from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (SKILL_ROOT / relative_path).read_text()


def test_skill_no_longer_mandates_pydantic_models():
    text = _read("SKILL.md")
    forbidden = [
        "Model-Driven Architecture",
        "All CLI tools use Pydantic models",
        "Commands return typed models, not raw dicts",
        "uses requests, pydantic",
        "uses Playwright CLI with named sessions, BaseConfig, pydantic",
        "uses subprocess, pydantic",
        "Ensures models are defined and client returns models",
    ]
    found = [phrase for phrase in forbidden if phrase in text]
    assert found == [], (
        "SKILL.md still describes the old model-first template contract. "
        f"Remove or rewrite: {found}"
    )


def test_model_reference_describes_models_as_optional():
    text = _read("references/model-standards.md")
    forbidden = [
        "All CLI tools use Pydantic models",
        "All commands return Pydantic models | REQUIRED",
        "Client methods return typed models | REQUIRED",
        "Never return raw dicts from client | FORBIDDEN",
        "Every CLI must use Pydantic models",
    ]
    found = [phrase for phrase in forbidden if phrase in text]
    assert found == [], (
        "references/model-standards.md still treats local models as mandatory. "
        f"Remove or rewrite: {found}"
    )
