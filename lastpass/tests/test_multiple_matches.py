"""Synthetic tests for LastPass ambiguous-match (multiple matches) handling.

lpass prints "Multiple matches found." plus a candidate list to STDOUT (exit 0)
when a name/ID lookup is ambiguous. The wrapper must turn that prose into a
structured MultipleMatchesError so callers get parseable data, while leaving the
single-match value/parse paths untouched.
"""
import subprocess

import pytest

from lastpass_cli.client import (
    LastpassClient,
    MultipleMatchesError,
    MULTIPLE_MATCHES_SENTINEL,
)


MULTI_MATCH_OUTPUT = "\n".join(
    [
        MULTIPLE_MATCHES_SENTINEL,
        "Email/google.com [id: 8969039733861907751]",
        "google.com [id: 7600439653866760487]",
        "google.com [id: 8602805921737405963]",
    ]
)


def _client_with_show_output(output: str, expected_args=None) -> LastpassClient:
    client = LastpassClient.__new__(LastpassClient)

    def fake_run_command(args, **kwargs):
        if expected_args is not None:
            assert args == expected_args
        return subprocess.CompletedProcess(args, 0, output, "")

    client._run_command = fake_run_command
    return client


def test_get_username_raises_structured_error_on_multiple_matches():
    client = _client_with_show_output(
        MULTI_MATCH_OUTPUT, ["show", "--username", "google.com"]
    )

    with pytest.raises(MultipleMatchesError) as excinfo:
        client.get_username("google.com")

    error = excinfo.value
    assert error.query == "google.com"
    ids = [match["id"] for match in error.matches]
    assert ids == [
        "8969039733861907751",
        "7600439653866760487",
        "8602805921737405963",
    ]
    # Candidate records carry the structured fields a caller needs to pick one.
    assert error.matches[0]["name"] == "google.com"
    assert error.matches[0]["group"] == "Email"
    assert error.matches[0]["full_path"] == "Email/google.com"


def test_get_password_raises_structured_error_on_multiple_matches():
    client = _client_with_show_output(
        MULTI_MATCH_OUTPUT, ["show", "--password", "google.com"]
    )

    with pytest.raises(MultipleMatchesError) as excinfo:
        client.get_password("google.com")

    assert len(excinfo.value.matches) == 3


def test_get_item_raises_structured_error_on_multiple_matches():
    client = _client_with_show_output(MULTI_MATCH_OUTPUT, ["show", "google.com"])

    with pytest.raises(MultipleMatchesError) as excinfo:
        client.get_item("google.com")

    assert excinfo.value.query == "google.com"
    assert len(excinfo.value.matches) == 3


def test_single_match_username_returns_raw_value_unchanged():
    client = _client_with_show_output(
        "user@example.com", ["show", "--username", "7600439653866760487"]
    )

    assert client.get_username("7600439653866760487") == "user@example.com"


def test_single_match_password_returns_raw_value_unchanged():
    client = _client_with_show_output(
        "s3cr3t-value", ["show", "--password", "7600439653866760487"]
    )

    assert client.get_password("7600439653866760487") == "s3cr3t-value"


def test_value_starting_like_sentinel_without_candidates_is_not_treated_as_ambiguous():
    # A real value whose first line coincidentally equals the sentinel but has
    # no "[id: ...]" candidate lines must NOT be misread as ambiguous.
    client = _client_with_show_output(
        MULTIPLE_MATCHES_SENTINEL, ["show", "--username", "weird-entry"]
    )

    assert client.get_username("weird-entry") == MULTIPLE_MATCHES_SENTINEL
