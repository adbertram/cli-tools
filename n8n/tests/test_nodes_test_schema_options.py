"""Behavior tests for `n8n nodes test` resource/operation schema values.

n8n compares `resource` and `operation` parameter values against the node
schema's option values with exact string equality, so camelCase values such as
`pullRequest` / `findPullRequest` must reach the node unchanged. The command
must therefore transmit the requested values verbatim and must reject a value
the schema does not declare -- including a wrong-case variant -- instead of
rewriting it into a form the schema never declares.

No server contact: every API boundary is a fake, and the SSH-based UI
visibility probe is stubbed out.
"""

import subprocess

import pytest
from typer.testing import CliRunner

import n8n_cli.commands.test as test_module
from n8n_cli import health
from n8n_cli.commands import nodes as nodes_module


NODE_TYPE = "n8n-nodes-issue-manager-github-app.issueManagerGithubApp"
CRED_TYPE = "issueManagerGithubAppApi"
CRED_ID = "PWAVb31Kd2LS9GLJ"
CREDENTIALS = '{"%s":{"id":"%s","name":"Issue Manager GitHub App"}}' % (CRED_TYPE, CRED_ID)

RESOURCE_OPTIONS = ["pullRequest", "issue", "repository"]
OPERATION_OPTIONS = {
    "pullRequest": ["findPullRequest", "createPullRequest", "getPullRequests"],
    "issue": ["createIssue", "getIssues"],
    "repository": ["getRepository"],
}


def _node_schema(node_type=NODE_TYPE, resource_options=None, operation_options=None):
    """A node schema shaped like a generated GitHub App node."""
    resource_options = RESOURCE_OPTIONS if resource_options is None else resource_options
    operation_options = OPERATION_OPTIONS if operation_options is None else operation_options
    properties = [
        {
            "name": "resource",
            "displayName": "Resource",
            "type": "options",
            "required": True,
            "default": resource_options[0],
            "options": [{"name": value, "value": value} for value in resource_options],
        },
    ]
    for resource, operations in operation_options.items():
        properties.append({
            "name": "operation",
            "displayName": "Operation",
            "type": "options",
            "required": True,
            "default": operations[0],
            "displayOptions": {"show": {"resource": [resource]}},
            "options": [{"name": value, "value": value} for value in operations],
        })
    return {
        "name": node_type,
        "displayName": "Issue Manager GitHub App",
        "version": 1,
        "defaultVersion": 1,
        "credentials": [{"name": CRED_TYPE}],
        "properties": properties,
    }


class FakeTestApi:
    """Records the temp workflow `nodes test` builds; talks to nothing."""

    def __init__(self, schema=None):
        self.schema = schema if schema is not None else _node_schema()
        self.created_workflows = []
        self.activated = []
        self.deleted = []

    # -- temp workflow construction
    def resolve_node_type(self, node_name):
        return NODE_TYPE

    def create_workflow(self, name, nodes, connections):
        workflow = {
            "id": f"wf-{len(self.created_workflows) + 1}",
            "name": name,
            "nodes": nodes,
            "connections": connections,
            "active": False,
        }
        self.created_workflows.append(workflow)
        return workflow

    def activate_workflow(self, workflow_id):
        self.activated.append(workflow_id)
        return {}

    def deactivate_workflow(self, workflow_id):
        return {}

    def delete_workflow(self, workflow_id):
        self.deleted.append(workflow_id)
        return {}

    def trigger_webhook(self, webhook_path, data=None):
        return {}

    def get_executions(self, **kwargs):
        return [{"id": 23208, "status": "success", "finished": True}]

    # -- health-check engine boundary
    def get_node_type(self, node_type):
        return self.schema if node_type == NODE_TYPE else None

    def list_credentials(self):
        return [{"id": CRED_ID, "name": "Issue Manager GitHub App", "type": CRED_TYPE}]


def _no_server_ui_issues(*args, **kwargs):
    """The UI-visibility probe shells out over SSH; report 'nothing found'."""
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")


def _invoke_nodes_test(monkeypatch, api, resource, operation, with_params=True):
    """Drive the real `n8n nodes test` boundary with the report's arguments."""
    monkeypatch.setattr(test_module, "get_n8n_api_client", lambda: api)
    monkeypatch.setattr(test_module, "run_on_server_raw", _no_server_ui_issues)
    monkeypatch.setattr(test_module.time, "sleep", lambda seconds: None)
    args = [
        "test",
        "issue-manager-github-app",
        "--resource", resource,
        "--operation", operation,
        "--credentials", CREDENTIALS,
        "--node-type", NODE_TYPE,
        "--timeout", "60",
    ]
    if with_params:
        args += [
            "--params",
            '{"owner":"adbertram","repo":"issue-manager",'
            '"head":"issue-manager-credential-smoke-nonexistent","base":"main"}',
        ]
    return CliRunner().invoke(nodes_module.app, args)


def test_should_transmit_camel_case_resource_and_operation_unchanged(monkeypatch):
    api = FakeTestApi()

    result = _invoke_nodes_test(monkeypatch, api, "pullRequest", "findPullRequest")

    assert result.exit_code == 0, result.output
    assert len(api.created_workflows) == 1
    node_under_test = api.created_workflows[0]["nodes"][1]
    assert node_under_test["parameters"] == {
        "resource": "pullRequest",
        "operation": "findPullRequest",
        "owner": "adbertram",
        "repo": "issue-manager",
        "head": "issue-manager-credential-smoke-nonexistent",
        "base": "main",
    }, "resource and operation schema values must reach the node verbatim"
    assert api.activated == ["wf-1"]


def test_should_keep_lowercase_schema_values_that_the_schema_declares(monkeypatch):
    """A node whose schema declares lowercase values still works unchanged."""
    api = FakeTestApi(schema=_node_schema(
        resource_options=["order", "inventory"],
        operation_options={"order": ["list", "get"], "inventory": ["list"]},
    ))

    result = _invoke_nodes_test(monkeypatch, api, "order", "list", with_params=False)

    assert result.exit_code == 0, result.output
    assert api.created_workflows[0]["nodes"][1]["parameters"] == {
        "resource": "order",
        "operation": "list",
    }


@pytest.mark.parametrize(
    ("resource", "operation"),
    [
        pytest.param("pullrequest", "findPullRequest", id="wrong-case-resource"),
        pytest.param("pullRequest", "findpullrequest", id="wrong-case-operation"),
        pytest.param("pullRequest", "listPullRequests", id="undeclared-operation"),
    ],
)
def test_should_fail_preflight_when_option_value_is_not_declared(monkeypatch, resource, operation):
    api = FakeTestApi()

    result = _invoke_nodes_test(monkeypatch, api, resource, operation, with_params=False)

    assert result.exit_code == 1, result.output
    assert api.activated == [], "an invalid option value must not reach activation"
    assert "option_values_exact" in result.output
    assert "Pre-activation health check failed" in result.output
    params = api.created_workflows[0]["nodes"][1]["parameters"]
    assert (params.get("resource"), params.get("operation")) == (resource, operation)


def _health_workflow(resource, operation):
    return {
        "id": "wf-temp",
        "name": "Test: issue-manager-github-app pullRequest/findPullRequest",
        "nodes": [
            {
                "id": "webhook-trigger",
                "name": "Webhook Trigger",
                "type": "n8n-nodes-base.webhook",
                "typeVersion": 2,
                "parameters": {"path": "test-abc123", "httpMethod": "POST"},
            },
            {
                "id": "node-under-test",
                "name": "Issue-manager-github-app Node",
                "type": NODE_TYPE,
                "typeVersion": 1,
                "parameters": {"resource": resource, "operation": operation},
            },
        ],
        "connections": {
            "Webhook Trigger": {
                "main": [[{"node": "Issue-manager-github-app Node", "type": "main", "index": 0}]]
            }
        },
    }


def _option_findings(workflow, schema=None):
    api = FakeTestApi(schema=schema)
    findings = health.run_health_checks(workflow, api)
    return [f for f in findings if f.check == "option_values_exact"]


def test_health_check_flags_lowercased_resource():
    findings = _option_findings(_health_workflow("pullrequest", "findPullRequest"))

    assert [(f.severity, f.node) for f in findings] == [
        ("fail", "Issue-manager-github-app Node"),
    ]
    assert "parameter 'resource' value 'pullrequest' is not one of the node schema's option values" in findings[0].message
    assert "did you mean 'pullRequest'" in findings[0].message


def test_health_check_flags_lowercased_operation():
    findings = _option_findings(_health_workflow("pullRequest", "findpullrequest"))

    assert [(f.severity, f.node) for f in findings] == [
        ("fail", "Issue-manager-github-app Node"),
    ]
    assert "parameter 'operation' value 'findpullrequest'" in findings[0].message
    assert "did you mean 'findPullRequest'" in findings[0].message


def test_health_check_does_not_guess_operations_for_an_undeclared_resource():
    """With an undeclared resource the operation's own option list is not knowable."""
    findings = _option_findings(_health_workflow("inventory", "findPullRequest"))

    assert [f.message.split(" value ")[0] for f in findings] == ["parameter 'resource'"]


def test_health_check_accepts_exact_option_values():
    assert _option_findings(_health_workflow("pullRequest", "findPullRequest")) == []


def test_health_check_accepts_lowercase_values_when_the_schema_declares_them():
    schema = _node_schema(
        resource_options=["order", "inventory"],
        operation_options={"order": ["list", "get"], "inventory": ["list"]},
    )

    assert _option_findings(_health_workflow("order", "list"), schema=schema) == []


def test_health_check_skips_nodes_without_a_resolvable_schema():
    """An unknown node type is not evidence of a bad option value."""
    workflow = _health_workflow("pullrequest", "findpullrequest")
    api = FakeTestApi()
    api.get_node_type = lambda node_type: None

    findings = [
        f for f in health.run_health_checks(workflow, api)
        if f.check == "option_values_exact"
    ]

    assert findings == []
