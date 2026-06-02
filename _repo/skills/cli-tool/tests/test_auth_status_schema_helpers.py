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
                "authenticated": True,
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


def test_validate_payload_rejects_unauthenticated_profile():
    errors = validate_payload({
        "profiles": [
            {
                "name": "default",
                "auth_type": "default",
                "active": True,
                "authenticated": False,
                "credential_types": {
                    "api_key": {
                        "credentials_saved": True,
                        "authenticated": True,
                        "api_test": "passed",
                    }
                },
            }
        ]
    })

    assert errors == ["profile default authenticated must be true in auth status output"]


def test_validate_payload_reports_missing_credential_authenticated_as_schema_error():
    errors = validate_payload({
        "profiles": [
            {
                "name": "default",
                "auth_type": "default",
                "active": True,
                "authenticated": True,
                "credential_types": {
                    "api_key": {
                        "credentials_saved": True,
                        "api_test": "passed",
                    }
                },
            }
        ]
    })

    assert errors == ["profile default credential_types[api_key] missing authenticated"]


def test_validate_payload_allows_unused_unauthenticated_credential_type():
    payload, errors = parse_and_validate_stdout(
        """
        {
          "cache_hit": false,
          "profiles": [
            {
              "name": "default",
              "auth_type": "default",
              "active": true,
              "authenticated": true,
              "credential_types": {
                "api_key": {
                  "credentials_saved": true,
                  "api_test": "passed",
                  "method": "api_key",
                  "authenticated": true,
                  "api_key": "b343...07b1"
                },
                "browser_session": {
                  "credentials_saved": false,
                  "browser_session": false,
                  "browser_available": false,
                  "authenticated": false,
                  "message": "Not authenticated. Run 'brickowl auth login' to configure."
                }
              }
            }
          ]
        }
        """
    )

    assert payload is not None
    assert errors == []


def test_validate_payload_rejects_authenticated_profile_with_no_authenticated_type():
    payload, errors = parse_and_validate_stdout(
        """
        {
          "profiles": [
            {
              "name": "default",
              "auth_type": "default",
              "active": true,
              "authenticated": true,
              "credential_types": {
                "api_key": {
                  "credentials_saved": true,
                  "api_test": "failed: revoked",
                  "authenticated": false
                }
              }
            }
          ]
        }
        """
    )

    assert payload is not None
    assert errors == [
        "profile default must have at least one authenticated credential type"
    ]
