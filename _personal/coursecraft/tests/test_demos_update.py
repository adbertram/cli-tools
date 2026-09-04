import json

from typer.testing import CliRunner

from coursecraft_cli.commands import demos
from coursecraft_cli.coursecraft_project import coursecraft_project_root
from coursecraft_cli.field_mappings import FIELD_MAPPINGS


runner = CliRunner()


def _demo_script(narration: str) -> str:
    return (
        f"{narration}\n\n"
        "<click the Sign up button on the Event sign-up page>\n\n"
        "The confirmation appears."
    )


class FakeClient:
    def __init__(self):
        self.updated_fields = None
        self.listed_records = [
            {
                "id": "recExistingDemo",
                "fields": {
                    "Name": "Existing",
                    "Status": "Designing",
                    "Demo Overview": "Overview text",
                },
            }
        ]
        # Slides linked back to a demo via its "Demo" field. Empty by default
        # so existing tests (which never touch the Slides table) are unaffected;
        # dependency-graph-reminder tests set this to exercise the Demo Intro
        # Slide lookup.
        self.listed_slides = []

    def get_record(self, table_name, record_id):
        assert table_name == "Demos"
        assert record_id == "recExistingDemo"
        return {"id": record_id, "fields": {"Name": "Existing"}}

    def list_records(self, table_name, formula=None):
        if table_name == "Slides":
            return self.listed_slides
        assert table_name == "Demos"
        assert formula == "{Clip Record ID}='recClip'"
        return self.listed_records

    def update_record(self, table_name, record_id, fields):
        assert table_name == "Demos"
        assert record_id == "recExistingDemo"
        self.updated_fields = fields

    def check_demo_exists(self, name, clip_record_id):
        return None

    def create_record(self, table_name, fields):
        assert table_name == "Demos"
        self.updated_fields = fields
        return "recCreatedDemo"


def test_create_demo_does_not_require_environment(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "create",
            "--clip",
            "recClip",
            "--clip-order",
            "1",
            "--name",
            "Demo",
        ],
    )

    assert result.exit_code == 0
    # Create always writes its own Recording Dictation Method: the option
    # defaults to manual instructor generation and is never inherited from the
    # course-level field.
    assert fake_client.updated_fields == {
        "Clip": ["recClip"],
        "Clip Order": 1,
        "Name": "Demo",
        "Recording Dictation Method": "Manual Instructor Generation",
    }


def test_create_demo_accepts_execution_method(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "create",
            "--clip",
            "recClip",
            "--clip-order",
            "1",
            "--name",
            "Demo",
            "--execution-method",
            "Manual Instructor",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {
        "Clip": ["recClip"],
        "Clip Order": 1,
        "Name": "Demo",
        "Execution Method": "Manual Instructor",
        "Recording Dictation Method": "Manual Instructor Generation",
    }


def test_create_demo_writes_target_length_to_target_length_min(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "create",
            "--clip",
            "recClip",
            "--clip-order",
            "1",
            "--name",
            "Demo",
            "--target-length",
            "2",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {
        "Clip": ["recClip"],
        "Clip Order": 1,
        "Name": "Demo",
        "Target Length (Min)": 2.0,
        "Recording Dictation Method": "Manual Instructor Generation",
    }


def test_create_demo_batch_accepts_execution_method(monkeypatch):
    fake_client = FakeClient()
    created = []

    def record_create(table_name, fields):
        assert table_name == "Demos"
        created.append(fields)
        return f"recCreated{len(created)}"

    fake_client.create_record = record_create
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "create",
            "--clip",
            "recClip",
            "--clip-order",
            "1",
            "--execution-method",
            "Automated Walkthrough",
            "--json",
            json.dumps(
                [
                    {"name": "Demo One", "clip_order": 1},
                    {
                        "name": "Demo Two",
                        "clip_order": 2,
                        "execution_method": "Manual Instructor",
                    },
                ]
            ),
        ],
    )

    assert result.exit_code == 0
    assert created[0]["Execution Method"] == "Automated Walkthrough"
    assert created[1]["Execution Method"] == "Manual Instructor"


def test_create_demo_batch_writes_target_length_to_target_length_min(monkeypatch):
    fake_client = FakeClient()
    created = []

    def record_create(table_name, fields):
        assert table_name == "Demos"
        created.append(fields)
        return f"recCreated{len(created)}"

    fake_client.create_record = record_create
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "create",
            "--clip",
            "recClip",
            "--clip-order",
            "1",
            "--json",
            json.dumps(
                [
                    {"name": "Demo One", "clip_order": 1, "target_length": 2},
                    {"name": "Demo Two", "clip_order": 2},
                ]
            ),
        ],
    )

    assert result.exit_code == 0
    assert created[0]["Target Length (Min)"] == 2
    assert "Estimated Length" not in created[0]
    assert "Estimated Length" not in created[1]


def test_create_demo_rejects_invalid_execution_method(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "create",
            "--clip",
            "recClip",
            "--clip-order",
            "1",
            "--name",
            "Demo",
            "--execution-method",
            "Bogus Value",
        ],
    )

    assert result.exit_code == 2
    assert "Invalid value" in result.output
    assert fake_client.updated_fields is None


def test_create_demo_help_does_not_expose_demo_environment():
    result = runner.invoke(demos.app, ["create", "--help"], terminal_width=200)

    assert result.exit_code == 0
    assert "--demo-environment" not in result.output


def test_create_demo_rejects_demo_environment_option(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "create",
            "--clip",
            "recClip",
            "--clip-order",
            "1",
            "--name",
            "Demo",
            "--demo-environment",
            "azure-adam-the-automator",
            "--demo-environment",
            "local-macos",
        ],
    )

    assert result.exit_code == 2
    assert "No such option" in result.output
    assert "--demo-environment" in result.output
    assert fake_client.updated_fields is None


def test_update_demo_accepts_execution_method(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--execution-method",
            "Automated Walkthrough",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {"Execution Method": "Automated Walkthrough"}


def test_update_demo_accepts_recording_dictation_method(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--recording-dictation-method",
            "Automatic Narration Generation",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {
        "Recording Dictation Method": "Automatic Narration Generation"
    }


def test_update_demo_outputs_record_id_as_json(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        ["update", "recExistingDemo", "--notes", "Reviewed"],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == "recExistingDemo"
    assert "Updated demo: recExistingDemo" in result.stderr


def test_update_demo_writes_target_length_to_target_length_min(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--target-length",
            "2",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {"Target Length (Min)": 2.0}


def test_update_demo_rejects_invalid_execution_method(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--execution-method",
            "Bogus Value",
        ],
    )

    assert result.exit_code == 2
    assert "Invalid value" in result.output
    assert fake_client.updated_fields is None


def test_demo_execution_method_enum_values():
    # The enum is the single source of truth for the allowed Airtable option
    # labels; asserting on it avoids depending on Rich's help-text line wrapping.
    assert [m.value for m in demos.DemoExecutionMethod] == [
        "Automated Walkthrough",
        "Manual Instructor",
        "Manual Step-Through",
    ]


def test_update_demo_help_lists_execution_method_option():
    result = runner.invoke(demos.app, ["update", "--help"], terminal_width=200)

    assert result.exit_code == 0
    assert "--execution-method" in result.output


def test_update_demo_accepts_proof_state(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        ["update", "recExistingDemo", "--proof-state", "Walking"],
    )

    assert result.exit_code == 0, result.output
    assert fake_client.updated_fields == {"Proof State": "Walking"}


def test_update_demo_rejects_invalid_proof_state(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        ["update", "recExistingDemo", "--proof-state", "Bogus"],
    )

    assert result.exit_code == 2
    assert "Invalid value" in result.output
    assert fake_client.updated_fields is None


def test_demo_proof_state_enum_matches_lane_states_registry_in_order():
    """``DemoProofState`` is a projection of the fleet lane-state registry.

    The registry (``lane-states.json`` in the CourseCraft checkout) is the one
    table the Airtable ``Proof State`` single-select and this enum both derive
    from, so the member VALUES must equal its ``state`` column in file order.
    """
    registry_path = (
        coursecraft_project_root()
        / ".agents/skills/demo-execute/scripts/coursecraft_demo_fleet/lane-states.json"
    )
    assert registry_path.is_file(), registry_path
    rows = json.loads(registry_path.read_text(encoding="utf-8"))["rows"]
    expected = [row["state"] for row in rows]

    assert len(expected) == 16
    assert [m.value for m in demos.DemoProofState] == expected


def test_update_demo_help_lists_proof_state_and_not_retired_path():
    result = runner.invoke(demos.app, ["update", "--help"], terminal_width=200)

    assert result.exit_code == 0
    assert "--proof-state" in result.output
    assert "--path" not in result.output


def test_update_demo_rejects_retired_path_option(monkeypatch):
    """The Demos ``Path`` field is retired; ``--path`` is an unknown option."""
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        ["update", "recExistingDemo", "--path", "GitHub Actions"],
    )

    assert result.exit_code == 2
    assert "No such option" in result.output
    assert "--path" in result.output
    assert fake_client.updated_fields is None


def test_create_demo_rejects_retired_path_option(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    help_result = runner.invoke(demos.app, ["create", "--help"], terminal_width=200)
    result = runner.invoke(
        demos.app,
        [
            "create",
            "--clip",
            "recClip",
            "--clip-order",
            "1",
            "--name",
            "Demo",
            "--path",
            "Adam Server",
        ],
    )

    assert help_result.exit_code == 0
    assert "--path" not in help_result.output
    assert result.exit_code == 2
    assert "No such option" in result.output
    assert fake_client.updated_fields is None


def test_create_demo_batch_ignores_no_retired_path_key(monkeypatch):
    """A batch ``path`` key has no CLI home any more: it must never reach Airtable."""
    fake_client = FakeClient()
    created = []

    def record_create(table_name, fields):
        assert table_name == "Demos"
        created.append(fields)
        return f"recCreated{len(created)}"

    fake_client.create_record = record_create
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "create",
            "--clip",
            "recClip",
            "--clip-order",
            "1",
            "--json",
            json.dumps([{"name": "Demo One", "clip_order": 1, "path": "Adam Server"}]),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Path" not in created[0]


def test_update_demo_accepts_clip_reparent(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--clip",
            "recNewClip",
        ],
    )

    assert result.exit_code == 0
    # The Clip linked-record field is written as a single-element array; the
    # client applies --typecast and JSON-encodes the list (see client.py).
    assert fake_client.updated_fields == {"Clip": ["recNewClip"]}


def test_update_demo_accepts_clip_unlink(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--clip",
            "",
        ],
    )

    assert result.exit_code == 0
    # An empty string is the unlink sentinel: it must send an empty linked-record
    # array, never a single-element list containing "" (which Airtable rejects as
    # an invalid record ID -- see the coursecraft-cli skill Known Issues log).
    assert fake_client.updated_fields == {"Clip": []}


def test_update_demo_help_lists_clip_option():
    result = runner.invoke(demos.app, ["update", "--help"], terminal_width=200)

    assert result.exit_code == 0
    assert "--clip " in result.output


def test_update_demo_accepts_dictation_recorded(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--dictation-recorded",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {"Dictation Recorded": True}


def test_update_demo_accepts_audio_synced(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--audio-synced",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {"Audio Synced": True}


def test_update_demo_accepts_no_audio_synced(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--no-audio-synced",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {"Audio Synced": False}


def test_update_demo_accepts_recording_review_human(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--recording-review-human",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {"Recording Human Verified": True}


def test_update_demo_accepts_no_recording_review_human(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--no-recording-review-human",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {"Recording Human Verified": False}


def test_update_demo_has_no_voice_recording_path_option(monkeypatch):
    """A demo's take path is derived from Folder Root, so it is never written."""
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    help_result = runner.invoke(demos.app, ["update", "--help"], terminal_width=200)
    removed_flag_result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--voice-recording-path",
            "/path/to/course/m2c3/demos/recExistingDemo.mp3",
        ],
    )

    assert help_result.exit_code == 0
    assert "--voice-recording-path" not in help_result.output
    assert removed_flag_result.exit_code == 2
    assert "No such option" in removed_flag_result.output
    assert fake_client.updated_fields is None


def _manual_take_fields(folder_root):
    return {
        "Name": "Existing",
        "Folder Root": str(folder_root),
        "Recording Dictation Method": "Manual Instructor Generation",
        "Dictation Recorded": True,
        "Script": _demo_script("Original narration."),
    }


def test_preserve_manual_voice_recording_derives_take_from_folder_root(monkeypatch, tmp_path):
    """The take is derived as <Folder Root>/voiceover.edited.wav, never read from a field."""
    updated_script = _demo_script("Corrected narration.")
    take_path = tmp_path / "voiceover.edited.wav"
    take_path.write_bytes(b"audio")
    fake_client = FakeClient()
    fake_client.get_record = lambda table_name, record_id: {
        "id": record_id,
        "fields": _manual_take_fields(tmp_path),
    }
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)
    verified = []
    monkeypatch.setattr(
        demos,
        "validate_manual_demo_narration",
        lambda fields, script, voice_path: verified.append(voice_path) or {"valid": True},
    )

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--script",
            updated_script,
            "--preserve-manual-voice-recording",
        ],
    )

    assert result.exit_code == 0, result.output
    assert verified == [take_path]
    # The preserved take keeps every voice field. The Script update resets the
    # rendered-audio state (Audio Synced/Recorded stay command-side -- see
    # commands/demos.py), while the unchanged cue keeps Walkthrough Test
    # Complete intact. Script Review (AI)/Script Human Verified auto-clear on
    # a real content change is now owned by the write-time versioning engine
    # (coursecraft_cli.artifact_versions), not this command.
    assert fake_client.updated_fields == {
        "Script": updated_script,
        "Audio Synced": False,
        "Recorded": False,
    }


def test_preserve_manual_voice_recording_requires_a_derivable_take(monkeypatch, tmp_path):
    """No file at the derived location fails loudly; there is no stored path to fall back on."""
    fake_client = FakeClient()
    fake_client.get_record = lambda table_name, record_id: {
        "id": record_id,
        "fields": _manual_take_fields(tmp_path),
    }
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--script",
            "Corrected narration.",
            "--preserve-manual-voice-recording",
        ],
    )

    assert result.exit_code != 0
    assert fake_client.updated_fields is None


def test_update_demo_accepts_walkthrough_test_complete(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--walkthrough-test-complete",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {"Walkthrough Test Complete": True}


def test_update_demo_accepts_no_walkthrough_test_complete(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        ["update", "recExistingDemo", "--no-walkthrough-test-complete"],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {"Walkthrough Test Complete": False}


def test_update_demo_has_no_tested_approved_compatibility_alias():
    help_result = runner.invoke(demos.app, ["update", "--help"], terminal_width=200)
    old_flag_result = runner.invoke(
        demos.app,
        ["update", "recExistingDemo", "--tested-approved"],
    )

    assert help_result.exit_code == 0
    assert "--walkthrough-test-complete" in help_result.output
    assert "--tested-approved" not in help_result.output
    assert old_flag_result.exit_code == 2
    assert "No such option" in old_flag_result.output


def test_demo_field_mapping_uses_walkthrough_test_complete_only():
    assert FIELD_MAPPINGS["Demos"]["walkthrough_test_complete"] == "Walkthrough Test Complete"
    assert "tested_approved" not in FIELD_MAPPINGS["Demos"]


def test_demo_overview_change_should_preserve_walk_proof_when_host_action_is_none(monkeypatch):
    router = demos.load_router()
    assert (
        router["automated_walkthrough_policy"]["review_impact_map"]["overview"]["hostAction"]
        == "none"
    )

    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        ["update", "recExistingDemo", "--demo-overview", "Updated overview"],
    )

    assert result.exit_code == 0
    # Demo Overview Review (AI)/Human Verified auto-clear on a real content
    # change is now owned by the write-time versioning engine
    # (coursecraft_cli.artifact_versions), not this command.
    assert fake_client.updated_fields == {"Demo Overview": "Updated overview"}
    assert "Cleared Walkthrough Test Complete" not in result.stderr


def test_demo_source_change_should_fail_when_review_delta_is_unmapped(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)
    monkeypatch.setattr(demos, "load_router", lambda: {})

    result = runner.invoke(
        demos.app,
        ["update", "recExistingDemo", "--demo-overview", "Updated overview"],
    )

    assert result.exit_code == 1
    assert "UNMAPPED_REVIEW_DELTA: overview" in result.stderr
    assert fake_client.updated_fields is None


def test_demo_walk_source_changes_clear_walkthrough_test_complete(monkeypatch):
    # Walkthrough Test Complete invalidation stays command-side (it consults
    # the proven-walk contract, not a paired review field). The paired
    # "... Review (AI)"/Human Verified auto-clear moved to the write-time
    # versioning engine (coursecraft_cli.artifact_versions).
    cases = (
        ("--environment-spec", "Updated environment", "Environment Spec"),
        ("--action-summary", "Updated actions", "Action Summary"),
    )

    for option, value, field_name in cases:
        fake_client = FakeClient()
        monkeypatch.setattr(demos, "get_client", lambda: fake_client)

        result = runner.invoke(
            demos.app,
            ["update", "recExistingDemo", option, value],
        )

        assert result.exit_code == 0
        assert fake_client.updated_fields == {
            field_name: value,
            "Walkthrough Test Complete": False,
        }


def test_demo_content_resubmission_no_op_does_not_clear_paired_fields(monkeypatch):
    # Resubmitting the exact same (stripped) content must not clear Walkthrough Test Complete
    # or the paired AI-review/human-verified fields.
    fake_client = FakeClient()
    fake_client.get_record = lambda table_name, record_id: {
        "id": record_id,
        "fields": {
            "Name": "Existing",
            "Demo Overview": "Same overview",
            "Walkthrough Test Complete": True,
            "Demo Overview Review (AI)": "Looks good",
            "Demo Overview Human Verified": True,
        },
    }
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        ["update", "recExistingDemo", "--demo-overview", "Same overview  "],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {"Demo Overview": "Same overview  "}


def test_demo_content_change_with_explicit_review_human_reaches_client(monkeypatch):
    # The mutual-exclusion reject for "content changed + its paired review
    # field explicitly set in the same call" is now owned by the write-time
    # versioning engine's stamp_versions, at the real client.update_record
    # chokepoint -- FakeClient has no such logic, so both values now reach
    # it together. See coursecraft_cli.artifact_versions.stamp_versions and
    # its VersioningError for the real (client-level) rejection behavior.
    fake_client = FakeClient()
    fake_client.get_record = lambda table_name, record_id: {
        "id": record_id,
        "fields": {"Name": "Existing", "Action Summary": "Old summary"},
    }
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--action-summary",
            "New summary",
            "--action-summary-review-human",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields["Action Summary"] == "New summary"
    assert fake_client.updated_fields["Action Summary Human Verified"] is True


def test_demo_content_change_with_explicit_review_ai_reaches_client(monkeypatch):
    fake_client = FakeClient()
    fake_client.get_record = lambda table_name, record_id: {
        "id": record_id,
        "fields": {"Name": "Existing", "Script": _demo_script("Old script.")},
    }
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--script",
            _demo_script("New script."),
            "--script-review-ai",
            "Needs work",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields["Script"] == _demo_script("New script.")
    assert fake_client.updated_fields["Script Review (AI)"] == "Needs work"


def test_demo_no_op_content_with_explicit_review_flag_is_respected(monkeypatch):
    # A no-op resubmission combined with an explicit review flag is fine: the
    # explicit value is respected, not silently overwritten.
    fake_client = FakeClient()
    fake_client.get_record = lambda table_name, record_id: {
        "id": record_id,
        "fields": {"Name": "Existing", "Script": "Same script"},
    }
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--script",
            "Same script",
            "--script-review-human",
        ],
    )

    assert result.exit_code == 0
    # --script always triggers the (pre-existing, unrelated) voice-recording
    # invalidation fields regardless of content change; only the paired
    # review flag behavior is under test here.
    assert fake_client.updated_fields["Script"] == "Same script"
    assert fake_client.updated_fields["Script Human Verified"] is True


def test_demo_non_design_update_does_not_touch_walkthrough_test_complete(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        ["update", "recExistingDemo", "--notes", "Internal note"],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {"Notes": "Internal note"}


def test_demo_script_update_never_rewrites_remote_walkthrough_test_complete(monkeypatch):
    # A --script update must omit Walkthrough Test Complete from the payload entirely. Writing
    # it back from this process's own read would clobber a value another
    # machine set after that read (e.g. finalize_walkthrough marking the demo
    # Walkthrough Test Complete on adam-server while this laptop still holds the stale copy).
    fake_client = FakeClient()
    fake_client.get_record = lambda table_name, record_id: {
        "id": record_id,
        "fields": {
            "Name": "Existing",
            "Script": _demo_script("Old script."),
            "Walkthrough Test Complete": True,
        },
    }
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        ["update", "recExistingDemo", "--script", _demo_script("New script.")],
    )

    assert result.exit_code == 0
    assert "Walkthrough Test Complete" not in fake_client.updated_fields


def test_demo_walk_source_update_rejects_walkthrough_test_complete_finalization(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--environment-spec",
            "Updated environment",
            "--walkthrough-test-complete",
        ],
    )

    assert result.exit_code == 1
    assert "Update the content first" in result.output
    assert fake_client.updated_fields is None


def test_update_demo_accepts_action_summary_review_ai(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--action-summary-review-ai",
            "The action summary needs tighter step ordering.",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {
        "Action Summary Review (AI)": "The action summary needs tighter step ordering.",
    }


def test_update_demo_accepts_demo_overview_review_ai(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--demo-overview-review-ai",
            "The demo overview should name the target audience.",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {
        "Demo Overview Review (AI)": "The demo overview should name the target audience.",
    }


def test_update_demo_accepts_environment_spec_review_ai(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--environment-spec-review-ai",
            "The environment spec is missing the required CLI version.",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {
        "Environment Spec Review (AI)": "The environment spec is missing the required CLI version.",
    }


def test_update_demo_accepts_demo_overview_review_human(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--demo-overview-review-human",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {"Demo Overview Human Verified": True}


def test_update_demo_accepts_no_demo_overview_review_human(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--no-demo-overview-review-human",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {"Demo Overview Human Verified": False}


def test_update_demo_accepts_action_summary_review_human(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--action-summary-review-human",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {"Action Summary Human Verified": True}


def test_update_demo_accepts_script_review_human(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--script-review-human",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {"Script Human Verified": True}


def test_update_demo_accepts_bulk_human_review_completion_flags(monkeypatch):
    # Bulk-setting review-completion flags with no accompanying content change
    # (a content change combined with its own paired review flag is rejected
    # -- see test_demo_content_change_rejects_explicit_review_human_same_call).
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--demo-overview-review-human",
            "--action-summary-review-human",
            "--script-review-human",
            "--recorded",
            "--recording-review-human",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {
        "Demo Overview Human Verified": True,
        "Action Summary Human Verified": True,
        "Script Human Verified": True,
        "Recorded": True,
        "Recording Human Verified": True,
    }


def test_update_demo_accepts_no_action_summary_review_human(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--no-action-summary-review-human",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {"Action Summary Human Verified": False}


def test_update_demo_rejects_old_action_summary_human_review_complete_flag(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--action-summary-human-review-complete",
        ],
    )

    assert result.exit_code == 2
    assert "No such option" in result.output
    assert "--action-summary-human-review-complete" in result.output
    assert fake_client.updated_fields is None


def test_update_demo_rejects_demo_walkthrough_script_created(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--demo-walkthrough-script-created",
        ],
    )

    assert result.exit_code == 2
    assert "No such option" in result.output
    assert "--demo-walkthrough-script-created" in result.output
    assert fake_client.updated_fields is None


def test_update_demo_rejects_demo_walkthrough_script_options(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        ["update", "recExistingDemo", "--demo-walkthrough-script-path", "/path/to/course/m2c3/demo_walkthrough.ps1"],
        terminal_width=200,
    )

    assert result.exit_code == 2
    assert "No such option" in result.output
    assert "--demo-walkthrough-script-path" in result.output
    assert fake_client.updated_fields is None


def test_demo_field_mappings_target_length_uses_writable_target_length_field():
    assert FIELD_MAPPINGS["Demos"]["target_length"] == "Target Length (Min)"


def test_get_demo_accepts_properties(monkeypatch):
    fake_client = FakeClient()
    fake_client.get_record = lambda table_name, record_id: {
        "id": record_id,
        "fields": {
            "Name": "Existing",
            "Action Summary": "Summary text",
            "Script": "Script text",
        },
    }
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "get",
            "recExistingDemo",
            "--properties",
            "id,fields.Name,fields.Action Summary,fields.Script",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "id": "recExistingDemo",
        "fields.Name": "Existing",
        "fields.Action Summary": "Summary text",
        "fields.Script": "Script text",
    }


def test_get_demo_properties_reported_artifact_projection(monkeypatch):
    fake_client = FakeClient()
    fake_client.get_record = lambda table_name, record_id: {
        "id": record_id,
        "fields": {
            "Name": "Triaging SQL with Copilot",
            "Demo Overview": "Overview text",
            "Action Summary": "Summary text",
            "Script": "Script text",
            "Folder Root": "ai-native-tuning-modern-resilience-patterns/m1/demos/59 - Triaging SQL with Copilot",
            "Execution Method": "VS Code",
            "Target Length (Min)": 3,
            "Script Review (AI)": "Review text",
            "Status": "Designing (Human Script Review)",
        },
    }
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "get",
            "recExistingDemo",
            "--properties",
            "id,fields.Name,fields.Demo Overview,fields.Action Summary,fields.Script,fields.Folder Root,fields.Execution Method,fields.Target Length (Min),fields.Script Review (AI),fields.Status",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "id": "recExistingDemo",
        "fields.Name": "Triaging SQL with Copilot",
        "fields.Demo Overview": "Overview text",
        "fields.Action Summary": "Summary text",
        "fields.Script": "Script text",
        "fields.Folder Root": "ai-native-tuning-modern-resilience-patterns/m1/demos/59 - Triaging SQL with Copilot",
        "fields.Execution Method": "VS Code",
        "fields.Target Length (Min)": 3,
        "fields.Script Review (AI)": "Review text",
        "fields.Status": "Designing (Human Script Review)",
    }


def test_list_demo_properties_project_dot_notation_to_flat_keys(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "list",
            "--clip",
            "recClip",
            "--properties",
            "id,fields.Name,fields.Status,fields.Demo Overview",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == [
        {
            "id": "recExistingDemo",
            "fields.Name": "Existing",
            "fields.Status": "Designing",
            "fields.Demo Overview": "Overview text",
        }
    ]


def test_get_demo_properties_bare_field_name_returns_populated_value(monkeypatch):
    """A bare Airtable field name (no ``fields.`` prefix) must resolve to the
    populated value, not project ``null``. Regression for ``--properties
    "Environment Spec"`` nulling an 8322-char field: the bare name was looked up
    at the record top level (where it never exists) instead of inside ``fields``.
    Field names contain spaces, so the space-containing name must work too.
    """
    spec_value = "S" * 8322
    fake_client = FakeClient()
    fake_client.get_record = lambda table_name, record_id: {
        "id": record_id,
        "fields": {
            "Name": "Existing",
            "Environment Spec": spec_value,
        },
    }
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        ["get", "recExistingDemo", "--properties", "Environment Spec"],
    )

    assert result.exit_code == 0
    # Bare name normalizes to the same flat key as the documented dotted form.
    assert json.loads(result.output) == {"fields.Environment Spec": spec_value}


def test_get_demo_properties_bare_empty_field_projects_explicit_null(monkeypatch):
    """A genuinely-empty/absent field requested by bare name still projects an
    explicit ``null`` with the key present (never silently dropped), matching the
    shared projection contract.
    """
    fake_client = FakeClient()
    fake_client.get_record = lambda table_name, record_id: {
        "id": record_id,
        "fields": {"Name": "Existing"},  # no "Voice Source Hash"
    }
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        ["get", "recExistingDemo", "--properties", "Voice Source Hash"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload == {"fields.Voice Source Hash": None}
    assert "fields.Voice Source Hash" in payload  # key present, not dropped


def test_get_demo_properties_bare_and_dotted_are_equivalent(monkeypatch):
    """Bare and dotted forms of the same field project identical output, and a
    bare name mixes correctly with the top-level ``id`` key.
    """
    fake_client = FakeClient()
    fake_client.get_record = lambda table_name, record_id: {
        "id": record_id,
        "fields": {"Name": "Existing", "Status": "Designing"},
    }
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    bare = runner.invoke(
        demos.app,
        ["get", "recExistingDemo", "--properties", "id,Name,Status"],
    )
    dotted = runner.invoke(
        demos.app,
        ["get", "recExistingDemo", "--properties", "id,fields.Name,fields.Status"],
    )

    assert bare.exit_code == 0
    assert dotted.exit_code == 0
    assert json.loads(bare.output) == json.loads(dotted.output)
    assert json.loads(bare.output) == {
        "id": "recExistingDemo",
        "fields.Name": "Existing",
        "fields.Status": "Designing",
    }


def test_list_demo_properties_bare_field_name_returns_populated_value(monkeypatch):
    """The list projection path shares the same normalization: a bare field name
    resolves to the populated ``fields`` value.
    """
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        ["list", "--clip", "recClip", "--properties", "id,Name,Demo Overview"],
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == [
        {
            "id": "recExistingDemo",
            "fields.Name": "Existing",
            "fields.Demo Overview": "Overview text",
        }
    ]


def test_get_demo_output_is_escape_free_json(monkeypatch):
    """`demos get` stdout must be machine-readable JSON with no terminal escapes.

    Guards the documented ``--no-cache get`` write-verification path: print_json
    writes raw JSON bytes (no OSC/ANSI color), so the output pipes cleanly to
    ``jq``. Any OSC sequence an agent sees around the JSON (e.g. a shell
    background-color query like ``\x1b]11;#1e1e1e\x1b\\``) comes from the
    surrounding terminal, never from this command's stdout.
    """
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(demos.app, ["get", "recExistingDemo"])

    assert result.exit_code == 0
    assert "\x1b" not in result.output  # ESC byte (OSC/ANSI) must be absent
    assert "\033" not in result.output  # same byte, octal spelling
    parsed = json.loads(result.output)  # raises if stdout is not pure JSON
    assert parsed["id"] == "recExistingDemo"
    assert parsed["fields"]["Name"] == "Existing"


def test_demo_script_update_review_reminder_includes_action_summary_and_demo_intro_slide(monkeypatch):
    """A --script edit is graph-driven, not a fixed pair: course-pipeline.json
    puts Action Summary (same consistency cluster) and the Demo Intro Slide
    (also a cluster sibling, resolved via the linked Slides record) both in
    scope for review, not just the one hardcoded Script<->Action Summary pair.
    """
    fake_client = FakeClient()
    fake_client.get_record = lambda table_name, record_id: {
        "id": record_id,
        "fields": {"Name": "Existing", "Action Summary": "Old action summary"},
    }
    fake_client.listed_slides = [
        {
            "id": "recSlideIntro",
            "fields": {"Demo": ["recExistingDemo"], "Script": "Old intro slide script"},
        }
    ]
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        ["update", "recExistingDemo", "--script", _demo_script("New script text.")],
    )

    assert result.exit_code == 0
    assert "Action Summary" in result.output
    assert "Demo Intro Slide" in result.output


def test_demo_script_update_review_reminder_skips_absent_demo_intro_slide(monkeypatch):
    """When no Slides record links back to the demo, the Demo Intro Slide
    reminder is skipped entirely rather than printed with an empty preview.
    """
    fake_client = FakeClient()
    fake_client.get_record = lambda table_name, record_id: {
        "id": record_id,
        "fields": {"Name": "Existing", "Action Summary": "Old action summary"},
    }
    fake_client.listed_slides = []
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        ["update", "recExistingDemo", "--script", _demo_script("New script text.")],
    )

    assert result.exit_code == 0
    assert "Action Summary" in result.output
    assert "Demo Intro Slide" not in result.output
