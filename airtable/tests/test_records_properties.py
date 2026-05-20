import json

from typer.testing import CliRunner

from airtable_cli.commands import records


runner = CliRunner()


class FakeRecordsClient:
    def list_records(self, **kwargs):
        assert kwargs["fields"] is None
        return {
            "records": [
                {
                    "id": "recDeal1",
                    "fields": {
                        "name": "Launch",
                        "Status": "Open",
                    },
                }
            ]
        }


def test_records_list_properties_filters_output_without_api_field_projection(monkeypatch):
    monkeypatch.setattr(records, "resolve_base_id", lambda base_id: "appBase")
    monkeypatch.setattr(records, "get_client", lambda: FakeRecordsClient())

    result = runner.invoke(records.app, ["list", "Deals", "--properties", "id,name"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [{"id": "recDeal1", "name": "Launch"}]
