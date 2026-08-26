"""Behavior tests for `n8n data-tables add-column` and `delete-column`."""

from typer.testing import CliRunner

import n8n_cli.commands.data_tables as data_tables_module


class FakeDataTablesApi:
    """Fake API client that records calls without hitting a real n8n server."""

    def __init__(self, columns=None, add_result=None, error=None):
        self.columns = columns if columns is not None else []
        self.add_result = add_result
        self.error = error
        self.add_calls = []
        self.delete_calls = []

    def get_data_table_columns(self, table_id):
        return self.columns

    def add_data_table_column(self, table_id, name, column_type, index=None):
        if self.error is not None:
            raise self.error
        self.add_calls.append((table_id, name, column_type, index))
        return self.add_result or {
            "id": "col-new",
            "name": name,
            "type": column_type,
            "index": index,
            "dataTableId": table_id,
        }

    def delete_data_table_column(self, table_id, column_id):
        if self.error is not None:
            raise self.error
        self.delete_calls.append((table_id, column_id))
        return None


def _invoke(monkeypatch, api, args):
    monkeypatch.setattr(data_tables_module, "get_n8n_api_client", lambda: api)
    return CliRunner().invoke(data_tables_module.app, args)


def test_should_add_column_when_type_is_valid(monkeypatch):
    api = FakeDataTablesApi()

    result = _invoke(
        monkeypatch, api, ["add-column", "table-1", "status", "string"]
    )

    assert result.exit_code == 0
    assert api.add_calls == [("table-1", "status", "string", None)]
    assert "status" in result.stdout


def test_should_pass_index_when_index_option_given(monkeypatch):
    api = FakeDataTablesApi()

    result = _invoke(
        monkeypatch,
        api,
        ["add-column", "table-1", "priority", "number", "--index", "2"],
    )

    assert result.exit_code == 0
    assert api.add_calls == [("table-1", "priority", "number", 2)]


def test_should_reject_invalid_column_type(monkeypatch):
    api = FakeDataTablesApi()

    result = _invoke(
        monkeypatch, api, ["add-column", "table-1", "status", "wrongtype"]
    )

    assert result.exit_code == 1
    assert api.add_calls == []
    assert "Invalid column type" in result.stderr


def test_should_delete_column_when_yes_flag_skips_confirmation(monkeypatch):
    api = FakeDataTablesApi()

    result = _invoke(
        monkeypatch, api, ["delete-column", "table-1", "col-123", "--yes"]
    )

    assert result.exit_code == 0
    assert api.delete_calls == [("table-1", "col-123")]


def test_should_abort_delete_when_user_declines_confirmation(monkeypatch):
    api = FakeDataTablesApi(columns=[{"id": "col-123", "name": "old_status"}])

    monkeypatch.setattr(data_tables_module, "get_n8n_api_client", lambda: api)
    result = CliRunner().invoke(
        data_tables_module.app,
        ["delete-column", "table-1", "col-123"],
        input="n\n",
    )

    assert result.exit_code == 0
    assert api.delete_calls == []
    assert "Aborted" in result.stderr


def test_should_delete_column_when_user_confirms(monkeypatch):
    api = FakeDataTablesApi(columns=[{"id": "col-123", "name": "old_status"}])

    monkeypatch.setattr(data_tables_module, "get_n8n_api_client", lambda: api)
    result = CliRunner().invoke(
        data_tables_module.app,
        ["delete-column", "table-1", "col-123"],
        input="y\n",
    )

    assert result.exit_code == 0
    assert api.delete_calls == [("table-1", "col-123")]


def test_should_error_when_column_id_not_found_before_confirming(monkeypatch):
    api = FakeDataTablesApi(columns=[{"id": "other-col", "name": "x"}])

    result = _invoke(monkeypatch, api, ["delete-column", "table-1", "col-123"])

    assert result.exit_code == 1
    assert api.delete_calls == []
    assert "not found" in result.stderr
