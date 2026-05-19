import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

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
    def fake_run(args, capture_output, text, check):
        calls.append(args)
        if args[:3] == ["elevenlabs", "pronunciation-dictionaries", "list"]:
            return SimpleNamespace(
                stdout=json.dumps(
                    {
                        "pronunciation_dictionaries": [
                            {
                                "id": dictionary_id,
                                "name": "CourseCraft Voice Pronunciations",
                                "latest_version_id": version_id,
                                "latest_version_rules_num": len(SAMPLE_PRONUNCIATION_RULES),
                            }
                        ],
                        "has_more": False,
                        "next_cursor": None,
                    }
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


def test_generate_slide_voice_recording_calls_elevenlabs_and_updates_slide(monkeypatch, tmp_path):
    install_pronunciation_rules(monkeypatch)
    script = "Open the shell. Click Next."
    spoken_text = "Open the shell. Click Next."
    pronunciation_dictionary_locator = "dict-existing:version-existing"
    source_hash = hashlib.sha256(spoken_text.encode("utf-8")).hexdigest()
    recording_hash = hashlib.sha256(
        json.dumps(
            {
                "model_id": "eleven_multilingual_v2",
                "output_format": "mp3_44100_128",
                "pronunciation_dictionary_locator": pronunciation_dictionary_locator,
                "similarity_boost": None,
                "speaker_boost": None,
                "speed": None,
                "spoken_text": spoken_text,
                "stability": None,
                "style": None,
                "voice_id": "voice-slide",
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    fake_client = FakeClient(
        "Slides",
        "recSlideVoice",
        script,
        fields={
            "Module Number": [2],
            "Clip Order": 3,
            "Name": "Configure Azure VMs",
        },
    )
    calls = []

    monkeypatch.setattr(voice_recordings, "get_client", lambda: fake_client)
    monkeypatch.setattr(voice_recordings.subprocess, "run", fake_matching_dictionary_run(calls, spoken_text))

    result = runner.invoke(
        voice_recordings.app,
        [
            "generate",
            "--slide",
            "recSlideVoice",
            "--voice-id",
            "voice-slide",
            "--output-format",
            "mp3_44100_128",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    expected_output_path = tmp_path / "m2" / "slides" / "3 - Configure Azure VMs.mp3"
    assert calls == [
        [
            "elevenlabs",
            "pronunciation-dictionaries",
            "list",
            "--page-size",
            "100",
        ],
        [
            "elevenlabs",
            "pronunciation-dictionaries",
            "get",
            "dict-existing",
        ],
        [
            "elevenlabs",
            "speech",
            "create",
            "voice-slide",
            spoken_text,
            "--output",
            str(expected_output_path),
            "--model-id",
            "eleven_multilingual_v2",
            "--output-format",
            "mp3_44100_128",
            "--pronunciation-dictionary",
            pronunciation_dictionary_locator,
        ]
    ]
    assert "Recorded" not in fake_client.updated_fields
    assert fake_client.updated_fields["Dictation Recorded"] is True
    assert fake_client.updated_fields["Voice Recording Path"] == str(expected_output_path)
    assert fake_client.updated_fields["Voice Recording ID"] == f"coursecraft:slide:recSlideVoice:{recording_hash}"
    assert fake_client.updated_fields["Voice Source Hash"] == source_hash
    assert fake_client.updated_fields["ElevenLabs Voice ID"] == "voice-slide"
    assert fake_client.updated_fields["ElevenLabs Model ID"] == "eleven_multilingual_v2"
    assert fake_client.updated_fields["ElevenLabs Output Format"] == "mp3_44100_128"
    assert fake_client.updated_fields["ElevenLabs Request ID"] == "req-speech"
    assert fake_client.updated_fields["ElevenLabs History Item ID"] == "hist-speech"
    assert fake_client.updated_fields["Voice Character Count"] == len(spoken_text)
    assert fake_client.updated_fields["Voice Generated At"]


def test_generate_demo_voice_recording_strips_demo_action_cues(monkeypatch, tmp_path):
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
    spoken_text = "Narrate this sentence. Explain the running services output."
    fake_client = FakeClient("Demos", "recDemoVoice", script)
    calls = []

    monkeypatch.setattr(voice_recordings, "get_client", lambda: fake_client)
    monkeypatch.setattr(voice_recordings.subprocess, "run", fake_matching_dictionary_run(calls, spoken_text))

    result = runner.invoke(
        voice_recordings.app,
        [
            "generate",
            "--demo",
            "recDemoVoice",
            "--voice-id",
            "voice-demo",
            "--model-id",
            "eleven_multilingual_v2",
            "--output-format",
            "mp3_44100_128",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls[2][4] == spoken_text
    assert "Recorded" not in fake_client.updated_fields
    assert fake_client.updated_fields["Dictation Recorded"] is True
    assert fake_client.updated_fields["Voice Recording Path"] == str(tmp_path / "demos" / "recDemoVoice.mp3")


def test_generate_voice_recording_passes_explicit_tuning_options_to_elevenlabs(monkeypatch, tmp_path):
    install_pronunciation_rules(monkeypatch)
    script = "Use a little more energy."
    fake_client = FakeClient(
        "Slides",
        "recSlideVoice",
        script,
        fields={
            "Module Number": [1],
            "Clip Order": 2,
            "Name": "Emotional Sample",
        },
    )
    calls = []

    monkeypatch.setattr(voice_recordings, "get_client", lambda: fake_client)
    monkeypatch.setattr(voice_recordings.subprocess, "run", fake_matching_dictionary_run(calls, script))

    result = runner.invoke(
        voice_recordings.app,
        [
            "generate",
            "--slide",
            "recSlideVoice",
            "--voice-id",
            "voice-slide",
            "--model-id",
            "eleven_multilingual_v2",
            "--output-format",
            "mp3_44100_128",
            "--output-dir",
            str(tmp_path),
            "--stability",
            "0.4",
            "--similarity-boost",
            "0.8",
            "--style",
            "0.32",
            "--speaker-boost",
            "--speed",
            "0.94",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls[2][-11:] == [
        "--pronunciation-dictionary",
        "dict-existing:version-existing",
        "--stability",
        "0.4",
        "--similarity-boost",
        "0.8",
        "--style",
        "0.32",
        "--speaker-boost",
        "--speed",
        "0.94",
    ]


def test_generate_voice_recording_defaults_to_eleven_multilingual_v2_without_legacy_tuning(monkeypatch, tmp_path):
    install_pronunciation_rules(monkeypatch)
    script = "Use the current speech model."
    fake_client = FakeClient(
        "Slides",
        "recSlideVoice",
        script,
        fields={
            "Module Number": [1],
            "Clip Order": 3,
            "Name": "Current Model",
        },
    )
    calls = []

    monkeypatch.setattr(voice_recordings, "get_client", lambda: fake_client)
    monkeypatch.setattr(voice_recordings.subprocess, "run", fake_matching_dictionary_run(calls, script))

    result = runner.invoke(
        voice_recordings.app,
        [
            "generate",
            "--slide",
            "recSlideVoice",
            "--voice-id",
            "voice-slide",
            "--output-format",
            "mp3_44100_128",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls[2] == [
        "elevenlabs",
        "speech",
        "create",
        "voice-slide",
        script,
        "--output",
        str(tmp_path / "m1" / "slides" / "3 - Current Model.mp3"),
        "--model-id",
        "eleven_multilingual_v2",
        "--output-format",
        "mp3_44100_128",
        "--pronunciation-dictionary",
        "dict-existing:version-existing",
    ]
    assert fake_client.updated_fields["ElevenLabs Model ID"] == "eleven_multilingual_v2"


def test_generate_slide_voice_recording_creates_missing_pronunciation_dictionary(monkeypatch, tmp_path):
    install_pronunciation_rules(monkeypatch)
    script = "Use the Az CLI to manage Azure VMs."
    spoken_text = "Use the Az CLI to manage Azure VMs."
    source_hash = hashlib.sha256(spoken_text.encode("utf-8")).hexdigest()
    fake_client = FakeClient(
        "Slides",
        "recSlideVoice",
        script,
        fields={
            "Module Number": [1],
            "Clip Order": 4,
            "Name": "Pronunciation Sample",
        },
    )
    calls = []

    def fake_run(args, capture_output, text, check):
        calls.append(args)
        if args[:3] == ["elevenlabs", "pronunciation-dictionaries", "list"]:
            return SimpleNamespace(
                stdout=json.dumps({"pronunciation_dictionaries": [], "has_more": False, "next_cursor": None}),
                stderr="",
            )
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
        output_path = Path(args[args.index("--output") + 1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"mp3")
        return SimpleNamespace(
            stdout=json.dumps(
                {
                    "output_path": str(output_path),
                    "content_type": "audio/mpeg",
                    "request_id": "req-pronunciation",
                    "character_count": len(spoken_text),
                    "history_item_id": "hist-pronunciation",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(voice_recordings, "get_client", lambda: fake_client)
    monkeypatch.setattr(voice_recordings.subprocess, "run", fake_run)

    result = runner.invoke(
        voice_recordings.app,
        [
            "generate",
            "--slide",
            "recSlideVoice",
            "--voice-id",
            "voice-slide",
            "--model-id",
            "eleven_multilingual_v2",
            "--output-format",
            "mp3_44100_128",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls[1][:5] == [
        "elevenlabs",
        "pronunciation-dictionaries",
        "create-from-rules",
        "--name",
        "CourseCraft Voice Pronunciations",
    ]
    alias_rules = [
        calls[1][index + 1]
        for index, item in enumerate(calls[1])
        if item == "--alias-rule"
    ]
    assert alias_rules == [
        "Az CLI=A Z C L I",
        "Azure VMs=Azure virtual machines",
    ]
    assert calls[2][4] == spoken_text
    assert calls[2][-2:] == ["--pronunciation-dictionary", "dict-created:version-created"]
    assert fake_client.updated_fields["Voice Source Hash"] == source_hash
    assert fake_client.updated_fields["Voice Character Count"] == len(spoken_text)


def test_generate_slide_voice_recording_reuses_matching_pronunciation_dictionary(monkeypatch, tmp_path):
    install_pronunciation_rules(monkeypatch)
    script = "The PowerShell for Sysadmins course uses the Az CLI."
    fake_client = FakeClient(
        "Slides",
        "recSlideVoice",
        script,
        fields={
            "Module Number": [1],
            "Clip Order": 5,
            "Name": "Reuse Dictionary",
        },
    )
    calls = []

    monkeypatch.setattr(voice_recordings, "get_client", lambda: fake_client)
    monkeypatch.setattr(voice_recordings.subprocess, "run", fake_matching_dictionary_run(calls, script))

    result = runner.invoke(
        voice_recordings.app,
        [
            "generate",
            "--slide",
            "recSlideVoice",
            "--voice-id",
            "voice-slide",
            "--model-id",
            "eleven_multilingual_v2",
            "--output-format",
            "mp3_44100_128",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert [call[:3] for call in calls] == [
        ["elevenlabs", "pronunciation-dictionaries", "list"],
        ["elevenlabs", "pronunciation-dictionaries", "get"],
        ["elevenlabs", "speech", "create"],
    ]
    assert calls[2][-2:] == ["--pronunciation-dictionary", "dict-existing:version-existing"]


def test_generate_slide_voice_recording_updates_mismatched_pronunciation_dictionary(monkeypatch, tmp_path):
    install_pronunciation_rules(monkeypatch)
    script = "The PowerShell for Sysadmins course uses the Az CLI."
    fake_client = FakeClient(
        "Slides",
        "recSlideVoice",
        script,
        fields={
            "Module Number": [1],
            "Clip Order": 6,
            "Name": "Update Dictionary",
        },
    )
    calls = []

    def fake_run(args, capture_output, text, check):
        calls.append(args)
        if args[:3] == ["elevenlabs", "pronunciation-dictionaries", "list"]:
            return SimpleNamespace(
                stdout=json.dumps(
                    {
                        "pronunciation_dictionaries": [
                            {
                                "id": "dict-existing",
                                "name": "CourseCraft Voice Pronunciations",
                                "latest_version_id": "version-old",
                                "latest_version_rules_num": 1,
                            }
                        ],
                        "has_more": False,
                        "next_cursor": None,
                    }
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
                        "rules": [
                            {
                                "string_to_replace": "old",
                                "type": "alias",
                                "alias": "older",
                            }
                        ],
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
        if args[:3] == ["elevenlabs", "speech", "create"]:
            output_path = Path(args[args.index("--output") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"mp3")
            return SimpleNamespace(
                stdout=json.dumps(
                    {
                        "output_path": str(output_path),
                        "content_type": "audio/mpeg",
                        "request_id": "req-updated",
                        "character_count": len(script),
                        "history_item_id": "hist-updated",
                    }
                ),
                stderr="",
            )
        raise AssertionError(f"Unexpected command: {args}")

    monkeypatch.setattr(voice_recordings, "get_client", lambda: fake_client)
    monkeypatch.setattr(voice_recordings.subprocess, "run", fake_run)

    result = runner.invoke(
        voice_recordings.app,
        [
            "generate",
            "--slide",
            "recSlideVoice",
            "--voice-id",
            "voice-slide",
            "--model-id",
            "eleven_multilingual_v2",
            "--output-format",
            "mp3_44100_128",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert [call[:3] for call in calls] == [
        ["elevenlabs", "pronunciation-dictionaries", "list"],
        ["elevenlabs", "pronunciation-dictionaries", "get"],
        ["elevenlabs", "pronunciation-dictionaries", "set-rules"],
        ["elevenlabs", "speech", "create"],
    ]
    alias_rules = [
        calls[2][index + 1]
        for index, item in enumerate(calls[2])
        if item == "--alias-rule"
    ]
    assert alias_rules == [
        "Az CLI=A Z C L I",
        "Azure VMs=Azure virtual machines",
    ]
    assert calls[3][-2:] == ["--pronunciation-dictionary", "dict-existing:version-new"]


def test_generate_slide_voice_recording_fails_on_duplicate_pronunciation_dictionary_names(monkeypatch, tmp_path):
    install_pronunciation_rules(monkeypatch)
    fake_client = FakeClient(
        "Slides",
        "recSlideVoice",
        "Hello.",
        fields={
            "Module Number": [1],
            "Clip Order": 7,
            "Name": "Duplicate Dictionary",
        },
    )

    def fake_run(args, capture_output, text, check):
        assert args[:3] == ["elevenlabs", "pronunciation-dictionaries", "list"]
        return SimpleNamespace(
            stdout=json.dumps(
                {
                    "pronunciation_dictionaries": [
                        {"id": "dict-1", "name": "CourseCraft Voice Pronunciations", "latest_version_id": "v1"},
                        {"id": "dict-2", "name": "CourseCraft Voice Pronunciations", "latest_version_id": "v2"},
                    ],
                    "has_more": False,
                    "next_cursor": None,
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(voice_recordings, "get_client", lambda: fake_client)
    monkeypatch.setattr(voice_recordings.subprocess, "run", fake_run)

    result = runner.invoke(
        voice_recordings.app,
        [
            "generate",
            "--slide",
            "recSlideVoice",
            "--voice-id",
            "voice-slide",
            "--model-id",
            "eleven_multilingual_v2",
            "--output-format",
            "mp3_44100_128",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    assert "Expected exactly one pronunciation dictionary named CourseCraft Voice Pronunciations, got 2" in result.output


def test_to_spoken_text_keeps_static_terms_for_pronunciation_dictionary():
    script = "PowerShell for Sysadmins uses SysAdmins, sysadmins, the Az CLI, and Azure VMs."

    spoken_text = voice_recordings._to_spoken_text(script, "slide")

    assert spoken_text == script


def test_to_spoken_text_keeps_static_terms_inside_other_words():
    script = "Azure automation uses the Az module, but identity remains identity."

    spoken_text = voice_recordings._to_spoken_text(script, "slide")

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


def test_to_spoken_text_applies_generic_powershell_code_patterns():
    script = (
        "Run Connect-AzAccount -ServicePrincipal -TenantId $tenantId, then call "
        "Invoke-AzVMRunCommand -ResourceGroupName $resourceGroupName."
    )

    spoken_text = voice_recordings._to_spoken_text(script, "slide")

    assert spoken_text == (
        "Run Connect A Z Account dash Service Principal dash Tenant I D dollar tenant I D, "
        "then call Invoke A Z virtual machine Run Command dash Resource Group Name dollar resource Group Name."
    )


def test_to_spoken_text_applies_generic_path_shell_and_file_patterns():
    script = "Open C:\\TaskManagementAPI\\GetTasks\\run.ps1 and run func start | Select-Object Name."

    spoken_text = voice_recordings._to_spoken_text(script, "slide")

    assert spoken_text == (
        "Open C colon backslash Task Management A P I backslash Get Tasks backslash run dot P S one "
        "and run func start pipe Select Object Name."
    )


def test_to_spoken_text_keeps_sentence_period_after_windows_path():
    script = "Open C:\\TaskManagementAPI\\GetTasks\\run.ps1."

    spoken_text = voice_recordings._to_spoken_text(script, "slide")

    assert spoken_text == "Open C colon backslash Task Management A P I backslash Get Tasks backslash run dot P S one."


def test_to_spoken_text_applies_generic_dotted_module_and_file_patterns():
    script = "Install Az.Accounts from requirements.psd1 and update function.json."

    spoken_text = voice_recordings._to_spoken_text(script, "slide")

    assert spoken_text == "Install A Z dot Accounts from requirements dot P S D one and update function dot J S O N."


def test_to_spoken_text_handles_variable_properties_lowercase_commands_and_plural_acronyms():
    script = (
        "Read $job.JobId, pipe to convertto-json, then explain TCP, NICs, IP addresses, "
        "URLs, and HTTPS endpoints."
    )

    spoken_text = voice_recordings._to_spoken_text(script, "slide")

    assert spoken_text == (
        "Read dollar job dot Job I D, pipe to convert to J S O N, then explain TCP, "
        "NICs, IP addresses, URLs, and HTTPS endpoints."
    )


def test_generate_voice_recording_requires_one_record_type(tmp_path):
    result = runner.invoke(
        voice_recordings.app,
        [
            "generate",
            "--slide",
            "recSlideVoice",
            "--demo",
            "recDemoVoice",
            "--voice-id",
            "voice",
            "--model-id",
            "eleven_multilingual_v2",
            "--output-format",
            "mp3_44100_128",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    assert "Provide exactly one of --slide or --demo." in result.output
