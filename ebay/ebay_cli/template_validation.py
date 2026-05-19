"""Template validation against JSON schema."""
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from jsonschema import Draft7Validator, ValidationError

# Schema file location (optional - validation skipped if not present)
SCHEMA_DIR = Path(__file__).parent.parent / "templates"


def _find_schema() -> Optional[Path]:
    """Find a schema file in the templates directory."""
    if not SCHEMA_DIR.exists():
        return None
    schemas = list(SCHEMA_DIR.glob("*-schema.json"))
    return schemas[0] if schemas else None


class TemplateValidationError(Exception):
    """Raised when template validation fails."""

    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__(f"Template validation failed: {'; '.join(errors)}")


def load_schema() -> Optional[Dict]:
    """Load the template JSON schema if available."""
    schema_path = _find_schema()
    if not schema_path:
        return None
    return json.loads(schema_path.read_text())


def validate_template(template_record: Dict) -> Tuple[bool, List[str]]:
    """
    Validate a template record against the JSON schema.

    Args:
        template_record: The full template record including name, description, template, etc.

    Returns:
        Tuple of (is_valid, list of error messages)
        Returns (True, []) if no schema is available (validation skipped)
    """
    schema = load_schema()
    if schema is None:
        return True, []  # No schema = skip validation

    validator = Draft7Validator(schema)

    errors = []
    for error in validator.iter_errors(template_record):
        # Build a human-readable error path
        path = " -> ".join(str(p) for p in error.absolute_path) if error.absolute_path else "root"
        errors.append(f"{path}: {error.message}")

    return len(errors) == 0, errors


def validate_template_data(template_data: Dict) -> Tuple[bool, List[str]]:
    """
    Validate just the template data (the 'template' field contents).

    Args:
        template_data: The template configuration (contents of 'template' field)

    Returns:
        Tuple of (is_valid, list of error messages)
        Returns (True, []) if no schema is available (validation skipped)
    """
    schema = load_schema()
    if schema is None:
        return True, []  # No schema = skip validation

    # Extract just the template properties schema, but preserve $defs for references
    template_schema = schema.get("properties", {}).get("template", {})
    if not template_schema:
        return True, []

    # Include $defs from root schema so $ref works
    if "$defs" in schema:
        template_schema = template_schema.copy()
        template_schema["$defs"] = schema["$defs"]

    validator = Draft7Validator(template_schema)

    errors = []
    for error in validator.iter_errors(template_data):
        path = " -> ".join(str(p) for p in error.absolute_path) if error.absolute_path else "root"
        errors.append(f"{path}: {error.message}")

    return len(errors) == 0, errors


def validate_and_raise(template_record: Dict) -> None:
    """
    Validate a template and raise TemplateValidationError if invalid.

    Args:
        template_record: The full template record

    Raises:
        TemplateValidationError: If validation fails
    """
    is_valid, errors = validate_template(template_record)
    if not is_valid:
        raise TemplateValidationError(errors)
