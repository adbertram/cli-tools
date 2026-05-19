from typer.testing import CliRunner

from coursecraft_cli.commands import slides


runner = CliRunner()


class FakeClient:
    def __init__(self):
        self.updated_fields = None

    def get_record(self, table_name, record_id):
        assert table_name == "Slides"
        assert record_id == "recExistingSlide"
        return {"id": record_id, "fields": {"Name": "Existing"}}

    def update_record(self, table_name, record_id, fields):
        assert table_name == "Slides"
        assert record_id == "recExistingSlide"
        self.updated_fields = fields


def test_update_slide_accepts_built(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(slides, "get_client", lambda: fake_client)

    result = runner.invoke(
        slides.app,
        [
            "update",
            "recExistingSlide",
            "--built",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {"Built": True}


def test_update_slide_accepts_no_built(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(slides, "get_client", lambda: fake_client)

    result = runner.invoke(
        slides.app,
        [
            "update",
            "recExistingSlide",
            "--no-built",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {"Built": False}


def test_update_slide_accepts_dictation_recorded(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(slides, "get_client", lambda: fake_client)

    result = runner.invoke(
        slides.app,
        [
            "update",
            "recExistingSlide",
            "--dictation-recorded",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {"Dictation Recorded": True}


def test_update_slide_accepts_recorded(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(slides, "get_client", lambda: fake_client)

    result = runner.invoke(
        slides.app,
        [
            "update",
            "recExistingSlide",
            "--recorded",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {"Recorded": True}


def test_update_slide_rejects_action_cue_count_compliance_status(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(slides, "get_client", lambda: fake_client)

    result = runner.invoke(
        slides.app,
        [
            "update",
            "recExistingSlide",
            "--action-cue-count-compliance-status",
            "Compliant",
        ],
    )

    assert result.exit_code == 2
    assert fake_client.updated_fields is None
