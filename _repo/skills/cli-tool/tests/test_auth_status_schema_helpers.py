"""Unit coverage for the shared auth-status schema validator."""

from __future__ import annotations

from auth_status_schema import parse_and_validate_stdout, validate_payload


def test_validate_payload_requires_non_empty_credential_types():
    errors = validate_payload({
        "profiles": [
            {
                "name": "default",
                "auth_type": "default",
                "active": True,
                "authenticated": False,
                "credential_types": {},
            }
        ]
    })

    assert errors == ["profile default credential_types must contain at least one entry"]


def test_parse_and_validate_stdout_reports_json_error():
    payload, errors = parse_and_validate_stdout("not-json")

    assert payload is None
    assert len(errors) == 1
    assert errors[0].startswith("stdout is not a single valid JSON document:")
