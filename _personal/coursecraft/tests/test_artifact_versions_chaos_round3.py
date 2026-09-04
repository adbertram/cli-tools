"""Tests for the two real, reproduced chaos-engineer round-3 findings against
``coursecraft_cli.artifact_versions``:

* Finding 1: ``check_write_conflict``'s round-2 ``Name``-only false-positive
  fix generalized to every ambiguous Slides-table field -- ``Build
  Instructions`` has the identical unfixed shape (a content field on only
  some slide types, not all six).
Finding 2's tests are gone. They covered ``stamp_versions`` and its internal
follow-up/retry write -- a two-write architecture (content PATCH, then a
separate Version Control stamp) that no longer exists. ``plan_record_update``
replaced it with a single merged PATCH, so there is no follow-up write left to
race and no ``_write_versioning_follow_up`` to call. What survives of that
finding is covered here by
``test_client_update_record_genuine_original_field_mismatch_still_raises``.
"""

import json

import pytest

from coursecraft_cli import artifact_versions as av
from coursecraft_cli.client import CourseCraftClient, WriteVerificationError


def _client() -> CourseCraftClient:
    """Build a client without touching config/auth (mirrors other client tests)."""
    client = CourseCraftClient.__new__(CourseCraftClient)
    # __init__ is bypassed above, so every instance attribute a real client
    # relies on must be installed here. _field_metadata_cache backs
    # _field_storage_metadata, which the write path calls on every
    # create/update; without it these fixtures fail with an AttributeError
    # that says nothing about the behavior under test.
    client._field_metadata_cache = {}
    return client


# ---------------------------------------------------------------------------
# Finding 1: check_write_conflict's Name-only fix generalized to Build
# Instructions (and any other non-uniform Slides field)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("template_name", ["Course Intro", "Module Intro", "Clip Intro"])
def test_check_write_conflict_build_instructions_on_non_tracking_type_does_not_reject(template_name):
    """Build Instructions isn't a real content field on these three slide
    types -- setting it alongside Script Human Verified is legitimate."""
    av.check_write_conflict(
        "Slides",
        {"Build Instructions": "New steps", "Script Human Verified": True},
        fetch_persisted_fields=lambda t=template_name: {"Template Name": [t]},
    )  # must not raise


@pytest.mark.parametrize(
    "template_name,expected_slug",
    [
        ("Demo Intro", "slide.demo_intro"),
        ("Content", "slide.content"),
        # slide.module_recap is retired. Its former course-scoped template now
        # resolves through the slide.content fallback.
        ("Course Summary with Takeaways", "slide.content"),
    ],
)
def test_check_write_conflict_build_instructions_on_tracking_type_still_rejects(template_name, expected_slug):
    """The SAME combination on a slide type that really does track Build
    Instructions as content is a genuine conflict."""
    with pytest.raises(av.VersioningError, match=expected_slug):
        av.check_write_conflict(
            "Slides",
            {"Build Instructions": "New steps", "Script Human Verified": True},
            fetch_persisted_fields=lambda t=template_name: {"Template Name": [t]},
        )



# Exact Airtable storage types for the Slides content fields these fixtures
# write. artifact_versions._canonicalize_storage_value branches on the type, so
# these are the real types, not placeholders: none of the three is one of the
# five richText fields documented in client.py (Demos.Script,
# Clips/Modules."Learning Objectives", Modules."Brainstorming Outline",
# Courses."Brainstorming Notes").
_SLIDES_FIELD_METADATA = [
    {"name": "Name", "type": "singleLineText"},
    {"name": "Script", "type": "multilineText"},
    {"name": "Build Instructions", "type": "multilineText"},
]


def _is_field_list(args) -> bool:
    """Is this the `fields list <table>` read the write path makes?

    create_record/update_record call _field_storage_metadata before planning the
    PATCH, so a stub that answers every airtable invocation with a record dict
    makes the client (correctly) reject the metadata response. This is a READ:
    a fixture asserting that no WRITE is issued must still allow it through.
    """
    return list(args[:2]) == ["fields", "list"]

def test_check_write_conflict_build_instructions_unresolvable_type_does_not_reject():
    """An unresolvable real type (record vanished / blank Template) never guesses."""
    av.check_write_conflict(
        "Slides",
        {"Build Instructions": "New steps", "Script Human Verified": True},
        fetch_persisted_fields=lambda: None,
    )  # must not raise -- unresolvable is not "prove it's a tracking type"


def test_check_write_conflict_build_instructions_without_resolver_stays_conservative():
    """create_record has no record yet to re-read -- stays conservative (rejects)."""
    with pytest.raises(av.VersioningError, match="slide"):
        av.check_write_conflict(
            "Slides", {"Build Instructions": "New steps", "Script Human Verified": True}
        )


def test_check_write_conflict_name_is_validation_only_for_current_slide_types():
    """Name is not a content field for any current slide artifact."""
    av.check_write_conflict(
        "Slides",
        {"Name": "Intro to Widgets", "Script Human Verified": True},
        fetch_persisted_fields=lambda: {"Template Name": ["Clip Intro"]},
    )  # must not raise
    av.check_write_conflict(
        "Slides",
        {"Name": "Recap", "Script Human Verified": True},
        fetch_persisted_fields=lambda: {
            "Template Name": ["Course Summary with Takeaways"]
        },
    )


def test_check_write_conflict_script_regression_needs_zero_extra_reads():
    """Round-2 regression: Script's candidates cover the full slide-type
    universe, so it stays unambiguous and must reject without ever calling
    the resolver, even after generalizing the ambiguity rule."""

    def _never_call():
        raise AssertionError("fetch_persisted_fields must not be called for Script")

    with pytest.raises(av.VersioningError, match="slide"):
        av.check_write_conflict(
            "Slides",
            {"Script": "New body", "Script Human Verified": True},
            fetch_persisted_fields=_never_call,
        )


def test_client_update_record_build_instructions_on_course_intro_slide_succeeds(monkeypatch):
    """End-to-end through the real client: setting Build Instructions on a
    Course Intro slide alongside marking its script human-verified must reach
    Airtable, not be rejected as a phantom demo_intro/content/module_recap
    conflict."""
    client = _client()
    client.base_id = "appTEST"

    state = {
        "Build Instructions": "Old steps",
        "Script": "Body",
        "Template Name": ["Course Intro"],
    }

    def fake_run(args):
        if _is_field_list(args):
            return _SLIDES_FIELD_METADATA
        for token in args:
            if "=" not in token:
                continue
            key, _, raw_value = token.partition("=")
            try:
                state[key] = json.loads(raw_value)
            except json.JSONDecodeError:
                state[key] = raw_value
        return {"id": "recCourseIntro1", "fields": dict(state)}

    def fake_get(table, record_id):
        return {"id": record_id, "fields": dict(state)}

    monkeypatch.setattr(client, "_run_airtable_command", fake_run)
    monkeypatch.setattr(client, "get_record", fake_get)

    result = client.update_record(
        "Slides",
        "recCourseIntro1",
        {"Build Instructions": "New steps", "Script Human Verified": True},
    )

    assert result["fields"]["Build Instructions"] == "New steps"
    assert result["fields"]["Script Human Verified"] is True


def test_client_update_record_build_instructions_on_demo_intro_slide_rejects(monkeypatch):
    """The exact same call against a REAL Demo Intro slide is a genuine
    content+review conflict and must still be rejected."""
    client = _client()
    client.base_id = "appTEST"

    state = {
        "Build Instructions": "Old steps",
        "Script": "Body",
        "Template Name": ["Demo Intro"],
    }

    def fake_run(args):
        if _is_field_list(args):
            return _SLIDES_FIELD_METADATA
        raise AssertionError("must reject before issuing any Airtable write")

    def fake_get(table, record_id):
        return {"id": record_id, "fields": dict(state)}

    monkeypatch.setattr(client, "_run_airtable_command", fake_run)
    monkeypatch.setattr(client, "get_record", fake_get)

    with pytest.raises(av.VersioningError, match="slide.demo_intro"):
        client.update_record(
            "Slides",
            "recDemoIntro1",
            {"Build Instructions": "New steps", "Script Human Verified": True},
        )




def test_client_update_record_genuine_original_field_mismatch_still_raises(monkeypatch):
    """Regression: a genuine verification failure on the caller's own write
    must still raise. _verify_persisted's general behavior is unchanged: a
    field that reads back as something other than what was sent is a real
    write failure, never something to absorb."""
    client = _client()
    client.base_id = "appTEST"

    def fake_run(args):
        if _is_field_list(args):
            return _SLIDES_FIELD_METADATA
        return {"id": "recClipIntro1", "fields": {}}

    def fake_get(table, record_id):
        # The caller's own Script write never persisted. Template Name is
        # present so slide-type resolution succeeds and execution reaches the
        # verification step this test is about.
        return {
            "id": record_id,
            "fields": {
                "Script": "Something else entirely",
                "Template Name": ["Clip Intro"],
            },
        }

    monkeypatch.setattr(client, "_run_airtable_command", fake_run)
    monkeypatch.setattr(client, "get_record", fake_get)

    with pytest.raises(WriteVerificationError, match="did not persist as sent"):
        client.update_record("Slides", "recClipIntro1", {"Script": "New body"})
