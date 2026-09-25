"""Tests for record-ID validation against REST-path traversal.

Regression coverage: get_record/update_record/replace_record/delete_record/
upload_attachment used to interpolate record_id straight into the REST path
with no validation or quoting. A record ID crafted as
"recEsJWrnVm4cJs0V/../../Modules/rec1ULrEThKqSVJpa" built a URL that Airtable
normalizes server-side, so it read or wrote a record in a different table
than the one requested. Every method must reject a traversal ID before any
HTTP request is built.
"""
import pytest

from airtable_cli.client import AirtableClient
from cli_tools_shared.exceptions import ClientError

TRAVERSAL_RECORD_ID = "recEsJWrnVm4cJs0V/../../Modules/rec1ULrEThKqSVJpa"


class _RequestShouldNotRun:
    def __call__(self, *args, **kwargs):
        raise AssertionError("no HTTP request must be built for an invalid record ID")


def _client() -> AirtableClient:
    client = AirtableClient.__new__(AirtableClient)
    client.base_url = "https://api.airtable.test/v0"
    client.headers = {"Authorization": "Bearer test"}
    client._make_request = _RequestShouldNotRun()
    return client


@pytest.mark.parametrize(
    "method_name, extra_args",
    [
        ("get_record", ()),
        ("update_record", ({"Name": "x"},)),
        ("replace_record", ({"Name": "x"},)),
        ("delete_record", ()),
    ],
)
def test_traversal_record_id_rejected_before_request(method_name, extra_args):
    client = _client()
    method = getattr(client, method_name)

    with pytest.raises(ClientError, match="Invalid record ID"):
        method("appBase", "Courses", TRAVERSAL_RECORD_ID, *extra_args)


def test_traversal_record_id_rejected_by_upload_attachment(tmp_path):
    client = _client()
    file_path = tmp_path / "photo.png"
    file_path.write_bytes(b"fake-bytes")

    with pytest.raises(ClientError, match="Invalid record ID"):
        client.upload_attachment("appBase", TRAVERSAL_RECORD_ID, "Photo", str(file_path))


def test_valid_record_id_builds_expected_endpoint(monkeypatch):
    client = _client()
    captured = {}

    def fake_make_request(method, endpoint, data=None, params=None, retry=True):
        captured["method"] = method
        captured["endpoint"] = endpoint
        return {"id": "recABC123"}

    client._make_request = fake_make_request

    result = client.get_record("appBase", "Courses", "recABC123")

    assert result == {"id": "recABC123"}
    assert captured["endpoint"] == "/appBase/Courses/recABC123"
