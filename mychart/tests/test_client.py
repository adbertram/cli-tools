import pytest

from mychart_cli.client import ClientError, MychartClient, filters_to_search_params


class FakeConfig:
    base_url = "https://fhir.example.test/api/FHIR/R4"
    access_token = "access-token"
    refresh_token = "refresh-token"
    token_expires_at = "4102444800"
    client_id = "client-id"
    patient_id = "patient-123"
    OAUTH_TOKEN_URL = "https://fhir.example.test/oauth2/token"
    OAUTH_TOKEN_AUTH = "none"
    OAUTH_REDIRECT_URI = "http://localhost"
    CREDENTIAL_TYPES = []

    def __init__(self, storage_dir):
        self.storage_dir = storage_dir

    def has_credentials(self):
        return True

    def get_missing_credentials(self):
        return []


class FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = str(payload)
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._payload


def test_metadata_uses_fhir_headers_and_epic_client_id(monkeypatch, tmp_path):
    captured = {}

    def fake_request(method, url, **kwargs):
        captured.update({"method": method, "url": url, **kwargs})
        return FakeResponse({"resourceType": "CapabilityStatement"})

    monkeypatch.setattr("mychart_cli.client.requests.request", fake_request)

    client = MychartClient(config=FakeConfig(tmp_path), require_auth=False)
    payload = client.get_metadata()

    assert payload["resourceType"] == "CapabilityStatement"
    assert captured["method"] == "GET"
    assert captured["url"] == "https://fhir.example.test/api/FHIR/R4/metadata"
    assert captured["headers"]["Accept"] == "application/fhir+json"
    assert captured["headers"]["Epic-Client-ID"] == "client-id"
    assert captured["headers"]["Authorization"] == "Bearer access-token"


def test_filters_translate_to_fhir_search_parameters():
    assert filters_to_search_params(
        [
            "status:eq:final",
            "date:gte:2026-01-01",
            "code:in:123|456",
        ]
    ) == {
        "status": "final",
        "date": "ge2026-01-01",
        "code": "123,456",
    }


def test_filters_reject_client_side_only_operators():
    with pytest.raises(ClientError, match="FHIR server-side filtering"):
        filters_to_search_params(["status:ilike:%final%"])


def test_list_resource_sends_patient_limit_and_filters(monkeypatch, tmp_path):
    captured = {}

    def fake_request(method, url, **kwargs):
        captured.update({"method": method, "url": url, **kwargs})
        return FakeResponse(
            {
                "resourceType": "Bundle",
                "entry": [
                    {
                        "resource": {
                            "resourceType": "Observation",
                            "id": "obs-1",
                            "status": "final",
                            "valueString": "Positive",
                        }
                    }
                ],
            }
        )

    monkeypatch.setattr("mychart_cli.client.requests.request", fake_request)

    client = MychartClient(config=FakeConfig(tmp_path))
    rows = client.list_resource(
        "Observation",
        patient_id="patient-456",
        limit=5,
        filters=["status:eq:final", "date:gte:2026-01-01"],
    )

    assert rows == [
        {
            "resourceType": "Observation",
            "id": "obs-1",
            "status": "final",
            "valueString": "Positive",
        }
    ]
    assert captured["url"] == "https://fhir.example.test/api/FHIR/R4/Observation"
    assert captured["params"] == {
        "_count": 5,
        "patient": "patient-456",
        "status": "final",
        "date": "ge2026-01-01",
    }


def test_list_resource_enforces_limit_when_server_returns_extra_entries(monkeypatch, tmp_path):
    def fake_request(method, url, **kwargs):
        return FakeResponse(
            {
                "resourceType": "Bundle",
                "entry": [
                    {"resource": {"resourceType": "Patient", "id": "patient-1"}},
                    {"resource": {"resourceType": "Patient", "id": "patient-2"}},
                ],
            }
        )

    monkeypatch.setattr("mychart_cli.client.requests.request", fake_request)

    client = MychartClient(config=FakeConfig(tmp_path))
    rows = client.list_resource("Patient", limit=1)

    assert rows == [{"resourceType": "Patient", "id": "patient-1"}]


def test_get_patient_requires_patient_context(tmp_path):
    class NoPatientConfig(FakeConfig):
        patient_id = None

    client = MychartClient(config=NoPatientConfig(tmp_path))

    with pytest.raises(ClientError, match="No patient ID"):
        client.get_patient()
