"""Template examples must follow the lean CLI architecture."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = SKILL_ROOT / "templates"
TEMPLATE_TYPES = ("api", "browser", "wrapper")


def _template_pyproject(template_type: str) -> dict:
    return tomllib.loads(_render_template((TEMPLATES / template_type / "pyproject.toml").read_text()))


def _render_template(text: str) -> str:
    replacements = {
        "{{name}}": "sample",
        "{{name_underscore}}": "sample",
        "{{Name}}": "Sample",
        "{{NAME}}": "SAMPLE",
        "{{base_url}}": "https://example.com",
        "{{cli_command}}": "samplectl",
        "{{credential_types}}": "CredentialType.API_KEY",
    }
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value)
    return text


def _has_browser_method(path: Path) -> bool:
    tree = ast.parse(_render_template(path.read_text()))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if not any(getattr(base, "id", None) == "BrowserAutomation" for base in node.bases):
            continue
        return any(isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) for stmt in node.body)
    return False


def test_templates_do_not_ship_model_first_scaffolding():
    forbidden_paths = []
    for template_type in TEMPLATE_TYPES:
        pkg_dir = TEMPLATES / template_type / "{{name}}_cli"
        for relative in ("models", "commands", "filters.py", "output.py"):
            path = pkg_dir / relative
            if path.exists():
                forbidden_paths.append(path.relative_to(SKILL_ROOT).as_posix())
    assert forbidden_paths == []


def test_templates_do_not_declare_pydantic_by_default():
    offenders = []
    for template_type in TEMPLATE_TYPES:
        dependencies = _template_pyproject(template_type)["project"]["dependencies"]
        if any(dependency.split(">=", 1)[0] == "pydantic" for dependency in dependencies):
            offenders.append(template_type)
    assert offenders == []


def test_template_source_uses_output_contract_language():
    forbidden = [
        "Pydantic",
        "pydantic",
        "CLIModel",
        "BaseModel",
        "model_dump",
        "returns models",
        "return models",
        "strongly-typed",
        "from .models",
        "from .filters",
        "from .output",
    ]
    hits = []
    for path in TEMPLATES.rglob("*"):
        if not path.is_file() or any(part.startswith(".") for part in path.parts):
            continue
        text = path.read_text()
        for phrase in forbidden:
            if phrase in text:
                hits.append(f"{path.relative_to(SKILL_ROOT)} contains {phrase!r}")
    assert hits == []


def test_rendered_template_python_is_valid():
    for path in TEMPLATES.rglob("*.py"):
        ast.parse(_render_template(path.read_text()), filename=str(path))


def test_browser_template_subclass_is_declarative():
    browser_file = TEMPLATES / "browser" / "{{name}}_cli" / "browser.py"
    assert not _has_browser_method(browser_file)
