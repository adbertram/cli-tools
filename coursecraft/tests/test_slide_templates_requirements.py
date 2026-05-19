from typer.testing import CliRunner

from coursecraft_cli.commands import templates


runner = CliRunner()


class FakeClient:
    def __init__(self):
        self.created_fields = None
        self.updated_fields = None

    def list_records(self, table_name, formula):
        assert table_name == "Slide Templates"
        return []

    def create_record(self, table_name, fields):
        assert table_name == "Slide Templates"
        self.created_fields = fields
        return "recCreatedTemplate"

    def get_record(self, table_name, record_id):
        assert table_name == "Slide Templates"
        assert record_id == "recExistingTemplate"
        return {"id": record_id, "fields": {"Name": "Existing"}}

    def update_record(self, table_name, record_id, fields):
        assert table_name == "Slide Templates"
        assert record_id == "recExistingTemplate"
        self.updated_fields = fields


def test_create_template_accepts_requirements(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(templates, "get_client", lambda: fake_client)

    result = runner.invoke(
        templates.app,
        [
            "create",
            "--name",
            "Image with Three Points",
            "--requirements",
            "Exactly three points; each point must be 64 characters or fewer.",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.created_fields == {
        "Name": "Image with Three Points",
        "Requirements": "Exactly three points; each point must be 64 characters or fewer.",
    }


def test_update_template_accepts_requirements(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(templates, "get_client", lambda: fake_client)

    result = runner.invoke(
        templates.app,
        [
            "update",
            "recExistingTemplate",
            "--requirements",
            "Circle labels must be 18 characters or fewer.",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {
        "Requirements": "Circle labels must be 18 characters or fewer.",
    }


def test_update_template_accepts_template_deck_version(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(templates, "get_client", lambda: fake_client)

    result = runner.invoke(
        templates.app,
        [
            "update",
            "recExistingTemplate",
            "--template-deck-version",
            "2025.2",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {
        "Template Deck Version": 2025.2,
    }


def test_create_template_rejects_animations(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(templates, "get_client", lambda: fake_client)

    result = runner.invoke(
        templates.app,
        [
            "create",
            "--name",
            "Image with Three Points",
            "--animations",
            "3",
        ],
    )

    assert result.exit_code == 2
    assert fake_client.created_fields is None


def test_update_template_rejects_animations(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(templates, "get_client", lambda: fake_client)

    result = runner.invoke(
        templates.app,
        [
            "update",
            "recExistingTemplate",
            "--animations",
            "3",
        ],
    )

    assert result.exit_code == 2
    assert fake_client.updated_fields is None
