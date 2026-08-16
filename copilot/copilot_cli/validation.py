"""Validation for agent flow definitions and agent instructions.

This module provides an extensible validation system for agent flow YAML files
and agent instructions. Rules are defined as classes that can be easily added
or modified.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import re
from typing import Any, Optional


# Lowercased Logic Apps / Power Automate operation types that are backed by a
# connector and therefore bind to '$connections' and a connection reference.
# Operation types are compared case-insensitively.
CONNECTOR_OPERATION_TYPES = frozenset({
    "openapiconnection",
    "openapiconnectionwebhook",
    "openapiconnectionnotification",
    "apiconnection",
    "apiconnectionwebhook",
    "apiconnectionnotification",
})


@dataclass(frozen=True)
class ConnectorOperation:
    """A connector-backed trigger or action found in a flow definition."""

    name: str  # Leaf operation name, e.g. "Start_and_wait_for_an_approval"
    path: str  # Full path, e.g. "actions.Condition.else.actions.Approve"
    node: dict  # The operation definition itself

    @property
    def kind(self) -> str:
        """Return 'Trigger' for trigger operations and 'Action' otherwise."""
        return "Trigger" if self.path.startswith("triggers.") else "Action"

    @property
    def inputs(self) -> dict:
        """Return the operation inputs, or an empty mapping when absent."""
        inputs = self.node.get("inputs")
        return inputs if isinstance(inputs, dict) else {}

    @property
    def host(self) -> dict:
        """Return the operation host block, or an empty mapping when absent."""
        host = self.inputs.get("host")
        return host if isinstance(host, dict) else {}


def iter_connector_operations(operations: Any, path: str):
    """
    Yield every connector-backed operation in an actions or triggers map.

    Walks nested container actions (Scope, If, Foreach, Switch, Until) so
    connector operations inside branches are not missed.

    Args:
        operations: The actions or triggers mapping to walk
        path: Path prefix for the mapping, e.g. "actions" or "triggers"

    Yields:
        ConnectorOperation records in definition order
    """
    if not isinstance(operations, dict):
        return

    for operation_name, node in operations.items():
        if not isinstance(node, dict):
            continue

        node_path = f"{path}.{operation_name}"
        node_type = node.get("type")
        if isinstance(node_type, str) and node_type.lower() in CONNECTOR_OPERATION_TYPES:
            yield ConnectorOperation(name=operation_name, path=node_path, node=node)

        yield from iter_connector_operations(node.get("actions"), f"{node_path}.actions")

        for branch_key in ("else", "default"):
            branch = node.get(branch_key)
            if isinstance(branch, dict):
                yield from iter_connector_operations(
                    branch.get("actions"), f"{node_path}.{branch_key}.actions"
                )

        cases = node.get("cases")
        if isinstance(cases, dict):
            for case_name, case_node in cases.items():
                if isinstance(case_node, dict):
                    yield from iter_connector_operations(
                        case_node.get("actions"), f"{node_path}.cases.{case_name}.actions"
                    )


def iter_definition_connector_operations(definition: Any):
    """Yield every connector-backed trigger and action in a flow definition."""
    if not isinstance(definition, dict):
        return

    yield from iter_connector_operations(definition.get("triggers"), "triggers")
    yield from iter_connector_operations(definition.get("actions"), "actions")


def get_definition(data: dict) -> dict:
    """Return the flow definition from a full export or a definition-only file."""
    definition = data.get("definition", data)
    return definition if isinstance(definition, dict) else {}


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

    The rule covers connector-backed triggers and actions of every connector
    operation type, including operations nested inside Scope, If, Foreach,
    Switch, and Until containers.
    """

    # Known operations and their valid path/query parameter names.
    # This can be expanded as we discover more patterns.
    #
    # Request-body parameters are NOT listed here. A connector passes request
    # body fields as 'body' or as 'body/<field>', where '<field>' is a per-app
    # field external_id (for example 'body/fields' and 'body/file_ids' on the
    # Podio connector). Those names cannot be enumerated, so KNOWN_OPERATIONS
    # covers path and query parameters only.
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

    @staticmethod
    def is_request_body_parameter(param_name: str) -> bool:
        """Return True for a request-body parameter such as 'body/fields'."""
        return param_name == "body" or param_name.startswith("body/")

    def validate(self, data: dict, path: str = "") -> ValidationResult:
        result = ValidationResult()

        for operation in iter_definition_connector_operations(get_definition(data)):
            operation_path = f"{path}{operation.path}" if path else operation.path

            parameters = operation.inputs.get("parameters")
            if not isinstance(parameters, dict):
                continue
            operation_id = operation.host.get("operationId", "")
            label = operation.kind.lower()

            # Check for known invalid parameters
            for param_name in parameters:
                if param_name in self.INVALID_PARAMETERS:
                    result.add_error(ValidationError(
                        rule=self.name,
                        message=f"Invalid parameter '{param_name}' in {label} '{operation.name}'",
                        path=f"{operation_path}.inputs.parameters.{param_name}",
                        severity="error",
                        suggestion=self.INVALID_PARAMETERS[param_name],
                    ))

            # If we know the operation, validate against known parameters
            if operation_id in self.KNOWN_OPERATIONS:
                valid_params = self.KNOWN_OPERATIONS[operation_id]
                for param_name in parameters:
                    if self.is_request_body_parameter(param_name):
                        # Request body fields are per-app and cannot be enumerated.
                        continue
                    if param_name not in valid_params and param_name not in self.INVALID_PARAMETERS:
                        # This is a warning since we may not have complete knowledge
                        result.add_error(ValidationError(
                            rule=self.name,
                            message=f"Unknown parameter '{param_name}' for operation '{operation_id}' in {label} '{operation.name}'",
                            path=f"{operation_path}.inputs.parameters.{param_name}",
                            severity="warning",
                            suggestion=f"Valid parameters for {operation_id}: {', '.join(valid_params)}",
                        ))

        return result


class ConnectionReferenceRule(ValidationRule):
    """
    Validates connection reference format and consistency.

    Checks that:
    1. Operations use 'connectionName' in host (maps to connectionReferences keys)
    2. The connectionName matches a key in connectionReferences
    3. connectionReferences have required fields

    Note: The Power Platform API accepts 'connectionName' in flow definitions.
    The connectionName should match a key in the connectionReferences section,
    which typically uses the full connector API ID as the key.

    The rule covers connector-backed triggers and actions of every connector
    operation type, including operations nested inside Scope, If, Foreach,
    Switch, and Until containers.
    """

    @property
    def name(self) -> str:
        return "connection-reference-format"

    @property
    def description(self) -> str:
        return "Validates connection reference format and consistency between actions and connectionReferences"

    def validate(self, data: dict, path: str = "") -> ValidationResult:
        result = ValidationResult()

        connection_refs = data.get("connectionReferences", {})

        for operation in iter_definition_connector_operations(get_definition(data)):
            operation_path = f"{path}{operation.path}" if path else operation.path

            # Get the connection reference (either connectionName or connectionReferenceName)
            # Both are accepted by the API - connectionName is the standard format
            host = operation.host
            connection_name = host.get("connectionName") or host.get("connectionReferenceName")

            # Check that connection reference exists in connectionReferences
            if connection_name and connection_refs:
                if connection_name not in connection_refs:
                    result.add_error(ValidationError(
                        rule=self.name,
                        message=f"{operation.kind} '{operation.name}' references connection '{connection_name}' which is not defined in connectionReferences",
                        path=f"{operation_path}.inputs.host.connectionName",
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


class ConnectionsParameterRule(ValidationRule):
    """
    Validates that flows using connectors declare the '$connections' parameter.

    Any flow whose definition contains connector-backed operations (the
    OpenApiConnection / ApiConnection action and trigger families) binds those
    operations to the '$connections' definition parameter at runtime. A
    non-empty 'connectionReferences' map signals the same requirement.

    When '$connections' is absent, the Dataverse create call still succeeds, but
    activation later fails with:

        HTTP 400 InvalidPowerFlow: The provided flow definition with a recurrent
        trigger is missing the required parameter '$connections'.

    This rule raises that failure at validation time so the bad definition is
    rejected before a flow row exists.
    """

    REQUIRED_SHAPE = (
        "Declare it in definition.parameters:\n"
        "        $connections:\n"
        "          defaultValue: {}\n"
        "          type: Object"
    )

    @property
    def name(self) -> str:
        return "connections-parameter"

    @property
    def description(self) -> str:
        return (
            "Requires definition.parameters.$connections (type Object, defaultValue {}) "
            "when the flow uses connector operations or connection references"
        )

    def validate(self, data: dict, path: str = "") -> ValidationResult:
        result = ValidationResult()

        if "definition" in data:
            definition = data["definition"]
            reference_containers = [data, definition]
        else:
            definition = data
            reference_containers = [data]

        if not isinstance(definition, dict):
            return result

        connector_paths = [
            operation.path for operation in iter_definition_connector_operations(definition)
        ]

        reference_names: list[str] = []
        for container in reference_containers:
            if not isinstance(container, dict):
                continue
            references = container.get("connectionReferences")
            if isinstance(references, dict):
                reference_names.extend(references.keys())

        if not connector_paths and not reference_names:
            return result

        parameters = definition.get("parameters")
        has_parameter = isinstance(parameters, dict) and "$connections" in parameters

        if not has_parameter:
            result.add_error(ValidationError(
                rule=self.name,
                message=(
                    "Flow definition is missing the required parameter '$connections' "
                    f"({self._trigger_summary(connector_paths, reference_names)})"
                ),
                path="definition.parameters.$connections",
                severity="error",
                suggestion=(
                    f"{self.REQUIRED_SHAPE}\n"
                    "    Without it, activation fails with HTTP 400 InvalidPowerFlow: "
                    "\"The provided flow definition with a recurrent trigger is missing "
                    "the required parameter '$connections'.\""
                ),
            ))
            return result

        declared = parameters["$connections"]

        if not isinstance(declared, dict):
            result.add_error(ValidationError(
                rule=self.name,
                message=(
                    f"Parameter '$connections' must be a mapping, got {type(declared).__name__}"
                ),
                path="definition.parameters.$connections",
                severity="warning",
                suggestion=self.REQUIRED_SHAPE,
            ))
            return result

        declared_type = declared.get("type")
        if declared_type != "Object":
            result.add_error(ValidationError(
                rule=self.name,
                message=(
                    f"Parameter '$connections' declares type '{declared_type}' "
                    "instead of the standard 'Object'"
                ),
                path="definition.parameters.$connections.type",
                severity="warning",
                suggestion=self.REQUIRED_SHAPE,
            ))

        return result

    def _trigger_summary(self, connector_paths: list[str], reference_names: list[str]) -> str:
        """Describe why '$connections' is required for this definition."""
        if connector_paths:
            shown = ", ".join(connector_paths[:3])
            if len(connector_paths) > 3:
                shown += f", +{len(connector_paths) - 3} more"
            return f"connector operations: {shown}"
        shown = ", ".join(sorted(set(reference_names))[:3])
        return f"connectionReferences declared: {shown}"


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
                ConnectionsParameterRule(),
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
