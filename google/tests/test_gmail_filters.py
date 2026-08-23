import base64
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


class FakeMessagesResource:
    def __init__(self, list_payload=None, get_payloads=None, send_payload=None):
        self.list_payload = list_payload
        self.get_payloads = get_payloads or {}
        self.send_payload = send_payload or {"id": "sent-msg-1"}
        self.list_calls = []
        self.get_calls = []
        self.modify_calls = []
        self.send_calls = []

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        return FakeExecute(self.list_payload)

    def get(self, **kwargs):
        self.get_calls.append(kwargs)
        return FakeExecute(self.get_payloads[kwargs["id"]])

    def modify(self, **kwargs):
        self.modify_calls.append(kwargs)
        return FakeExecute({"id": kwargs["id"]})

    def send(self, **kwargs):
        self.send_calls.append(kwargs)
        return FakeExecute(self.send_payload)


class FakeDraftsResource:
    def __init__(self, get_payload=None, send_payload=None):
        self.get_payload = get_payload
        self.send_payload = send_payload or {"id": "sent-draft-1", "threadId": "thread-1"}
        self.get_calls = []
        self.send_calls = []

    def get(self, **kwargs):
        self.get_calls.append(kwargs)
        return FakeExecute(self.get_payload)

    def send(self, **kwargs):
        self.send_calls.append(kwargs)
        return FakeExecute(self.send_payload)


class FakeLabelsResource:
    def __init__(self, list_payload=None):
        self.list_payload = list_payload
        self.list_calls = []

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        return FakeExecute(self.list_payload)


class FakeGmailService:
    def __init__(
        self,
        filters_resource=None,
        messages_resource=None,
        labels_resource=None,
        drafts_resource=None,
    ):
        self.filters_resource = filters_resource
        self.messages_resource = messages_resource
        self.labels_resource = labels_resource
        self.drafts_resource = drafts_resource

    def users(self):
        return self

    def settings(self):
        return self

    def filters(self):
        return self.filters_resource

    def messages(self):
        return self.messages_resource

    def drafts(self):
        return self.drafts_resource

    def labels(self):
        return self.labels_resource

    def getProfile(self, **kwargs):
        return FakeExecute({"emailAddress": "adam@example.com"})


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


def _patch_message_client(monkeypatch, messages_resource):
    service = FakeGmailService(messages_resource=messages_resource)
    monkeypatch.setattr(
        gmail_commands, "get_client", lambda profile=None: FakeClient(service)
    )
    return messages_resource


def _patch_labels_client(monkeypatch, messages_resource, labels_resource):
    service = FakeGmailService(
        messages_resource=messages_resource,
        labels_resource=labels_resource,
    )
    monkeypatch.setattr(
        gmail_commands, "get_client", lambda profile=None: FakeClient(service)
    )
    return messages_resource, labels_resource


def _patch_drafts_client(monkeypatch, drafts_resource):
    service = FakeGmailService(drafts_resource=drafts_resource)
    monkeypatch.setattr(
        gmail_commands, "get_client", lambda profile=None: FakeClient(service)
    )
    return drafts_resource


def _encoded_body(text):
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


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


def test_gmail_labels_list_supports_comma_separated_properties(monkeypatch):
    messages_resource = FakeMessagesResource(
        get_payloads={"msg-1": {"id": "msg-1", "labelIds": ["INBOX", "Label_1"]}}
    )
    labels_resource = FakeLabelsResource(
        list_payload={
            "labels": [
                {"id": "INBOX", "name": "Inbox"},
                {"id": "Label_1", "name": "Client"},
            ]
        }
    )
    _patch_labels_client(monkeypatch, messages_resource, labels_resource)

    result = CliRunner().invoke(
        app,
        ["gmail", "labels", "list", "msg-1", "--properties", "id,name"],
    )

    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == {
        "message_id": "msg-1",
        "labels": [
            {"id": "INBOX", "name": "Inbox"},
            {"id": "Label_1", "name": "Client"},
        ],
    }
    assert messages_resource.get_calls == [
        {"userId": "me", "id": "msg-1", "format": "minimal"}
    ]
    assert labels_resource.list_calls == [{"userId": "me"}]


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


def test_gmail_trash_adds_trash_label_to_messages(monkeypatch):
    resource = _patch_message_client(monkeypatch, FakeMessagesResource())

    result = CliRunner().invoke(app, ["gmail", "trash", "msg-1", "msg-2"])

    assert result.exit_code == 0, result.stderr
    assert resource.modify_calls == [
        {
            "userId": "me",
            "id": "msg-1",
            "body": {"addLabelIds": ["TRASH"]},
        },
        {
            "userId": "me",
            "id": "msg-2",
            "body": {"addLabelIds": ["TRASH"]},
        },
    ]


def test_gmail_search_outputs_empty_json_array_for_no_results(monkeypatch):
    resource = _patch_message_client(
        monkeypatch, FakeMessagesResource(list_payload={})
    )

    result = CliRunner().invoke(
        app,
        ["gmail", "search", "in:inbox subject:missing", "--limit", "20"],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == []
    assert resource.list_calls == [
        {"userId": "me", "q": "in:inbox subject:missing", "maxResults": 20}
    ]
    assert resource.get_calls == []


def test_gmail_search_supports_comma_separated_properties(monkeypatch):
    message = {
        "id": "msg-1",
        "threadId": "thread-1",
        "labelIds": ["INBOX"],
        "payload": {
            "headers": [
                {"name": "From", "value": "alerts@example.com"},
                {"name": "Subject", "value": "Balance Alert"},
                {"name": "Date", "value": "Fri, 12 Jun 2026 10:00:00 -0500"},
            ]
        },
    }
    resource = _patch_message_client(
        monkeypatch,
        FakeMessagesResource(
            list_payload={"messages": [{"id": "msg-1"}]},
            get_payloads={"msg-1": message},
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "gmail",
            "search",
            "subject:Balance Alert",
            "--properties",
            "id,from,subject,labelIds",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [
        {
            "id": "msg-1",
            "from": "alerts@example.com",
            "subject": "Balance Alert",
            "labelIds": ["INBOX"],
        }
    ]
    assert resource.get_calls == [
        {"userId": "me", "id": "msg-1", "format": "full"}
    ]


def test_gmail_send_confirm_sends_from_noninteractive_session(monkeypatch):
    resource = _patch_message_client(monkeypatch, FakeMessagesResource())

    result = CliRunner().invoke(
        app,
        [
            "gmail",
            "send",
            "--to",
            "user@example.com",
            "--subject",
            "Hello",
            "--body",
            "Message body",
            "--confirm",
        ],
    )

    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == {
        "id": "sent-msg-1",
        "to": "user@example.com",
        "subject": "Hello",
        "attachments": [],
        "status": "sent",
    }
    assert len(resource.send_calls) == 1
    assert resource.send_calls[0]["userId"] == "me"


def test_gmail_send_draft_confirm_sends_from_noninteractive_session(monkeypatch):
    draft = {
        "id": "draft-1",
        "message": {
            "id": "msg-1",
            "payload": {
                "headers": [
                    {"name": "To", "value": "user@example.com"},
                    {"name": "Subject", "value": "Draft subject"},
                ]
            },
        },
    }
    resource = _patch_drafts_client(monkeypatch, FakeDraftsResource(get_payload=draft))

    result = CliRunner().invoke(app, ["gmail", "send-draft", "draft-1", "--confirm"])

    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == {
        "id": "sent-draft-1",
        "thread_id": "thread-1",
        "draft_id": "draft-1",
        "to": "user@example.com",
        "subject": "Draft subject",
        "status": "sent",
    }
    assert resource.send_calls == [{"userId": "me", "body": {"id": "draft-1"}}]


def test_gmail_draft_get_uses_drafts_api_and_decodes_body(monkeypatch):
    draft = {
        "id": "draft-1",
        "message": {
            "id": "msg-1",
            "threadId": "thread-1",
            "labelIds": ["DRAFT"],
            "payload": {
                "headers": [
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "To", "value": "user@example.com"},
                    {"name": "Subject", "value": "Draft subject"},
                    {"name": "Date", "value": "Fri, 3 Jul 2026 09:48:33 -0700"},
                ],
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {"data": _encoded_body("Draft body")},
                    }
                ],
            },
        },
    }
    resource = _patch_drafts_client(monkeypatch, FakeDraftsResource(get_payload=draft))

    result = CliRunner().invoke(
        app, ["gmail", "draft-get", "draft-1", "--include-body"]
    )

    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == {
        "draft_id": "draft-1",
        "message_id": "msg-1",
        "threadId": "thread-1",
        "labelIds": ["DRAFT"],
        "from": "sender@example.com",
        "to": "user@example.com",
        "subject": "Draft subject",
        "date": "Fri, 3 Jul 2026 09:48:33 -0700",
        "body": "Draft body",
    }
    assert resource.get_calls == [{"userId": "me", "id": "draft-1", "format": "full"}]


def test_gmail_reply_confirm_sends_from_noninteractive_session(monkeypatch):
    message = {
        "id": "msg-1",
        "threadId": "thread-1",
        "payload": {
            "headers": [
                {"name": "From", "value": "sender@example.com"},
                {"name": "Subject", "value": "Question"},
                {"name": "Message-ID", "value": "<msg-1@example.com>"},
            ]
        },
    }
    resource = _patch_message_client(
        monkeypatch,
        FakeMessagesResource(get_payloads={"msg-1": message}),
    )

    result = CliRunner().invoke(
        app, ["gmail", "reply", "msg-1", "--body", "Reply body", "--confirm"]
    )

    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == {
        "id": "sent-msg-1",
        "to": "sender@example.com",
        "subject": "Re: Question",
        "thread_id": "thread-1",
        "attachments": [],
        "status": "sent",
    }
    assert len(resource.send_calls) == 1
    assert resource.send_calls[0]["userId"] == "me"
    assert resource.send_calls[0]["body"]["threadId"] == "thread-1"


def test_gmail_reply_all_confirm_sends_from_noninteractive_session(monkeypatch):
    message = {
        "id": "msg-1",
        "threadId": "thread-1",
        "payload": {
            "headers": [
                {"name": "From", "value": "sender@example.com"},
                {"name": "To", "value": "adam@example.com, teammate@example.com"},
                {"name": "Cc", "value": "manager@example.com"},
                {"name": "Subject", "value": "Question"},
                {"name": "Message-ID", "value": "<msg-1@example.com>"},
            ]
        },
    }
    resource = _patch_message_client(
        monkeypatch,
        FakeMessagesResource(get_payloads={"msg-1": message}),
    )

    result = CliRunner().invoke(
        app, ["gmail", "reply-all", "msg-1", "--body", "Reply body", "--confirm"]
    )

    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == {
        "id": "sent-msg-1",
        "to": "sender@example.com, teammate@example.com",
        "cc": "manager@example.com",
        "subject": "Re: Question",
        "thread_id": "thread-1",
        "attachments": [],
        "status": "sent",
    }
    assert len(resource.send_calls) == 1
    assert resource.send_calls[0]["userId"] == "me"
    assert resource.send_calls[0]["body"]["threadId"] == "thread-1"


def test_gmail_search_rejects_invalid_properties(monkeypatch):
    _patch_message_client(
        monkeypatch,
        FakeMessagesResource(list_payload={"messages": [{"id": "msg-1"}]}),
    )

    result = CliRunner().invoke(
        app,
        ["gmail", "search", "subject:Balance", "--properties", "sender"],
    )

    assert result.exit_code == 1
    assert "Unsupported Gmail message properties: sender" in result.stderr


def test_gmail_list_include_body_adds_decoded_body(monkeypatch):
    message = {
        "id": "msg-1",
        "threadId": "thread-1",
        "labelIds": ["INBOX"],
        "payload": {
            "headers": [
                {"name": "From", "value": "alerts@example.com"},
                {"name": "Subject", "value": "Balance Alert"},
                {"name": "Date", "value": "Fri, 12 Jun 2026 10:00:00 -0500"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": _encoded_body("Full inbox body")},
                }
            ],
        },
    }
    resource = _patch_message_client(
        monkeypatch,
        FakeMessagesResource(
            list_payload={"messages": [{"id": "msg-1"}]},
            get_payloads={"msg-1": message},
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "gmail",
            "list",
            "--label",
            "INBOX",
            "--limit",
            "1",
            "--properties",
            "id,subject",
            "--include-body",
        ],
    )

    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == [
        {
            "id": "msg-1",
            "subject": "Balance Alert",
            "body": "Full inbox body",
        }
    ]
    assert resource.list_calls == [
        {"userId": "me", "maxResults": 1, "labelIds": ["INBOX"]}
    ]
    assert resource.get_calls == [
        {"userId": "me", "id": "msg-1", "format": "full"}
    ]


def test_gmail_list_name_property_aliases_subject(monkeypatch):
    message = {
        "id": "msg-1",
        "threadId": "thread-1",
        "labelIds": ["INBOX"],
        "payload": {
            "headers": [
                {"name": "From", "value": "alerts@example.com"},
                {"name": "Subject", "value": "Balance Alert"},
                {"name": "Date", "value": "Fri, 12 Jun 2026 10:00:00 -0500"},
            ],
        },
    }
    _patch_message_client(
        monkeypatch,
        FakeMessagesResource(
            list_payload={"messages": [{"id": "msg-1"}]},
            get_payloads={"msg-1": message},
        ),
    )

    result = CliRunner().invoke(
        app,
        ["gmail", "list", "--limit", "1", "--properties", "id,name"],
    )

    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == [{"id": "msg-1", "name": "Balance Alert"}]


def test_gmail_get_include_body_outputs_decoded_body(monkeypatch):
    message = {
        "id": "msg-1",
        "threadId": "thread-1",
        "labelIds": ["INBOX"],
        "payload": {
            "headers": [
                {"name": "From", "value": "alerts@example.com"},
                {"name": "To", "value": "adam@example.com"},
                {"name": "Subject", "value": "Balance Alert"},
                {"name": "Date", "value": "Fri, 12 Jun 2026 10:00:00 -0500"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": _encoded_body("Single message body")},
                }
            ],
        },
    }
    resource = _patch_message_client(
        monkeypatch,
        FakeMessagesResource(get_payloads={"msg-1": message}),
    )

    result = CliRunner().invoke(
        app,
        ["gmail", "get", "msg-1", "--include-body"],
    )

    assert result.exit_code == 0, result.stderr
    record = json.loads(result.stdout)
    assert record["body"] == "Single message body"
    assert resource.get_calls == [
        {"userId": "me", "id": "msg-1", "format": "full"}
    ]


def test_gmail_get_returns_headers_when_names_are_lowercase(monkeypatch):
    message = {
        "id": "sent-msg-1",
        "threadId": "thread-1",
        "labelIds": ["SENT"],
        "payload": {
            "headers": [
                {"name": "From", "value": "adam@example.com"},
                {"name": "to", "value": "recipient@example.com"},
                {"name": "subject", "value": "Sent message subject"},
                {"name": "Date", "value": "Tue, 28 Jul 2026 10:00:00 -0500"},
            ],
        },
    }
    _patch_message_client(
        monkeypatch,
        FakeMessagesResource(get_payloads={"sent-msg-1": message}),
    )

    result = CliRunner().invoke(
        app,
        ["gmail", "get", "sent-msg-1"],
    )

    assert result.exit_code == 0, result.stderr
    record = json.loads(result.stdout)
    assert record["to"] == "recipient@example.com"
    assert record["subject"] == "Sent message subject"
