"""Tests for the identity-verification (Persona) parser.

Both fixtures are verbatim bodies captured from Adam's authenticated session
on 2026-09-03, while `onboarding status` reported
`step_type: "persona"` / `step_display_name: "Persona"` and `nextStep.id:
"identity"`:

  * ``GET /internal/identity-verification/assignments``
    -> ``{"personaIdentityVerification": false}``
  * ``GET /internal/tns-audits/idv_audit_status`` -> ``null``

The naming is the point of these tests. Outlier calls the same step two
things: the onboarding endpoint's `stepType` is the vendor name `persona`,
while the dashboard row and `nextStep.id` are `identity` / "Verify identity".
Anything reading `step_type` alone cannot tell that the account is sitting on
government-ID-and-selfie verification, which is why the CLI reports both.
"""

from outlier_cli.parsers import (
    normalize_identity_verification,
    normalize_onboarding_status,
)

LIVE_ASSIGNMENTS = {"personaIdentityVerification": False}
LIVE_AUDIT_STATUS = None

# Verbatim onboarding body captured at the same moment.
LIVE_PERSONA_ONBOARDING = {
    "currentState": {
        "result": "in_progress",
        "state": {
            "flowDisplayName": "Unified Onboarding MVP",
            "stepDisplayName": "Persona",
            "stepType": "persona",
            "stepStatus": "in-progress",
            "checkpoint": 2,
        },
    },
    "qualifications": [
        {"id": "complete-profile", "title": "Create profile", "status": "qualified"},
        {
            "id": "skill-selection",
            "title": "Import skills",
            "description": "matches you with projects",
            "status": "qualified",
        },
        {"id": "identity", "title": "Verify identity", "status": "unstarted"},
        {
            "id": "skill-screenings",
            "title": "Verify skills",
            "description": "unlocks your first project",
            "disallowMobile": True,
            "status": "unstarted",
        },
        {
            "id": "fraud_checkpoint",
            "title": "Fraud Checkpoint",
            "status": "unstarted",
            "metadata": {},
        },
    ],
    "nextStep": {"id": "identity", "title": "Verify identity", "status": "unstarted"},
}


def test_identity_verification_maps_the_live_bodies():
    assert normalize_identity_verification(LIVE_ASSIGNMENTS, LIVE_AUDIT_STATUS) == {
        "persona_identity_verification": False,
        "idv_audit_status": None,
    }


def test_absent_assignment_field_is_none_not_false():
    """An empty body must not be reported as 'no Persona inquiry'."""
    row = normalize_identity_verification({}, None)
    assert row["persona_identity_verification"] is None


def test_audit_status_is_passed_through_verbatim():
    """No sub-fields are invented for a payload never seen populated."""
    payload = {"status": "pending", "auditId": "abc123"}
    row = normalize_identity_verification(LIVE_ASSIGNMENTS, payload)
    assert row["idv_audit_status"] == payload


def test_persona_step_type_pairs_with_the_identity_next_step():
    """`persona` and `identity` are the same step under two names."""
    row = normalize_onboarding_status(LIVE_PERSONA_ONBOARDING)
    assert row["step_type"] == "persona"
    assert row["step_display_name"] == "Persona"
    assert row["next_step_id"] == "identity"
    assert row["next_step_title"] == "Verify identity"
    assert row["checkpoint"] == 2


def test_first_two_steps_are_qualified_and_the_rest_are_not():
    row = normalize_onboarding_status(LIVE_PERSONA_ONBOARDING)
    assert [(s["id"], s["status"]) for s in row["steps"]] == [
        ("complete-profile", "qualified"),
        ("skill-selection", "qualified"),
        ("identity", "unstarted"),
        ("skill-screenings", "unstarted"),
        ("fraud_checkpoint", "unstarted"),
    ]
