"""Swagger ``$ref`` parameter resolution for connector operations.

Regression cover for ``connections <id> operations invoke`` exiting with a bare
``Error: 'name'``. Connector swaggers express shared parameters as local JSON
pointers such as ``{"$ref": "#/parameters/DynamicApprovalType"}``; reading
``param["name"]`` on those raised a raw ``KeyError``.
"""
import pytest

from copilot_cli.client import ClientError, DataverseClient, resolve_swagger_parameters
from copilot_cli.commands.connections_operations import _extract_operations_from_swagger

# Shape taken verbatim from the live shared_approvals connector swagger.
APPROVALS_SWAGGER = {
    "host": "example.azure-apim.net",
    "basePath": "/apim/approvals",
    "parameters": {
        "DynamicApprovalType": {
            "name": "approvalType",
            "x-ms-summary": "Approval type",
            "description": "Select an approval type.",
            "in": "path",
            "required": True,
            "type": "string",
        }
    },
    "paths": {
        "/{connectionId}/types/{approvalType}": {
            "post": {
                "operationId": "CreateAnApproval",
                "summary": "Create an approval",
                "parameters": [
                    {
                        "name": "connectionId",
                        "in": "path",
                        "required": True,
                        "type": "string",
                    },
                    {"$ref": "#/parameters/DynamicApprovalType"},
                    {
                        "name": "ApprovalCreationInput",
                        "in": "body",
                        "required": True,
                        "schema": {
                            "type": "object",
                            "x-ms-dynamic-schema": {
                                "operationId": "GetApprovalTypeMetadataV2",
                                "value-path": "schema",
                            },
                        },
                    },
                ],
            }
        }
    },
}


def _operation_parameters(swagger, operation_id="CreateAnApproval"):
    op = swagger["paths"]["/{connectionId}/types/{approvalType}"]["post"]
    return resolve_swagger_parameters(swagger, operation_id, op["parameters"])


def test_ref_parameter_resolves_to_its_shared_definition():
    resolved = _operation_parameters(APPROVALS_SWAGGER)

    assert [p["name"] for p in resolved] == [
        "connectionId",
        "approvalType",
        "ApprovalCreationInput",
    ]
    approval_type = resolved[1]
    assert approval_type["in"] == "path"
    assert approval_type["required"] is True


def test_sibling_keys_override_the_referenced_definition():
    swagger = {
        "parameters": {"Shared": {"name": "shared", "in": "query", "type": "string"}},
    }
    resolved = resolve_swagger_parameters(
        swagger, "Op", [{"$ref": "#/parameters/Shared", "required": True}]
    )

    assert resolved[0]["name"] == "shared"
    assert resolved[0]["required"] is True


def test_unresolvable_ref_raises_an_actionable_error():
    swagger = {"parameters": {"Known": {"name": "known", "in": "query"}}}

    with pytest.raises(ClientError) as excinfo:
        resolve_swagger_parameters(swagger, "CreateAnApproval", [{"$ref": "#/parameters/Missing"}])

    message = str(excinfo.value)
    assert "CreateAnApproval" in message
    assert "#/parameters/Missing" in message
    assert "Known" in message


def test_external_ref_is_rejected_with_the_pointer_named():
    with pytest.raises(ClientError, match="other.json#/parameters/X"):
        resolve_swagger_parameters(
            {}, "CreateAnApproval", [{"$ref": "other.json#/parameters/X"}]
        )


def test_nameless_parameter_reports_operation_and_index():
    with pytest.raises(ClientError) as excinfo:
        resolve_swagger_parameters({}, "CreateAnApproval", [{"in": "query"}])

    message = str(excinfo.value)
    assert "CreateAnApproval" in message
    assert "#0" in message
    assert "no 'name'" in message


def test_operations_listing_shows_the_resolved_parameter():
    operations = _extract_operations_from_swagger(APPROVALS_SWAGGER)

    params = operations[0]["parameters"]
    assert [p["name"] for p in params] == [
        "connectionId",
        "approvalType",
        "ApprovalCreationInput",
    ]
    # Previously this entry rendered as name/in/type all empty.
    assert params[1]["in"] == "path"
    assert params[1]["type"] == "string"
    assert params[2]["type"] == "object"


def test_invoke_substitutes_a_ref_path_parameter_into_the_url(monkeypatch):
    """The resolved approvalType must reach the URL, not the request body."""
    client = DataverseClient("https://example.crm.dynamics.com", "token")
    captured = {}

    class FakeResponse:
        status_code = 202
        headers = {}
        text = "{}"
        is_success = True

        def json(self):
            return {"ok": True}

    def fake_request(method, url, headers=None, timeout=None, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["kwargs"] = kwargs
        return FakeResponse()

    monkeypatch.setattr(client._http_client, "request", fake_request)
    monkeypatch.setattr(
        "copilot_cli.client.get_access_token", lambda resource: "apim-token"
    )

    client.invoke_connector_operation(
        swagger=APPROVALS_SWAGGER,
        connection_id="conn-123",
        operation_id="CreateAnApproval",
        params={"approvalType": "Basic", "title": "Review", "assignedTo": "a@b.com"},
        runtime_url="https://example.azure-apim.net/apim/approvals",
    )

    assert captured["url"].endswith("/conn-123/types/Basic")
    assert captured["kwargs"]["json"] == {"title": "Review", "assignedTo": "a@b.com"}


def test_invoke_reports_a_nameless_parameter_instead_of_raising_keyerror():
    client = DataverseClient("https://example.crm.dynamics.com", "token")
    broken = {
        "paths": {
            "/{connectionId}/x": {
                "post": {
                    "operationId": "Broken",
                    "parameters": [{"in": "", "type": ""}],
                }
            }
        }
    }

    with pytest.raises(ClientError) as excinfo:
        client.invoke_connector_operation(
            swagger=broken,
            connection_id="conn-123",
            operation_id="Broken",
            params={},
            runtime_url="https://example.azure-apim.net/apim/x",
        )

    assert "Broken" in str(excinfo.value)
    assert "no 'name'" in str(excinfo.value)
