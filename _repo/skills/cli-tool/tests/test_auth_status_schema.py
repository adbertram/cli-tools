"""Validate the canonical schema of `<cli> auth status` stdout.

Every authenticating CLI must emit a single JSON document on stdout that matches
the canonical fleet-wide shape::

    {"profiles": [
        {
            "name": <str>,
            "is_default": <bool>,
            "authenticated": <bool>,
            "credential_types": {
                "<credential_type>": {
                    "credentials_saved": <bool>,
                    "authenticated": <bool>,
                    "api_test": <"passed" | "failed: ...">   # optional
                },
                ...
            }
        },
        ...
    ]}

This test was previously a 140-line inline ``jq`` phase in ``test-cli-tool.sh``;
moving it here keeps the logic, drops the bash, and lets it be invoked from any
caller that runs the compliance suite.
"""

from __future__ import annotations

import json

import pytest

from cli_test_utils import run_cli_command

VALID_CREDENTIAL_TYPES = {
    "custom",
    "api_key",
    "oauth",
    "oauth_authorization_code",
    "personal_access_token",
    "username_password",
    "browser_session",
}


def _has_subcommand(help_text: str, name: str) -> bool:
    return any(name in line.split() for line in help_text.splitlines() if name in line)


def _validate_profile(profile: dict, errors: list) -> None:
    name = profile.get("name")
    if not isinstance(name, str):
        errors.append("profile missing or non-string name")
        return
    for field, expected_type in [("is_default", bool), ("authenticated", bool), ("credential_types", dict)]:
        if field not in profile:
            errors.append(f"profile {name} missing {field}")
        elif not isinstance(profile[field], expected_type):
            errors.append(f"profile {name} {field} must be {expected_type.__name__}")
    cred_types = profile.get("credential_types", {})
    if not isinstance(cred_types, dict):
        return
    for cred_key, cred_value in cred_types.items():
        if cred_key not in VALID_CREDENTIAL_TYPES:
            errors.append(f"profile {name} has invalid credential_type key: {cred_key}")
            continue
        if not isinstance(cred_value, dict):
            errors.append(f"profile {name} credential_types[{cred_key}] must be object")
            continue
        for field in ("credentials_saved", "authenticated"):
            if field not in cred_value:
                errors.append(f"profile {name} credential_types[{cred_key}] missing {field}")
            elif not isinstance(cred_value[field], bool):
                errors.append(f"profile {name} credential_types[{cred_key}].{field} must be boolean")
        if "api_test" in cred_value:
            api_test = cred_value["api_test"]
            if not (isinstance(api_test, str) and (api_test == "passed" or api_test.startswith("failed:"))):
                errors.append(
                    f"profile {name} credential_types[{cred_key}].api_test must be \"passed\" or start with \"failed:\""
                )


def test_auth_status_schema(cli_executable, cli_name, help_cache, command_filter):
    """Auth status stdout must parse as a single JSON doc matching the canonical schema."""
    if command_filter:
        pytest.skip("Skipping (command filter active)")
    root_help = help_cache("")
    if not _has_subcommand(root_help, "auth"):
        pytest.skip(f"{cli_name} has no auth subcommand")
    auth_help = help_cache("auth")
    if not _has_subcommand(auth_help, "status"):
        pytest.skip(f"{cli_name} has no 'auth status' subcommand")

    result = run_cli_command(cli_executable, ["auth", "status"])

    assert result.returncode == 0, f"'{cli_name} auth status' exited {result.returncode}: {result.stderr[:300]}"

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(
            f"'{cli_name} auth status' stdout is not a single valid JSON document "
            f"(stream-separation violation): {exc}.\nstdout: {result.stdout[:300]}"
        )

    errors: list[str] = []
    if not isinstance(payload, dict):
        errors.append("top-level must be object")
    elif "profiles" not in payload:
        errors.append("missing profiles")
    elif not isinstance(payload["profiles"], list):
        errors.append("profiles must be array")
    elif len(payload["profiles"]) == 0:
        errors.append("profiles array is empty")
    else:
        for profile in payload["profiles"]:
            if isinstance(profile, dict):
                _validate_profile(profile, errors)
            else:
                errors.append("profile must be object")

    assert not errors, "auth status schema violations:\n  - " + "\n  - ".join(errors)
