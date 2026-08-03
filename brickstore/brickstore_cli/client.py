"""BrickStore MCP client."""

import json
import subprocess
import time
from contextlib import contextmanager
from typing import Any

import requests
from cli_tools_shared.activity_log import get_activity_logger
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.http_session import (
    DEFAULT_REQUESTS_BASE_DELAY,
    DEFAULT_REQUESTS_JITTER,
    DEFAULT_REQUESTS_MAX_DELAY,
    DEFAULT_REQUESTS_MAX_RETRIES,
    RequestsRetryPolicy,
    request_with_retry,
)

from . import __version__
from .config import get_config


MCP_PROTOCOL_VERSION = "2025-03-26"
JSONRPC_VERSION = "2.0"
REQUEST_TIMEOUT_SECONDS = 60
SERVER_READINESS_TIMEOUT_SECONDS = 30
SERVER_READINESS_POLL_SECONDS = 1
SERVER_STOP_TIMEOUT_SECONDS = 10
CATALOG_QUERY_TOOL = "catalog_query"
CATALOG_PRICE_GUIDE_TOOL = "catalog_price_guide"
SET_ITEM_TYPE = "S"
REQUIRED_TOOL_NAMES = {CATALOG_QUERY_TOOL, CATALOG_PRICE_GUIDE_TOOL}
MAX_SET_BATCH_SIZE = 25

activity = get_activity_logger("brickstore")


class BrickStoreServerUnavailableError(ClientError):
    """Report a connection failure before an MCP session starts."""


def validate_set_numbers(set_numbers: list[str], command_name: str) -> None:
    """Validate the shared multi-set input contract."""
    if not set_numbers:
        raise ClientError("{} requires from 1 through {} unique set IDs".format(command_name, MAX_SET_BATCH_SIZE))
    if len(set_numbers) > MAX_SET_BATCH_SIZE:
        raise ClientError("{} accepts at most {} set IDs".format(command_name, MAX_SET_BATCH_SIZE))

    seen = set()
    for set_number in set_numbers:
        if set_number in seen:
            raise ClientError("{} set IDs must be unique: {}".format(command_name, set_number))
        seen.add(set_number)


class BrickStoreClient:
    """Read BrickStore catalog data through its Streamable HTTP MCP server."""

    def __init__(
        self,
        config=None,
        max_retries: int = DEFAULT_REQUESTS_MAX_RETRIES,
        base_delay: float = DEFAULT_REQUESTS_BASE_DELAY,
        max_delay: float = DEFAULT_REQUESTS_MAX_DELAY,
        jitter: float = DEFAULT_REQUESTS_JITTER,
    ):
        self.config = config or get_config()
        self.base_url = self.config.base_url
        self.retry_policy = RequestsRetryPolicy(
            max_retries=max_retries,
            base_delay=base_delay,
            max_delay=max_delay,
            jitter=jitter,
        )
        self._next_request_id = 1

    @staticmethod
    def _response_detail(response: requests.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return response.text[:500]
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            message = body["error"].get("message")
            if isinstance(message, str):
                return message
        return str(body)[:500]

    def _post(self, payload: dict) -> requests.Response:
        def send() -> requests.Response:
            response = requests.request(
                "POST",
                self.base_url,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                json=payload,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            activity.info("POST %s -> %s", self.base_url, response.status_code)
            return response

        try:
            return request_with_retry(send, self.retry_policy)
        except requests.exceptions.RequestException as error:
            raise BrickStoreServerUnavailableError(
                "BrickStore MCP server is unavailable at {}: {}. "
                "Open BrickStore, enable the MCP server and Catalog Read permission in Settings > AI, "
                "then confirm the configured port.".format(self.base_url, error)
            ) from error

    def _rpc(self, method: str, params: dict | None = None, notification: bool = False) -> dict | None:
        request: dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "method": method}
        if params is not None:
            request["params"] = params
        request_id: int | None = None
        if not notification:
            request_id = self._next_request_id
            request["id"] = request_id
            self._next_request_id += 1

        response = self._post(request)
        expected_status = 202 if notification else 200
        if response.status_code != expected_status:
            raise ClientError(
                "BrickStore MCP server returned HTTP {} for {}: {}".format(
                    response.status_code,
                    method,
                    self._response_detail(response),
                )
            )
        if notification:
            return None

        try:
            payload = response.json()
        except ValueError as error:
            raise ClientError("BrickStore MCP returned invalid JSON for {}".format(method)) from error
        if not isinstance(payload, dict):
            raise ClientError("JSON_CONTRACT_MISMATCH: MCP response must be an object")
        if payload.get("jsonrpc") != JSONRPC_VERSION:
            raise ClientError("JSON_CONTRACT_MISMATCH: MCP response jsonrpc must be 2.0")
        if payload.get("id") != request_id:
            raise ClientError("JSON_CONTRACT_MISMATCH: MCP response id does not match the request")
        if "error" in payload:
            error_data = payload["error"]
            if not isinstance(error_data, dict) or not isinstance(error_data.get("message"), str):
                raise ClientError("JSON_CONTRACT_MISMATCH: MCP error must include a string message")
            raise ClientError("BrickStore MCP error: {}".format(error_data["message"]))
        result = payload.get("result")
        if not isinstance(result, dict):
            raise ClientError("JSON_CONTRACT_MISMATCH: MCP response result must be an object")
        return result

    @staticmethod
    def _tool_text(result: dict) -> str:
        content = result.get("content")
        if not isinstance(content, list) or not content:
            raise ClientError("JSON_CONTRACT_MISMATCH: MCP tool result content must be a non-empty array")
        first = content[0]
        if not isinstance(first, dict) or first.get("type") != "text" or not isinstance(first.get("text"), str):
            raise ClientError("JSON_CONTRACT_MISMATCH: MCP tool result content[0] must be text")
        return first["text"]

    def _call_tool(self, name: str, arguments: dict) -> dict:
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        if result is None:
            raise ClientError("JSON_CONTRACT_MISMATCH: MCP tools/call returned no result")
        text = self._tool_text(result)
        if result.get("isError") is True:
            raise ClientError("BrickStore source error: {}".format(text))
        if result.get("isError") is not False:
            raise ClientError("JSON_CONTRACT_MISMATCH: MCP tool result isError must be boolean")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise ClientError("JSON_CONTRACT_MISMATCH: MCP tool text must contain JSON") from error
        if not isinstance(payload, dict):
            raise ClientError("JSON_CONTRACT_MISMATCH: MCP tool JSON must be an object")
        return payload

    def _start_mcp_session(self, required_tool_names: set[str] = REQUIRED_TOOL_NAMES) -> None:
        initialized = self._rpc(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "brickstore-cli", "version": __version__},
            },
        )
        if initialized is None or initialized.get("protocolVersion") != MCP_PROTOCOL_VERSION:
            raise ClientError("JSON_CONTRACT_MISMATCH: BrickStore MCP protocol version is invalid")
        server_info = initialized.get("serverInfo")
        if not isinstance(server_info, dict) or server_info.get("name") != "BrickStore MCP Server":
            raise ClientError("JSON_CONTRACT_MISMATCH: BrickStore MCP server identity is invalid")
        self._rpc("initialized", notification=True)

        tools_result = self._rpc("tools/list")
        if tools_result is None or not isinstance(tools_result.get("tools"), list):
            raise ClientError("JSON_CONTRACT_MISMATCH: MCP tools/list result must include tools")
        tool_names = {
            tool["name"]
            for tool in tools_result["tools"]
            if isinstance(tool, dict) and isinstance(tool.get("name"), str)
        }
        missing = sorted(required_tool_names - tool_names)
        if missing:
            raise ClientError(
                "BrickStore source error: MCP Catalog Read permission does not expose {}. "
                "Enable it in Settings > AI.".format(", ".join(missing))
            )

    def _start_mcp_server(self, leave_open: bool = False):
        try:
            return subprocess.Popen(
                [self.config.executable],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=leave_open,
            )
        except OSError as error:
            raise ClientError(str(error)) from error

    @staticmethod
    def _start_error(process) -> str:
        stdout, stderr = process.communicate()
        source_error = stderr.strip() or stdout.strip()
        if source_error:
            return source_error
        return "BrickStore exited with {}".format(process.returncode)

    def _wait_for_mcp_server(self, process, required_tool_names: set[str]) -> None:
        deadline = time.monotonic() + SERVER_READINESS_TIMEOUT_SECONDS
        while True:
            try:
                self._start_mcp_session(required_tool_names)
                return
            except BrickStoreServerUnavailableError as error:
                readiness_error = error

            exit_code = process.poll()
            if exit_code is not None:
                if exit_code != 0:
                    raise ClientError(self._start_error(process))
                if time.monotonic() >= deadline:
                    raise readiness_error
                time.sleep(SERVER_READINESS_POLL_SECONDS)
                continue
            if time.monotonic() >= deadline:
                raise readiness_error
            time.sleep(SERVER_READINESS_POLL_SECONDS)

    @staticmethod
    def _stop_mcp_server(process) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=SERVER_STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as error:
            raise ClientError(
                "BrickStore MCP server did not stop within {} seconds".format(SERVER_STOP_TIMEOUT_SECONDS)
            ) from error

    @contextmanager
    def _price_guide_session(
        self,
        required_tool_names: set[str] = REQUIRED_TOOL_NAMES,
        leave_open: bool = False,
    ):
        try:
            self._start_mcp_session(required_tool_names)
        except BrickStoreServerUnavailableError:
            process = self._start_mcp_server(leave_open=leave_open)
            try:
                self._wait_for_mcp_server(process, required_tool_names)
                yield
            finally:
                if not leave_open:
                    self._stop_mcp_server(process)
        else:
            yield

    @staticmethod
    def _single_price_guide(payload: dict) -> dict:
        results = payload.get("results")
        if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
            raise ClientError("JSON_CONTRACT_MISMATCH: price guide results must contain one object")
        result = results[0]
        if "error" in result:
            if not isinstance(result["error"], str):
                raise ClientError("JSON_CONTRACT_MISMATCH: price guide error must be a string")
            raise ClientError("BrickStore source error: {}".format(result["error"]))
        required_fields = {
            "item_id",
            "item_name",
            "color",
            "currency",
            "last_updated",
            "last_six_months",
            "current",
        }
        missing = sorted(required_fields - set(result))
        if missing:
            raise ClientError(
                "JSON_CONTRACT_MISMATCH: price guide result is missing {}".format(", ".join(missing))
            )
        return result

    def part(self, item_number: str, color: str | None, leave_open: bool = False) -> dict:
        """Return the price guide for one part."""
        with self._price_guide_session(leave_open=leave_open):
            item = {"item_id": item_number, "item_type": "P"}
            if color is not None:
                item["color"] = color
            return self._single_price_guide(self._call_tool(CATALOG_PRICE_GUIDE_TOOL, {"items": [item]}))

    def set(self, set_number: str, leave_open: bool = False) -> dict:
        """Return the price guide for one set."""
        with self._price_guide_session(leave_open=leave_open):
            query = self._call_tool(CATALOG_QUERY_TOOL, {"item_id": set_number, "item_type": SET_ITEM_TYPE})
            items = query.get("items")
            if not isinstance(items, list):
                raise ClientError("JSON_CONTRACT_MISMATCH: catalog_query items must be an array")
            matches = [
                item
                for item in items
                if isinstance(item, dict) and item.get("id") == set_number and item.get("type_id") == SET_ITEM_TYPE
            ]
            if len(matches) != 1:
                raise ClientError(
                    "BrickStore source error: catalog_query did not return one exact Set item for {}".format(set_number)
                )
            source_item = matches[0]
            return self._single_price_guide(
                self._call_tool(
                    CATALOG_PRICE_GUIDE_TOOL,
                    {"items": [{"item_id": source_item["id"], "item_type": source_item["type_id"]}]},
                )
            )

    @staticmethod
    def _set_contents_record(set_number: str, source_subsets: list) -> dict:
        items = []
        for source_subset in source_subsets:
            if not isinstance(source_subset, dict):
                raise ClientError("JSON_CONTRACT_MISMATCH: BrickLink subset group must be an object")
            match_no = source_subset.get("match_no")
            if type(match_no) is not int:
                raise ClientError("JSON_CONTRACT_MISMATCH: BrickLink subset group match_no must be an integer")
            entries = source_subset.get("entries")
            if not isinstance(entries, list):
                raise ClientError("JSON_CONTRACT_MISMATCH: BrickLink subset group entries must be an array")
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ClientError("JSON_CONTRACT_MISMATCH: BrickLink subset entry must be an object")
                item = dict(entry)
                item["match_no"] = match_no
                items.append(item)
        return {"set_id": set_number, "items": items}

    @staticmethod
    def _bricklink_subsets(set_number: str) -> list:
        command_args = ["bricklink", "catalog", "subsets", "SET", set_number]
        try:
            result = subprocess.run(
                command_args,
                capture_output=True,
                check=False,
                text=True,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as error:
            raise ClientError("BrickLink CLI is unavailable on PATH") from error
        except subprocess.TimeoutExpired as error:
            raise ClientError("BrickLink set contents command timed out for {}".format(set_number)) from error

        activity.info("%s -> %s", " ".join(command_args[:-1]), result.returncode)
        if result.returncode != 0:
            raise ClientError(
                "BrickLink set contents command failed for {} with exit {}".format(set_number, result.returncode)
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise ClientError("JSON_CONTRACT_MISMATCH: BrickLink set contents output must be JSON") from error
        if not isinstance(payload, list):
            raise ClientError("JSON_CONTRACT_MISMATCH: BrickLink set contents output must be an array")
        return payload

    def set_contents(self, set_numbers: list[str]) -> list:
        """Return direct item records for each requested set."""
        validate_set_numbers(set_numbers, "set-contents")
        return [
            self._set_contents_record(set_number, self._bricklink_subsets(set_number))
            for set_number in set_numbers
        ]

    @staticmethod
    def _require_query_fields(source: dict, required_fields, subject: str) -> None:
        missing = sorted(required_fields - set(source))
        if missing:
            raise ClientError(
                "JSON_CONTRACT_MISMATCH: catalog_query {} is missing {}".format(subject, ", ".join(missing))
            )

    @staticmethod
    def _validate_query_result(payload: dict) -> dict:
        BrickStoreClient._require_query_fields(payload, {"total_count", "returned_count", "items"}, "result")
        if not isinstance(payload["items"], list):
            raise ClientError("JSON_CONTRACT_MISMATCH: catalog_query items must be an array")
        if type(payload["total_count"]) is not int or type(payload["returned_count"]) is not int:
            raise ClientError(
                "JSON_CONTRACT_MISMATCH: catalog_query total_count and returned_count must be integers"
            )
        for item in payload["items"]:
            if not isinstance(item, dict):
                raise ClientError("JSON_CONTRACT_MISMATCH: catalog_query item must be an object")
            BrickStoreClient._require_query_fields(
                item, {"id", "name", "type_id", "type_name", "category"}, "item"
            )
        if "note" in payload and not isinstance(payload["note"], str):
            raise ClientError("JSON_CONTRACT_MISMATCH: catalog_query note must be a string")
        return payload

    def query(
        self,
        item_id: str | None = None,
        item_name: str | None = None,
        item_type: str | None = None,
        category: str | None = None,
        color: str | None = None,
        related_to_item_id: str | None = None,
        related_to_item_type: str | None = None,
        relationship: str | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        leave_open: bool = False,
    ) -> dict:
        """Return catalog_query results for the given filters."""
        arguments = {
            key: value
            for key, value in {
                "item_id": item_id,
                "item_name": item_name,
                "item_type": item_type,
                "category": category,
                "color": color,
                "related_to_item_id": related_to_item_id,
                "related_to_item_type": related_to_item_type,
                "relationship": relationship,
                "year_min": year_min,
                "year_max": year_max,
            }.items()
            if value is not None
        }
        with self._price_guide_session({CATALOG_QUERY_TOOL}, leave_open=leave_open):
            return self._validate_query_result(self._call_tool(CATALOG_QUERY_TOOL, arguments))

    def set_batch(self, set_numbers: list[str], leave_open: bool = False) -> dict:
        """Return price guides for known BrickLink set IDs."""
        validate_set_numbers(set_numbers, "set-batch")
        with self._price_guide_session({CATALOG_PRICE_GUIDE_TOOL}, leave_open=leave_open):
            payload = self._call_tool(
                CATALOG_PRICE_GUIDE_TOOL,
                {"items": [{"item_id": set_number, "item_type": SET_ITEM_TYPE} for set_number in set_numbers]},
            )
            results = payload.get("results")
            if not isinstance(results, list):
                raise ClientError("BrickStore source error: catalog_price_guide results must be an array")

            requested_set_numbers = set(set_numbers)
            returned_set_numbers = set()
            for source_result in results:
                if not isinstance(source_result, dict):
                    raise ClientError("BrickStore source error: catalog_price_guide returned an invalid result")
                result = self._single_price_guide({"results": [source_result]})
                set_number = result["item_id"]
                if set_number not in requested_set_numbers:
                    raise ClientError(
                        "BrickStore source error: catalog_price_guide returned unexpected result for {}".format(set_number)
                    )
                for field_name in ("item_type", "type_id"):
                    if field_name in result and result[field_name] != SET_ITEM_TYPE:
                        raise ClientError(
                            "BrickStore source error: catalog_price_guide returned {} {} for {}, expected {}".format(
                                field_name,
                                result[field_name],
                                set_number,
                                SET_ITEM_TYPE,
                            )
                        )
                if set_number in returned_set_numbers:
                    raise ClientError(
                        "BrickStore source error: catalog_price_guide returned duplicate result for {}".format(set_number)
                    )
                returned_set_numbers.add(set_number)

            for set_number in set_numbers:
                if set_number not in returned_set_numbers:
                    raise ClientError(
                        "BrickStore source error: catalog_price_guide did not return a result for {}".format(set_number)
                    )
            return {"results": results}


_client: BrickStoreClient | None = None


def get_client() -> BrickStoreClient:
    """Get or create the BrickStore client."""
    global _client
    if _client is None:
        _client = BrickStoreClient()
    return _client
