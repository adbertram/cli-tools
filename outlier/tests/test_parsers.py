"""Parser regression tests pinned to real Outlier data.

Two sources, both captured 2026-09-02 and both real:

* ``LIVE_EMPTY_QUEUE`` is the verbatim body of
  ``GET /internal/v2/tasks/peek_queue`` from Adam's authenticated session.
  The account's queue was empty, so it is the only live response available.
* ``BUNDLE_ASSIGNMENT`` is a verbatim assignment object out of the deployed
  frontend bundle ``96381-9a75b7fbb7bffcba.js``, which ships twelve peek_queue
  response fixtures registered against that exact path. It is Outlier's own
  data, not a hand-written stand-in.
"""

from outlier_cli.parsers import (
    normalize_queue_status,
    normalize_task_detail,
    normalize_task_rows,
)

LIVE_EMPTY_QUEUE = {
    "assignments": [],
    "emptyQueueEvent": {
        "serverSideRequestId": "8c3a552f-01c6-4440-81f7-7b5824cca592",
        "userId": "6a94b8daf0b15c4cc80e96fa",
        "activeWorkerTeam": "65c3f4ed5c9add81c7fab588",
        "currentPrimaryTeamAssignments": [],
        "currentSecondaryTeamAssignments": [],
        "emptyQueueReasons": {},
        "preAssignmentEmptyQueueReason": "KYCInfoCollection",
        "requestedAt": "2026-09-02T23:48:19.630Z",
        "currentAssignedProjectLayers": [],
    },
    "isEmptyQueue": True,
    "missionsCreated": False,
}

BUNDLE_ASSIGNMENT = {
    "type": "OUTLIER_QUALIFICATION_IN_QUEUE",
    "projectId": "66edda0f65beb7be44e8d0a7",
    "reviewLevel": -1,
    "JSONResponse": {
        "_id": "67c17b368fd2e378fa49d931",
        "name": "Mail Valley - Intro Course v2",
        "displayName": "Mail Valley - Intro Course v2",
        "externalDescription": "Mail Valley - Intro Course v2",
        "qualificationType": "course",
        "metadata": {
            "courseId": "67c17b368fd2e378fa49d92c",
            "courseDuration": 36,
            "courseVersion": "v2",
        },
        "isPayMultiplier": False,
        "isAssessment": False,
        "createdAt": "2025-02-28T09:00:38.967Z",
        "updatedAt": "2025-03-01T20:54:59.600Z",
        "qualificationStatus": "worker_pending",
        "qualificationCallToAction": {
            "type": "relative_url",
            "url": "/expert/course?id=67c17b368fd2e378fa49d92c",
        },
        "qualificationEstimatedTime": 0,
        "id": "67c17b368fd2e378fa49d931",
        "reviewLevel": -1,
    },
    "qualificationList": {
        "qualificationListId": "67bd5987f8de94ad976e4438",
        "qualificationListStatus": "pending",
        "requiredQualificationListInfo": [
            {
                "_id": "67c215b623729bed2e2e3a1c",
                "name": "Writing a Good Prompt for Mail Valley",
                "displayName": "Common Errors + Prompt Deep Dive",
                "externalDescription": "Please review this course thoroughly.",
                "qualificationType": "course",
                "isAssessment": False,
                "qualificationStatus": "unstarted",
                "qualificationCallToAction": {
                    "type": "relative_url",
                    "url": "/expert/course?id=67c215b623729bed2e2e3a14",
                },
                "id": "67c215b623729bed2e2e3a1c",
            }
        ],
    },
    "onboardingFlowId": "66edda11c59ea1429a668c76",
    "assignmentType": "chosen",
}

LIST_FIELDS = {
    "id",
    "url",
    "type",
    "assignment_type",
    "node_type",
    "project_id",
    "review_level",
    "onboarding_flow_id",
    "name",
    "display_name",
    "description",
    "qualification_id",
    "qualification_type",
    "qualification_status",
    "qualification_list_status",
    "qualification_estimated_time",
    "is_assessment",
    "is_pay_multiplier",
    "created_at",
    "updated_at",
}

DETAIL_ONLY_FIELDS = {
    "qualification_list_id",
    "required_qualifications",
    "metadata",
    "user_project_onboarding_state",
    "json_response",
}


def test_live_empty_queue_yields_no_rows():
    assert normalize_task_rows(LIVE_EMPTY_QUEUE["assignments"]) == []


def test_live_empty_queue_status_reports_the_blocking_reason():
    status = normalize_queue_status(LIVE_EMPTY_QUEUE)
    assert status["is_empty_queue"] is True
    assert status["assignment_count"] == 0
    assert status["empty_queue_reason"] == "KYCInfoCollection"
    assert status["user_id"] == "6a94b8daf0b15c4cc80e96fa"
    assert status["active_worker_team"] == "65c3f4ed5c9add81c7fab588"
    assert status["requested_at"] == "2026-09-02T23:48:19.630Z"
    # Absent from the live response: reported as None, never invented.
    assert status["available_projects"] is None
    assert status["current_chosen_project_id"] is None


def test_missing_assignments_key_is_not_an_error():
    assert normalize_task_rows(None) == []
    assert normalize_queue_status({})["assignment_count"] == 0


def test_row_shape_is_exactly_the_documented_contract():
    (row,) = normalize_task_rows([BUNDLE_ASSIGNMENT])
    assert set(row) == LIST_FIELDS


def test_row_maps_every_field_from_the_bundle_fixture():
    (row,) = normalize_task_rows([BUNDLE_ASSIGNMENT])
    assert row == {
        "id": "66edda0f65beb7be44e8d0a7",
        "url": "https://app.outlier.ai/expert/course?id=67c17b368fd2e378fa49d92c",
        "type": "OUTLIER_QUALIFICATION_IN_QUEUE",
        "assignment_type": "chosen",
        "node_type": None,
        "project_id": "66edda0f65beb7be44e8d0a7",
        "review_level": -1,
        "onboarding_flow_id": "66edda11c59ea1429a668c76",
        "name": "Mail Valley - Intro Course v2",
        "display_name": "Mail Valley - Intro Course v2",
        "description": "Mail Valley - Intro Course v2",
        "qualification_id": "67c17b368fd2e378fa49d931",
        "qualification_type": "course",
        "qualification_status": "worker_pending",
        "qualification_list_status": "pending",
        "qualification_estimated_time": 0,
        "is_assessment": False,
        "is_pay_multiplier": False,
        "created_at": "2025-02-28T09:00:38.967Z",
        "updated_at": "2025-03-01T20:54:59.600Z",
    }


def test_detail_adds_only_the_documented_extra_fields():
    detail = normalize_task_detail(BUNDLE_ASSIGNMENT)
    assert set(detail) == LIST_FIELDS | DETAIL_ONLY_FIELDS
    assert detail["qualification_list_id"] == "67bd5987f8de94ad976e4438"
    assert detail["metadata"]["courseId"] == "67c17b368fd2e378fa49d92c"
    assert detail["json_response"] is BUNDLE_ASSIGNMENT["JSONResponse"]
    assert detail["user_project_onboarding_state"] is None
    assert detail["required_qualifications"] == [
        {
            "id": "67c215b623729bed2e2e3a1c",
            "name": "Writing a Good Prompt for Mail Valley",
            "display_name": "Common Errors + Prompt Deep Dive",
            "description": "Please review this course thoroughly.",
            "qualification_type": "course",
            "qualification_status": "unstarted",
            "is_assessment": False,
            "url": "https://app.outlier.ai/expert/course?id=67c215b623729bed2e2e3a14",
        }
    ]


def test_assignment_without_a_payload_still_produces_the_full_record():
    """The bundle also ships assignments carrying only type/projectId/
    JSONResponse/nodeType, so a missing sub-object must not raise."""
    (row,) = normalize_task_rows(
        [{"type": "ACCOUNT_VERIFIACTION_IN_QUEUE", "projectId": "abc", "nodeType": "task"}]
    )
    assert set(row) == LIST_FIELDS
    assert row["id"] == "abc"
    assert row["node_type"] == "task"
    assert row["url"] is None
    assert row["display_name"] is None


def test_absolute_call_to_action_url_is_passed_through():
    assignment = {
        "projectId": "p1",
        "JSONResponse": {
            "qualificationCallToAction": {
                "type": "external_url",
                "url": "https://example.com/x",
            }
        },
    }
    (row,) = normalize_task_rows([assignment])
    assert row["url"] == "https://example.com/x"
