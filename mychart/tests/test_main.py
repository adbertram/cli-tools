import json

from typer.testing import CliRunner

from mychart_cli import main
from mychart_cli.main import app


runner = CliRunner()


class FakeClient:
    def get_metadata(self):
        return {
            "resourceType": "CapabilityStatement",
            "status": "active",
            "fhirVersion": "4.0.1",
        }

    def list_resource_types(self, limit=100):
        return [
            {"type": "Patient", "profile": "", "search_params": ["_id", "identifier"]},
            {"type": "Observation", "profile": "", "search_params": ["patient", "code"]},
        ][:limit]

    def get_resource_type(self, resource_type):
        return {"type": resource_type, "search_params": ["patient", "status"]}

    def list_resource(self, resource_type, patient_id=None, limit=100, filters=None):
        self.list_call = {
            "resource_type": resource_type,
            "patient_id": patient_id,
            "limit": limit,
            "filters": filters,
        }
        return [
            {
                "resourceType": resource_type,
                "id": "obs-1",
                "status": "final",
                "code": {"text": "Hemoglobin"},
            }
        ]

    def get_resource(self, resource_type, resource_id):
        return {"resourceType": resource_type, "id": resource_id, "status": "final"}

    def get_patient(self, patient_id=None):
        return {"resourceType": "Patient", "id": patient_id or "patient-123"}

    def list_sandbox_test_patients(self, limit=100):
        return [{"id": "sandbox-patient-1", "name": "Sandbox Patient"}][:limit]

    def get_sandbox_test_patient(self, patient_id):
        return {"id": patient_id, "name": "Sandbox Patient"}

    def get_summary(self, patient_id=None, resource_types=None, limit_per_resource=10):
        return {
            "patient_id": patient_id or "patient-123",
            "resources": {
                "Observation": [
                    {"resourceType": "Observation", "id": "obs-1", "status": "final"}
                ]
            },
        }


def test_metadata_get_returns_capability_statement(monkeypatch):
    monkeypatch.setattr(main, "get_client", lambda require_auth=False: FakeClient())

    result = runner.invoke(app, ["metadata", "get"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["resourceType"] == "CapabilityStatement"


def test_metadata_list_returns_discoverable_record(monkeypatch):
    monkeypatch.setattr(main, "get_client", lambda require_auth=False: FakeClient())

    result = runner.invoke(app, ["metadata", "list", "--properties", "id,resourceType"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload[0] == {"id": "capability-statement", "resourceType": "CapabilityStatement"}


def test_resources_list_passes_patient_limit_and_filters(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(main, "get_client", lambda require_auth=True: fake)

    result = runner.invoke(
        app,
        [
            "resources",
            "list",
            "Observation",
            "--patient-id",
            "patient-456",
            "--limit",
            "2",
            "--filter",
            "status:eq:final",
        ],
    )

    assert result.exit_code == 0
    assert fake.list_call == {
        "resource_type": "Observation",
        "patient_id": "patient-456",
        "limit": 2,
        "filters": ["status:eq:final"],
    }
    payload = json.loads(result.stdout)
    assert payload[0]["resourceType"] == "Observation"


def test_patient_get_uses_saved_patient_context(monkeypatch):
    class AuthConfig:
        def has_credentials(self):
            return True

    monkeypatch.setattr(main, "get_config", lambda: AuthConfig())
    monkeypatch.setattr(main, "get_client", lambda require_auth=True: FakeClient())

    result = runner.invoke(app, ["patient", "get"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload == {"resourceType": "Patient", "id": "patient-123"}


def test_patient_list_without_auth_returns_sandbox_catalog(monkeypatch):
    class NoAuthConfig:
        def has_credentials(self):
            return False

    monkeypatch.setattr(main, "get_config", lambda: NoAuthConfig())
    monkeypatch.setattr(main, "get_client", lambda require_auth=False: FakeClient())

    result = runner.invoke(app, ["patient", "list", "--limit", "1"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload == [{"id": "sandbox-patient-1", "name": "Sandbox Patient"}]


def test_summary_get_returns_grouped_resources(monkeypatch):
    monkeypatch.setattr(main, "get_client", lambda require_auth=True: FakeClient())

    result = runner.invoke(app, ["summary", "get", "--resource", "Observation"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["patient_id"] == "patient-123"
    assert payload["resources"]["Observation"][0]["id"] == "obs-1"
