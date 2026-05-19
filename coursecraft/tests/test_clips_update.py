from typer.testing import CliRunner

from coursecraft_cli.commands import clips


runner = CliRunner()


class FakeClient:
    def __init__(self):
        self.updated_fields = None

    def get_record(self, table_name, record_id):
        assert table_name == "Clips"
        assert record_id == "recExistingClip"
        return {"id": record_id, "fields": {"Name": "Existing"}}

    def update_record(self, table_name, record_id, fields):
        assert table_name == "Clips"
        assert record_id == "recExistingClip"
        self.updated_fields = fields


class FactCheckedClipClient:
    def __init__(self):
        self.updated_fields = None

    def get_record(self, table_name, record_id):
        assert table_name == "Clips"
        assert record_id == "recExistingClip"
        return {
            "id": record_id,
            "fields": {
                "Name": "Existing",
                "Brainstorming Outline": "Old outline",
                "Brainstorming Outline Fact Checked": True,
            },
        }

    def update_record(self, table_name, record_id, fields):
        assert table_name == "Clips"
        assert record_id == "recExistingClip"
        self.updated_fields = fields


def test_update_clip_accepts_content_done(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(clips, "get_client", lambda: fake_client)

    result = runner.invoke(
        clips.app,
        [
            "update",
            "recExistingClip",
            "--content-done",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {"Clip Structure Confirmed": True}


def test_update_clip_accepts_module(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(clips, "get_client", lambda: fake_client)

    result = runner.invoke(
        clips.app,
        [
            "update",
            "recExistingClip",
            "--module",
            "recNewModule",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {"Module": ["recNewModule"]}


def test_update_clip_explicit_fact_checked_overrides_brainstorming_reset(monkeypatch):
    fake_client = FactCheckedClipClient()
    monkeypatch.setattr(clips, "get_client", lambda: fake_client)

    result = runner.invoke(
        clips.app,
        [
            "update",
            "recExistingClip",
            "--brainstorming-outline",
            "New outline",
            "--brainstorming-outline-fact-checked",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {
        "Brainstorming Outline": "New outline",
        "Brainstorming Outline Fact Checked": True,
    }
