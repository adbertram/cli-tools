"""Canonical human-verification projection and mutation contract."""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from coursecraft_cli import artifact_versions
from coursecraft_cli.commands import clips, courses, demos, human_verification, modules, slides
from coursecraft_cli.human_verification import (
    HumanVerificationError,
    HumanVerificationPreconditionError,
    build_human_verification_index,
    evaluate_human_verification_write,
    human_verification_clear_targets,
    human_verification_index,
    human_verification_projection,
)


runner = CliRunner()
PROJECT_ROOT = Path("/Users/adam/Dropbox/GitRepos/Agents/CourseCraft")
VALIDATION_TOOLS = Path(
    "/Users/adam/Dropbox/GitRepos/Agents/skills/project/coursecraft-validation/tools"
)


class FakeClient:
    def __init__(self, fields):
        self.fields = dict(fields)
        self.get_calls = []
        self.update_calls = []

    def get_record(self, table, record_id):
        self.get_calls.append((table, record_id))
        return {"id": record_id, "fields": dict(self.fields)}

    def update_record(self, table, record_id, fields):
        self.update_calls.append((table, record_id, dict(fields)))
        self.fields.update(fields)
        return {"id": record_id, "fields": dict(self.fields)}


def _argv(
    verb="set",
    *,
    artifact="demo.overview",
    gate="demos.overview",
    actor="human-ui",
    caller_agent=None,
):
    argv = [
        verb,
        "recDemo",
        "--artifact",
        artifact,
        "--gate",
        gate,
        "--actor",
        actor,
    ]
    if caller_agent is not None:
        argv.extend(["--caller-agent", caller_agent])
    return argv


def test_packaged_projection_exactly_matches_canonical_helper():
    sys.path.insert(0, str(VALIDATION_TOOLS))
    try:
        from _shared import (  # type: ignore
            build_human_verification_index as build_source_index,
            human_verification_cli_projection,
            load_human_verification,
        )
    finally:
        sys.path.pop(0)

    source = load_human_verification(PROJECT_ROOT / "course-pipeline.json", PROJECT_ROOT)
    source_index = build_source_index(source)
    expected = human_verification_cli_projection(source_index)
    assert human_verification_projection() == expected
    disabled_ids = {
        gate.id for gate in source_index.by_id.values() if gate.state != "active"
    }
    assert disabled_ids.isdisjoint(gate["id"] for gate in expected)
    assert all(
        set(gate)
        == {"id", "table", "field", "artifactIds", "owner", "clearOn", "prerequisites"}
        for gate in expected
    )


def test_projection_covers_many_gate_and_shared_field_artifacts():
    index = human_verification_index()
    assert [gate.id for gate in index.by_artifact_id["module.plan"]] == [
        "modules.description",
        "modules.learning_objectives",
    ]
    assert [gate.id for gate in index.by_artifact_id["slide.content"]] == [
        "slides.script",
        "slides.slide_type",
    ]
    assert index.by_table_field[("Demos", "Script Human Verified")].id == "demos.script"
    assert index.by_table_field[("Slides", "Script Human Verified")].id == "slides.script"


def test_every_projected_gate_clears_on_content_change():
    index = human_verification_index()
    for gate in index.by_id.values():
        assert gate.clear_on == ("content_change",)
        for artifact_id in gate.artifact_ids:
            assert gate.field in human_verification_clear_targets(
                artifact_id, gate.table, "content_change", index
            )


def test_built_wheel_contains_generated_projection(tmp_path):
    project = Path(__file__).resolve().parents[1]
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as wheel:
        assert "coursecraft_cli/data/human-verification.generated.json" in wheel.namelist()


@pytest.mark.parametrize(
    ("actor_kind", "caller_agent"),
    [("human_ui", None), ("artifact_agent", "coursecraft-demo-expert")],
)
def test_evaluator_accepts_both_authorized_actor_kinds(actor_kind, caller_agent):
    result = evaluate_human_verification_write(
        actor_kind,
        "demo.overview",
        "demos.overview",
        caller_agent,
        "recDemo",
        True,
        {"Demo Overview Human Verified": False},
        {("check", "Demo Overview Review (AI)"): True},
        human_verification_index(),
    )
    assert result["changed"] is True
    assert result["persisted_state"] is True


@pytest.mark.parametrize(
    ("actor_kind", "caller_agent", "code"),
    [
        ("artifact_agent", None, "HV_CALLER_AGENT_REQUIRED"),
        ("artifact_agent", "recording-expert", "HV_CALLER_AGENT"),
        ("human_ui", "coursecraft-demo-expert", "HV_CALLER_AGENT_FORBIDDEN"),
    ],
)
def test_evaluator_rejects_missing_wrong_or_forbidden_owner(actor_kind, caller_agent, code):
    with pytest.raises(HumanVerificationError, match=rf"\[{code}\]"):
        evaluate_human_verification_write(
            actor_kind,
            "demo.overview",
            "demos.overview",
            caller_agent,
            "recDemo",
            True,
            {},
            {("check", "Demo Overview Review (AI)"): True},
            human_verification_index(),
        )


def test_evaluator_reports_failed_prerequisites_in_declared_order():
    custom = build_human_verification_index(
        [
            {
                "id": "demos.first",
                "table": "Demos",
                "field": "First Human Verified",
                "artifactIds": ["demo.first"],
                "owner": "demo-owner",
                "clearOn": ["content_change"],
                "prerequisites": [],
            },
            {
                "id": "demos.target",
                "table": "Demos",
                "field": "Target Human Verified",
                "artifactIds": ["demo.target"],
                "owner": "demo-owner",
                "clearOn": ["content_change"],
                "prerequisites": [
                    {"kind": "check", "ref": "Review (AI)", "required_state": "passed"},
                    {"kind": "walkthrough", "ref": "walk", "required_state": "passed"},
                    {"kind": "gate", "ref": "demos.first", "required_state": "passed"},
                ],
            },
        ]
    )
    with pytest.raises(HumanVerificationPreconditionError) as raised:
        evaluate_human_verification_write(
            "artifact_agent",
            "demo.target",
            "demos.target",
            "demo-owner",
            "recDemo",
            True,
            {},
            {
                ("check", "Review (AI)"): False,
                ("walkthrough", "walk"): True,
                ("gate", "demos.first"): False,
            },
            custom,
        )
    assert [(item["kind"], item["ref"]) for item in raised.value.missing] == [
        ("check", "Review (AI)"),
        ("gate", "demos.first"),
    ]


def test_human_ui_set_writes_and_returns_normalized_readback(monkeypatch):
    fake = FakeClient({"Demo Overview Review (AI)": "  PASS\nReviewed-Version: demo.overview@v1"})
    monkeypatch.setattr(human_verification, "get_client", lambda: fake)

    result = runner.invoke(human_verification.app, _argv())

    assert result.exit_code == 0, result.output
    assert fake.update_calls == [
        ("Demos", "recDemo", {"Demo Overview Human Verified": True})
    ]
    assert json.loads(result.stdout) == {
        "actor_kind": "human_ui",
        "artifact_slug": "demo.overview",
        "gate_id": "demos.overview",
        "record_id": "recDemo",
        "table": "Demos",
        "field": "Demo Overview Human Verified",
        "requested_state": True,
        "changed": True,
        "persisted_state": True,
    }


def test_artifact_agent_set_requires_and_accepts_exact_owner(monkeypatch):
    fake = FakeClient({"Demo Overview Review (AI)": "PASS"})
    monkeypatch.setattr(human_verification, "get_client", lambda: fake)

    result = runner.invoke(
        human_verification.app,
        _argv(actor="artifact-agent", caller_agent="coursecraft-demo-expert"),
    )

    assert result.exit_code == 0, result.output
    assert fake.update_calls == [
        ("Demos", "recDemo", {"Demo Overview Human Verified": True})
    ]


def test_no_op_set_reads_but_does_not_mutate(monkeypatch):
    fake = FakeClient(
        {
            "Demo Overview Review (AI)": "PASS",
            "Demo Overview Human Verified": True,
        }
    )
    monkeypatch.setattr(human_verification, "get_client", lambda: fake)

    result = runner.invoke(human_verification.app, _argv())

    assert result.exit_code == 0, result.output
    assert fake.update_calls == []
    assert json.loads(result.stdout)["changed"] is False


def test_clear_skips_prerequisites_and_writes_false(monkeypatch):
    fake = FakeClient({"Demo Overview Human Verified": True})
    monkeypatch.setattr(human_verification, "get_client", lambda: fake)

    result = runner.invoke(human_verification.app, _argv("clear"))

    assert result.exit_code == 0, result.output
    assert fake.update_calls == [
        ("Demos", "recDemo", {"Demo Overview Human Verified": False})
    ]
    assert json.loads(result.stdout)["persisted_state"] is False


def test_walkthrough_prerequisite_uses_proven_walkthrough_field(monkeypatch):
    fake = FakeClient({"Walkthrough Test Complete": True})
    monkeypatch.setattr(human_verification, "get_client", lambda: fake)

    result = runner.invoke(
        human_verification.app,
        _argv(artifact="demo.script", gate="demos.script"),
    )

    assert result.exit_code == 0, result.output
    assert fake.update_calls == [("Demos", "recDemo", {"Script Human Verified": True})]


def test_prerequisite_rejection_performs_zero_mutations(monkeypatch):
    fake = FakeClient({"Demo Overview Review (AI)": "FAIL"})
    monkeypatch.setattr(human_verification, "get_client", lambda: fake)

    result = runner.invoke(human_verification.app, _argv())

    assert result.exit_code == 1
    assert "[HV_PREREQUISITE]" in result.output
    assert fake.update_calls == []


@pytest.mark.parametrize(
    "argv,code",
    [
        (_argv(gate="missing.gate"), "HV_GATE"),
        (_argv(artifact="demo.script"), "HV_ARTIFACT_GATE"),
        (_argv(actor="artifact-agent"), "HV_CALLER_AGENT_REQUIRED"),
        (
            _argv(actor="artifact-agent", caller_agent="recording-expert"),
            "HV_CALLER_AGENT",
        ),
        (_argv(caller_agent="coursecraft-demo-expert"), "HV_CALLER_AGENT_FORBIDDEN"),
    ],
)
def test_identity_rejections_happen_before_client_access(monkeypatch, argv, code):
    def unexpected_client_access():
        raise AssertionError("client accessed before identity validation")

    monkeypatch.setattr(human_verification, "get_client", unexpected_client_access)
    result = runner.invoke(human_verification.app, argv)
    assert result.exit_code == 1
    assert f"[{code}]" in result.output


def test_successful_write_requires_matching_readback(monkeypatch):
    fake = FakeClient({"Demo Overview Review (AI)": "PASS"})

    def bad_update(table, record_id, fields):
        fake.update_calls.append((table, record_id, dict(fields)))
        return {"id": record_id, "fields": {}}

    fake.update_record = bad_update
    monkeypatch.setattr(human_verification, "get_client", lambda: fake)

    result = runner.invoke(human_verification.app, _argv())

    assert result.exit_code == 1
    assert "[HV_READBACK]" in result.output


@pytest.mark.parametrize(
    ("command_app", "flag"),
    [
        (courses.app, "--outline-draft-human-verified"),
        (courses.app, "--carry-forward-plan-human-verified"),
        (modules.app, "--powerpoint-deck-human-verified"),
        (modules.app, "--slide-build-review-human-verified"),
        (modules.app, "--description-human-verified"),
        (modules.app, "--learning-objectives-human-verified"),
        (modules.app, "--brainstorming-outline-human-verified"),
        (clips.app, "--recording-review-human"),
        (demos.app, "--demo-overview-review-human"),
        (demos.app, "--action-summary-review-human"),
        (demos.app, "--script-review-human"),
        (demos.app, "--recording-review-human"),
        (slides.app, "--slide-type-human-verified"),
        (slides.app, "--script-human-verified"),
    ],
)
def test_retired_per_field_options_fail_during_parse(command_app, flag):
    result = runner.invoke(command_app, ["update", "recRecord", flag])
    assert result.exit_code == 2
    assert "No such option" in result.output


def test_registry_clears_all_same_record_gates_and_retains_unrelated_stamps():
    assert set(artifact_versions._paired_review_targets("module.plan")) >= {
        "Plan Review (AI)",
        "Description Human Verified",
        "Learning Objectives Human Verified",
    }
    assert set(artifact_versions._paired_review_targets("demo.overview")) >= {
        "Demo Overview Review (AI)",
        "Demo Overview Human Verified",
    }
    assert "Recording Human Verified" not in artifact_versions._paired_review_targets(
        "demo.overview"
    )


def test_stamp_only_write_does_not_change_version_or_other_fields():
    planned = artifact_versions.plan_record_update(
        "Demos",
        "recDemo",
        {"Demo Overview Human Verified": True},
        {
            "Demo Overview": "Existing overview",
            "Demo Overview Human Verified": False,
            "Version Control": json.dumps(
                {
                    "demo.overview": {
                        "v": 4,
                        "sha256": "existing",
                        "at": "2026-09-06T00:00:00Z",
                    }
                }
            ),
        },
        {},
    )
    assert planned == {"Demo Overview Human Verified": True}
