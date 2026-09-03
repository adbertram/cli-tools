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
        # NOT human-verified. A live stamp is read-only: since
        # artifact_versions._require_human_verified_reopen landed, a content
        # write to a stamped artifact is REFUSED outright (the reopen is its
        # own separate write) rather than silently un-stamping it. A stamped
        # draft therefore cannot reach the dependency cascade these tests are
        # about -- only an unstamped one can.
        "Outline Draft Human Verified": False,
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

    # course.outline declares rebuilt_from_dependencies: it is the mechanical
    # copy of the approved draft, so a draft change clears it back to the
    # Build Outline state.
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


def test_submitted_draft_change_resets_lifecycle_and_blocks_stale_submit(capsys):
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

    # The readiness gate reports and continues rather than refusing -- see
    # commit 3792e077 ("convert workflow gates to non-blocking reminders").
    # What this test guards is that a draft change still leaves the built
    # outline blank and that the gate still SAYS so.
    external_review.plan_transition("course_outline", "submit", "operator", record)
    stderr = capsys.readouterr().err
    assert "⚠ REMINDER" in stderr, stderr
    assert "Readiness field 'Course Outline' is blank" in stderr, stderr


CLIP_OBJECTIVES = "- Explain what the rule engine does\n- Write one rule"
CLIP_STORY = (
    "The learner has already watched Cursor guess wrong twice. This clip pays "
    "that off by writing the rule that stops the guessing."
)


def _clip_fields():
    """A Clips record with BOTH clip.plan and clip.story content persisted."""
    return {
        "Name": "Writing your first rule",
        "Learning Objectives": CLIP_OBJECTIVES,
        "Story": CLIP_STORY,
        "Version Control": json.dumps({
            "clip.plan": _version(1, CLIP_OBJECTIVES),
            "clip.story": _version(1, CLIP_STORY),
        }),
    }


CLIP_METADATA = {
    "Learning Objectives": {"type": "multilineText"},
    "Story": {"type": "multilineText"},
}


def _plan_clip(proposed, fields=None):
    return av.plan_record_update(
        "Clips", "recClip", proposed, fields or _clip_fields(), CLIP_METADATA
    )


def test_clip_objectives_update_leaves_the_sibling_story_untouched():
    """Regression: --learning-objectives silently blanked Story.

    clip.story depends_on clip.plan, so a Learning Objectives write pulled
    clip.story into the dependency-invalidation set, wrote Story="" into the
    same PATCH, and stamped clip.story with sha256("") --
    e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855.
    """
    planned = _plan_clip({"Learning Objectives": "- Explain the rule engine\n- Ship a rule"})

    assert "Story" not in planned
    versions = json.loads(planned["Version Control"])
    assert versions["clip.plan"]["v"] == 2
    # clip.story is stale, so it bumps -- but from the LIVE Story value.
    assert versions["clip.story"]["v"] == 2
    assert versions["clip.story"]["sha256"] == hashlib.sha256(
        CLIP_STORY.encode()
    ).hexdigest()
    assert versions["clip.story"]["sha256"] != hashlib.sha256(b"").hexdigest()


def test_clip_story_update_leaves_the_sibling_objectives_untouched():
    """The inverse direction: a Story write must not touch Learning Objectives."""
    planned = _plan_clip({"Story": "A tighter story that lands the same beat."})

    assert "Learning Objectives" not in planned
    versions = json.loads(planned["Version Control"])
    assert versions["clip.story"]["v"] == 2
    # clip.plan is clip.story's dependency, not its dependent: untouched.
    assert versions["clip.plan"]["v"] == 1
    assert versions["clip.plan"]["sha256"] == hashlib.sha256(
        CLIP_OBJECTIVES.encode()
    ).hexdigest()


def test_two_separate_clip_updates_preserve_both_fields_end_to_end():
    """Replays the exact live sequence: write Story, then write objectives only."""
    fields = _clip_fields()
    fields["Story"] = ""
    fields["Version Control"] = json.dumps({"clip.plan": _version(1, CLIP_OBJECTIVES)})

    first = _plan_clip({"Story": CLIP_STORY}, fields)
    fields.update(first)

    second = _plan_clip({"Learning Objectives": "- Rewritten objective"}, fields)
    fields.update(second)

    assert fields["Story"] == CLIP_STORY
    assert json.loads(fields["Version Control"])["clip.story"]["sha256"] == (
        hashlib.sha256(CLIP_STORY.encode()).hexdigest()
    )


def test_demo_overview_update_does_not_wipe_the_downstream_demo_chain():
    """demo.overview -> demo.environment_spec -> demo.action_summary -> demo.script."""
    persisted = {
        "Demo Overview": "old overview",
        "Environment Spec": "the spec",
        "Action Summary": "the walk",
        "Script": "the narration",
        "Version Control": json.dumps({
            "demo.overview": _version(1, "old overview"),
            "demo.environment_spec": _version(1, "the spec"),
            "demo.action_summary": _version(1, "the walk"),
            "demo.script": _version(1, "the narration"),
        }),
    }
    planned = av.plan_record_update(
        "Demos",
        "recDemo",
        {"Demo Overview": "new overview"},
        persisted,
        {
            "Demo Overview": {"type": "multilineText"},
            "Environment Spec": {"type": "multilineText"},
            "Action Summary": {"type": "multilineText"},
            "Script": {"type": "multilineText"},
        },
    )

    for field in ("Environment Spec", "Action Summary", "Script"):
        assert field not in planned, f"{field} must not be blanked by a dependency change"
    versions = json.loads(planned["Version Control"])
    for slug, content in (
        ("demo.environment_spec", "the spec"),
        ("demo.action_summary", "the walk"),
        ("demo.script", "the narration"),
    ):
        assert versions[slug]["v"] == 2
        assert versions[slug]["sha256"] == hashlib.sha256(content.encode()).hexdigest()
