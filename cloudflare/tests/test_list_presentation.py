"""Shared discovery presentation and preflight contracts."""
import inspect
from unittest.mock import Mock

import pytest

from cloudflare_cli.client import CloudflareClient
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import FilterValidationError


@pytest.mark.parametrize("method,args,label", [
    ("list_account_tokens", ("account",), "Token"),
    ("list_account_token_permissions", ("account",), "Permission"),
    ("list_queues", ("account",), "Queue"),
    ("list_queue_consumers", ("account", "queue"), "Consumer"),
])
def test_should_reject_invalid_list_queries_before_transport(method, args, label):
    client = CloudflareClient.__new__(CloudflareClient)
    client._envelope = Mock()
    operation = getattr(client, method)
    with pytest.raises(ClientError, match=f"{label} limit must be zero \\(all\\) or positive"):
        operation(*args, limit=-1)
    with pytest.raises(FilterValidationError):
        operation(*args, filters=["not-a-filter"])
    client._envelope.assert_not_called()
    assert inspect.signature(operation).parameters["limit"].default == 100


@pytest.mark.parametrize("value,properties,columns,expected", [
    ([{"id": "one", "name": "Name", "extra": 3}], None, ("id", "name"), [{"id": "one", "name": "Name", "extra": 3}]),
    ({"id": "one", "name": "Name"}, "name", ("id", "name"), {"name": "Name"}),
    ([{"id": "one"}], "name,id", ("id", "name"), [{"name": None, "id": "one"}]),
    ([], None, ("queue_id", "queue_name"), []),
])
def test_should_preserve_record_shape_and_projection(monkeypatch, value, properties, columns, expected):
    from cloudflare_cli import presentation
    output = Mock()
    monkeypatch.setattr(presentation, "print_output", output)
    presentation.print_records(value, True, properties, columns)
    expected_columns = properties.split(",") if properties else list(columns)
    output.assert_called_once_with(expected, table=True, columns=expected_columns, headers=expected_columns)


@pytest.mark.parametrize("properties,columns,expected", [
    ("id,, name, ", ["id", "name"], [{"id": "one", "name": "Name"}]),
    (", ,", ["id", "name"], [{"id": "one", "name": "Name", "extra": 3}]),
    ("   ", ["id", "name"], [{"id": "one", "name": "Name", "extra": 3}]),
])
def test_should_normalize_blank_properties_for_data_and_columns(monkeypatch, properties, columns, expected):
    from cloudflare_cli import presentation
    output = Mock()
    monkeypatch.setattr(presentation, "print_output", output)
    presentation.print_records([{"id": "one", "name": "Name", "extra": 3}], True, properties)
    output.assert_called_once_with(expected, table=True, columns=columns, headers=columns)
