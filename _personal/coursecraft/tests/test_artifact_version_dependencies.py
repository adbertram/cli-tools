import hashlib
import json

import pytest

from coursecraft_cli import artifact_versions as av
from coursecraft_cli import external_review


def _version(version, content):
    return {
        "v": version,
        "sha256": hashlib.sha256(content.encode()).hexdigest(),
        "at": "2026-08-23T00:00:00Z",
    }


def _course_fields(state="Not Submitted"):
    return {
        "Platform": "Pluralsight",
        "Status": "Submit Outline for Approval",
        "Outline Draft": "old draft",
        "Outline Draft Review (AI)": (
            "PASS\nReviewed-Version: course.outline_draft@v1 sha256:"
            + hashlib.sha256(b"old draft").hexdigest()
        ),
        "Outline Draft Human Verified": True,
        "Course Outline": "stale built outline",
        "Course Outline Review State": state,
        "Course Outline Submitted Revision": external_review.version_evidence(
            "course.outline", _version(1, "stale built outline")
        ),
        "Version Control": json.dumps({
            "course.outline_draft": _version(1, "old draft"),
            "course.outline": _version(1, "stale built outline"),
        }),
    }


def _plan(fields):
    return av.plan_record_update(
        "Courses",
        "recCourse",
        {"Outline Draft": "new draft"},
        fields,
        {
            "Outline Draft": {"type": "multilineText"},
            "Course Outline": {"type": "multilineText"},
        },
    )


def test_draft_change_clears_dependent_outline_gates_and_versions_both():
    planned = _plan(_course_fields())

    assert planned["Course Outline"] == ""
    assert planned["Outline Draft Review (AI)"] == ""
    assert planned["Outline Draft Human Verified"] is False
    versions = json.loads(planned["Version Control"])
    assert versions["course.outline_draft"]["v"] == 2
    assert versions["course.outline_draft"]["sha256"] == hashlib.sha256(
        b"new draft"
    ).hexdigest()
    assert versions["course.outline"]["v"] == 2
    assert versions["course.outline"]["sha256"] == hashlib.sha256(b"").hexdigest()


def test_not_submitted_routes_to_review_then_build_from_canonical_mapping():
    fields = _course_fields()
    fields.update(_plan(fields))
    contract = external_review._instance_contract("course_outline")

    assert contract["status_mapping"]["Not Submitted+draft_review"] == (
        "Outline Draft Review"
    )
    assert fields["Outline Draft Review (AI)"] == ""
    assert fields["Outline Draft Human Verified"] is False

    fields["Outline Draft Review (AI)"] = "PASS"
    fields["Outline Draft Human Verified"] = True
    assert contract["status_mapping"][
        "Not Submitted+draft_released+outline_missing"
    ] == "Build Outline"
    assert fields["Course Outline"] == ""


def test_submitted_draft_change_resets_lifecycle_and_blocks_stale_submit():
    fields = _course_fields("Submitted")
    fields.update(_plan(fields))

    assert fields["Course Outline Review State"] == "Not Submitted"
    assert fields["Course Outline Submitted Revision"] == ""

    draft_version = json.loads(fields["Version Control"])["course.outline_draft"]
    fields.update({
        "Status": "Submit Outline for Approval",
        "Outline Draft Review (AI)": (
            "PASS\nReviewed-Version: course.outline_draft@v2 sha256:"
            + draft_version["sha256"]
        ),
        "Outline Draft Human Verified": True,
    })
    outline_version = json.loads(fields["Version Control"])["course.outline"]
    record = {
        "fields": fields,
        "current_revision": external_review.version_evidence(
            "course.outline", outline_version
        ),
    }

    with pytest.raises(
        external_review.ExternalReviewError,
        match="Readiness field 'Course Outline' is blank",
    ):
        external_review.plan_transition(
            "course_outline", "submit", "operator", record
        )
