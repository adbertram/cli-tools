import json

from typer.testing import CliRunner

from mychart_cli.main import app


runner = CliRunner()


def test_live_metadata_get_reaches_epic_sandbox():
    result = runner.invoke(app, ["metadata", "get", "--properties", "resourceType,fhirVersion"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["resourceType"] == "CapabilityStatement"
    assert payload["fhirVersion"]
