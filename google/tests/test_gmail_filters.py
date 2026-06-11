import json

from typer.testing import CliRunner

from google_cli.commands import gmail as gmail_commands
from google_cli.main import app


class FakeExecute:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class FakeFiltersResource:
    def __init__(self, list_payload=None, get_payload=None, create_payload=None):
        self.list_payload = list_payload
        self.get_payload = get_payload
        self.create_payload = create_payload
        self.list_calls = []
        self.get_calls = []
        self.create_calls = []
        self.delete_calls = []

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        return FakeExecute(self.list_payload)

    def get(self, **kwargs):
        self.get_calls.append(kwargs)
        return FakeExecute(self.get_payload)

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return FakeExecute(self.create_payload)

    def delete(self, **kwargs):
        self.delete_calls.append(kwargs)
        return FakeExecute({})


class FakeGmailService:
    def __init__(self, filters_resource):
        self.filters_resource = filters_resource

    def users(self):
        return self

    def settings(self):
        return self

    def filters(self):
        return self.filters_resource


class FakeClient:
    def __init__(self, service):
        self.service = service

    def get_gmail_service(self):
        return self.service


FILTER_RESOURCE = {
    "id": "ANe1Bmj_filter1",
    "criteria": {"from": "news@example.com", "subject": "Digest"},
    "action": {"addLabelIds": ["Label_1"], "removeLabelIds": ["INBOX"]},
}


def _patch_client(monkeypatch, filters_resource):
    service = FakeGmailService(filters_resource)
    monkeypatch.setattr(
        gmail_commands, "get_client", lambda profile=None: FakeClient(service)
    )
    return filters_resource


def test_gmail_filters_list_outputs_flattened_records(monkeypatch):
    resource = _patch_client(
        monkeypatch, FakeFiltersResource(list_payload={"filter": [FILTER_RESOURCE]})
    )

    result = CliRunner().invoke(app, ["gmail", "filters", "list"])

    assert result.exit_code == 0
    records = json.loads(result.stdout)
    assert records == [
        {
            "id": "ANe1Bmj_filter1",
            "from": "news@example.com",
            "to": None,
            "subject": "Digest",
            "query": None,
            "negated_query": None,
            "has_attachment": None,
            "exclude_chats": None,
            "size": None,
            "size_comparison": None,
            "add_label_ids": ["Label_1"],
            "remove_label_ids": ["INBOX"],
            "forward": None,
        }
    ]
    assert resource.list_calls == [{"userId": "me"}]


def test_gmail_filters_list_supports_filter_limit_properties(monkeypatch):
    other = {
        "id": "ANe1Bmj_filter2",
        "criteria": {"from": "boss@example.com"},
        "action": {"removeLabelIds": ["UNREAD"]},
    }
    _patch_client(
        monkeypatch,
        FakeFiltersResource(list_payload={"filter": [FILTER_RESOURCE, other]}),
    )

    result = CliRunner().invoke(
        app,
        [
            "gmail", "filters", "list",
            "--filter", "from:contains:news",
            "--limit", "1",
            "--properties", "id",
            "--properties", "from",
        ],
    )

    assert result.exit_code == 0
    records = json.loads(result.stdout)
    assert records == [{"id": "ANe1Bmj_filter1", "from": "news@example.com"}]


def test_gmail_filters_get_outputs_raw_resource(monkeypatch):
    resource = _patch_client(
        monkeypatch, FakeFiltersResource(get_payload=FILTER_RESOURCE)
    )

    result = CliRunner().invoke(app, ["gmail", "filters", "get", "ANe1Bmj_filter1"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == FILTER_RESOURCE
    assert resource.get_calls == [{"userId": "me", "id": "ANe1Bmj_filter1"}]


def test_gmail_filters_create_sends_criteria_and_action(monkeypatch):
    resource = _patch_client(
        monkeypatch, FakeFiltersResource(create_payload=FILTER_RESOURCE)
    )

    result = CliRunner().invoke(
        app,
        [
            "gmail", "filters", "create",
            "--from", "news@example.com",
            "--subject", "Digest",
            "--add-label", "Label_1",
            "--remove-label", "INBOX",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == FILTER_RESOURCE
    assert resource.create_calls == [
        {
            "userId": "me",
            "body": {
                "criteria": {"from": "news@example.com", "subject": "Digest"},
                "action": {"addLabelIds": ["Label_1"], "removeLabelIds": ["INBOX"]},
            },
        }
    ]


def test_gmail_filters_create_requires_criteria(monkeypatch):
    _patch_client(monkeypatch, FakeFiltersResource())

    result = CliRunner().invoke(
        app, ["gmail", "filters", "create", "--add-label", "Label_1"]
    )

    assert result.exit_code == 1


def test_gmail_filters_create_requires_action(monkeypatch):
    _patch_client(monkeypatch, FakeFiltersResource())

    result = CliRunner().invoke(
        app, ["gmail", "filters", "create", "--from", "news@example.com"]
    )

    assert result.exit_code == 1


def test_gmail_filters_delete_with_confirm_flag(monkeypatch):
    resource = _patch_client(monkeypatch, FakeFiltersResource())

    result = CliRunner().invoke(
        app, ["gmail", "filters", "delete", "ANe1Bmj_filter1", "--confirm"]
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "filter_id": "ANe1Bmj_filter1",
        "deleted": True,
    }
    assert resource.delete_calls == [{"userId": "me", "id": "ANe1Bmj_filter1"}]
