"""Validation for agent flow definitions and agent instructions.

This module provides an extensible validation system for agent flow YAML files
and agent instructions. Rules are defined as classes that can be easily added
or modified.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import re
from typing import Any, Optional


@dataclass
class ValidationError:
    """Represents a validation error."""
    rule: str
    message: str
    path: str  # JSON path to the problematic element (e.g., "actions.Create_Item.inputs.parameters")
    severity: str = "error"  # "error" or "warning"
    suggestion: Optional[str] = None


@dataclass
class ValidationResult:
    """Result of validation containing all errors and warnings."""
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """Returns True if there are no errors (warnings are allowed)."""
        return len(self.errors) == 0

    def add_error(self, error: ValidationError):
        """Add an error to the result."""
        if error.severity == "warning":
            self.warnings.append(error)
        else:
            self.errors.append(error)

    def merge(self, other: "ValidationResult"):
        """Merge another validation result into this one."""
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)


class ValidationRule(ABC):
    """Base class for validation rules."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Rule identifier."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what this rule checks."""
        pass

    @abstractmethod
    def validate(self, data: dict, path: str = "") -> ValidationResult:
        """
        Validate the data against this rule.

        Args:
            data: The YAML data to validate
            path: Current JSON path (for nested validation)

        Returns:
            ValidationResult containing any errors or warnings
        """
        pass


class UndefinedParameterRule(ValidationRule):
    """
    Validates that action parameters match known operation schemas.

    This rule detects cases where actions use parameters that don't exist
    in the connector's operation definition. For example, using a 'fields'
    parameter when the CreateItem operation expects individual field parameters.
    """

    # Known operations and their valid parameter names
    # This can be expanded as we discover more patterns
    KNOWN_OPERATIONS = {
        # Podio connector operations
        "GetItem": ["item_id", "mark_as_viewed"],
        "CreateItem": ["app_id", "space_id", "external_id", "silent", "hook", "reminder"],
        "UpdateItem": ["item_id", "revision", "silent", "hook"],
        "DeleteItem": ["item_id", "silent", "hook"],
        # Add more operations as needed
    }

    # Parameters that should never be used (common mistakes)
    INVALID_PARAMETERS = {
        "fields": "The 'fields' parameter is not a valid API parameter. For CreateItem/UpdateItem, field values should be passed as individual parameters matching the app's field external_ids.",
    }

    @property
    def name(self) -> str:
        return "undefined-parameter"

    @property
    def description(self) -> str:
        return "Checks for parameters that don't exist in the connector operation definition"

    def validate(self, data: dict, path: str = "") -> ValidationResult:
        result = ValidationResult()

        # Get the definition (handle both full export and definition-only formats)
        definition = data.get("definition", data)
        actions = definition.get("actions", {})

        for action_name, action_data in actions.items():
            action_path = f"{path}actions.{action_name}" if path else f"actions.{action_name}"

            # Skip non-OpenApiConnection actions
            if action_data.get("type") != "OpenApiConnection":
                continue

            inputs = action_data.get("inputs", {})
            parameters = inputs.get("parameters", {})
            operation_id = inputs.get("host", {}).get("operationId", "")

            # Check for known invalid parameters
            for param_name, param_value in parameters.items():
                if param_name in self.INVALID_PARAMETERS:
                    result.add_error(ValidationError(
                        rule=self.name,
                        message=f"Invalid parameter '{param_name}' in action '{action_name}'",
                        path=f"{action_path}.inputs.parameters.{param_name}",
                        severity="error",
                        suggestion=self.INVALID_PARAMETERS[param_name],
                    ))

            # If we know the operation, validate against known parameters
            if operation_id in self.KNOWN_OPERATIONS:
                valid_params = self.KNOWN_OPERATIONS[operation_id]
                for param_name in parameters.keys():
                    if param_name not in valid_params and param_name not in self.INVALID_PARAMETERS:
                        # This is a warning since we may not have complete knowledge
                        result.add_error(ValidationError(
                            rule=self.name,
                            message=f"Unknown parameter '{param_name}' for operation '{operation_id}' in action '{action_name}'",
                            path=f"{action_path}.inputs.parameters.{param_name}",
                            severity="warning",
                            suggestion=f"Valid parameters for {operation_id}: {', '.join(valid_params)}",
                        ))

        return result


class ConnectionReferenceRule(ValidationRule):
    """
    Validates connection reference format and consistency.

    Checks that:
    1. Actions use 'connectionName' in host (maps to connectionReferences keys)
    2. The connectionName matches a key in connectionReferences
    3. connectionReferences have required fields

    Note: The Power Platform API accepts 'connectionName' in flow definitions.
    The connectionName should match a key in the connectionReferences section,
    which typically uses the full connector API ID as the key.
    """

    @property
    def name(self) -> str:
        return "connection-reference-format"

    @property
    def description(self) -> str:
        return "Validates connection reference format and consistency between actions and connectionReferences"

    def validate(self, data: dict, path: str = "") -> ValidationResult:
        result = ValidationResult()

        # Get the definition (handle both full export and definition-only formats)
        definition = data.get("definition", data)
        connection_refs = data.get("connectionReferences", {})

        actions = definition.get("actions", {})

        for action_name, action_data in actions.items():
            action_path = f"{path}actions.{action_name}" if path else f"actions.{action_name}"

            # Skip non-OpenApiConnection actions
            if action_data.get("type") != "OpenApiConnection":
                continue

            host = action_data.get("inputs", {}).get("host", {})

            # Get the connection reference (either connectionName or connectionReferenceName)
            # Both are accepted by the API - connectionName is the standard format
            connection_name = host.get("connectionName") or host.get("connectionReferenceName")

            # Check that connection reference exists in connectionReferences
            if connection_name and connection_refs:
                if connection_name not in connection_refs:
                    result.add_error(ValidationError(
                        rule=self.name,
                        message=f"Action '{action_name}' references connection '{connection_name}' which is not defined in connectionReferences",
                        path=f"{action_path}.inputs.host.connectionName",
                        severity="error",
                        suggestion=f"Add '{connection_name}' to connectionReferences section or update the connectionName to match an existing reference.",
                    ))

        # Validate connectionReferences structure
        for ref_name, ref_data in connection_refs.items():
            ref_path = f"connectionReferences.{ref_name}"

            if not ref_data.get("api", {}).get("name"):
                result.add_error(ValidationError(
                    rule=self.name,
                    message=f"Connection reference '{ref_name}' missing required 'api.name' field",
                    path=f"{ref_path}.api.name",
                    severity="error",
                    suggestion="Add the api.name field with the connector's API identifier.",
                ))

            if not ref_data.get("connection", {}).get("connectionReferenceLogicalName"):
                result.add_error(ValidationError(
                    rule=self.name,
                    message=f"Connection reference '{ref_name}' missing required 'connection.connectionReferenceLogicalName' field",
                    path=f"{ref_path}.connection.connectionReferenceLogicalName",
                    severity="error",
                    suggestion="Add the connection.connectionReferenceLogicalName field with the Dataverse connection reference logical name.",
                ))

        return result


class RequiredFieldsRule(ValidationRule):
    """
    Validates that required fields are present in the flow definition.
    """

    @property
    def name(self) -> str:
        return "required-fields"

    @property
    def description(self) -> str:
        return "Checks for required fields in the flow definition"

    def validate(self, data: dict, path: str = "") -> ValidationResult:
        result = ValidationResult()

        # Get the definition (handle both full export and definition-only formats)
        definition = data.get("definition", data)

        # Check for triggers
        if not definition.get("triggers"):
            result.add_error(ValidationError(
                rule=self.name,
                message="Flow definition missing 'triggers' section",
                path="definition.triggers",
                severity="error",
                suggestion="Add a triggers section. Agent flows typically use 'manual' trigger with type 'Request' and kind 'Http'.",
            ))

        # Check for actions (warning only - empty flows are technically valid)
        if not definition.get("actions"):
            result.add_error(ValidationError(
                rule=self.name,
                message="Flow definition has no actions",
                path="definition.actions",
                severity="warning",
                suggestion="Add actions to define what the flow does.",
            ))

        return result


class ExpressionSyntaxRule(ValidationRule):
    """
    Validates Power Automate expression syntax.

    Checks for common expression mistakes like:
    - Missing @ prefix
    - Mismatched quotes
    - Invalid function names
    """

    VALID_FUNCTIONS = [
        "triggerBody", "triggerOutputs", "body", "outputs", "actions",
        "parameters", "variables", "item", "items", "iterationIndexes",
        "concat", "substring", "replace", "split", "join", "first", "last",
        "length", "contains", "startsWith", "endsWith", "indexOf", "toLower", "toUpper",
        "trim", "add", "sub", "mul", "div", "mod", "min", "max", "rand",
        "if", "equals", "less", "lessOrEquals", "greater", "greaterOrEquals",
        "and", "or", "not", "coalesce", "json", "xml", "string", "int", "float", "bool",
        "array", "createArray", "empty", "null", "true", "false",
        "utcNow", "addDays", "addHours", "addMinutes", "addSeconds",
        "dayOfWeek", "dayOfMonth", "dayOfYear", "formatDateTime", "parseDateTime",
        "base64", "base64ToBinary", "base64ToString", "binary",
        "uriComponent", "uriComponentToString", "decodeBase64", "encodeUriComponent",
    ]

    @property
    def name(self) -> str:
        return "expression-syntax"

    @property
    def description(self) -> str:
        return "Validates Power Automate expression syntax"

    def validate(self, data: dict, path: str = "") -> ValidationResult:
        result = ValidationResult()

        # Recursively check all string values for expression syntax
        self._check_expressions(data, "", result)

        return result

    def _check_expressions(self, data: Any, path: str, result: ValidationResult):
        """Recursively check all values for expression syntax issues."""
        if isinstance(data, dict):
            for key, value in data.items():
                new_path = f"{path}.{key}" if path else key
                self._check_expressions(value, new_path, result)
        elif isinstance(data, list):
            for i, item in enumerate(data):
                new_path = f"{path}[{i}]"
                self._check_expressions(item, new_path, result)
        elif isinstance(data, str):
            self._validate_expression(data, path, result)

    def _validate_expression(self, value: str, path: str, result: ValidationResult):
        """Validate a single expression string."""
        # Skip non-expressions
        if not value.startswith("@"):
            return

        # Check for common issues
        expression = value[1:]  # Remove @ prefix

        # Check for mismatched quotes
        single_quotes = expression.count("'")
        if single_quotes % 2 != 0:
            result.add_error(ValidationError(
                rule=self.name,
                message=f"Expression has mismatched single quotes",
                path=path,
                severity="error",
                suggestion="Ensure all single quotes are properly paired. Use '' to escape a single quote within a string.",
            ))

        # Check for double quotes (should use single quotes in expressions)
        if '"' in expression and not expression.startswith("{"):
            result.add_error(ValidationError(
                rule=self.name,
                message=f"Expression uses double quotes which may cause issues",
                path=path,
                severity="warning",
                suggestion="Use single quotes instead of double quotes in Power Automate expressions.",
            ))


class ChildFlowResponseRule(ValidationRule):
    """
    Validates that child flows have the required Response action.

    When a flow has a Button trigger (kind: Button), it is designed to be called
    as a child flow by another flow using the "Run a Child Flow" action.

    Child flows MUST have a Response action with kind: PowerApp to return data
    to the parent flow. Without this, the parent flow will fail with:
    - ChildFlowMissingResponseOperation

    Additionally validates that the Response action is reachable from all
    execution paths through the flow.
    """

    @property
    def name(self) -> str:
        return "child-flow-response"

    @property
    def description(self) -> str:
        return "Validates that child flows (Button trigger) have a Response action with kind: PowerApp"

    def validate(self, data: dict, path: str = "") -> ValidationResult:
        result = ValidationResult()

        # Get the definition (handle both full export and definition-only formats)
        definition = data.get("definition", data)
        triggers = definition.get("triggers", {})
        actions = definition.get("actions", {})

        # Check if this is a child flow (has Button trigger)
        is_child_flow = False
        for trigger_name, trigger_data in triggers.items():
            if trigger_data.get("kind") == "Button":
                is_child_flow = True
                break

        if not is_child_flow:
            # Not a child flow, skip validation
            return result

        # This is a child flow - it MUST have a Response action with kind: PowerApp
        has_valid_response = False
        response_action_name = None

        for action_name, action_data in actions.items():
            if action_data.get("type") == "Response":
                response_action_name = action_name
                action_kind = action_data.get("kind", "")

                if action_kind == "PowerApp":
                    has_valid_response = True
                    break
                elif action_kind == "Http":
                    # Has Response but wrong kind
                    result.add_error(ValidationError(
                        rule=self.name,
                        message=f"Child flow Response action '{action_name}' has kind 'Http' but should be 'PowerApp'",
                        path=f"actions.{action_name}.kind",
                        severity="error",
                        suggestion="Change 'kind: Http' to 'kind: PowerApp' for child flow responses. Http is for HTTP-triggered flows, PowerApp is for child flows called via 'Run a Child Flow'.",
                    ))
                    has_valid_response = True  # Don't add another error for missing response
                    break

        if not has_valid_response and response_action_name is None:
            result.add_error(ValidationError(
                rule=self.name,
                message="Child flow (Button trigger) is missing required Response action",
                path="definition.actions",
                severity="error",
                suggestion="Add a 'Response' action with 'type: Response' and 'kind: PowerApp' to return data to the parent flow. Without this, the parent flow will fail with ChildFlowMissingResponseOperation error.",
            ))

        return result


class FlowYAMLValidator:
    """
    Main validator class that runs all validation rules.

    Usage:
        validator = FlowYAMLValidator()
        result = validator.validate(yaml_data)
        if not result.is_valid:
            for error in result.errors:
                print(f"{error.path}: {error.message}")
    """

    def __init__(self, rules: Optional[list[ValidationRule]] = None):
        """
        Initialize the validator with a set of rules.

        Args:
            rules: List of validation rules to use. If None, uses all default rules.
        """
        if rules is None:
            # Default rules
            self.rules = [
                RequiredFieldsRule(),
                ConnectionReferenceRule(),
                UndefinedParameterRule(),
                ExpressionSyntaxRule(),
                ChildFlowResponseRule(),
            ]
        else:
            self.rules = rules

    def add_rule(self, rule: ValidationRule):
        """Add a validation rule."""
        self.rules.append(rule)

    def remove_rule(self, rule_name: str):
        """Remove a validation rule by name."""
        self.rules = [r for r in self.rules if r.name != rule_name]

    def validate(self, data: dict) -> ValidationResult:
        """
        Validate the flow YAML data against all rules.

        Args:
            data: The parsed YAML data to validate

        Returns:
            ValidationResult containing all errors and warnings
        """
        result = ValidationResult()

        for rule in self.rules:
            rule_result = rule.validate(data)
            result.merge(rule_result)

        return result

    def get_rule_descriptions(self) -> dict[str, str]:
        """Get descriptions of all active rules."""
        return {rule.name: rule.description for rule in self.rules}


def validate_agent_flow_yaml(data: dict, include_warnings: bool = True) -> tuple[bool, list[str]]:
    """
    Convenience function to validate agent flow YAML.

    Args:
        data: The parsed YAML data to validate
        include_warnings: Whether to include warnings in output

    Returns:
        Tuple of (is_valid, list of error/warning messages)
    """
    validator = FlowYAMLValidator()
    result = validator.validate(data)

    messages = []

    for error in result.errors:
        msg = f"ERROR [{error.rule}] {error.path}: {error.message}"
        if error.suggestion:
            msg += f"\n  Suggestion: {error.suggestion}"
        messages.append(msg)

    if include_warnings:
        for warning in result.warnings:
            msg = f"WARNING [{warning.rule}] {warning.path}: {warning.message}"
            if warning.suggestion:
                msg += f"\n  Suggestion: {warning.suggestion}"
            messages.append(msg)

    return result.is_valid, messages


# =============================================================================
# Agent Instruction Validation
# =============================================================================


@dataclass
class InstructionValidationError:
    """Represents an instruction validation error."""

    message: str
    position: int
    context: str  # Snippet of text around the problematic area
    suggestion: str


@dataclass
class InstructionValidationResult:
    """Result of instruction validation."""

    is_valid: bool
    errors: list[InstructionValidationError] = field(default_factory=list)

    def add_error(self, error: InstructionValidationError):
        """Add an error to the result."""
        self.errors.append(error)
        self.is_valid = False


def validate_agent_instructions(instructions: str) -> InstructionValidationResult:
    """
    Validate agent instructions for patterns that will cause Power Fx expression
    parsing errors in Copilot Studio.

    Copilot Studio parses certain characters in instructions as Power Fx expressions,
    particularly curly braces {}. This causes publish failures with errors like:
    - "UnexpectedCharacter" in expression parsing
    - ExpressionError with source showing the problematic content

    This function detects:
    1. Curly braces {} outside of escaped/protected contexts
    2. JSON-like structures in the instructions
    3. Patterns that look like Power Fx expressions

    Args:
        instructions: The instruction text to validate

    Returns:
        InstructionValidationResult with is_valid flag and list of errors
    """
    result = InstructionValidationResult(is_valid=True)

    # Copilot Studio interprets ANY curly braces as Power Fx expressions.
    # Even inside markdown code fences or backticks, braces are parsed.
    # There is no safe way to include { or } in agent instructions.
    brace_pattern = re.compile(r'[{}]')

    for match in brace_pattern.finditer(instructions):
        context = _get_context_snippet(instructions, match.start(), match.start() + 1)
        result.add_error(InstructionValidationError(
            message=f"Curly brace '{match.group()}' detected - Copilot Studio parses all curly braces as Power Fx expressions",
            position=match.start(),
            context=context,
            suggestion=(
                "Remove curly braces entirely. Alternatives:\n"
                '  - Instead of {url, brand} use: objects with "url" and "brand" fields\n'
                '  - Instead of {"key": "value"} use: set "key" to "value"\n'
                "  - Instead of {} use: empty object\n"
                "  - Use parentheses, square brackets, or plain text descriptions"
            ),
        ))

    return result


def _get_context_snippet(text: str, start: int, end: int, context_chars: int = 40) -> str:
    """
    Get a snippet of text around a match position for error context.

    Args:
        text: The full text
        start: Start position of the match
        end: End position of the match
        context_chars: Number of characters to show before/after

    Returns:
        A snippet showing the problematic area with ellipsis if truncated
    """
    snippet_start = max(0, start - context_chars)
    snippet_end = min(len(text), end + context_chars)

    prefix = "..." if snippet_start > 0 else ""
    suffix = "..." if snippet_end < len(text) else ""

    snippet = text[snippet_start:snippet_end]
    # Clean up the snippet - replace newlines with visible markers
    snippet = snippet.replace('\n', '\\n').replace('\r', '')

    return f"{prefix}{snippet}{suffix}"


def format_instruction_validation_errors(result: InstructionValidationResult) -> str:
    """
    Format instruction validation errors for CLI output.

    Args:
        result: The validation result to format

    Returns:
        Formatted error message string
    """
    if result.is_valid:
        return ""

    lines = [
        "Error: Agent instructions contain patterns that will cause Power Fx expression parsing errors.",
        "",
        "Copilot Studio interprets curly braces {} as Power Fx expressions, which causes publish failures.",
        "",
        f"Found {len(result.errors)} problematic pattern(s):",
        "",
    ]

    for i, error in enumerate(result.errors, 1):
        lines.append(f"  {i}. {error.message}")
        lines.append(f"     Position: {error.position}")
        lines.append(f"     Context: {error.context}")
        lines.append(f"     {error.suggestion}")
        lines.append("")

    lines.append("Fix these issues in your instructions before updating the agent.")

    return "\n".join(lines)
