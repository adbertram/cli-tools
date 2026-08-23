"""Tests for the shared connector-operation walk used by the flow rules.

`ConnectionReferenceRule` and `UndefinedParameterRule` used to inspect only
top-level `definition.actions` entries whose type was exactly
"OpenApiConnection". Real Power Automate exports break both assumptions:

- Connector actions nest inside Scope, If, Foreach, Switch, and Until containers.
- Power Automate uses six connector operation types, not one.
- Connector-backed triggers bind to a connection too.

Live exports from the PSDXAutomation environment contain 261 connector
operations. Only 64 of them matched the old top-level "OpenApiConnection"
check, so 197 operations were never validated. These tests lock the widened
walk into both rules.
"""
import copy

import pytest
import yaml
from typer.testing import CliRunner

from copilot_cli.commands import agent_flow
from copilot_cli.validation import (
    CONNECTOR_OPERATION_TYPES,
    ConnectionReferenceRule,
    FlowYAMLValidator,
    UndefinedParameterRule,
    get_definition,
    iter_definition_connector_operations,
)

CONNECTION_RULE = "connection-reference-format"
PARAMETER_RULE = "undefined-parameter"

DEFINED_CONNECTION = "shared_podio"
UNDEFINED_CONNECTION = "shared_missing"

CONNECTION_REFERENCES = {
    DEFINED_CONNECTION: {
        "api": {"name": DEFINED_CONNECTION},
        "connection": {"connectionReferenceLogicalName": "cr_podio"},
        "runtimeSource": "embedded",
    }
}


def connector_action(
    *,
    action_type: str = "OpenApiConnection",
    connection: str = UNDEFINED_CONNECTION,
    operation_id: str = "UpdateItem",
    parameters: dict | None = None,
) -> dict:
    """Build a connector-backed operation node."""
    return {
        "type": action_type,
        "inputs": {
            "parameters": copy.deepcopy(parameters) if parameters else {"item_id": 1},
            "host": {
                "apiId": f"/providers/Microsoft.PowerApps/apis/{connection}",
                "connectionName": connection,
                "operationId": operation_id,
            },
        },
        "runAfter": {},
    }


def make_flow(*, actions: dict, triggers: dict | None = None, references: bool = True) -> dict:
    """Build a full flow payload with the '$connections' parameter declared."""
    data = {
        "definition": {
            "$schema": (
                "https://schema.management.azure.com/providers/Microsoft.Logic/"
                "schemas/2016-06-01/workflowdefinition.json#"
            ),
            "contentVersion": "1.0.0.0",
            "parameters": {"$connections": {"defaultValue": {}, "type": "Object"}},
            "triggers": copy.deepcopy(triggers)
            if triggers
            else {
                "manual": {
                    "type": "Request",
                    "kind": "Http",
                    "inputs": {"schema": {"type": "object", "properties": {}}},
                }
            },
            "actions": copy.deepcopy(actions),
            "outputs": {},
        }
    }
    if references:
        data["connectionReferences"] = copy.deepcopy(CONNECTION_REFERENCES)
    return data


def scope(inner: dict) -> dict:
    return {"type": "Scope", "actions": copy.deepcopy(inner), "runAfter": {}}


def if_else(inner: dict) -> dict:
    return {
        "type": "If",
        "expression": "@equals(1, 1)",
        "actions": {"Noop": {"type": "Compose", "inputs": "ok", "runAfter": {}}},
        "else": {"actions": copy.deepcopy(inner)},
        "runAfter": {},
    }


def foreach(inner: dict) -> dict:
    return {
        "type": "Foreach",
        "foreach": "@triggerBody()?['items']",
        "actions": copy.deepcopy(inner),
        "runAfter": {},
    }


def until(inner: dict) -> dict:
    return {
        "type": "Until",
        "expression": "@equals(1, 1)",
        "limit": {"count": 2, "timeout": "PT1M"},
        "actions": copy.deepcopy(inner),
        "runAfter": {},
    }


def switch_case(inner: dict) -> dict:
    return {
        "type": "Switch",
        "expression": "@triggerBody()?['kind']",
        "cases": {"Case_A": {"case": "a", "actions": copy.deepcopy(inner)}},
        "default": {"actions": {}},
        "runAfter": {},
    }


def switch_default(inner: dict) -> dict:
    return {
        "type": "Switch",
        "expression": "@triggerBody()?['kind']",
        "cases": {"Case_A": {"case": "a", "actions": {}}},
        "default": {"actions": copy.deepcopy(inner)},
        "runAfter": {},
    }


CONTAINERS = {
    "scope": scope,
    "if-else": if_else,
    "foreach": foreach,
    "until": until,
    "switch-case": switch_case,
    "switch-default": switch_default,
}


def rule_findings(rule, data: dict) -> tuple[list, list]:
    """Return the (errors, warnings) a single rule raises for a payload."""
    result = rule.validate(data)
    return result.errors, result.warnings


# ---------------------------------------------------------------------------
# Shared walker
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("operation_type", sorted(CONNECTOR_OPERATION_TYPES))
def test_walk_matches_every_connector_type_case_insensitively(operation_type):
    """All six connector operation types are recognised, whatever the casing."""
    data = make_flow(actions={"Call": connector_action(action_type=operation_type)})

    operations = list(iter_definition_connector_operations(get_definition(data)))

    assert [operation.name for operation in operations] == ["Call"]
    assert operations[0].path == "actions.Call"


@pytest.mark.parametrize("container_name", sorted(CONTAINERS))
def test_walk_descends_into_every_container_type(container_name):
    """Scope, If/else, Foreach, Until, and both Switch branches are walked."""
    build = CONTAINERS[container_name]
    data = make_flow(actions={"Container": build({"Call": connector_action()})})

    operations = list(iter_definition_connector_operations(get_definition(data)))

    assert [operation.name for operation in operations] == ["Call"]
    assert operations[0].path.startswith("actions.Container.")
    assert operations[0].path.endswith(".Call")


def test_walk_reports_the_full_nested_path():
    """The reported path names every container between the root and the leaf."""
    data = make_flow(
        actions={"Outer": if_else({"Inner": scope({"Call": connector_action()})})}
    )

    operations = list(iter_definition_connector_operations(get_definition(data)))

    assert operations[0].path == "actions.Outer.else.actions.Inner.actions.Call"


def test_walk_covers_connector_triggers():
    """A connector-backed trigger is yielded and labelled as a trigger."""
    data = make_flow(
        actions={"Noop": {"type": "Compose", "inputs": "ok", "runAfter": {}}},
        triggers={
            "When_a_new_email_arrives": connector_action(
                action_type="OpenApiConnectionNotification",
                operation_id="OnNewEmailV3",
            )
        },
    )

    operations = list(iter_definition_connector_operations(get_definition(data)))

    assert len(operations) == 1
    assert operations[0].path == "triggers.When_a_new_email_arrives"
    assert operations[0].kind == "Trigger"


def test_walk_labels_actions_as_actions():
    data = make_flow(actions={"Call": connector_action()})

    operations = list(iter_definition_connector_operations(get_definition(data)))

    assert operations[0].kind == "Action"


def test_walk_skips_non_connector_and_malformed_nodes():
    """Compose actions, string nodes, and missing inputs never yield results."""
    data = make_flow(
        actions={
            "Compose": {"type": "Compose", "inputs": "ok", "runAfter": {}},
            "Response": {"type": "Response", "kind": "PowerApp", "runAfter": {}},
            "NotAMapping": "oops",
            "NoType": {"inputs": {}, "runAfter": {}},
        }
    )

    assert list(iter_definition_connector_operations(get_definition(data))) == []


def test_walk_tolerates_missing_inputs_and_host():
    """Accessors return empty mappings instead of raising on partial nodes."""
    data = make_flow(actions={"Call": {"type": "OpenApiConnection", "runAfter": {}}})

    operation = next(iter_definition_connector_operations(get_definition(data)))

    assert operation.inputs == {}
    assert operation.host == {}


def test_walk_handles_definition_only_payloads():
    """A definition-only file is walked the same way as a full export."""
    data = make_flow(actions={"Call": connector_action()})

    operations = list(iter_definition_connector_operations(get_definition(data["definition"])))

    assert [operation.path for operation in operations] == ["actions.Call"]


# ---------------------------------------------------------------------------
# ConnectionReferenceRule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("operation_type", sorted(CONNECTOR_OPERATION_TYPES))
def test_connection_rule_checks_every_connector_type(operation_type):
    """An undefined connection is an error for every connector type."""
    data = make_flow(actions={"Call": connector_action(action_type=operation_type)})

    errors, _ = rule_findings(ConnectionReferenceRule(), data)

    assert len(errors) == 1
    assert errors[0].path == "actions.Call.inputs.host.connectionName"
    assert UNDEFINED_CONNECTION in errors[0].message


@pytest.mark.parametrize("container_name", sorted(CONTAINERS))
def test_connection_rule_checks_nested_operations(container_name):
    """An undefined connection nested in any container is still an error."""
    build = CONTAINERS[container_name]
    data = make_flow(actions={"Container": build({"Call": connector_action()})})

    errors, _ = rule_findings(ConnectionReferenceRule(), data)

    assert len(errors) == 1
    assert errors[0].path.startswith("actions.Container.")
    assert errors[0].path.endswith("Call.inputs.host.connectionName")


def test_connection_rule_reports_the_deep_nested_path():
    data = make_flow(
        actions={"Outer": if_else({"Inner": scope({"Call": connector_action()})})}
    )

    errors, _ = rule_findings(ConnectionReferenceRule(), data)

    assert errors[0].path == (
        "actions.Outer.else.actions.Inner.actions.Call.inputs.host.connectionName"
    )


def test_connection_rule_checks_connector_triggers():
    """A connector trigger with an undefined connection is an error."""
    data = make_flow(
        actions={"Noop": {"type": "Compose", "inputs": "ok", "runAfter": {}}},
        triggers={
            "When_a_new_email_arrives": connector_action(
                action_type="OpenApiConnectionNotification",
                operation_id="OnNewEmailV3",
            )
        },
    )

    errors, _ = rule_findings(ConnectionReferenceRule(), data)

    assert len(errors) == 1
    assert errors[0].path == (
        "triggers.When_a_new_email_arrives.inputs.host.connectionName"
    )
    assert errors[0].message.startswith("Trigger 'When_a_new_email_arrives'")


def test_connection_rule_message_names_actions_as_actions():
    data = make_flow(actions={"Call": connector_action()})

    errors, _ = rule_findings(ConnectionReferenceRule(), data)

    assert errors[0].message.startswith("Action 'Call'")


def test_connection_rule_accepts_a_defined_nested_connection():
    """A nested operation pointing at a declared reference produces no error."""
    data = make_flow(
        actions={"Container": foreach({"Call": connector_action(connection=DEFINED_CONNECTION)})}
    )

    errors, warnings = rule_findings(ConnectionReferenceRule(), data)

    assert errors == []
    assert warnings == []


def test_connection_rule_accepts_connection_reference_name_on_nested_operations():
    """The 'connectionReferenceName' host key is accepted like 'connectionName'."""
    action = connector_action(action_type="OpenApiConnectionWebhook")
    action["inputs"]["host"] = {
        "apiId": f"/providers/Microsoft.PowerApps/apis/{DEFINED_CONNECTION}",
        "connectionReferenceName": DEFINED_CONNECTION,
        "operationId": "StartAndWaitForAnApproval",
    }
    data = make_flow(actions={"Container": scope({"Approve": action})})

    errors, _ = rule_findings(ConnectionReferenceRule(), data)

    assert errors == []


def test_connection_rule_reports_every_nested_offender():
    """Multiple bad references in different branches are all reported."""
    data = make_flow(
        actions={
            "Branch": if_else({"First": connector_action()}),
            "Loop": foreach({"Second": connector_action()}),
        }
    )

    errors, _ = rule_findings(ConnectionReferenceRule(), data)

    assert len(errors) == 2
    assert {error.path.split(".")[-4] for error in errors} == {"First", "Second"}


# ---------------------------------------------------------------------------
# UndefinedParameterRule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("container_name", sorted(CONTAINERS))
def test_parameter_rule_finds_invalid_parameters_in_nested_operations(container_name):
    """The banned 'fields' parameter is an error at any nesting depth."""
    build = CONTAINERS[container_name]
    action = connector_action(
        connection=DEFINED_CONNECTION,
        operation_id="CreateItem",
        parameters={"app_id": 1, "fields": {"title": "x"}},
    )
    data = make_flow(actions={"Container": build({"Call": action})})

    errors, _ = rule_findings(UndefinedParameterRule(), data)

    assert len(errors) == 1
    assert errors[0].path.endswith("Call.inputs.parameters.fields")
    assert "Invalid parameter 'fields'" in errors[0].message


@pytest.mark.parametrize("operation_type", sorted(CONNECTOR_OPERATION_TYPES))
def test_parameter_rule_checks_every_connector_type(operation_type):
    action = connector_action(
        action_type=operation_type,
        connection=DEFINED_CONNECTION,
        operation_id="CreateItem",
        parameters={"fields": {"title": "x"}},
    )
    data = make_flow(actions={"Call": action})

    errors, _ = rule_findings(UndefinedParameterRule(), data)

    assert len(errors) == 1
    assert errors[0].path == "actions.Call.inputs.parameters.fields"


def test_parameter_rule_checks_connector_triggers():
    """A connector trigger's parameters are inspected too."""
    trigger = connector_action(
        action_type="OpenApiConnectionNotification",
        connection=DEFINED_CONNECTION,
        operation_id="GetItem",
        parameters={"fields": {"title": "x"}},
    )
    data = make_flow(
        actions={"Noop": {"type": "Compose", "inputs": "ok", "runAfter": {}}},
        triggers={"On_New_Item": trigger},
    )

    errors, _ = rule_findings(UndefinedParameterRule(), data)

    assert len(errors) == 1
    assert errors[0].path == "triggers.On_New_Item.inputs.parameters.fields"
    assert "in trigger 'On_New_Item'" in errors[0].message


def test_parameter_rule_warns_about_unknown_parameters_when_nested():
    """An unknown path/query parameter on a known operation stays a warning."""
    action = connector_action(
        connection=DEFINED_CONNECTION,
        operation_id="GetItem",
        parameters={"item_id": 1, "bogus_option": True},
    )
    data = make_flow(actions={"Container": scope({"Call": action})})

    errors, warnings = rule_findings(UndefinedParameterRule(), data)

    assert errors == []
    assert len(warnings) == 1
    assert warnings[0].path == (
        "actions.Container.actions.Call.inputs.parameters.bogus_option"
    )
    assert "Unknown parameter 'bogus_option'" in warnings[0].message


@pytest.mark.parametrize(
    "param_name",
    ["body", "body/fields", "body/file_ids", "body/title"],
)
def test_parameter_rule_ignores_request_body_parameters(param_name):
    """Connector request-body fields are per-app and must not be flagged.

    Every live PSDXAutomation Podio action passes field values this way. The
    widened walk would otherwise turn 5 spurious warnings into 56.
    """
    action = connector_action(
        connection=DEFINED_CONNECTION,
        operation_id="UpdateItem",
        parameters={"item_id": 1, param_name: {"title": "x"}},
    )
    data = make_flow(actions={"Container": foreach({"Call": action})})

    errors, warnings = rule_findings(UndefinedParameterRule(), data)

    assert errors == []
    assert warnings == []


def test_parameter_rule_still_flags_the_bare_fields_parameter():
    """'body/fields' is valid, but a bare 'fields' remains an error."""
    action = connector_action(
        connection=DEFINED_CONNECTION,
        operation_id="UpdateItem",
        parameters={"item_id": 1, "body/fields": {"a": 1}, "fields": {"b": 2}},
    )
    data = make_flow(actions={"Call": action})

    errors, warnings = rule_findings(UndefinedParameterRule(), data)

    assert len(errors) == 1
    assert errors[0].path == "actions.Call.inputs.parameters.fields"
    assert warnings == []


def test_parameter_rule_skips_operations_without_a_parameters_mapping():
    action = connector_action(connection=DEFINED_CONNECTION)
    action["inputs"]["parameters"] = "not-a-mapping"
    data = make_flow(actions={"Call": action})

    errors, warnings = rule_findings(UndefinedParameterRule(), data)

    assert errors == []
    assert warnings == []


# ---------------------------------------------------------------------------
# Command-surface coverage
# ---------------------------------------------------------------------------


def nested_bad_flow() -> dict:
    """A flow whose only fault is a nested undefined connection reference."""
    return make_flow(actions={"Container": if_else({"Call": connector_action()})})


def nested_good_flow() -> dict:
    """The same shape with the connection reference declared."""
    return make_flow(
        actions={
            "Container": if_else({"Call": connector_action(connection=DEFINED_CONNECTION)})
        }
    )


def write_flow(tmp_path, name: str, data: dict):
    path = tmp_path / name
    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
    return path


def test_validate_command_fails_on_a_nested_bad_connection(tmp_path):
    path = write_flow(tmp_path, "bad.yaml", nested_bad_flow())

    result = CliRunner().invoke(agent_flow.app, ["validate", str(path)])

    assert result.exit_code == 1
    assert CONNECTION_RULE in result.output
    assert "Validation FAILED." in result.output


def test_validate_command_passes_on_a_nested_good_connection(tmp_path):
    path = write_flow(tmp_path, "good.yaml", nested_good_flow())

    result = CliRunner().invoke(agent_flow.app, ["validate", str(path)])

    assert result.exit_code == 0
    assert "Validation PASSED." in result.output


def test_create_is_rejected_before_any_dataverse_call(tmp_path, monkeypatch):
    path = write_flow(tmp_path, "bad.yaml", nested_bad_flow())

    def fail_if_called(*args, **kwargs):
        raise AssertionError("get_client must not be reached for an invalid definition")

    monkeypatch.setattr(agent_flow, "get_client", fail_if_called)

    result = CliRunner().invoke(
        agent_flow.app,
        ["create", "--name", "Should Not Be Created", "--file", str(path), "--include-connections"],
    )

    assert result.exit_code == 1
    assert CONNECTION_RULE in result.output
    assert "Validation failed" in result.output


def test_import_is_rejected_before_any_dataverse_call(tmp_path, monkeypatch):
    path = write_flow(tmp_path, "bad.yaml", nested_bad_flow())

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
    assert CONNECTION_RULE in result.output
    assert "Validation failed with errors." in result.output


def test_both_rules_remain_registered_in_the_default_rule_set():
    validator = FlowYAMLValidator()

    descriptions = validator.get_rule_descriptions()
    assert CONNECTION_RULE in descriptions
    assert PARAMETER_RULE in descriptions
