import json
import subprocess

import pytest
import requests
from cli_tools_shared.exceptions import ClientError

from brickstore_cli.client import BrickStoreClient, BrickStoreServerUnavailableError
from brickstore_cli.config import Config


class TestConfig:
    base_url = "http://127.0.0.1:45111"
    executable = "/Applications/BrickStore.app/Contents/MacOS/BrickStore"
    database_path = "/tmp/brickstore-test-database"
    database_url = "https://example.test/brickstore-database"


def test_config_uses_the_dedicated_endpoint_variable(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("BASE_URL", "https://api.brickbuddy.io")
    monkeypatch.setenv("BRICKSTORE_BASE_URL", "http://127.0.0.1:45112")

    assert Config().base_url == "http://127.0.0.1:45112"


def test_config_ignores_a_foreign_generic_base_url(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("BASE_URL", "https://api.brickbuddy.io")
    monkeypatch.delenv("BRICKSTORE_BASE_URL", raising=False)

    assert Config().base_url == "http://127.0.0.1:45111"


def test_config_uses_the_brickstore_executable_variable(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("BRICKSTORE_EXECUTABLE", "/Applications/CustomBrickStore.app/Contents/MacOS/BrickStore")

    assert Config().executable == "/Applications/CustomBrickStore.app/Contents/MacOS/BrickStore"


def test_config_uses_the_database_path_variable(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("BRICKSTORE_DATABASE_PATH", "/custom/database-v12")

    assert Config().database_path == "/custom/database-v12"


def test_config_defaults_the_database_path_when_unset(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.delenv("BRICKSTORE_DATABASE_PATH", raising=False)

    assert Config().database_path == "~/Library/Caches/BrickStore/database-v12"


def test_config_uses_the_database_url_variable(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("BRICKSTORE_DATABASE_URL", "https://example.test/custom-database")

    assert Config().database_url == "https://example.test/custom-database"


def test_config_defaults_the_database_url_when_unset(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.delenv("BRICKSTORE_DATABASE_URL", raising=False)

    assert Config().database_url == "https://github.com/rgriebl/brickstore-database/releases/latest/download"


class Response:
    def __init__(self, payload=None, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.headers = {}
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        if self.payload is None:
            raise ValueError("No JSON response")
        return self.payload


def rpc_response(request_id, result):
    return Response({"jsonrpc": "2.0", "id": request_id, "result": result})


def price_guide_result(item_id, item_name, color):
    return {
        "item_id": item_id,
        "item_name": item_name,
        "color": color,
        "currency": "USD",
        "last_updated": "2026-07-29T13:35:58Z",
        "last_six_months": {
            "new": {
                "total_quantity": 10,
                "lots": 2,
                "prices": {"min": 0.1, "avg": 0.2, "qty_avg": 0.2, "max": 0.3},
            },
            "used": {
                "total_quantity": 5,
                "lots": 1,
                "prices": {"min": 0.05, "avg": 0.1, "qty_avg": 0.1, "max": 0.2},
            },
        },
        "current": {
            "new": {
                "total_quantity": 8,
                "lots": 2,
                "prices": {"min": 0.11, "avg": 0.21, "qty_avg": 0.21, "max": 0.31},
            },
            "used": {
                "total_quantity": 4,
                "lots": 1,
                "prices": {"min": 0.06, "avg": 0.11, "qty_avg": 0.11, "max": 0.21},
            },
        },
    }


def mcp_responses(*tool_payloads):
    responses = [
        rpc_response(
            1,
            {
                "protocolVersion": "2025-03-26",
                "serverInfo": {"name": "BrickStore MCP Server", "version": "2026.7.1"},
            },
        ),
        Response(status_code=202),
        rpc_response(
            2,
            {
                "tools": [
                    {"name": "catalog_query"},
                    {"name": "catalog_price_guide"},
                ]
            },
        ),
    ]
    for index, payload in enumerate(tool_payloads, start=3):
        responses.append(
            rpc_response(
                index,
                {
                    "content": [{"type": "text", "text": json.dumps(payload)}],
                    "isError": False,
                },
            )
        )
    return responses


def install_responses(monkeypatch, responses):
    calls = []

    def post(method, url, headers, json, timeout):
        calls.append({"method": method, "url": url, "headers": headers, "json": json, "timeout": timeout})
        return responses.pop(0)

    monkeypatch.setattr("brickstore_cli.client.requests.request", post)
    return calls


class BrickStoreProcess:
    def __init__(self):
        self.terminate_called = False
        self.wait_calls = []

    def poll(self):
        return None

    def terminate(self):
        self.terminate_called = True

    def wait(self, timeout):
        self.wait_calls.append(timeout)
        return 0


def install_owned_server(monkeypatch):
    process = BrickStoreProcess()
    calls = []

    def start(args, stdout, stderr, text, start_new_session=False):
        calls.append({
            "args": args,
            "stdout": stdout,
            "stderr": stderr,
            "text": text,
            "start_new_session": start_new_session,
        })
        return process

    monkeypatch.setattr("brickstore_cli.client.subprocess.Popen", start)
    return process, calls


class FakeDatabase:
    def __init__(self, contents_by_set=None, status_result=None):
        self.contents_by_set = contents_by_set or {}
        self.status_result = status_result
        self.requested_sets = []

    def set_contents(self, set_number):
        self.requested_sets.append(set_number)
        return self.contents_by_set[set_number]

    def status(self):
        return self.status_result


def install_database(monkeypatch, database):
    loaded_paths = []

    def load(path):
        loaded_paths.append(path)
        return database

    monkeypatch.setattr("brickstore_cli.client.CatalogDatabase.load", load)
    return loaded_paths


def test_part_uses_catalog_price_guide_with_exact_source_arguments(monkeypatch):
    source_result = price_guide_result("3001", "Brick 2 x 4", "Red")
    calls = install_responses(monkeypatch, mcp_responses({"results": [source_result]}))

    result = BrickStoreClient(config=TestConfig()).part("3001", "Red")

    assert result == source_result
    assert [call["json"]["method"] for call in calls] == [
        "initialize",
        "initialized",
        "tools/list",
        "tools/call",
    ]
    assert calls[0]["json"] == {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "brickstore-cli", "version": "0.1.0"},
        },
    }
    assert calls[3]["json"] == {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "catalog_price_guide",
            "arguments": {"items": [{"item_id": "3001", "item_type": "P", "color": "Red"}]},
        },
    }


def test_minifig_uses_catalog_price_guide_with_the_minifig_item_type(monkeypatch):
    source_result = price_guide_result("sw0001a", "Battle Droid - Tan", "(Not Applicable)")
    calls = install_responses(monkeypatch, mcp_responses({"results": [source_result]}))

    result = BrickStoreClient(config=TestConfig()).minifig("sw0001a")

    assert result == source_result
    assert calls[3]["json"]["params"] == {
        "name": "catalog_price_guide",
        "arguments": {"items": [{"item_id": "sw0001a", "item_type": "M"}]},
    }


def test_minifig_sends_no_color_because_the_source_rejects_one(monkeypatch):
    source_result = price_guide_result("sw0001a", "Battle Droid - Tan", "(Not Applicable)")
    calls = install_responses(monkeypatch, mcp_responses({"results": [source_result]}))

    BrickStoreClient(config=TestConfig()).minifig("sw0001a")

    assert calls[3]["json"]["params"]["arguments"]["items"][0].keys() == {"item_id", "item_type"}


def test_part_starts_and_stops_only_the_server_it_owns(monkeypatch):
    source_result = price_guide_result("3001", "Brick 2 x 4", "Red")
    responses = [
        requests.exceptions.ConnectionError("Connection refused"),
        rpc_response(
            2,
            {
                "protocolVersion": "2025-03-26",
                "serverInfo": {"name": "BrickStore MCP Server", "version": "2026.7.1"},
            },
        ),
        Response(status_code=202),
        rpc_response(3, {"tools": [{"name": "catalog_query"}, {"name": "catalog_price_guide"}]}),
        rpc_response(
            4,
            {"content": [{"type": "text", "text": json.dumps({"results": [source_result]})}], "isError": False},
        ),
    ]

    def post(method, url, headers, json, timeout):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr("brickstore_cli.client.requests.request", post)
    process, starts = install_owned_server(monkeypatch)

    assert BrickStoreClient(config=TestConfig(), max_retries=0).part("3001", "Red") == source_result
    assert starts == [
        {
            "args": [TestConfig.executable],
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "start_new_session": False,
        }
    ]
    assert process.terminate_called is True
    assert process.wait_calls == [10]


def test_part_leaves_an_owned_server_open_when_requested(monkeypatch):
    source_result = price_guide_result("3001", "Brick 2 x 4", "Red")
    responses = [
        requests.exceptions.ConnectionError("Connection refused"),
        rpc_response(
            2,
            {
                "protocolVersion": "2025-03-26",
                "serverInfo": {"name": "BrickStore MCP Server", "version": "2026.7.1"},
            },
        ),
        Response(status_code=202),
        rpc_response(3, {"tools": [{"name": "catalog_query"}, {"name": "catalog_price_guide"}]}),
        rpc_response(
            4,
            {"content": [{"type": "text", "text": json.dumps({"results": [source_result]})}], "isError": False},
        ),
    ]

    def post(method, url, headers, json, timeout):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr("brickstore_cli.client.requests.request", post)
    process, starts = install_owned_server(monkeypatch)

    result = BrickStoreClient(config=TestConfig(), max_retries=0).part("3001", "Red", leave_open=True)

    assert result == source_result
    assert starts[0]["start_new_session"] is True
    assert process.terminate_called is False
    assert process.wait_calls == []


def test_part_keeps_an_existing_server_running(monkeypatch):
    source_result = price_guide_result("3001", "Brick 2 x 4", "Red")
    install_responses(monkeypatch, mcp_responses({"results": [source_result]}))

    def start(*args, **kwargs):
        raise AssertionError("The CLI must not start an available BrickStore MCP server")

    monkeypatch.setattr("brickstore_cli.client.subprocess.Popen", start)

    assert BrickStoreClient(config=TestConfig()).part("3001", "Red") == source_result


def test_part_stops_an_owned_server_when_the_price_source_fails(monkeypatch):
    responses = [
        requests.exceptions.ConnectionError("Connection refused"),
        rpc_response(
            2,
            {
                "protocolVersion": "2025-03-26",
                "serverInfo": {"name": "BrickStore MCP Server", "version": "2026.7.1"},
            },
        ),
        Response(status_code=202),
        rpc_response(3, {"tools": [{"name": "catalog_query"}, {"name": "catalog_price_guide"}]}),
        rpc_response(4, {"content": [{"type": "text", "text": "Catalog service failed"}], "isError": True}),
    ]

    def post(method, url, headers, json, timeout):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr("brickstore_cli.client.requests.request", post)
    process, _ = install_owned_server(monkeypatch)

    with pytest.raises(ClientError, match="BrickStore source error: Catalog service failed"):
        BrickStoreClient(config=TestConfig(), max_retries=0).part("3001", "Red")

    assert process.terminate_called is True


def test_part_stops_an_owned_server_when_readiness_fails(monkeypatch):
    def fail(*args, **kwargs):
        raise requests.exceptions.ConnectionError("Readiness source error")

    monkeypatch.setattr("brickstore_cli.client.requests.request", fail)
    monkeypatch.setattr("brickstore_cli.client.SERVER_READINESS_TIMEOUT_SECONDS", 0)
    process, _ = install_owned_server(monkeypatch)

    with pytest.raises(ClientError, match="Readiness source error"):
        BrickStoreClient(config=TestConfig(), max_retries=0).part("3001", "Red")

    assert process.terminate_called is True


def test_wait_for_mcp_server_retries_after_clean_duplicate_launch(monkeypatch):
    client = BrickStoreClient(config=TestConfig(), max_retries=0)
    attempts = []

    class CleanExitProcess:
        returncode = 0

        def poll(self):
            return self.returncode

        def communicate(self):
            return "", ""

    def start_session(required_tool_names):
        attempts.append(required_tool_names)
        if len(attempts) == 1:
            raise BrickStoreServerUnavailableError("Connection refused")

    monkeypatch.setattr(client, "_start_mcp_session", start_session)
    monkeypatch.setattr("brickstore_cli.client.time.sleep", lambda seconds: None)

    client._wait_for_mcp_server(CleanExitProcess(), {"catalog_price_guide"})

    assert attempts == [{"catalog_price_guide"}, {"catalog_price_guide"}]


def test_wait_for_mcp_server_reports_nonzero_launch_exit(monkeypatch):
    client = BrickStoreClient(config=TestConfig(), max_retries=0)

    class FailedProcess:
        returncode = 1

        def poll(self):
            return self.returncode

        def communicate(self):
            return "", "BrickStore launch failed"

    def fail_session(required_tool_names):
        raise BrickStoreServerUnavailableError("Connection refused")

    monkeypatch.setattr(client, "_start_mcp_session", fail_session)

    with pytest.raises(ClientError, match="BrickStore launch failed"):
        client._wait_for_mcp_server(FailedProcess(), {"catalog_price_guide"})


def test_set_queries_then_uses_the_exact_set_item(monkeypatch):
    source_result = price_guide_result("30670-1", "Santa's Sleigh Ride polybag", "(Not Applicable)")
    calls = install_responses(
        monkeypatch,
        mcp_responses(
            {"items": [{"id": "30670-1", "type_id": "S", "name": "Santa's Sleigh Ride polybag"}]},
            {"results": [source_result]},
        ),
    )

    result = BrickStoreClient(config=TestConfig()).set("30670-1")

    assert result == source_result
    assert calls[3]["json"]["params"] == {
        "name": "catalog_query",
        "arguments": {"item_id": "30670-1", "item_type": "S"},
    }
    assert calls[4]["json"]["params"] == {
        "name": "catalog_price_guide",
        "arguments": {"items": [{"item_id": "30670-1", "item_type": "S"}]},
    }


def test_set_batch_uses_one_price_guide_call_with_exact_set_inputs_and_preserves_records(monkeypatch):
    first = price_guide_result("30670-1", "Santa's Sleigh Ride polybag", "(Not Applicable)")
    first["source_extension"] = {"exact": ["value", 3.14]}
    second = price_guide_result("75313-1", "Islander's Beach House", "(Not Applicable)")
    responses = mcp_responses({"results": [first, second]})
    responses[2] = rpc_response(2, {"tools": [{"name": "catalog_price_guide"}]})
    calls = install_responses(monkeypatch, responses)

    result = BrickStoreClient(config=TestConfig()).set_batch(["30670-1", "75313-1"])

    assert result == {"results": [first, second]}
    assert [call["json"]["method"] for call in calls] == [
        "initialize",
        "initialized",
        "tools/list",
        "tools/call",
    ]
    assert calls[3]["json"]["params"] == {
        "name": "catalog_price_guide",
        "arguments": {
            "items": [
                {"item_id": "30670-1", "item_type": "S"},
                {"item_id": "75313-1", "item_type": "S"},
            ]
        },
    }


@pytest.mark.parametrize(
    ("set_numbers", "message"),
    [
        ([], "set-batch requires from 1 through 25 unique set IDs"),
        ([str(index) for index in range(26)], "set-batch accepts at most 25 set IDs"),
        (["30670-1", "30670-1"], "set-batch set IDs must be unique: 30670-1"),
    ],
)
def test_set_batch_rejects_invalid_inputs_before_mcp_access(set_numbers, message):
    with pytest.raises(ClientError, match=message):
        BrickStoreClient(config=TestConfig()).set_batch(set_numbers)


@pytest.mark.parametrize(
    ("results", "message"),
    [
        (
            [price_guide_result("30670-1", "Santa's Sleigh Ride polybag", "(Not Applicable)")],
            "BrickStore source error: catalog_price_guide did not return a result for 75313-1",
        ),
        (
            [
                price_guide_result("30670-1", "Santa's Sleigh Ride polybag", "(Not Applicable)"),
                price_guide_result("30670-1", "Santa's Sleigh Ride polybag", "(Not Applicable)"),
            ],
            "BrickStore source error: catalog_price_guide returned duplicate result for 30670-1",
        ),
    ],
)
def test_set_batch_rejects_missing_or_duplicate_source_results(monkeypatch, results, message):
    calls = install_responses(monkeypatch, mcp_responses({"results": results}))

    with pytest.raises(ClientError, match=message):
        BrickStoreClient(config=TestConfig()).set_batch(["30670-1", "75313-1"])

    assert len(calls) == 4


@pytest.mark.parametrize("field_name", ["item_type", "type_id"])
def test_set_batch_rejects_a_wrong_source_type_when_the_source_provides_one(monkeypatch, field_name):
    wrong_type = price_guide_result("30670-1", "Santa's Sleigh Ride polybag", "(Not Applicable)")
    wrong_type[field_name] = "P"
    calls = install_responses(monkeypatch, mcp_responses({"results": [wrong_type]}))

    with pytest.raises(
        ClientError,
        match="BrickStore source error: catalog_price_guide returned {} P for 30670-1, expected S".format(
            field_name
        ),
    ):
        BrickStoreClient(config=TestConfig()).set_batch(["30670-1"])

    assert len(calls) == 4


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {"results": {}},
            "BrickStore source error: catalog_price_guide results must be an array",
        ),
        (
            {"results": [price_guide_result("3001", "Brick 2 x 4", "Red")]},
            "BrickStore source error: catalog_price_guide returned unexpected result for 3001",
        ),
        (
            {"results": [{"error": "Item not found"}]},
            "BrickStore source error: Item not found",
        ),
    ],
)
def test_set_batch_rejects_invalid_source_result_shapes(monkeypatch, payload, message):
    calls = install_responses(monkeypatch, mcp_responses(payload))

    with pytest.raises(ClientError, match=message):
        BrickStoreClient(config=TestConfig()).set_batch(["30670-1"])

    assert len(calls) == 4


def test_set_batch_maps_tool_errors_to_source_errors(monkeypatch):
    responses = mcp_responses()
    responses.append(
        rpc_response(
            3,
            {"content": [{"type": "text", "text": "Catalog service failed"}], "isError": True},
        )
    )
    install_responses(monkeypatch, responses)

    with pytest.raises(ClientError, match="BrickStore source error: Catalog service failed"):
        BrickStoreClient(config=TestConfig()).set_batch(["30670-1"])


def test_set_contents_loads_the_configured_database_once_and_aggregates_each_set(monkeypatch):
    first_record = {"set_id": "30670-1", "items": [{"item": {"no": "3001"}, "quantity": 2}]}
    second_record = {"set_id": "75313-1", "items": []}
    database = FakeDatabase({"30670-1": first_record, "75313-1": second_record})
    loaded_paths = install_database(monkeypatch, database)

    result = BrickStoreClient(config=TestConfig()).set_contents(["30670-1", "75313-1"])

    assert result == [first_record, second_record]
    assert database.requested_sets == ["30670-1", "75313-1"]
    assert loaded_paths == [TestConfig.database_path]


@pytest.mark.parametrize(
    ("set_numbers", "message"),
    [
        ([], "set-contents requires from 1 through 25 unique set IDs"),
        ([str(index) for index in range(26)], "set-contents accepts at most 25 set IDs"),
        (["30670-1", "30670-1"], "set-contents set IDs must be unique: 30670-1"),
    ],
)
def test_set_contents_reuses_the_one_to_twenty_five_unique_id_contract(set_numbers, message):
    with pytest.raises(ClientError, match=message):
        BrickStoreClient(config=TestConfig()).set_contents(set_numbers)


def test_set_contents_reports_an_unknown_set_as_a_client_error(monkeypatch):
    database = FakeDatabase({})

    def load(path):
        def missing_set(set_number):
            raise ClientError("BrickStore database {} holds no set with the ID {}".format(path, set_number))

        database.set_contents = missing_set
        return database

    monkeypatch.setattr("brickstore_cli.client.CatalogDatabase.load", load)

    with pytest.raises(ClientError, match="holds no set with the ID 30670-1"):
        BrickStoreClient(config=TestConfig()).set_contents(["30670-1"])


def test_database_status_loads_the_configured_database_path(monkeypatch):
    status = {"path": "/tmp/database-v12", "version": 12, "sets": 10}
    database = FakeDatabase(status_result=status)
    loaded_paths = install_database(monkeypatch, database)

    result = BrickStoreClient(config=TestConfig()).database_status()

    assert result == status
    assert loaded_paths == [TestConfig.database_path]


def test_database_update_forwards_the_configured_path_url_and_force_flag(monkeypatch):
    calls = []

    def fake_download(path, url, force=False):
        calls.append((path, url, force))
        return {"path": path, "url": url, "updated": True}

    monkeypatch.setattr("brickstore_cli.client.download", fake_download)

    result = BrickStoreClient(config=TestConfig()).database_update(force=True)

    assert result == {"path": TestConfig.database_path, "url": TestConfig.database_url, "updated": True}
    assert calls == [(TestConfig.database_path, TestConfig.database_url, True)]


def test_database_update_defaults_force_to_false(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "brickstore_cli.client.download",
        lambda path, url, force=False: calls.append((path, url, force)) or {},
    )

    BrickStoreClient(config=TestConfig()).database_update()

    assert calls == [(TestConfig.database_path, TestConfig.database_url, False)]


def test_source_item_error_is_a_clear_client_error(monkeypatch):
    calls = install_responses(monkeypatch, mcp_responses({"results": [{"error": "Item not found"}]}))

    with pytest.raises(ClientError, match="BrickStore source error: Item not found"):
        BrickStoreClient(config=TestConfig()).part("missing", None)

    assert len(calls) == 4


def test_connection_failure_reports_brickstore_availability(monkeypatch):
    def fail(*args, **kwargs):
        raise requests.exceptions.ConnectionError("Connection refused")

    monkeypatch.setattr("brickstore_cli.client.requests.request", fail)
    monkeypatch.setattr("brickstore_cli.client.SERVER_READINESS_TIMEOUT_SECONDS", 0)
    process, _ = install_owned_server(monkeypatch)

    with pytest.raises(ClientError, match="BrickStore MCP server is unavailable"):
        BrickStoreClient(config=TestConfig(), max_retries=0).part("3001", "Red")

    assert process.terminate_called is True


def test_part_preserves_the_source_start_error(monkeypatch):
    def fail(*args, **kwargs):
        raise requests.exceptions.ConnectionError("Connection refused")

    def start(*args, **kwargs):
        raise OSError("BrickStore launch source error")

    monkeypatch.setattr("brickstore_cli.client.requests.request", fail)
    monkeypatch.setattr("brickstore_cli.client.subprocess.Popen", start)

    with pytest.raises(ClientError, match="BrickStore launch source error"):
        BrickStoreClient(config=TestConfig(), max_retries=0).part("3001", "Red")


def query_item(item_id, name, type_id="P", type_name="Part", category="Brick", **extra):
    item = {"id": item_id, "name": name, "type_id": type_id, "type_name": type_name, "category": category}
    item.update(extra)
    return item


def test_query_uses_catalog_query_with_only_the_given_filters(monkeypatch):
    items = [query_item("3001", "Brick 2 x 4", year_released=1978)]
    calls = install_responses(
        monkeypatch,
        mcp_responses({"items": items, "returned_count": 1, "total_count": 1}),
    )

    result = BrickStoreClient(config=TestConfig()).query(item_id="3001", color="Red")

    assert result == {"items": items, "returned_count": 1, "total_count": 1}
    assert calls[3]["json"]["params"] == {
        "name": "catalog_query",
        "arguments": {"item_id": "3001", "color": "Red"},
    }


def test_query_forwards_every_supported_filter_argument(monkeypatch):
    calls = install_responses(
        monkeypatch,
        mcp_responses({"items": [], "returned_count": 0, "total_count": 0}),
    )

    BrickStoreClient(config=TestConfig()).query(
        item_id="3001",
        item_name="Brick",
        item_type="Part",
        category="Brick",
        color="Red",
        related_to_item_id="30670-1",
        related_to_item_type="S",
        relationship="Alternate",
        year_min=1970,
        year_max=2020,
    )

    assert calls[3]["json"]["params"]["arguments"] == {
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
    }


def test_query_only_requires_the_catalog_query_tool(monkeypatch):
    responses = mcp_responses({"items": [], "returned_count": 0, "total_count": 0})
    responses[2] = rpc_response(2, {"tools": [{"name": "catalog_query"}]})
    install_responses(monkeypatch, responses)

    result = BrickStoreClient(config=TestConfig()).query(item_id="3001")

    assert result == {"items": [], "returned_count": 0, "total_count": 0}


def test_query_returns_empty_results_when_the_source_finds_nothing(monkeypatch):
    install_responses(
        monkeypatch,
        mcp_responses({"items": [], "returned_count": 0, "total_count": 0}),
    )

    result = BrickStoreClient(config=TestConfig()).query(item_id="zzzznotreal999")

    assert result == {"items": [], "returned_count": 0, "total_count": 0}


def test_query_preserves_the_note_field_when_results_are_capped(monkeypatch):
    items = [query_item("3001pb001", "Brick 2 x 4 with Pattern")]
    payload = {
        "items": items,
        "returned_count": 200,
        "total_count": 1184,
        "note": "Results capped at 200. Refine the filters to see all matches.",
    }
    install_responses(monkeypatch, mcp_responses(payload))

    result = BrickStoreClient(config=TestConfig()).query(item_name="Brick 2 x 4")

    assert result == payload


def test_query_forwards_leave_open(monkeypatch):
    responses = [
        requests.exceptions.ConnectionError("Connection refused"),
        rpc_response(
            2,
            {
                "protocolVersion": "2025-03-26",
                "serverInfo": {"name": "BrickStore MCP Server", "version": "2026.7.1"},
            },
        ),
        Response(status_code=202),
        rpc_response(3, {"tools": [{"name": "catalog_query"}]}),
        rpc_response(
            4,
            {"content": [{"type": "text", "text": json.dumps({"items": [], "returned_count": 0, "total_count": 0})}], "isError": False},
        ),
    ]

    def post(method, url, headers, json, timeout):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr("brickstore_cli.client.requests.request", post)
    process, starts = install_owned_server(monkeypatch)

    result = BrickStoreClient(config=TestConfig(), max_retries=0).query(item_id="3001", leave_open=True)

    assert result == {"items": [], "returned_count": 0, "total_count": 0}
    assert starts[0]["start_new_session"] is True
    assert process.terminate_called is False


def test_query_maps_tool_errors_to_source_errors(monkeypatch):
    responses = mcp_responses()
    responses.append(
        rpc_response(
            3,
            {
                "content": [
                    {"type": "text", "text": 'Unknown item type "NotAType": catalog_schema lists all item types'}
                ],
                "isError": True,
            },
        )
    )
    install_responses(monkeypatch, responses)

    with pytest.raises(
        ClientError,
        match='BrickStore source error: Unknown item type "NotAType": catalog_schema lists all item types',
    ):
        BrickStoreClient(config=TestConfig()).query(item_type="NotAType")


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {"items": []},
            "JSON_CONTRACT_MISMATCH: catalog_query result is missing returned_count, total_count",
        ),
        (
            {"items": "not-a-list", "returned_count": 0, "total_count": 0},
            "JSON_CONTRACT_MISMATCH: catalog_query items must be an array",
        ),
        (
            {"items": [], "returned_count": "0", "total_count": 0},
            "JSON_CONTRACT_MISMATCH: catalog_query total_count and returned_count must be integers",
        ),
        (
            {"items": ["not-an-object"], "returned_count": 1, "total_count": 1},
            "JSON_CONTRACT_MISMATCH: catalog_query item must be an object",
        ),
        (
            {"items": [{"id": "3001"}], "returned_count": 1, "total_count": 1},
            "JSON_CONTRACT_MISMATCH: catalog_query item is missing category, name, type_id, type_name",
        ),
        (
            {"items": [], "returned_count": 0, "total_count": 0, "note": 7},
            "JSON_CONTRACT_MISMATCH: catalog_query note must be a string",
        ),
    ],
)
def test_query_rejects_invalid_source_result_shapes(monkeypatch, payload, message):
    install_responses(monkeypatch, mcp_responses(payload))

    with pytest.raises(ClientError, match=message):
        BrickStoreClient(config=TestConfig()).query(item_id="3001")
