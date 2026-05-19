import json

from typer.testing import CliRunner

from coursecraft_cli.commands import environments


runner = CliRunner()


class FakeClient:
    def __init__(self):
        self.list_formula = None

    def list_records(self, table_name, formula=None):
        assert table_name == "Demo Environments"
        self.list_formula = formula
        return [
            {
                "id": "recEnv",
                "fields": {
                    "Name": "Azure - Adam the Automator",
                    "Environment ID": "azure-adam-the-automator",
                    "Provider": "Azure",
                    "Status": "Active",
                    "Tenant ID": "tenant-id",
                },
            }
        ]

    def resolve_environment_id(self, environment):
        assert environment == "azure-adam-the-automator"
        return "recEnv"

    def get_record(self, table_name, record_id):
        assert table_name == "Demo Environments"
        assert record_id == "recEnv"
        return {
            "id": "recEnv",
            "fields": {
                "Name": "Azure - Adam the Automator",
                "Environment ID": "azure-adam-the-automator",
                "Provider": "Azure",
                "Status": "Active",
                "Tenant ID": "tenant-id",
            },
        }


def test_list_environments_accepts_provider(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(environments, "get_client", lambda: fake_client)

    result = runner.invoke(environments.app, ["list", "--provider", "Azure"])

    assert result.exit_code == 0
    records = json.loads(result.output)
    assert records[0]["fields"]["Environment ID"] == "azure-adam-the-automator"
    assert "Provider" in fake_client.list_formula
    assert "Azure" in fake_client.list_formula


def test_get_environment_accepts_properties(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(environments, "get_client", lambda: fake_client)

    result = runner.invoke(
        environments.app,
        [
            "get",
            "azure-adam-the-automator",
            "--properties",
            "id,fields.Name,fields.Tenant ID",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "id": "recEnv",
        "fields.Name": "Azure - Adam the Automator",
        "fields.Tenant ID": "tenant-id",
    }
