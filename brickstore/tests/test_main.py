import json

import pytest
from cli_tools_shared.exceptions import ClientError
from typer.testing import CliRunner

from brickstore_cli.client import validate_set_numbers
from brickstore_cli.main import app


PRICE_GUIDE = {
    "item_id": "3001",
    "item_name": "Brick 2 x 4",
    "color": "Red",
    "currency": "USD",
    "last_updated": "2026-07-29T13:35:58Z",
    "last_six_months": {"new": {}, "used": {}},
    "current": {"new": {}, "used": {}},
}

SET_CONTENTS = [
    {
        "set_id": "30670-1",
        "items": [
            {
                "item": {"no": "3001", "type": "PART"},
                "color_id": 5,
                "match_no": 0,
                "quantity": 2,
            }
        ],
    },
    {"set_id": "75313-1", "items": []},
]

QUERY_RESULT = {
    "items": [
        {
            "id": "3001",
            "name": "Brick 2 x 4",
            "type_id": "P",
            "type_name": "Part",
            "category": "Brick",
            "year_released": 1978,
            "year_last_produced": 2026,
        }
    ],
    "returned_count": 1,
    "total_count": 1,
}

QUERY_KWARGS = {
    "item_id": None,
    "item_name": None,
    "item_type": None,
    "category": None,
    "color": None,
    "related_to_item_id": None,
    "related_to_item_type": None,
    "relationship": None,
    "year_min": None,
    "year_max": None,
}


class Client:
    def __init__(self):
        self.part_args = None
        self.set_args = None
        self.set_batch_args = None
        self.set_contents_args = None
        self.query_kwargs = None

    def part(self, item_number, color, leave_open):
        self.part_args = (item_number, color, leave_open)
        return PRICE_GUIDE

    def set(self, set_number, leave_open):
        self.set_args = (set_number, leave_open)
        return PRICE_GUIDE

    def set_batch(self, set_numbers, leave_open):
        validate_set_numbers(set_numbers, "set-batch")
        self.set_batch_args = (tuple(set_numbers), leave_open)
        return {"results": [PRICE_GUIDE]}

    def set_contents(self, set_numbers):
        self.set_contents_args = tuple(set_numbers)
        return [record for record in SET_CONTENTS if record["set_id"] in set_numbers]

    def query(self, **kwargs):
        self.query_kwargs = kwargs
        return QUERY_RESULT


def test_part_prints_unmodified_source_json(monkeypatch):
    client = Client()
    monkeypatch.setattr("brickstore_cli.main.get_client", lambda: client)

    result = CliRunner().invoke(app, ["part", "3001", "Red"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == PRICE_GUIDE
    assert client.part_args == ("3001", "Red", False)


def test_set_table_prints_source_fields(monkeypatch):
    client = Client()
    monkeypatch.setattr("brickstore_cli.main.get_client", lambda: client)

    result = CliRunner().invoke(app, ["set", "30670-1", "--table"])

    assert result.exit_code == 0
    assert "Field" in result.stdout
    assert "item_id" in result.stdout
    assert "3001" in result.stdout
    assert client.set_args == ("30670-1", False)


def test_set_batch_prints_the_results_envelope_and_forwards_every_id(monkeypatch):
    client = Client()
    monkeypatch.setattr("brickstore_cli.main.get_client", lambda: client)

    result = CliRunner().invoke(app, ["set-batch", "30670-1"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"results": [PRICE_GUIDE]}
    assert client.set_batch_args == (("30670-1",), False)


@pytest.mark.parametrize(
    ("args", "attribute", "expected"),
    [
        (["part", "3001", "Red", "--leave-open"], "part_args", ("3001", "Red", True)),
        (["set", "30670-1", "--leave-open"], "set_args", ("30670-1", True)),
        (["set-batch", "30670-1", "--leave-open"], "set_batch_args", (("30670-1",), True)),
    ],
)
def test_price_guide_command_forwards_leave_open(monkeypatch, args, attribute, expected):
    client = Client()
    monkeypatch.setattr("brickstore_cli.main.get_client", lambda: client)

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0
    assert getattr(client, attribute) == expected


def test_set_contents_prints_a_root_array_with_nested_items_and_forwards_every_id(monkeypatch):
    client = Client()
    monkeypatch.setattr("brickstore_cli.main.get_client", lambda: client)

    result = CliRunner().invoke(app, ["set-contents", "30670-1", "75313-1"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == SET_CONTENTS
    assert client.set_contents_args == ("30670-1", "75313-1")


def test_set_contents_prints_one_set_record_with_nested_items(monkeypatch):
    client = Client()
    monkeypatch.setattr("brickstore_cli.main.get_client", lambda: client)

    result = CliRunner().invoke(app, ["set-contents", "30670-1"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [SET_CONTENTS[0]]
    assert client.set_contents_args == ("30670-1",)


def test_set_batch_requires_at_least_one_id_before_calling_the_client(monkeypatch):
    client = Client()
    monkeypatch.setattr("brickstore_cli.main.get_client", lambda: client)

    result = CliRunner().invoke(app, ["set-batch"])

    assert result.exit_code == 2
    assert client.set_batch_args is None


def test_set_batch_accepts_twenty_five_ids_and_rejects_too_many_ids(monkeypatch):
    client = Client()
    monkeypatch.setattr("brickstore_cli.main.get_client", lambda: client)
    set_numbers = ["set-{}".format(index) for index in range(25)]
    runner = CliRunner()

    accepted = runner.invoke(app, ["set-batch", *set_numbers])
    rejected = runner.invoke(app, ["set-batch", *set_numbers, "set-25"])

    assert accepted.exit_code == 0
    assert client.set_batch_args == (tuple(set_numbers), False)
    assert rejected.exit_code != 0
    assert "at most 25 set IDs" in rejected.output


def test_set_batch_rejects_duplicate_ids_through_client_validation(monkeypatch):
    client = Client()
    monkeypatch.setattr("brickstore_cli.main.get_client", lambda: client)

    result = CliRunner().invoke(app, ["set-batch", "30670-1", "30670-1"])

    assert result.exit_code != 0
    assert "must be unique: 30670-1" in result.output
    assert client.set_batch_args is None


def test_set_batch_reports_client_errors_without_json_output(monkeypatch):
    class FailingClient:
        def set_batch(self, set_numbers, leave_open):
            raise ClientError("BrickStore source error: Catalog service failed")

    monkeypatch.setattr("brickstore_cli.main.get_client", FailingClient)

    result = CliRunner().invoke(app, ["set-batch", "30670-1"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Error: BrickStore source error: Catalog service failed" in result.output


def test_set_contents_reports_client_errors_without_json_output(monkeypatch):
    class FailingClient:
        def set_contents(self, set_numbers):
            raise ClientError("BrickLink set contents command failed for 30670-1 with exit 1")

    monkeypatch.setattr("brickstore_cli.main.get_client", FailingClient)

    result = CliRunner().invoke(app, ["set-contents", "30670-1"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Error: BrickLink set contents command failed for 30670-1 with exit 1" in result.output


def test_query_prints_unmodified_source_json_and_defaults_unset_filters_to_none(monkeypatch):
    client = Client()
    monkeypatch.setattr("brickstore_cli.main.get_client", lambda: client)

    result = CliRunner().invoke(app, ["query", "--item-id", "3001"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == QUERY_RESULT
    assert client.query_kwargs == {**QUERY_KWARGS, "item_id": "3001", "leave_open": False}


def test_query_forwards_every_filter_option(monkeypatch):
    client = Client()
    monkeypatch.setattr("brickstore_cli.main.get_client", lambda: client)

    result = CliRunner().invoke(
        app,
        [
            "query",
            "--item-id", "3001",
            "--item-name", "Brick",
            "--item-type", "Part",
            "--category", "Brick",
            "--color", "Red",
            "--related-to-item-id", "30670-1",
            "--related-to-item-type", "S",
            "--relationship", "Alternate",
            "--year-min", "1970",
            "--year-max", "2020",
        ],
    )

    assert result.exit_code == 0
    assert client.query_kwargs == {
        "item_id": "3001",
        "item_name": "Brick",
        "item_type": "Part",
        "category": "Brick",
        "color": "Red",
        "related_to_item_id": "30670-1",
        "related_to_item_type": "S",
        "relationship": "Alternate",
        "year_min": 1970,
        "year_max": 2020,
        "leave_open": False,
    }


def test_query_table_prints_item_columns(monkeypatch):
    client = Client()
    monkeypatch.setattr("brickstore_cli.main.get_client", lambda: client)

    result = CliRunner().invoke(app, ["query", "--item-id", "3001", "--table"])

    assert result.exit_code == 0
    assert "Brick 2 x 4" in result.stdout
    assert "Part" in result.stdout
    assert "1978" in result.stdout


def test_query_forwards_leave_open(monkeypatch):
    client = Client()
    monkeypatch.setattr("brickstore_cli.main.get_client", lambda: client)

    result = CliRunner().invoke(app, ["query", "--item-id", "3001", "--leave-open"])

    assert result.exit_code == 0
    assert client.query_kwargs == {**QUERY_KWARGS, "item_id": "3001", "leave_open": True}


def test_query_reports_client_errors_without_json_output(monkeypatch):
    class FailingClient:
        def query(self, **kwargs):
            raise ClientError('BrickStore source error: Unknown item type "NotAType"')

    monkeypatch.setattr("brickstore_cli.main.get_client", FailingClient)

    result = CliRunner().invoke(app, ["query", "--item-type", "NotAType"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert 'Error: BrickStore source error: Unknown item type "NotAType"' in result.output


def test_help_exposes_the_requested_commands():
    runner = CliRunner()

    assert runner.invoke(app, ["part", "--help"]).exit_code == 0
    assert "--table" in runner.invoke(app, ["part", "--help"]).stdout
    assert "--leave-open" in runner.invoke(app, ["part", "--help"]).stdout
    assert runner.invoke(app, ["set", "--help"]).exit_code == 0
    assert "--table" in runner.invoke(app, ["set", "--help"]).stdout
    assert "--leave-open" in runner.invoke(app, ["set", "--help"]).stdout
    assert runner.invoke(app, ["set-batch", "--help"]).exit_code == 0
    assert "--leave-open" in runner.invoke(app, ["set-batch", "--help"]).stdout
    set_contents_help = runner.invoke(app, ["set-contents", "--help"])
    assert set_contents_help.exit_code == 0
    assert "--leave-open" not in set_contents_help.stdout
    query_help = runner.invoke(app, ["query", "--help"])
    assert query_help.exit_code == 0
    for option in (
        "--item-id",
        "--item-name",
        "--item-type",
        "--category",
        "--color",
        "--related-to-item-id",
        "--related-to-item-type",
        "--relationship",
        "--year-min",
        "--year-max",
        "--table",
        "--leave-open",
    ):
        assert option in query_help.stdout
