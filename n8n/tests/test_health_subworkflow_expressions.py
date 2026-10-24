import pytest

from n8n_cli import health


class WorkflowApi:
    def __init__(self, workflows):
        self.workflows = workflows
        self.requested_ids = []

    def get_workflow(self, workflow_id):
        self.requested_ids.append(workflow_id)
        if workflow_id not in self.workflows:
            raise RuntimeError("Not Found")
        return self.workflows[workflow_id]


def execute_workflow(workflow_id):
    return {
        "nodes": [{
            "id": "refill",
            "name": "Refill Coordinator",
            "type": "n8n-nodes-base.executeWorkflow",
            "parameters": {"workflowId": workflow_id},
        }],
    }


@pytest.mark.parametrize("expression", [
    '={{ "coordinator-id" }}',
    "={{ 'coordinator-id' }}",
])
def test_subworkflow_refs_resolve_constant_expressions_without_requiring_active_target(expression):
    api = WorkflowApi({"coordinator-id": {"id": "coordinator-id", "name": "Coordinator", "active": False}})

    findings = health.check_subworkflow_refs_valid(
        execute_workflow({"__rl": True, "mode": "id", "value": expression}),
        api,
    )

    assert findings == []
    assert api.requested_ids == ["coordinator-id"]


def test_subworkflow_refs_warn_for_dynamic_expression_without_fetching_literal_expression():
    api = WorkflowApi({})

    findings = health.check_subworkflow_refs_valid(
        execute_workflow('={{ $json.workflowId }}'),
        api,
    )

    assert api.requested_ids == []
    assert [(finding.check, finding.severity, finding.message) for finding in findings] == [(
        "subworkflow_refs_valid",
        "warn",
        "dynamic workflowId expression cannot be validated statically",
    )]


def test_subworkflow_refs_still_fail_for_inactive_literal_target():
    api = WorkflowApi({"coordinator-id": {"id": "coordinator-id", "name": "Coordinator", "active": False}})

    findings = health.check_subworkflow_refs_valid(
        execute_workflow({"__rl": True, "mode": "id", "value": "coordinator-id"}),
        api,
    )

    assert api.requested_ids == ["coordinator-id"]
    assert [(finding.severity, finding.message) for finding in findings] == [(
        "fail",
        "referenced workflow 'Coordinator' (id=coordinator-id) is not active",
    )]
