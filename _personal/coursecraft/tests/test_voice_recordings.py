import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from coursecraft_cli import narration_transaction
from coursecraft_cli.commands import voice_recordings


runner = CliRunner()

SAMPLE_PRONUNCIATION_RULES = [
    {
        "string_to_replace": "Az CLI",
        "type": "alias",
        "alias": "A Z C L I",
    },
    {
        "string_to_replace": "Azure VMs",
        "type": "alias",
        "alias": "Azure virtual machines",
    },
]


class FakeClient:
    def __init__(self, table_name, record_id, script, fields=None):
        self.table_name = table_name
        self.record_id = record_id
        self.script = script
        self.fields = fields or {}
        self.updated_fields = None

    def get_record(self, table_name, record_id):
        assert table_name == self.table_name
        assert record_id == self.record_id
        fields = {
            "Name": "Voice Test",
            "Script": self.script,
            **self.fields,
        }
        return {
            "id": record_id,
            "fields": fields,
        }

    def update_record(self, table_name, record_id, fields):
        assert table_name == self.table_name
        assert record_id == self.record_id
        self.updated_fields = fields


def install_pronunciation_rules(monkeypatch, rules=None):
    monkeypatch.setattr(
        voice_recordings,
        "_load_pronunciation_rules",
        lambda: tuple(rules or SAMPLE_PRONUNCIATION_RULES),
        raising=False,
    )


def fake_matching_dictionary_run(calls, spoken_text, dictionary_id="dict-existing", version_id="version-existing"):
    def fake_run(args, capture_output, text, check, timeout=None):
        calls.append(args)
        if args[:3] == ["elevenlabs", "pronunciation-dictionaries", "list"]:
            return SimpleNamespace(
                stdout=json.dumps(
                    [
                        {
                            "id": dictionary_id,
                            "name": "CourseCraft Voice Pronunciations",
                            "latest_version_id": version_id,
                            "latest_version_rules_num": len(SAMPLE_PRONUNCIATION_RULES),
                        }
                    ]
                ),
                stderr="",
            )
        if args[:3] == ["elevenlabs", "pronunciation-dictionaries", "get"]:
            return SimpleNamespace(
                stdout=json.dumps(
                    {
                        "id": dictionary_id,
                        "name": "CourseCraft Voice Pronunciations",
                        "latest_version_id": version_id,
                        "rules": SAMPLE_PRONUNCIATION_RULES,
                    }
                ),
                stderr="",
            )
        if args[:3] == ["elevenlabs", "speech", "create"]:
            # The paid call must always be bounded.
            assert timeout == narration_transaction.GENERATION_TIMEOUT_SECONDS
            output_path = Path(args[args.index("--output") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"mp3")
            return SimpleNamespace(
                stdout=json.dumps(
                    {
                        "output_path": str(output_path),
                        "content_type": "audio/mpeg",
                        "request_id": "req-speech",
                        "character_count": len(spoken_text),
                        "history_item_id": "hist-speech",
                    }
                ),
                stderr="",
            )
        raise AssertionError(f"Unexpected command: {args}")

    return fake_run


def test_elevenlabs_json_runner_enforces_expected_container(monkeypatch):
    captured = {}

    def fake_run(args, capture_output, text, check, timeout):
        captured["timeout"] = timeout
        return SimpleNamespace(stdout='[1, 2]', stderr="")

    monkeypatch.setattr(narration_transaction.subprocess, "run", fake_run)

    assert voice_recordings._run_elevenlabs_json(["elevenlabs", "items", "list"], list) == [1, 2]
    assert captured["timeout"] is None
    with pytest.raises(
        ValueError,
        match="ElevenLabs command returned non-object JSON",
    ):
        voice_recordings._run_elevenlabs_json(
            ["elevenlabs", "items", "list"],
            dict,
        )


def test_narration_json_runner_preserves_invalid_json_error(monkeypatch):
    def fake_run(args, capture_output, text, check, timeout):
        return SimpleNamespace(stdout="not-json", stderr="")

    monkeypatch.setattr(narration_transaction.subprocess, "run", fake_run)

    with pytest.raises(ValueError) as error:
        narration_transaction._run_json(["elevenlabs", "voices", "get"])

    assert str(error.value) == "Command returned invalid JSON: elevenlabs voices get"


def test_generate_demo_voice_recording_rejects_legacy_stage_directions_before_paid_call(monkeypatch):
    # Legacy pre-canonical Scripts used `ACTION:`/`CALLOUT:`/`DEMO GOAL:` prefix lines.
    # The canonical Script contract rejects them outright rather than silently stripping,
    # so a stage direction can never reach the paid ElevenLabs call.
    install_pronunciation_rules(monkeypatch)
    script = "\n".join(
        [
            "**🎯 DEMO GOAL:** Show running services",
            "Narrate this sentence.",
            "🔧 ACTION: Run Get-Service",
            "Explain the running services output.",
            "👉 CALLOUT: Point to the Status column",
        ]
    )
    fake_client = FakeClient("Demos", "recDemoVoice", script, fields={"Target Length (Min)": 3})
    calls = []

    monkeypatch.setattr(voice_recordings, "get_client", lambda: fake_client)
    monkeypatch.setattr(voice_recordings.subprocess, "run", fake_matching_dictionary_run(calls, ""))

    result = runner.invoke(
        voice_recordings.app,
        ["generate", "--demo", "recDemoVoice"],
    )

    assert result.exit_code == 1
    assert "non-spoken metadata or format markup" in result.output
    assert calls == []
    assert fake_client.updated_fields is None



def spoken(text: str) -> str:
    """Demo spoken text: the canonical narration after the packaged pronunciation patterns."""
    import re
    return re.sub(r"\s+", " ", voice_recordings._apply_pronunciation_patterns(text)).strip()


def sync_dictionary(monkeypatch, fake_run):
    monkeypatch.setattr(voice_recordings.subprocess, "run", fake_run)
    return voice_recordings._sync_pronunciation_dictionary()


def test_sync_pronunciation_dictionary_creates_missing_dictionary(monkeypatch):
    install_pronunciation_rules(monkeypatch)
    calls = []

    def fake_run(args, capture_output, text, check, timeout=None):
        calls.append(args)
        if args[:3] == ["elevenlabs", "pronunciation-dictionaries", "list"]:
            return SimpleNamespace(stdout=json.dumps([]), stderr="")
        if args[:3] == ["elevenlabs", "pronunciation-dictionaries", "create-from-rules"]:
            return SimpleNamespace(
                stdout=json.dumps(
                    {
                        "id": "dict-created",
                        "name": "CourseCraft Voice Pronunciations",
                        "version_id": "version-created",
                        "version_rules_num": len(SAMPLE_PRONUNCIATION_RULES),
                    }
                ),
                stderr="",
            )
        raise AssertionError(f"Unexpected command: {args}")

    locator = sync_dictionary(monkeypatch, fake_run)

    assert locator == "dict-created:version-created"
    assert calls[1][:5] == [
        "elevenlabs",
        "pronunciation-dictionaries",
        "create-from-rules",
        "--name",
        "CourseCraft Voice Pronunciations",
    ]
    alias_rules = [calls[1][index + 1] for index, item in enumerate(calls[1]) if item == "--alias-rule"]
    assert alias_rules == ["Az CLI=A Z C L I", "Azure VMs=Azure virtual machines"]


def test_sync_pronunciation_dictionary_reuses_matching_dictionary(monkeypatch):
    install_pronunciation_rules(monkeypatch)
    calls = []

    locator = sync_dictionary(monkeypatch, fake_matching_dictionary_run(calls, ""))

    assert locator == "dict-existing:version-existing"
    assert [call[:3] for call in calls] == [
        ["elevenlabs", "pronunciation-dictionaries", "list"],
        ["elevenlabs", "pronunciation-dictionaries", "get"],
    ]


def test_sync_pronunciation_dictionary_updates_mismatched_dictionary(monkeypatch):
    install_pronunciation_rules(monkeypatch)
    calls = []

    def fake_run(args, capture_output, text, check, timeout=None):
        calls.append(args)
        if args[:3] == ["elevenlabs", "pronunciation-dictionaries", "list"]:
            return SimpleNamespace(
                stdout=json.dumps(
                    [
                        {
                            "id": "dict-existing",
                            "name": "CourseCraft Voice Pronunciations",
                            "latest_version_id": "version-old",
                            "latest_version_rules_num": 1,
                        }
                    ]
                ),
                stderr="",
            )
        if args[:3] == ["elevenlabs", "pronunciation-dictionaries", "get"]:
            return SimpleNamespace(
                stdout=json.dumps(
                    {
                        "id": "dict-existing",
                        "name": "CourseCraft Voice Pronunciations",
                        "latest_version_id": "version-old",
                        "rules": [{"string_to_replace": "old", "type": "alias", "alias": "older"}],
                    }
                ),
                stderr="",
            )
        if args[:3] == ["elevenlabs", "pronunciation-dictionaries", "set-rules"]:
            return SimpleNamespace(
                stdout=json.dumps(
                    {
                        "id": "dict-existing",
                        "version_id": "version-new",
                        "version_rules_num": len(SAMPLE_PRONUNCIATION_RULES),
                    }
                ),
                stderr="",
            )
        raise AssertionError(f"Unexpected command: {args}")

    locator = sync_dictionary(monkeypatch, fake_run)

    assert locator == "dict-existing:version-new"
    assert [call[:3] for call in calls] == [
        ["elevenlabs", "pronunciation-dictionaries", "list"],
        ["elevenlabs", "pronunciation-dictionaries", "get"],
        ["elevenlabs", "pronunciation-dictionaries", "set-rules"],
    ]
    alias_rules = [calls[2][index + 1] for index, item in enumerate(calls[2]) if item == "--alias-rule"]
    assert alias_rules == ["Az CLI=A Z C L I", "Azure VMs=Azure virtual machines"]


def test_sync_pronunciation_dictionary_fails_on_duplicate_names(monkeypatch):
    install_pronunciation_rules(monkeypatch)

    def fake_run(args, capture_output, text, check, timeout=None):
        assert args[:3] == ["elevenlabs", "pronunciation-dictionaries", "list"]
        return SimpleNamespace(
            stdout=json.dumps(
                [
                    {"id": "dict-1", "name": "CourseCraft Voice Pronunciations", "latest_version_id": "v1"},
                    {"id": "dict-2", "name": "CourseCraft Voice Pronunciations", "latest_version_id": "v2"},
                ]
            ),
            stderr="",
        )

    with pytest.raises(ValueError, match="Expected exactly one pronunciation dictionary named CourseCraft Voice Pronunciations, got 2"):
        sync_dictionary(monkeypatch, fake_run)


def test_generate_voice_recording_rejects_slide_records():
    result = runner.invoke(voice_recordings.app, ["generate", "--slide", "recSlideVoice"])

    assert result.exit_code == 2
    assert "--slide" in result.output

def test_spoken_text_keeps_static_terms_for_pronunciation_dictionary():
    script = "PowerShell for Sysadmins uses SysAdmins, sysadmins, the Az CLI, and Azure VMs."

    spoken_text = spoken(script)

    assert spoken_text == script


def test_spoken_text_keeps_static_terms_inside_other_words():
    script = "Azure automation uses the Az module, but identity remains identity."

    spoken_text = spoken(script)

    assert spoken_text == "Azure automation uses the Az module, but identity remains identity."


def test_packaged_pronunciation_rules_use_alias_rule_shape():
    voice_recordings._load_pronunciation_rules.cache_clear()

    rules = voice_recordings._load_pronunciation_rules()
    replaced_terms = {rule["string_to_replace"] for rule in rules}

    assert "PowerShell for Sysadmins" not in replaced_terms
    assert "sysadmins" not in replaced_terms
    assert "Sysadmins" not in replaced_terms
    assert "SysAdmins" not in replaced_terms
    assert {
        "string_to_replace": "idempotent",
        "type": "alias",
        "alias": "Idimpohtent",
    } in rules
    for rule in rules:
        assert set(rule) == {"string_to_replace", "type", "alias"}
        assert rule["type"] == "alias"


def test_spoken_text_applies_generic_powershell_code_patterns():
    script = (
        "Run Connect-AzAccount -ServicePrincipal -TenantId $tenantId, then call "
        "Invoke-AzVMRunCommand -ResourceGroupName $resourceGroupName."
    )

    spoken_text = spoken(script)

    assert spoken_text == (
        "Run Connect A Z Account dash Service Principal dash Tenant I D dollar tenant I D, "
        "then call Invoke A Z virtual machine Run Command dash Resource Group Name dollar resource Group Name."
    )


def test_spoken_text_applies_generic_path_shell_and_file_patterns():
    script = "Open C:\\TaskManagementAPI\\GetTasks\\run.ps1 and run func start | Select-Object Name."

    spoken_text = spoken(script)

    assert spoken_text == (
        "Open C colon backslash Task Management A P I backslash Get Tasks backslash run dot P S one "
        "and run func start pipe Select Object Name."
    )


def test_spoken_text_keeps_sentence_period_after_windows_path():
    script = "Open C:\\TaskManagementAPI\\GetTasks\\run.ps1."

    spoken_text = spoken(script)

    assert spoken_text == "Open C colon backslash Task Management A P I backslash Get Tasks backslash run dot P S one."


def test_spoken_text_applies_generic_dotted_module_and_file_patterns():
    script = "Install Az.Accounts from requirements.psd1 and update function.json."

    spoken_text = spoken(script)

    assert spoken_text == "Install A Z dot Accounts from requirements dot P S D one and update function dot J S O N."


def test_spoken_text_handles_variable_properties_lowercase_commands_and_plural_acronyms():
    script = (
        "Read $job.JobId, pipe to convertto-json, then explain TCP, NICs, IP addresses, "
        "URLs, and HTTPS endpoints."
    )

    spoken_text = spoken(script)

    assert spoken_text == (
        "Read dollar job dot Job I D, pipe to convert to J S O N, then explain TCP, "
        "NICs, IP addresses, URLs, and HTTPS endpoints."
    )


# Demo narration has exactly one source: the canonical Script contract reached through
# `_canonical_demo_preview`. These tests pin the CLI's wiring to that boundary.
DEMO_CUE = "<click Run in the editor toolbar>"
DEMO_CLOSING = (
    "We just proved the service list renders live data, and that is the signal you want "
    "before you trust any downstream automation you build on top of it. Check that signal "
    "first, every time."
)


def canonical_demo_narration(*narration_lines):
    script = "\n".join([*narration_lines, DEMO_CUE, DEMO_CLOSING])
    _parsed, preview = voice_recordings._canonical_demo_preview(script)
    return preview["normalizedNarration"]


def test_canonical_demo_narration_excludes_standalone_cue_lines():
    narration = canonical_demo_narration("Open the console and watch the service list.")

    assert narration == f"Open the console and watch the service list. {DEMO_CLOSING}"
    assert "<" not in narration
    assert ">" not in narration


@pytest.mark.parametrize(
    "legacy_line",
    [
        "ACTION: Run Get-Service",
        "🔧 ACTION: Run Get-Service",
        "👉 CALLOUT: Point to the Status column",
        "**🎯 DEMO GOAL:** Show running services",
        "Expected: the service list renders",
    ],
)
def test_canonical_demo_narration_rejects_legacy_stage_direction_lines(legacy_line):
    # Retired prefix cues are rejected, not stripped: silently dropping a line would let
    # an authoring mistake cost a paid narration take.
    with pytest.raises(ValueError, match="non-spoken metadata or format markup"):
        canonical_demo_narration("Narrate the first step.", legacy_line)


def test_canonical_demo_narration_keeps_double_pipe_narration():
    # Slide `||` cue-stripping must NOT apply to demos; there `||` is ordinary narration.
    narration = canonical_demo_narration("Narrate this beat || with a literal marker.")

    assert narration.startswith("Narrate this beat || with a literal marker.")


def test_canonical_demo_narration_rejects_script_with_no_spoken_narration():
    script = "\n".join([DEMO_CUE, '<type "exit" in the terminal and press Return>'])

    with pytest.raises(ValueError, match="every cue must have spoken narration before and after it"):
        voice_recordings._canonical_demo_preview(script)
