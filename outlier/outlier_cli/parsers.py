"""Normalize the JSON Outlier's internal worker API returns.

`GET /internal/v2/tasks/peek_queue` is the only representation of "work that
is available to me" that app.outlier.ai has. Its response shape was captured
live from Adam's authenticated session on 2026-09-02:

    {"assignments": [], "emptyQueueEvent": {...}, "isEmptyQueue": true,
     "missionsCreated": false}

The account's queue was empty at capture time (`preAssignmentEmptyQueueReason:
"KYCInfoCollection"` — Outlier's own copy for that reason is "To continue,
please complete the required pay setup"), so no live assignment object was
observable. The assignment field names below are therefore taken from the
deployed frontend itself rather than guessed:

  * The bundle `96381-9a75b7fbb7bffcba.js` ships twelve verbatim peek_queue
    response fixtures registered against `/internal/v2/tasks/peek_queue`.
    Across them an assignment object carries exactly:
    `type`, `projectId`, `reviewLevel`, `JSONResponse`, `qualificationList`,
    `nodeType`, `userProjectOnboardingState`, `onboardingFlowId`,
    `assignmentType`.
  * `375458-…`/`96381-…` read those same properties off `assignments[0]`
    (`.type`, `.projectId`, `.qualificationList.requiredQualificationListInfo[]
    .qualificationStatus`).
  * `JSONResponse` carries `_id`, `id`, `name`, `displayName`,
    `externalDescription`, `qualificationType`, `metadata`, `isPayMultiplier`,
    `isAssessment`, `createdAt`, `updatedAt`, `qualificationStatus`,
    `qualificationCallToAction{type,url}`, `qualificationEstimatedTime`,
    `reviewLevel`.
  * Observed `type` values: `OUTLIER_QUALIFICATION_IN_QUEUE`,
    `ACCOUNT_VERIFIACTION_IN_QUEUE` (Outlier's own spelling).

Anything Outlier does not return for a given assignment stays `None` — no
field here is invented, and none is defaulted.

`qualification_estimated_time` is passed through verbatim: Outlier's frontend
never renders it with a unit, so this module does not claim one (it is NOT
asserted to be minutes).
"""
from typing import Any, Dict, List, Optional

APP_BASE_URL = "https://app.outlier.ai"


def _call_to_action_url(json_response: Dict[str, Any]) -> Optional[str]:
    """Absolute URL for an assignment's call to action, when it has one.

    Outlier expresses it as `{"type": "relative_url", "url": "/expert/..."}`;
    only that type is turned into an absolute app URL, because it is the only
    type observed in the site's own fixtures.
    """
    cta = json_response.get("qualificationCallToAction")
    if not isinstance(cta, dict):
        return None
    url = cta.get("url")
    if not url:
        return None
    if cta.get("type") == "relative_url":
        return f"{APP_BASE_URL}{url}"
    return url


def _json_response(raw: Dict[str, Any]) -> Dict[str, Any]:
    payload = raw.get("JSONResponse")
    return payload if isinstance(payload, dict) else {}


def _qualification_list(raw: Dict[str, Any]) -> Dict[str, Any]:
    qual_list = raw.get("qualificationList")
    return qual_list if isinstance(qual_list, dict) else {}


def normalize_task_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize one entry of `peek_queue.assignments`."""
    payload = _json_response(raw)
    qual_list = _qualification_list(raw)
    return {
        # Outlier assignments carry no id of their own; `projectId` is the
        # identity the frontend itself keys an assignment on.
        "id": raw.get("projectId"),
        "url": _call_to_action_url(payload),
        "type": raw.get("type"),
        "assignment_type": raw.get("assignmentType"),
        "node_type": raw.get("nodeType"),
        "project_id": raw.get("projectId"),
        "review_level": raw.get("reviewLevel"),
        "onboarding_flow_id": raw.get("onboardingFlowId"),
        "name": payload.get("name"),
        "display_name": payload.get("displayName"),
        "description": payload.get("externalDescription"),
        "qualification_id": payload.get("id"),
        "qualification_type": payload.get("qualificationType"),
        "qualification_status": payload.get("qualificationStatus"),
        "qualification_list_status": qual_list.get("qualificationListStatus"),
        "qualification_estimated_time": payload.get("qualificationEstimatedTime"),
        "is_assessment": payload.get("isAssessment"),
        "is_pay_multiplier": payload.get("isPayMultiplier"),
        "created_at": payload.get("createdAt"),
        "updated_at": payload.get("updatedAt"),
    }


def normalize_task_rows(raw_assignments: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Normalize the `assignments` array of a peek_queue response."""
    return [normalize_task_row(item) for item in (raw_assignments or [])]


def normalize_required_qualification(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize one entry of `qualificationList.requiredQualificationListInfo`."""
    return {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "display_name": raw.get("displayName"),
        "description": raw.get("externalDescription"),
        "qualification_type": raw.get("qualificationType"),
        "qualification_status": raw.get("qualificationStatus"),
        "is_assessment": raw.get("isAssessment"),
        "url": _call_to_action_url(raw),
    }


def normalize_task_detail(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize one assignment into the full detail record."""
    payload = _json_response(raw)
    qual_list = _qualification_list(raw)
    required = qual_list.get("requiredQualificationListInfo")
    row = normalize_task_row(raw)
    row.update(
        {
            "qualification_list_id": qual_list.get("qualificationListId"),
            "required_qualifications": [
                normalize_required_qualification(item)
                for item in (required if isinstance(required, list) else [])
            ],
            "metadata": payload.get("metadata"),
            "user_project_onboarding_state": raw.get("userProjectOnboardingState"),
            # Everything Outlier returned for this assignment, unfiltered.
            "json_response": payload or None,
        }
    )
    return row


def normalize_queue_status(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a peek_queue response into queue-level status.

    `emptyQueueEvent` field names are from the live capture plus the frontend
    fixtures: `serverSideRequestId`, `userId`, `activeWorkerTeam`,
    `currentPrimaryTeamAssignments`, `currentSecondaryTeamAssignments`,
    `emptyQueueReasons`, `preAssignmentEmptyQueueReason`, `requestedAt`,
    `currentAssignedProjectLayers`, `currentChosenProjectLayer`,
    `onboardedAndActiveProjects`, `onboardedProjects`, `availableProjects`.
    """
    event = raw.get("emptyQueueEvent")
    event = event if isinstance(event, dict) else {}
    chosen = event.get("currentChosenProjectLayer")
    return {
        "is_empty_queue": raw.get("isEmptyQueue"),
        "assignment_count": len(raw.get("assignments") or []),
        "missions_created": raw.get("missionsCreated"),
        "empty_queue_reason": event.get("preAssignmentEmptyQueueReason"),
        "empty_queue_reasons_by_project": event.get("emptyQueueReasons"),
        "user_id": event.get("userId"),
        "active_worker_team": event.get("activeWorkerTeam"),
        "requested_at": event.get("requestedAt"),
        "available_projects": event.get("availableProjects"),
        "onboarded_projects": event.get("onboardedProjects"),
        "onboarded_and_active_projects": event.get("onboardedAndActiveProjects"),
        "current_chosen_project_id": chosen.get("projectId") if isinstance(chosen, dict) else None,
        "current_assigned_project_layers": event.get("currentAssignedProjectLayers"),
        "server_side_request_id": event.get("serverSideRequestId"),
    }


# --- Onboarding -----------------------------------------------------------
#
# `GET /internal/experts/qualification/onboarding/v2` is the endpoint the
# /onboarding screen reads. Captured live from Adam's authenticated session on
# 2026-09-02:
#
#     {"currentState": {"result": "in_progress",
#                       "state": {"flowDisplayName": "Unified Onboarding MVP",
#                                 "stepDisplayName": "Phone Verification",
#                                 "stepType": "phone-verification",
#                                 "stepStatus": "in-progress", "checkpoint": 0}},
#      "qualifications": [{"id": "complete-profile", "title": "Create profile",
#                          "status": "unstarted"}, ...],
#      "nextStep": {"id": "complete-profile", "title": "Create profile",
#                   "status": "unstarted"}}
#
# The `id` values are the frontend's own `QualificationId` enum (chunk
# `5105-442d076b7716aa00.js`): complete-profile, identity, skill-selection,
# skill-screenings, task-training, intro-to-outlier, fraud_checkpoint,
# banking-setup, assessment, sample-assessment. `status` values come from the
# adjacent enum: unstarted, worker_pending, corp_pending, qualified, failed.

def normalize_onboarding_step(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize one entry of the onboarding response's `qualifications`."""
    return {
        "id": raw.get("id"),
        "title": raw.get("title"),
        "description": raw.get("description"),
        "status": raw.get("status"),
        "disallow_mobile": raw.get("disallowMobile"),
        "metadata": raw.get("metadata"),
    }


def normalize_onboarding_steps(
    raw_steps: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Normalize the `qualifications` array of an onboarding response."""
    return [normalize_onboarding_step(item) for item in (raw_steps or [])]


def normalize_onboarding_status(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize an onboarding response into current-state plus step list."""
    current = raw.get("currentState")
    current = current if isinstance(current, dict) else {}
    state = current.get("state")
    state = state if isinstance(state, dict) else {}
    next_step = raw.get("nextStep")
    next_step = next_step if isinstance(next_step, dict) else {}
    return {
        "result": current.get("result"),
        "flow_display_name": state.get("flowDisplayName"),
        "step_display_name": state.get("stepDisplayName"),
        "step_type": state.get("stepType"),
        "step_status": state.get("stepStatus"),
        "checkpoint": state.get("checkpoint"),
        "next_step_id": next_step.get("id"),
        "next_step_title": next_step.get("title"),
        "next_step_status": next_step.get("status"),
        "steps": normalize_onboarding_steps(raw.get("qualifications")),
    }


# `GET /internal/worker/get_pii` is what the Create Profile form loads its
# prefilled values from. Captured live 2026-09-02:
#
#     {"worker": "6a94b8daf0b15c4cc80e96fa", "status": "Unverified",
#      "firstName": "Adam", "lastName": "Bertram",
#      "addressSubdivision": "Indiana", "addressSubdivisionCode": "IN",
#      "countryCode": "US"}
#
# `phoneNumber` / `phoneNumberVerified` are the frontend's own field names for
# the worker record (chunks `87936-b412118544497d44.js`, `5105-…`). They were
# absent from the live capture because the account has no phone on file yet, so
# they normalize to None rather than to a fabricated value.

def normalize_profile(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize `GET /internal/worker/get_pii` into the profile record."""
    return {
        "worker_id": raw.get("worker"),
        "status": raw.get("status"),
        "first_name": raw.get("firstName"),
        "last_name": raw.get("lastName"),
        "country_code": raw.get("countryCode"),
        "state": raw.get("addressSubdivision"),
        "state_code": raw.get("addressSubdivisionCode"),
        "phone_number": raw.get("phoneNumber"),
        "phone_number_verified": raw.get("phoneNumberVerified"),
    }


# `GET /internal/identity-verification/assignments` is what the onboarding
# dashboard reads to decide whether the "Verify identity" row is a Persona
# inquiry. Captured live 2026-09-03 while the account sat on that step:
#
#     {"personaIdentityVerification": false}
#
# `GET /internal/tns-audits/idv_audit_status` returned a bare `null` at the
# same moment — no audit exists until an inquiry has been attempted — so it is
# passed through verbatim rather than being given invented sub-fields.
#
# Outlier names this step two different ways and the CLI reports both: the
# onboarding endpoint's `stepType` is `persona` (the vendor, Persona
# Identities) while the user-facing row and `nextStep.id` are `identity`
# ("Verify identity"). They are the same step.

def normalize_identity_verification(
    assignments: Dict[str, Any], audit_status: Any
) -> Dict[str, Any]:
    """Normalize the identity-verification state behind the Persona step."""
    return {
        "persona_identity_verification": assignments.get("personaIdentityVerification"),
        "idv_audit_status": audit_status,
    }
