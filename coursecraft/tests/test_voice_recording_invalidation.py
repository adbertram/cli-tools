from typer.testing import CliRunner

from coursecraft_cli.commands import demos, slides


runner = CliRunner()


class FakeClient:
    def __init__(self, table_name, record_id):
        self.table_name = table_name
        self.record_id = record_id
        self.updated_fields = None

    def get_record(self, table_name, record_id):
        assert table_name == self.table_name
        assert record_id == self.record_id
        return {"id": record_id, "fields": {"Name": "Existing"}}

    def update_record(self, table_name, record_id, fields):
        assert table_name == self.table_name
        assert record_id == self.record_id
        self.updated_fields = fields


def test_updating_slide_script_invalidates_voice_recording(monkeypatch):
    fake_client = FakeClient("Slides", "recExistingSlide")
    monkeypatch.setattr(slides, "get_client", lambda: fake_client)

    result = runner.invoke(
        slides.app,
        [
            "update",
            "recExistingSlide",
            "--script",
            "Updated narration.",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {
        "Script": "Updated narration.",
        "Dictation Recorded": False,
        "Voice Recording ID": "",
        "Voice Recording Path": "",
        "Voice Source Hash": "",
        "ElevenLabs Voice ID": "",
        "ElevenLabs Model ID": "",
        "ElevenLabs Output Format": "",
        "ElevenLabs Request ID": "",
        "ElevenLabs History Item ID": "",
        "Voice Character Count": "",
        "Voice Generated At": "",
    }


def test_updating_demo_script_invalidates_voice_recording(monkeypatch):
    fake_client = FakeClient("Demos", "recExistingDemo")
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--script",
            "Updated demo narration.",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {
        "Script": "Updated demo narration.",
        "Dictation Recorded": False,
        "Voice Recording ID": "",
        "Voice Recording Path": "",
        "Voice Source Hash": "",
        "ElevenLabs Voice ID": "",
        "ElevenLabs Model ID": "",
        "ElevenLabs Output Format": "",
        "ElevenLabs Request ID": "",
        "ElevenLabs History Item ID": "",
        "Voice Character Count": "",
        "Voice Generated At": "",
    }
