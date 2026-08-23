import json

from googleapiclient.errors import HttpError
from typer.testing import CliRunner

from google_cli.commands import contacts as contacts_commands
from google_cli.main import app


class FakeExecute:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        if isinstance(self.payload, BaseException):
            raise self.payload
        return self.payload


class FakeConnectionsResource:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.list_calls = []

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        return FakeExecute(self.payloads.pop(0))


class FakePeopleResource:
    def __init__(self, connections_resource, get_payload=None):
        self.connections_resource = connections_resource
        self.get_payload = get_payload
        self.get_calls = []

    def connections(self):
        return self.connections_resource

    def get(self, **kwargs):
        self.get_calls.append(kwargs)
        return FakeExecute(self.get_payload)


class FakePeopleService:
    def __init__(self, people_resource):
        self.people_resource = people_resource

    def people(self):
        return self.people_resource


class FakeClient:
    def __init__(self, service):
        self.service = service

    def get_people_service(self):
        return self.service


class FakeHttpResponse:
    status = 403
    reason = "Forbidden"

    def get(self, key, default=None):
        if key == "content-type":
            return "application/json"
        return default


PRIMARY_PERSON = {
    "resourceName": "people/c123",
    "names": [{"displayName": "Jane Example", "givenName": "Jane", "familyName": "Example"}],
    "emailAddresses": [
        {"value": "jane@example.com", "metadata": {"primary": True}},
        {"value": "jane.alt@example.com"},
    ],
    "phoneNumbers": [{"value": "812-555-0100"}],
    "organizations": [{"name": "Example Co", "title": "Owner", "metadata": {"primary": True}}],
    "addresses": [{"formattedValue": "123 Main St"}],
    "urls": [{"value": "https://example.com"}],
}


OTHER_PERSON = {
    "resourceName": "people/c456",
    "names": [{"displayName": "Other Person"}],
    "emailAddresses": [{"value": "other@example.com"}],
    "organizations": [{"name": "Other Co"}],
}


def _people_api_disabled_error():
    content = {
        "error": {
            "code": 403,
            "message": "People API has not been used in project 153584548092 before or it is disabled.",
            "status": "PERMISSION_DENIED",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                    "reason": "SERVICE_DISABLED",
                    "domain": "googleapis.com",
                    "metadata": {
                        "service": "people.googleapis.com",
                        "consumer": "projects/153584548092",
                        "activationUrl": (
                            "https://console.developers.google.com/apis/api/"
                            "people.googleapis.com/overview?project=153584548092"
                        ),
                    },
                }
            ],
        }
    }
    return HttpError(FakeHttpResponse(), json.dumps(content).encode("utf-8"))


def _non_json_forbidden_error():
    return HttpError(FakeHttpResponse(), b"<html>Forbidden</html>")


def _patch_people_client(monkeypatch, list_payloads=None, get_payload=None):
    connections_resource = FakeConnectionsResource(list_payloads or [])
    people_resource = FakePeopleResource(connections_resource, get_payload=get_payload)
    service = FakePeopleService(people_resource)
    monkeypatch.setattr(
        contacts_commands, "get_client", lambda profile=None: FakeClient(service)
    )
    return people_resource


def test_contacts_list_outputs_normalized_records(monkeypatch):
    people_resource = _patch_people_client(
        monkeypatch,
        list_payloads=[{"connections": [PRIMARY_PERSON], "nextPageToken": "next"}, {"connections": [OTHER_PERSON]}],
    )

    result = CliRunner().invoke(app, ["contacts", "list", "--limit", "2"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [
        {
            "resourceName": "people/c123",
            "etag": None,
            "displayName": "Jane Example",
            "givenName": "Jane",
            "familyName": "Example",
            "primaryEmail": "jane@example.com",
            "emailAddresses": ["jane@example.com", "jane.alt@example.com"],
            "primaryPhone": "812-555-0100",
            "phoneNumbers": ["812-555-0100"],
            "organization": "Example Co",
            "title": "Owner",
            "organizations": [{"name": "Example Co", "title": "Owner"}],
            "addresses": ["123 Main St"],
            "urls": ["https://example.com"],
        },
        {
            "resourceName": "people/c456",
            "etag": None,
            "displayName": "Other Person",
            "givenName": None,
            "familyName": None,
            "primaryEmail": "other@example.com",
            "emailAddresses": ["other@example.com"],
            "primaryPhone": None,
            "phoneNumbers": [],
            "organization": "Other Co",
            "title": None,
            "organizations": [{"name": "Other Co", "title": None}],
            "addresses": [],
            "urls": [],
        },
    ]
    assert people_resource.connections_resource.list_calls == [
        {
            "resourceName": "people/me",
            "pageSize": 2,
            "personFields": contacts_commands.CONTACT_PERSON_FIELDS,
        },
        {
            "resourceName": "people/me",
            "pageSize": 1,
            "personFields": contacts_commands.CONTACT_PERSON_FIELDS,
            "pageToken": "next",
        },
    ]


def test_contacts_list_supports_filter_limit_properties(monkeypatch):
    _patch_people_client(
        monkeypatch,
        list_payloads=[{"connections": [PRIMARY_PERSON, OTHER_PERSON]}],
    )

    result = CliRunner().invoke(
        app,
        [
            "contacts",
            "list",
            "--filter",
            "organization:contains:Example",
            "--limit",
            "1",
            "--properties",
            "resourceName,displayName,primaryEmail,organization",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [
        {
            "resourceName": "people/c123",
            "displayName": "Jane Example",
            "primaryEmail": "jane@example.com",
            "organization": "Example Co",
        }
    ]


def test_contacts_get_outputs_normalized_record(monkeypatch):
    people_resource = _patch_people_client(monkeypatch, get_payload=PRIMARY_PERSON)

    result = CliRunner().invoke(app, ["contacts", "get", "people/c123"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["primaryEmail"] == "jane@example.com"
    assert people_resource.get_calls == [
        {
            "resourceName": "people/c123",
            "personFields": contacts_commands.CONTACT_PERSON_FIELDS,
        }
    ]


def test_contacts_list_explains_disabled_people_api(monkeypatch):
    _patch_people_client(monkeypatch, list_payloads=[_people_api_disabled_error()])

    result = CliRunner().invoke(app, ["contacts", "list", "--profile", "adbertram"])

    output = result.stderr or result.output
    assert result.exit_code == 1
    assert "Google People API is disabled for Google Cloud project 153584548092." in output
    assert (
        "google cloud services enable people.googleapis.com "
        "--project 153584548092 --profile adbertram"
    ) in output
    assert (
        "https://console.developers.google.com/apis/api/"
        "people.googleapis.com/overview?project=153584548092"
    ) in output
    assert "HTTP error:" not in output


def test_contacts_get_explains_disabled_people_api(monkeypatch):
    _patch_people_client(monkeypatch, get_payload=_people_api_disabled_error())

    result = CliRunner().invoke(app, ["contacts", "get", "people/c123"])

    output = result.stderr or result.output
    assert result.exit_code == 1
    assert "Google People API is disabled for Google Cloud project 153584548092." in output
    assert (
        "google cloud services enable people.googleapis.com --project 153584548092"
    ) in output
    assert "--profile" not in output
    assert "HTTP error:" not in output


def test_contacts_list_keeps_generic_http_error_for_unstructured_403(monkeypatch):
    _patch_people_client(monkeypatch, list_payloads=[_non_json_forbidden_error()])

    result = CliRunner().invoke(app, ["contacts", "list"])

    output = result.stderr or result.output
    assert result.exit_code == 1
    assert "HTTP error:" in output
    assert "Google People API is disabled" not in output
