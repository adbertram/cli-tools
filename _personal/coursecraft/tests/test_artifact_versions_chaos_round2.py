"""Tests for the four real, reproduced chaos-engineer round-2 findings against
``coursecraft_cli.artifact_versions``:

* Finding 2: ``check_write_conflict`` false-positive on Name + Script Human
  Verified for a non-module_recap slide type.
* Finding 3: ``canonical_hash``'s file branch must raise ``VersioningError``
  (not a raw ``OSError``) on a real read failure, so ``versions sync``'s
  per-record guard actually catches it.

Findings 4 and 5 no longer have tests here. Both exercised ``stamp_versions``:
a post-write function that issued its own follow-up Version Control write,
with a pre-write fresh re-read and a bounded settle-check retry. That two-write
architecture is gone -- ``plan_record_update`` is a pure planner that folds
Version Control, review invalidation and readiness-gate clears into the single
owner PATCH and performs no writes of its own, so there is no follow-up write
left to race and no settle-check to retry. Their assertions (``get_calls == 2``,
``len(update_calls) == 2``, the retry merge) described machinery that no longer
exists, and the call contract inverted besides: ``stamp_versions`` took the
POST-write persisted state, ``plan_record_update`` takes the PRE-write current
state and returns a dict.

One behavior they covered has changed rather than moved, and is deliberately
uncovered here: an unresolvable slide type used to silently clear the paired
review. ``plan_record_update`` now raises ``VersioningError`` instead
("cannot resolve the slide artifact for tracked field ..."), which is the
fail-loud direction the project requires.
"""

import hashlib
import json

import pytest

from coursecraft_cli import artifact_versions as av
from coursecraft_cli.client import CourseCraftClient


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
# Airtable field-metadata stub
#
# The client write path calls ``_field_storage_metadata``, which issues its own
# ``fields list <table>`` airtable CLI call and requires a LIST of exact
# field-type objects back. The versioning engine branches on those exact types
# and raises on an unknown one, so these are the real Slides types:
# ``Script``/``Build Instructions`` are plain long text (only Demos.Script,
# Clips/Modules."Learning Objectives", Modules."Brainstorming Outline" and
# Courses."Brainstorming Notes" are ``richText`` -- see coursecraft_cli/
# client.py), ``Name`` is single-line text, the Human Verified gate is a
# checkbox, and ``Template Name`` is an Airtable lookup.
# ---------------------------------------------------------------------------

_FIELD_TYPES = {
    "Slides": {
        "Name": "singleLineText",
        "Script": "multilineText",
        "Build Instructions": "multilineText",
        "Template Name": "multipleLookupValues",
        "Status": "singleSelect",
        "Script Human Verified": "checkbox",
        "Script Review (AI)": "multilineText",
        "Version Control": "multilineText",
    },
}


def _field_list(table):
    """The ``fields list <table>`` response shape: a list of metadata objects."""
    if table not in _FIELD_TYPES:
        raise AssertionError(f"No fixture field metadata for table {table!r}.")
    return [
        {"name": name, "type": field_type}
        for name, field_type in _FIELD_TYPES[table].items()
    ]


def _with_field_list(run):
    """Wrap a record-returning ``_run_airtable_command`` stub with metadata dispatch.

    ``fields list`` is answered from :data:`_FIELD_TYPES`; every other airtable
    CLI invocation falls through to ``run`` unchanged, so a stub that asserts
    "no write may be issued" still sees every real record command.
    """

    def dispatch(args):
        if args[:2] == ["fields", "list"]:
            return _field_list(args[2])
        return run(args)

    return dispatch


# The retired module-recap artifact used this real, course-scoped template.
# Current coverage-map.json deliberately has no slide.module_recap entry, so
# this template now resolves through the slide.content fallback.
_MODULE_RECAP_TEMPLATE_NAME = "Course Summary with Takeaways"


# ---------------------------------------------------------------------------
# Finding 2: check_write_conflict's Name/Script Human Verified false positive
# ---------------------------------------------------------------------------


def test_check_write_conflict_name_on_clip_intro_does_not_reject():
    """Name + Script Human Verified is legitimate on a non-module_recap slide."""
    av.check_write_conflict(
        "Slides",
        {"Name": "Intro to Widgets", "Script Human Verified": True},
        fetch_persisted_fields=lambda: {"Template Name": ["Clip Intro"]},
    )  # must not raise


def test_check_write_conflict_name_on_retired_module_recap_template_does_not_reject():
    """Name is no longer content after slide.module_recap's retirement."""
    av.check_write_conflict(
        "Slides",
        {"Name": "Recap", "Script Human Verified": True},
        fetch_persisted_fields=lambda: {
            "Template Name": [_MODULE_RECAP_TEMPLATE_NAME]
        },
    )


def test_check_write_conflict_name_unresolvable_type_does_not_reject():
    """An unresolvable real type (record vanished / blank Template) never guesses."""
    av.check_write_conflict(
        "Slides",
        {"Name": "Untitled", "Script Human Verified": True},
        fetch_persisted_fields=lambda: None,
    )  # must not raise -- unresolvable is not "prove it's module_recap"


def test_check_write_conflict_name_without_resolver_does_not_reject():
    """Name is validation-only for every current slide artifact."""
    av.check_write_conflict(
        "Slides", {"Name": "Intro", "Script Human Verified": True}
    )


def test_check_write_conflict_unambiguous_conflict_needs_zero_extra_reads():
    """Script + its paired review field is a real conflict on EVERY slide type --
    must reject without ever calling the resolver (zero extra reads)."""

    def _never_call():
        raise AssertionError("fetch_persisted_fields must not be called for an unambiguous conflict")

    with pytest.raises(av.VersioningError, match="slide"):
        av.check_write_conflict(
            "Slides",
            {"Script": "New body", "Script Human Verified": True},
            fetch_persisted_fields=_never_call,
        )


def test_check_write_conflict_demos_script_review_ai_zero_extra_reads():
    """Demos has no Slides-style ambiguity at all -- Script's single candidate
    slug (demo.script) rejects immediately, no resolver ever supplied or needed."""
    with pytest.raises(av.VersioningError, match="demo.script"):
        av.check_write_conflict(
            "Demos", {"Script": "New narration", "Script Review (AI)": "PASS"}
        )


def test_client_update_record_name_rename_on_clip_intro_slide_succeeds(monkeypatch):
    """End-to-end through the real client: renaming a Clip Intro slide's title
    alongside marking its script human-verified must reach Airtable, not be
    rejected as a phantom module_recap conflict."""
    client = _client()
    client.base_id = "appTEST"

    state = {"Name": "Old Title", "Script": "Body", "Template Name": ["Clip Intro"]}

    def fake_run(args):
        for token in args:
            if "=" not in token:
                continue
            key, _, raw_value = token.partition("=")
            try:
                state[key] = json.loads(raw_value)
            except json.JSONDecodeError:
                state[key] = raw_value
        return {"id": "recClipIntro1", "fields": dict(state)}

    def fake_get(table, record_id):
        return {"id": record_id, "fields": dict(state)}

    monkeypatch.setattr(client, "_run_airtable_command", _with_field_list(fake_run))
    monkeypatch.setattr(client, "get_record", fake_get)

    result = client.update_record(
        "Slides", "recClipIntro1", {"Name": "New Title", "Script Human Verified": True}
    )

    assert result["fields"]["Name"] == "New Title"
    assert result["fields"]["Script Human Verified"] is True


def test_client_update_record_name_rename_on_retired_module_recap_template_succeeds(monkeypatch):
    """Retired module-recap templates no longer make Name tracked content."""
    client = _client()
    client.base_id = "appTEST"

    state = {
        "Name": "Old Title",
        "Script": "Body",
        "Template Name": [_MODULE_RECAP_TEMPLATE_NAME],
    }

    def fake_run(args):
        for token in args:
            if "=" not in token:
                continue
            key, _, raw_value = token.partition("=")
            try:
                state[key] = json.loads(raw_value)
            except json.JSONDecodeError:
                state[key] = raw_value
        return {"id": "recFormerModuleRecap1", "fields": dict(state)}

    def fake_get(table, record_id):
        return {"id": record_id, "fields": dict(state)}

    monkeypatch.setattr(client, "_run_airtable_command", _with_field_list(fake_run))
    monkeypatch.setattr(client, "get_record", fake_get)

    result = client.update_record(
        "Slides", "recFormerModuleRecap1", {"Name": "New Title", "Script Human Verified": True}
    )

    assert result["fields"]["Name"] == "New Title"
    assert result["fields"]["Script Human Verified"] is True


# ---------------------------------------------------------------------------
# Finding 3: canonical_hash's file branch must never leak a raw OSError
# ---------------------------------------------------------------------------


def test_canonical_hash_permission_denied_raises_versioning_error(tmp_path, monkeypatch):
    monkeypatch.setattr(av, "COURSES_ROOT", tmp_path)
    bad_file = tmp_path / "voiceover.wav"
    bad_file.write_bytes(b"audio bytes")
    bad_file.chmod(0o000)
    try:
        with pytest.raises(av.VersioningError, match="could not be read"):
            av.canonical_hash("demo.dictation_audio", bad_file)
    finally:
        bad_file.chmod(0o644)


def test_canonical_hash_readable_file_still_hashes(tmp_path, monkeypatch):
    """Control: a normal readable file is unaffected by the try/except addition."""
    monkeypatch.setattr(av, "COURSES_ROOT", tmp_path)
    good_file = tmp_path / "voiceover.wav"
    good_file.write_bytes(b"audio bytes")
    digest = av.canonical_hash("demo.dictation_audio", good_file)
    assert digest == hashlib.sha256(b"audio bytes").hexdigest()


def test_versions_sync_permission_error_does_not_abort_course_walk(monkeypatch, tmp_path):
    """Finding-6-style repro extended to a permission failure: one bad-permission
    file-kind record plus one clean record in the same course walk -- the walk
    must complete, the clean record synced, the bad one reported in errors."""
    import typer
    from typer.testing import CliRunner
    from coursecraft_cli.commands import versions as versions_cmd

    course_folder = tmp_path / "course"
    demo_folder = course_folder / "m1c1-demo"
    demo_folder.mkdir(parents=True)
    bad_env_prep = demo_folder / "env_prep.ps1"
    bad_env_prep.write_text("# setup")
    bad_env_prep.chmod(0o000)

    monkeypatch.setattr(versions_cmd, "resolve_course_folder", lambda folder_root: demo_folder)
    # canonical_hash's path-containment check needs the file inside COURSES_ROOT.
    monkeypatch.setattr(av, "COURSES_ROOT", tmp_path)

    class FakeClient:
        def resolve_course_id(self, course):
            return "recCourse1"

        def get_record(self, table, record_id):
            assert table == "Courses"
            return {"id": record_id, "fields": {"Name": "Course"}}

        def get_modules_by_course(self, course_id):
            return [{"id": "recModule1", "fields": {"Order": 1}}]

        def get_clips_by_module(self, module_id):
            return [{"id": "recClip1", "fields": {"Order": 1}}]

        def get_demos_by_clip(self, clip_id):
            return [
                {
                    "id": "recDemoBad",
                    "fields": {"Folder Root": "m1c1-demo", "Version Control": "{}"},
                },
                {
                    "id": "recDemoGood",
                    "fields": {
                        "Learner Takeaway": "Real, non-empty content",
                        "Version Control": "{}",
                    },
                },
            ]

        def get_slides_by_clip(self, clip_id):
            return []

        def update_record(self, table, record_id, fields, _stamp_versions=False):
            self.last_update = (table, record_id, fields)
            return {"id": record_id, "fields": fields}

    fake_client = FakeClient()
    monkeypatch.setattr(versions_cmd, "get_client", lambda: fake_client)

    # Invoke the real registered command function through a throwaway Typer
    # app, not coursecraft_cli.main's shared ``versions_cmd.app`` singleton --
    # importing coursecraft_cli.main elsewhere in the same test session
    # installs a credential-check callback onto that shared app object,
    # which changes how Typer parses a single-command app's arguments. This
    # isolates the test from that ordering-dependent shared state while
    # still exercising the exact same command function CourseCraft ships.
    isolated_app = typer.Typer()
    isolated_app.command("sync")(versions_cmd.versions_sync)

    runner = CliRunner()
    try:
        result = runner.invoke(isolated_app, ["my-course"])
    finally:
        bad_env_prep.chmod(0o644)

    # A per-record failure still exits non-zero (documented behavior), but the
    # walk must have COMPLETED -- the clean Demos record synced, and the bad
    # Demos record reported in errors, not an unhandled OSError traceback.
    assert result.exit_code == 1, result.output
    payload, _ = json.JSONDecoder().raw_decode(result.output[result.output.index("{"):])
    synced_record_ids = {entry["record_id"] for entry in payload["synced"]}
    assert "recDemoGood" in synced_record_ids
    error_record_ids = {entry["record_id"] for entry in payload["errors"]}
    assert "recDemoBad" in error_record_ids
    assert "could not be read" in payload["errors"][0]["error"]
