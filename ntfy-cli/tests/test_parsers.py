import pytest

from ntfy_cli_cli.client import ClientError
from ntfy_cli_cli.parsers import parse_ndjson, parse_publish


def test_parse_publish_requires_object():
    assert parse_publish('{"id":"abc","topic":"topic"}')["id"] == "abc"
    with pytest.raises(ClientError, match="not an object"):
        parse_publish("[]")


def test_parse_ndjson_requires_objects():
    assert parse_ndjson('{"id":"one"}\n{"id":"two"}\n') == [{"id": "one"}, {"id": "two"}]
    with pytest.raises(ClientError, match="malformed"):
        parse_ndjson("not json\n")
    with pytest.raises(ClientError, match="non-object"):
        parse_ndjson("[]\n")
