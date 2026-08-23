from airtable_cli.client import AirtableClient


def _make_client_without_init() -> AirtableClient:
    """Build an AirtableClient without running __init__ (no real credentials)."""
    return AirtableClient.__new__(AirtableClient)


def test_list_bases_follows_offset_across_pages():
    client = _make_client_without_init()

    pages = {
        None: {
            "bases": [
                {"id": "app1", "name": "One", "permissionLevel": "create"},
                {"id": "app2", "name": "Two", "permissionLevel": "edit"},
            ],
            "offset": "page2token",
        },
        "page2token": {
            "bases": [
                {"id": "app3", "name": "Three", "permissionLevel": "read"},
            ]
        },
    }

    calls = []

    def fake_make_request(method, endpoint, params=None):
        calls.append((method, endpoint, params))
        offset = params.get("offset") if params else None
        return pages[offset]

    client._make_request = fake_make_request

    result = client.list_bases()

    assert [b["id"] for b in result] == ["app1", "app2", "app3"]
    # First call has no offset; second call carries the offset token.
    assert calls == [
        ("GET", "/meta/bases", None),
        ("GET", "/meta/bases", {"offset": "page2token"}),
    ]


def test_list_bases_single_page_when_no_offset():
    client = _make_client_without_init()

    def fake_make_request(method, endpoint, params=None):
        assert params is None
        return {
            "bases": [
                {"id": "app1", "name": "One", "permissionLevel": "create"},
            ]
        }

    client._make_request = fake_make_request

    result = client.list_bases()

    assert [b["id"] for b in result] == ["app1"]
