import json

from typer.testing import CliRunner

from coursecraft_cli.commands import demos


runner = CliRunner()


class FakeClient:
    def __init__(self):
        self.updated_fields = None

    def get_record(self, table_name, record_id):
        assert table_name == "Demos"
        assert record_id == "recExistingDemo"
        return {"id": record_id, "fields": {"Name": "Existing"}}

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
    assert fake_client.updated_fields == {
        "Clip": ["recClip"],
        "Clip Order": 1,
        "Name": "Demo",
    }


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
    assert "No such option '--demo-environment'" in result.output
    assert fake_client.updated_fields is None


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


def test_update_demo_accepts_tested_approved(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--tested-approved",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {"Tested and Approved": True}


def test_update_demo_accepts_environment_prep_and_tested_approved_together(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--environment-prep-complete",
            "--tested-approved",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {
        "Environment Prep Complete": True,
        "Tested and Approved": True,
    }
    assert "Environment Prep is not marked complete" not in result.output


def test_update_demo_accepts_environment_setup_script_path(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--environment-setup-script-path",
            "/path/to/course/m2c3/env_prep.ps1",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {
        "Environment Setup Script Path": "/path/to/course/m2c3/env_prep.ps1",
    }


def test_update_demo_accepts_demo_walkthrough_script_path(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--demo-walkthrough-script-path",
            "/path/to/course/m2c3/demo_walkthrough.ps1",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {
        "Demo Walkthrough Script Path": "/path/to/course/m2c3/demo_walkthrough.ps1",
    }


def test_update_demo_accepts_demo_walkthrough_script_created(monkeypatch):
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

    assert result.exit_code == 0
    assert fake_client.updated_fields == {"Demo Walkthrough Script Created": True}


def test_update_demo_rejects_demo_environment_option(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "update",
            "recExistingDemo",
            "--demo-environment",
            "azure-adam-the-automator",
            "--demo-environment",
            "local-macos",
        ],
    )

    assert result.exit_code == 2
    assert "No such option '--demo-environment'" in result.output
    assert fake_client.updated_fields is None


def test_update_demo_help_exposes_walkthrough_options_only():
    result = runner.invoke(demos.app, ["update", "--help"], terminal_width=200)
    retired_test_flag = "--" + "test" + "-script"
    retired_action_flag = "--" + "action" + "-script-created"

    assert result.exit_code == 0
    assert "--demo-walkthrough-script-path" in result.output
    assert "--no-demo-walkthro" in result.output
    assert "demo_walkthrough.p" in result.output
    assert "created for this" in result.output
    assert "--demo-environment" not in result.output
    assert retired_test_flag not in result.output
    assert retired_action_flag not in result.output


def test_get_demo_accepts_properties(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(demos, "get_client", lambda: fake_client)

    result = runner.invoke(
        demos.app,
        [
            "get",
            "recExistingDemo",
            "--properties",
            "id,fields.Name",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "id": "recExistingDemo",
        "fields.Name": "Existing",
    }
