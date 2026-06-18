import json

from typer.testing import CliRunner

from airtable_cli.commands import bases


runner = CliRunner()


class FakeBasesClient:
    def list_bases(self):
        return [
            {
                "id": "app9uzzru5KZOImYQ",
                "name": "CourseCraft",
                "permissionLevel": "create",
            },
            {
                "id": "appl64Smt3blIeElx",
                "name": "Advertising",
                "permissionLevel": "edit",
            },
        ]

    def get_base(self, base_id):
        for base in self.list_bases():
            if base["id"] == base_id or base["name"] == base_id:
                return base
        raise AssertionError(f"unexpected base_id: {base_id}")


def test_bases_list_returns_summary_objects(monkeypatch):
    monkeypatch.setattr(bases, "get_client", lambda: FakeBasesClient())

    result = runner.invoke(bases.app, ["list"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [
        {"id": "app9uzzru5KZOImYQ", "name": "CourseCraft", "permissionLevel": "create"},
        {"id": "appl64Smt3blIeElx", "name": "Advertising", "permissionLevel": "edit"},
    ]


def test_bases_list_filter_narrows_output(monkeypatch):
    monkeypatch.setattr(bases, "get_client", lambda: FakeBasesClient())

    result = runner.invoke(bases.app, ["list", "--filter", "name:eq:CourseCraft"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [
        {"id": "app9uzzru5KZOImYQ", "name": "CourseCraft", "permissionLevel": "create"}
    ]


def test_bases_list_properties_filters_summary_output(monkeypatch):
    monkeypatch.setattr(bases, "get_client", lambda: FakeBasesClient())

    result = runner.invoke(bases.app, ["list", "--properties", "id,name"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [
        {"id": "app9uzzru5KZOImYQ", "name": "CourseCraft"},
        {"id": "appl64Smt3blIeElx", "name": "Advertising"},
    ]


def test_bases_get_resolves_by_name(monkeypatch):
    monkeypatch.setattr(bases, "get_client", lambda: FakeBasesClient())

    result = runner.invoke(bases.app, ["get", "CourseCraft"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "id": "app9uzzru5KZOImYQ",
        "name": "CourseCraft",
        "permissionLevel": "create",
    }
