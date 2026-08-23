from copilot_cli.commands import connections


def _connection_record(connection_id="conn-1", connector_id="shared_example"):
    return {
        "name": connection_id,
        "properties": {
            "displayName": "Example Connection",
            "apiId": f"/providers/Microsoft.PowerApps/apis/{connector_id}",
            "statuses": [{"status": "Connected"}],
        },
    }


def test_connections_test_default_output_is_json_only(monkeypatch, capsys):
    captured = {}

    class FakeClient:
        def list_connections(self, connector_id=None):
            captured["list_connector_id"] = connector_id
            return [_connection_record("conn-1", "shared_example")]

        def test_connection(self, connector_id, connection_id):
            captured["tested"] = (connector_id, connection_id)
            return {"success": True, "stored_status": "Connected"}

    monkeypatch.setattr(connections, "get_client", lambda: FakeClient())
    monkeypatch.setattr(
        connections, "print_json", lambda payload: captured.setdefault("payload", payload)
    )

    connections.connections_test(
        connector_id="shared_example",
        connection_id="conn-1",
        all_connectors=False,
        live=True,
        table=False,
    )

    assert captured["list_connector_id"] == "shared_example"
    assert captured["tested"] == ("shared_example", "conn-1")
    assert captured["payload"][0]["connection_id"] == "conn-1"
    assert capsys.readouterr().out == ""


def test_connections_test_empty_default_outputs_json_array(monkeypatch, capsys):
    captured = {}

    class FakeClient:
        def list_connections(self, connector_id=None):
            return []

    monkeypatch.setattr(connections, "get_client", lambda: FakeClient())
    monkeypatch.setattr(
        connections, "print_json", lambda payload: captured.setdefault("payload", payload)
    )

    connections.connections_test(
        connector_id="shared_example",
        connection_id=None,
        all_connectors=False,
        live=True,
        table=False,
    )

    assert captured["payload"] == []
    assert capsys.readouterr().out == ""


def test_connections_test_table_keeps_human_progress(monkeypatch, capsys):
    captured = {}

    class FakeClient:
        def list_connections(self, connector_id=None):
            return [_connection_record("conn-1", "shared_example")]

        def test_connection(self, connector_id, connection_id):
            return {"success": True, "stored_status": "Connected"}

    monkeypatch.setattr(connections, "get_client", lambda: FakeClient())
    monkeypatch.setattr(
        connections,
        "print_table",
        lambda rows, columns, headers: captured.setdefault("table", rows),
    )

    connections.connections_test(
        connector_id="shared_example",
        connection_id="conn-1",
        all_connectors=False,
        live=True,
        table=True,
    )

    stdout = capsys.readouterr().out
    assert "Finding connections for connector: shared_example..." in stdout
    assert "Found 1 connection(s). Checking via live probe..." in stdout
    assert "Summary: All 1 connection(s) are healthy" in stdout
    assert captured["table"][0]["connection_id"] == "conn-1"
