"""Onboarding parser tests pinned to real Outlier responses.

Both fixtures are verbatim bodies captured from Adam's authenticated session
on 2026-09-02:

  * ``LIVE_ONBOARDING`` from ``GET
    /internal/experts/qualification/onboarding/v2``
  * ``LIVE_PII`` from ``GET /internal/worker/get_pii``
"""

from outlier_cli.parsers import (
    normalize_onboarding_status,
    normalize_onboarding_steps,
    normalize_profile,
)

LIVE_ONBOARDING = {
    "currentState": {
        "result": "in_progress",
        "state": {
            "flowDisplayName": "Unified Onboarding MVP",
            "stepDisplayName": "Phone Verification",
            "stepType": "phone-verification",
            "stepStatus": "in-progress",
            "checkpoint": 0,
        },
    },
    "qualifications": [
        {"id": "complete-profile", "title": "Create profile", "status": "unstarted"},
        {
            "id": "skill-selection",
            "title": "Import skills",
            "description": "matches you with projects",
            "status": "unstarted",
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
    "nextStep": {
        "id": "complete-profile",
        "title": "Create profile",
        "status": "unstarted",
    },
}

LIVE_PII = {
    "worker": "6a94b8daf0b15c4cc80e96fa",
    "status": "Unverified",
    "firstName": "Adam",
    "lastName": "Bertram",
    "addressSubdivision": "Indiana",
    "addressSubdivisionCode": "IN",
    "countryCode": "US",
}


def test_status_reports_the_current_step_and_next_step():
    row = normalize_onboarding_status(LIVE_ONBOARDING)
    assert row["result"] == "in_progress"
    assert row["flow_display_name"] == "Unified Onboarding MVP"
    assert row["step_display_name"] == "Phone Verification"
    assert row["step_type"] == "phone-verification"
    assert row["step_status"] == "in-progress"
    assert row["checkpoint"] == 0
    assert row["next_step_id"] == "complete-profile"
    assert row["next_step_status"] == "unstarted"


def test_status_embeds_every_step():
    row = normalize_onboarding_status(LIVE_ONBOARDING)
    assert [step["id"] for step in row["steps"]] == [
        "complete-profile",
        "skill-selection",
        "identity",
        "skill-screenings",
        "fraud_checkpoint",
    ]


def test_steps_normalize_optional_fields_to_none():
    steps = normalize_onboarding_steps(LIVE_ONBOARDING["qualifications"])
    create_profile = steps[0]
    assert create_profile == {
        "id": "complete-profile",
        "title": "Create profile",
        "description": None,
        "status": "unstarted",
        "disallow_mobile": None,
        "metadata": None,
    }
    assert steps[3]["disallow_mobile"] is True
    assert steps[1]["description"] == "matches you with projects"


def test_missing_onboarding_containers_do_not_invent_values():
    row = normalize_onboarding_status({})
    assert row["result"] is None
    assert row["step_type"] is None
    assert row["next_step_id"] is None
    assert row["steps"] == []


def test_profile_maps_the_live_pii_record():
    row = normalize_profile(LIVE_PII)
    assert row == {
        "worker_id": "6a94b8daf0b15c4cc80e96fa",
        "status": "Unverified",
        "first_name": "Adam",
        "last_name": "Bertram",
        "country_code": "US",
        "state": "Indiana",
        "state_code": "IN",
        # Absent from the live response because no phone was on file yet.
        "phone_number": None,
        "phone_number_verified": None,
    }
