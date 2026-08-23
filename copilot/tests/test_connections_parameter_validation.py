"""Tests for the '$connections' definition-parameter validation rule.

A flow definition that uses connector operations must declare
`definition.parameters.$connections`. Without it the Dataverse create call
succeeds but activation fails with:

    HTTP 400 InvalidPowerFlow: The provided flow definition with a recurrent
    trigger is missing the required parameter '$connections'.

These tests lock the rule into the shared rule set so `agent-flow validate`,
`agent-flow create`, and `agent-flow import` all reject the bad shape.
"""
import copy

import pytest
import yaml
from typer.testing import CliRunner

from copilot_cli.commands import agent_flow
from copilot_cli.validation import (
    ConnectionsParameterRule,
    FlowYAMLValidator,
    validate_agent_flow_yaml,
)

RULE_NAME = "connections-parameter"

CONNECTION_REFERENCES = {
    "shared_approvals": {
        "api": {"name": "shared_approvals"},
        "connection": {"connectionReferenceLogicalName": "cr_approvals"},
        "runtimeSource": "embedded",
    }
}

APPROVAL_ACTION = {
    "type": "OpenApiConnectionWebhook",
    "inputs": {
        "parameters": {
            "approvalType": "Basic",
            "WebhookApprovalCreationInput/title": "Validation request",
            "WebhookApprovalCreationInput/assignedTo": "psdxautomation@progress.com",
        },
        "host": {
            "connectionReferenceName": "shared_approvals",
            "apiId": "/providers/Microsoft.PowerApps/apis/shared_approvals",
            "operationId": "StartAndWaitForAnApproval",
            "connectionName": "shared_approvals",
        },
    },
    "runAfter": {},
}


def make_definition(*, actions: dict, parameters: dict) -> dict:
    """Build a definition-only flow payload."""
    return {
        "$schema": (
            "https://schema.management.azure.com/providers/Microsoft.Logic/"
            "schemas/2016-06-01/workflowdefinition.json#"
        ),
        "contentVersion": "1.0.0.0",
        "parameters": copy.deepcopy(parameters),
        "triggers": {
            "manual": {
                "type": "Request",
                "kind": "Http",
                "inputs": {"schema": {"type": "object", "properties": {}}},
            }
        },
        "actions": copy.deepcopy(actions),
        "outputs": {},
    }


PARAMETERS_WITHOUT_CONNECTIONS = {
    "$authentication": {"defaultValue": {}, "type": "SecureObject"},
}

PARAMETERS_WITH_CONNECTIONS = {
    "$authentication": {"defaultValue": {}, "type": "SecureObject"},
    "$connections": {"defaultValue": {}, "type": "Object"},
}


def connections_errors(data: dict) -> list:
    """Return only the errors raised by the connections-parameter rule."""
    result = FlowYAMLValidator().validate(data)
    return [error for error in result.errors if error.rule == RULE_NAME]


def connections_warnings(data: dict) -> list:
    """Return only the warnings raised by the connections-parameter rule."""
    result = FlowYAMLValidator().validate(data)
    return [warning for warning in result.warnings if warning.rule == RULE_NAME]


def test_missing_connections_with_connector_action_is_an_error():
    """The reproduce case: connector action present, '$connections' absent."""
    data = make_definition(
        actions={"Start_and_wait_for_an_approval": APPROVAL_ACTION},
        parameters=PARAMETERS_WITHOUT_CONNECTIONS,
    )
    data["connectionReferences"] = copy.deepcopy(CONNECTION_REFERENCES)

    errors = connections_errors(data)

    assert len(errors) == 1
    error = errors[0]
    assert error.severity == "error"
    assert error.path == "definition.parameters.$connections"
    assert "$connections" in error.message
    assert "type: Object" in error.suggestion
    assert "defaultValue: {}" in error.suggestion


def test_missing_connections_detected_from_connection_references_only():
    """A non-empty connectionReferences map alone requires '$connections'."""
    data = make_definition(
        actions={"Noop": {"type": "Compose", "inputs": "hello", "runAfter": {}}},
        parameters=PARAMETERS_WITHOUT_CONNECTIONS,
    )
    data["connectionReferences"] = copy.deepcopy(CONNECTION_REFERENCES)

    errors = connections_errors(data)

    assert len(errors) == 1
    assert "connectionReferences declared: shared_approvals" in errors[0].message


def test_missing_connections_detected_inside_nested_containers():
    """Connector actions nested in If/else -> Scope must still be found."""
    nested_actions = {
        "Condition": {
            "type": "If",
            "expression": "@equals(1, 1)",
            "actions": {
                "Auto_Approved": {"type": "Compose", "inputs": "ok", "runAfter": {}}
            },
            "else": {
                "actions": {
                    "Scope_Human_Review": {
                        "type": "Scope",
                        "actions": {
                            "Start_and_wait_for_an_approval": copy.deepcopy(APPROVAL_ACTION)
                        },
                        "runAfter": {},
                    }
                }
            },
            "runAfter": {},
        }
    }
    data = make_definition(
        actions=nested_actions,
        parameters=PARAMETERS_WITHOUT_CONNECTIONS,
    )

    errors = connections_errors(data)

    assert len(errors) == 1
    assert (
        "actions.Condition.else.actions.Scope_Human_Review.actions."
        "Start_and_wait_for_an_approval" in errors[0].message
    )


@pytest.mark.parametrize(
    "container_action",
    [
        {
            "type": "Foreach",
            "foreach": "@triggerBody()?['items']",
            "actions": {"Call_Connector": copy.deepcopy(APPROVAL_ACTION)},
            "runAfter": {},
        },
        {
            "type": "Until",
            "expression": "@equals(1, 1)",
            "limit": {"count": 2, "timeout": "PT1M"},
            "actions": {"Call_Connector": copy.deepcopy(APPROVAL_ACTION)},
            "runAfter": {},
        },
        {
            "type": "Switch",
            "expression": "@triggerBody()?['kind']",
            "cases": {
                "Case_A": {
                    "case": "a",
                    "actions": {"Call_Connector": copy.deepcopy(APPROVAL_ACTION)},
                }
            },
            "default": {"actions": {}},
            "runAfter": {},
        },
        {
            "type": "Switch",
            "expression": "@triggerBody()?['kind']",
            "cases": {"Case_A": {"case": "a", "actions": {}}},
            "default": {"actions": {"Call_Connector": copy.deepcopy(APPROVAL_ACTION)}},
            "runAfter": {},
        },
    ],
    ids=["foreach", "until", "switch-case", "switch-default"],
)
def test_missing_connections_detected_in_every_container_type(container_action):
    """Foreach, Until, Switch cases, and Switch default are all walked."""
    data = make_definition(
        actions={"Container": container_action},
        parameters=PARAMETERS_WITHOUT_CONNECTIONS,
    )

    assert len(connections_errors(data)) == 1


def test_connector_trigger_without_connections_is_an_error():
    """A connector-backed trigger requires '$connections' too."""
    data = make_definition(
        actions={"Noop": {"type": "Compose", "inputs": "hello", "runAfter": {}}},
        parameters=PARAMETERS_WITHOUT_CONNECTIONS,
    )
    data["triggers"] = {
        "When_a_new_email_arrives": {
            "type": "OpenApiConnectionNotification",
            "inputs": {
                "host": {
                    "connectionName": "shared_office365",
                    "operationId": "OnNewEmailV3",
                }
            },
        }
    }

    errors = connections_errors(data)

    assert len(errors) == 1
    assert "triggers.When_a_new_email_arrives" in errors[0].message


def test_declared_connections_parameter_passes():
    """The fixed shape produces no connections-parameter findings."""
    data = make_definition(
        actions={"Start_and_wait_for_an_approval": APPROVAL_ACTION},
        parameters=PARAMETERS_WITH_CONNECTIONS,
    )
    data["connectionReferences"] = copy.deepcopy(CONNECTION_REFERENCES)

    assert connections_errors(data) == []
    assert connections_warnings(data) == []


def test_definition_without_connections_does_not_trigger_the_rule():
    """A flow with no connector operations and no references is untouched."""
    data = make_definition(
        actions={"Noop": {"type": "Compose", "inputs": "hello", "runAfter": {}}},
        parameters=PARAMETERS_WITHOUT_CONNECTIONS,
    )

    assert connections_errors(data) == []
    assert connections_warnings(data) == []


def test_full_export_format_is_validated():
    """The rule reads definition/connectionReferences from full export files."""
    data = {
        "name": "Some Flow",
        "workflowid": "00000000-0000-0000-0000-000000000000",
        "definition": make_definition(
            actions={"Start_and_wait_for_an_approval": APPROVAL_ACTION},
            parameters=PARAMETERS_WITHOUT_CONNECTIONS,
        ),
        "connectionReferences": copy.deepcopy(CONNECTION_REFERENCES),
    }

    assert len(connections_errors(data)) == 1


def test_wrong_connections_type_is_a_warning_not_an_error():
    """A non-Object '$connections' type still activates, so it is a warning."""
    parameters = copy.deepcopy(PARAMETERS_WITH_CONNECTIONS)
    parameters["$connections"]["type"] = "SecureObject"
    data = make_definition(
        actions={"Start_and_wait_for_an_approval": APPROVAL_ACTION},
        parameters=parameters,
    )

    warnings = connections_warnings(data)

    assert connections_errors(data) == []
    assert len(warnings) == 1
    assert warnings[0].path == "definition.parameters.$connections.type"
    assert "SecureObject" in warnings[0].message


def test_non_mapping_connections_parameter_is_a_warning():
    """A scalar '$connections' entry cannot declare a type."""
    parameters = copy.deepcopy(PARAMETERS_WITH_CONNECTIONS)
    parameters["$connections"] = "Object"
    data = make_definition(
        actions={"Start_and_wait_for_an_approval": APPROVAL_ACTION},
        parameters=parameters,
    )

    warnings = connections_warnings(data)

    assert connections_errors(data) == []
    assert len(warnings) == 1
    assert "must be a mapping" in warnings[0].message


def test_rule_is_registered_in_the_default_rule_set():
    """The rule ships in the shared rule set used by validate/create/import."""
    validator = FlowYAMLValidator()

    assert RULE_NAME in validator.get_rule_descriptions()
    assert any(isinstance(rule, ConnectionsParameterRule) for rule in validator.rules)


def test_validate_agent_flow_yaml_reports_the_error():
    """The aggregate entry point surfaces the failure as an ERROR message."""
    data = make_definition(
        actions={"Start_and_wait_for_an_approval": APPROVAL_ACTION},
        parameters=PARAMETERS_WITHOUT_CONNECTIONS,
    )

    is_valid, messages = validate_agent_flow_yaml(data)

    assert is_valid is False
    assert any(f"ERROR [{RULE_NAME}]" in message for message in messages)


# ---------------------------------------------------------------------------
# Command-surface coverage
# ---------------------------------------------------------------------------


def write_flow(tmp_path, name: str, data: dict):
    """Write a flow payload to a YAML file and return its path."""
    path = tmp_path / name
    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
    return path


def bad_flow_payload() -> dict:
    data = make_definition(
        actions={"Start_and_wait_for_an_approval": APPROVAL_ACTION},
        parameters=PARAMETERS_WITHOUT_CONNECTIONS,
    )
    data["connectionReferences"] = copy.deepcopy(CONNECTION_REFERENCES)
    return data


def good_flow_payload() -> dict:
    data = make_definition(
        actions={"Start_and_wait_for_an_approval": APPROVAL_ACTION},
        parameters=PARAMETERS_WITH_CONNECTIONS,
    )
    data["connectionReferences"] = copy.deepcopy(CONNECTION_REFERENCES)
    return data


def test_validate_command_fails_on_missing_connections(tmp_path):
    path = write_flow(tmp_path, "bad.yaml", bad_flow_payload())

    result = CliRunner().invoke(agent_flow.app, ["validate", str(path)])

    assert result.exit_code == 1
    assert RULE_NAME in result.output
    assert "Validation FAILED." in result.output


def test_validate_command_passes_on_declared_connections(tmp_path):
    path = write_flow(tmp_path, "good.yaml", good_flow_payload())

    result = CliRunner().invoke(agent_flow.app, ["validate", str(path)])

    assert result.exit_code == 0
    assert "Validation PASSED." in result.output


def test_list_rules_surfaces_the_rule():
    result = CliRunner().invoke(agent_flow.app, ["validate", "--list-rules"])

    assert result.exit_code == 0
    assert RULE_NAME in result.output


def test_create_is_rejected_before_any_dataverse_call(tmp_path, monkeypatch):
    """create must fail validation before the Dataverse row is created."""
    path = write_flow(tmp_path, "bad.yaml", bad_flow_payload())

    def fail_if_called(*args, **kwargs):
        raise AssertionError("get_client must not be reached for an invalid definition")

    monkeypatch.setattr(agent_flow, "get_client", fail_if_called)

    result = CliRunner().invoke(
        agent_flow.app,
        ["create", "--name", "Should Not Be Created", "--file", str(path), "--include-connections"],
    )

    assert result.exit_code == 1
    assert RULE_NAME in result.output
    assert "Validation failed" in result.output


def test_import_is_rejected_before_any_dataverse_call(tmp_path, monkeypatch):
    """import must fail validation before the Dataverse update is sent."""
    path = write_flow(tmp_path, "bad.yaml", bad_flow_payload())

    def fail_if_called(*args, **kwargs):
        raise AssertionError("get_client must not be reached for an invalid definition")

    monkeypatch.setattr(agent_flow, "get_client", fail_if_called)

    result = CliRunner().invoke(
        agent_flow.app,
        [
            "import",
            "00000000-0000-0000-0000-000000000000",
            "--file",
            str(path),
            "--include-connections",
        ],
    )

    assert result.exit_code == 1
    assert RULE_NAME in result.output
    assert "Validation failed with errors." in result.output
