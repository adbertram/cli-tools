import json

from typer.testing import CliRunner

from airtable_cli.commands import records


runner = CliRunner()


# A single Airtable-shaped record used by both list and get fakes. It includes
# a top-level ``createdTime``, a populated field (``name``), a null-valued field
# (``Priority``), and does NOT include ``Status`` in a way that both list and get
# resolve identically.
_FAKE_RECORD = {
    "id": "recDeal1",
    "createdTime": "2024-01-02T03:04:05.000Z",
    "fields": {
        "name": "Launch",
        "Status": "Open",
        "Priority": None,
    },
}


class FakeRecordsClient:
    def list_records(self, **kwargs):
        assert kwargs["fields"] is None
        return {"records": [dict(_FAKE_RECORD)]}

    def get_record(self, base_id, table_id, record_id):
        return dict(_FAKE_RECORD)


def _patch(monkeypatch):
    monkeypatch.setattr(records, "resolve_base_id", lambda base_id: "appBase")
    monkeypatch.setattr(records, "get_client", lambda: FakeRecordsClient())


# --- records list (command-level via CliRunner) ---


def test_records_list_properties_filters_output_without_api_field_projection(monkeypatch):
    _patch(monkeypatch)

    result = runner.invoke(records.app, ["list", "Deals", "--properties", "id,name"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [{"id": "recDeal1", "name": "Launch"}]


def test_records_list_absent_field_projects_explicit_null(monkeypatch):
    _patch(monkeypatch)

    # "Priority" exists but is null; a genuinely absent field would behave the
    # same. Here we request a field that is present-but-null to prove null keys
    # survive, plus a normal field.
    result = runner.invoke(records.app, ["list", "Deals", "--properties", "id,name,Priority"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [
        {"id": "recDeal1", "name": "Launch", "Priority": None}
    ]


def test_records_list_created_time_projects_top_level(monkeypatch):
    _patch(monkeypatch)

    result = runner.invoke(records.app, ["list", "Deals", "--properties", "id,createdTime"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [
        {"id": "recDeal1", "createdTime": "2024-01-02T03:04:05.000Z"}
    ]


def test_records_list_fields_dotted_equivalent_to_bare(monkeypatch):
    _patch(monkeypatch)

    result = runner.invoke(records.app, ["list", "Deals", "--properties", "fields.name"])

    assert result.exit_code == 0
    # dotted "fields.name" projects under the BARE key "name"
    assert json.loads(result.stdout) == [{"name": "Launch"}]


def test_records_list_fields_token_returns_whole_fields_object(monkeypatch):
    _patch(monkeypatch)

    result = runner.invoke(records.app, ["list", "Deals", "--properties", "fields"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [
        {"fields": {"name": "Launch", "Status": "Open", "Priority": None}}
    ]


# --- helper-level (direct import of records.project_records / project_record) ---


def test_project_records_absent_field_is_explicit_null():
    # "Deadline" is not present in fields at all -> explicit None, key preserved.
    projected = records.project_records([dict(_FAKE_RECORD)], "id,name,Deadline")
    assert projected == [{"id": "recDeal1", "name": "Launch", "Deadline": None}]


def test_project_records_null_valued_field_is_null():
    projected = records.project_records([dict(_FAKE_RECORD)], "Priority")
    assert projected == [{"Priority": None}]


def test_project_records_bare_and_dotted_are_equivalent():
    bare = records.project_records([dict(_FAKE_RECORD)], "name")
    dotted = records.project_records([dict(_FAKE_RECORD)], "fields.name")
    assert bare == dotted == [{"name": "Launch"}]


def test_project_records_tolerates_whitespace_between_tokens():
    projected = records.project_records([dict(_FAKE_RECORD)], " id , name ")
    assert projected == [{"id": "recDeal1", "name": "Launch"}]


def test_project_records_passthrough_when_properties_none():
    original = [dict(_FAKE_RECORD)]
    assert records.project_records(original, None) is original


def test_project_records_passthrough_when_properties_empty():
    original = [dict(_FAKE_RECORD)]
    assert records.project_records(original, "") is original
    # only-whitespace/only-commas also passes through unchanged
    assert records.project_records(original, " , ") is original


def test_project_records_passthrough_when_records_empty():
    assert records.project_records([], "id,name") == []


def test_project_record_single_absent_field_is_null():
    projected = records.project_record(dict(_FAKE_RECORD), "id,name,Deadline")
    assert projected == {"id": "recDeal1", "name": "Launch", "Deadline": None}


def test_project_record_passthrough_when_properties_none():
    original = dict(_FAKE_RECORD)
    assert records.project_record(original, None) is original


# --- records get (command-level via CliRunner) ---


def test_records_get_properties_projects_json(monkeypatch):
    _patch(monkeypatch)

    result = runner.invoke(
        records.app, ["get", "Deals", "recDeal1", "--properties", "id,name,Priority"]
    )

    assert result.exit_code == 0
    # get projects a single dict (not a list); absent/null -> explicit null.
    assert json.loads(result.stdout) == {
        "id": "recDeal1",
        "name": "Launch",
        "Priority": None,
    }


def test_records_get_properties_ignored_under_table(monkeypatch):
    _patch(monkeypatch)

    result = runner.invoke(
        records.app,
        ["get", "Deals", "recDeal1", "--properties", "id,name", "--table"],
    )

    assert result.exit_code == 0
    # Under --table, --properties is intentionally ignored: the full record is
    # rendered as a table, so a non-projected field like "Status" is present and
    # the output is NOT the projected JSON dict.
    assert "Status" in result.stdout
    assert not result.stdout.lstrip().startswith("{")


def test_records_get_without_properties_returns_full_record(monkeypatch):
    _patch(monkeypatch)

    result = runner.invoke(records.app, ["get", "Deals", "recDeal1"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == _FAKE_RECORD
