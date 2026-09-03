"""Parser behavior for CrowdGen worker responses.

Every assertion here guards the evidence-backed boundary: a provably-empty
response (pre-shortlist dashboard) yields [], and anything else raises instead
of guessing record keys. See crowdgen_cli/parsers.py for the evidence state.
"""

from __future__ import annotations

import pytest
from cli_tools_shared.exceptions import ClientError

from crowdgen_cli.parsers import is_empty_payload, task_rows, unverified_payload_error

ENDPOINT = "projects/available"


def test_none_is_empty():
    assert is_empty_payload(None) is True
    assert task_rows(ENDPOINT, None) == []


def test_empty_list_is_empty():
    assert is_empty_payload([]) is True
    assert task_rows(ENDPOINT, []) == []


def test_empty_object_is_empty():
    assert is_empty_payload({}) is True
    assert task_rows(ENDPOINT, {}) == []


def test_object_of_only_empty_containers_is_empty():
    # Plausible empty-dashboard shapes: {"projects": [], "total": 0} etc.
    for body in ({"projects": []}, {"projects": [], "total": 0}, {"data": [], "count": 0}):
        assert is_empty_payload(body) is True
        assert task_rows(ENDPOINT, body) == []


def test_nonempty_list_is_unverified():
    body = [{"id": "p1", "title": "Some Project"}]
    assert is_empty_payload(body) is False
    with pytest.raises(ClientError, match="non-empty"):
        task_rows(ENDPOINT, body)


def test_nonempty_scalar_value_is_unverified():
    # {"projects": [], "message": "something"} carries a signal => unverified.
    body = {"projects": [], "message": "unexpected"}
    assert is_empty_payload(body) is False
    with pytest.raises(ClientError, match="non-empty"):
        task_rows(ENDPOINT, body)


def test_nonempty_string_is_unverified():
    assert is_empty_payload("oops") is False
    with pytest.raises(ClientError, match="non-empty"):
        task_rows(ENDPOINT, "oops")


def test_unverified_error_names_endpoint_and_guidance():
    err = unverified_payload_error(ENDPOINT, {"x": [1]})
    assert isinstance(err, ClientError)
    assert ENDPOINT in str(err)
    assert "tests/fixtures/" in str(err)
