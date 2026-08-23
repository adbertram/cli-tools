"""Shared validator for the canonical `<cli> auth status` JSON shape."""

from __future__ import annotations

import json


VALID_CREDENTIAL_TYPES = {
    "custom",
    "api_key",
    "oauth",
    "oauth_authorization_code",
    "personal_access_token",
    "username_password",
    "browser_session",
}


def validate_profile(
    profile: dict,
    errors: list[str],
    *,
    require_authenticated: bool = True,
) -> None:
    name = profile.get("name")
    if not isinstance(name, str):
        errors.append("profile missing or non-string name")
        return

    for field, expected_type in [
        ("auth_type", str),
        ("active", bool),
        ("authenticated", bool),
        ("credential_types", dict),
    ]:
        if field not in profile:
            errors.append(f"profile {name} missing {field}")
        elif not isinstance(profile[field], expected_type):
            errors.append(f"profile {name} {field} must be {expected_type.__name__}")

    if require_authenticated and profile.get("active") is not True:
        errors.append(f"profile {name} active must be true in auth status output")
    if (
        require_authenticated
        and isinstance(profile.get("authenticated"), bool)
        and profile["authenticated"] is not True
    ):
        errors.append(f"profile {name} authenticated must be true in auth status output")

    cred_types = profile.get("credential_types")
    if not isinstance(cred_types, dict):
        return
    if not cred_types:
        errors.append(f"profile {name} credential_types must contain at least one entry")
        return

    authenticated_type_count = 0
    credential_shape_valid = True
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
                credential_shape_valid = False
            elif not isinstance(cred_value[field], bool):
                errors.append(f"profile {name} credential_types[{cred_key}].{field} must be boolean")
                credential_shape_valid = False
        if cred_value.get("authenticated") is True:
            authenticated_type_count += 1
        if "api_test" in cred_value:
            api_test = cred_value["api_test"]
            if not (isinstance(api_test, str) and (api_test == "passed" or api_test.startswith("failed:"))):
                errors.append(
                    f"profile {name} credential_types[{cred_key}].api_test must be \"passed\" or start with \"failed:\""
                )

    if (
        profile.get("authenticated") is True
        and credential_shape_valid
        and authenticated_type_count == 0
    ):
        errors.append(
            f"profile {name} must have at least one authenticated credential type"
        )


def validate_payload(payload: object, *, require_authenticated: bool = True) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["top-level must be object"]
    if "profiles" not in payload:
        return ["missing profiles"]
    if not isinstance(payload["profiles"], list):
        return ["profiles must be array"]
    if len(payload["profiles"]) == 0:
        return ["profiles array is empty"]

    for profile in payload["profiles"]:
        if isinstance(profile, dict):
            validate_profile(
                profile,
                errors,
                require_authenticated=require_authenticated,
            )
        else:
            errors.append("profile must be object")
    return errors


def parse_and_validate_stdout(
    stdout: str,
    *,
    require_authenticated: bool = True,
) -> tuple[object | None, list[str]]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return None, [f"stdout is not a single valid JSON document: {exc}"]
    return payload, validate_payload(payload, require_authenticated=require_authenticated)
