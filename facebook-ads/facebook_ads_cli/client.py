"""Pinned Meta SDK dispatch and authenticated Graph transport."""

from contextlib import ExitStack
import json
import math
import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from facebook_business.api import FacebookAdsApi, Cursor
from facebook_business.session import FacebookSession
from facebook_business.exceptions import FacebookRequestError
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import validate_filters, parse_filter_string
from cli_tools_shared.http_session import RequestsRetryPolicy, request_with_retry

from .catalog import operation, resource_class
from .config import get_config


SENSITIVE_KEYS = frozenset({"access_token", "appsecret_proof", "app_secret"})


def finite_number(value, name, positive=False):
    """Reject invalid, nonfinite or out-of-range runtime timing values."""
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ClientError(f"{name} must be a finite number.") from None
    if not math.isfinite(number) or number < 0 or positive and number == 0:
        requirement = "positive" if positive else "nonnegative"
        raise ClientError(f"{name} must be finite and {requirement}.")
    return number


def validate_json_numbers(value):
    """Reject nonfinite JSON values before preview, transport or output."""
    if isinstance(value, float) and not math.isfinite(value):
        raise ClientError("JSON numbers must be finite; NaN and Infinity are invalid.")
    if isinstance(value, dict):
        for item in value.values():
            validate_json_numbers(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            validate_json_numbers(item)


def response_data(value):
    if not isinstance(value, (dict, list)):
        raise ClientError("Graph API returned an invalid JSON response; expected object or array.")
    validate_json_numbers(value)
    if isinstance(value, dict) and isinstance(value.get("data"), list):
        if "paging" in value:
            paging = value["paging"]
            if not isinstance(paging, dict):
                raise ClientError("Graph API returned invalid paging metadata; expected object.")
            if "cursors" in paging and not isinstance(paging["cursors"], dict):
                raise ClientError("Graph API returned invalid paging cursors; expected object.")
            if "next" in paging and not isinstance(paging["next"], str):
                raise ClientError("Graph API returned invalid next page URL; expected string.")
        if "summary" in value and not isinstance(value["summary"], dict):
            raise ClientError("Graph API returned invalid summary metadata; expected object.")
    return value


def has_method_override(value):
    """Conservatively classify top-level HTTP override parameters."""
    keys = value.keys() if isinstance(value, dict) else [key for key, _ in parse_qsl(value)] if isinstance(value, str) else []
    return any(str(key).lower() in {"method", "_method"} for key in keys)


class RawResponseParser:
    """Preserve raw API fields instead of SDK object normalization."""

    def parse_single(self, response):
        return response_data(response)

    def parse_multiple(self, response):
        response_data(response)
        if not isinstance(response, dict) or not isinstance(response.get("data"), list):
            raise ClientError("Expected Graph edge response with data array.")
        return response["data"]


class GraphSession(requests.Session):
    """Confine credentials to Graph HTTPS and retry only read requests."""

    def __init__(self, policy):
        super().__init__()
        self.policy = policy

    def request(self, method, url, **kwargs):
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname not in {"graph.facebook.com", "graph-video.facebook.com"}
                or parsed.port not in (None, 443) or parsed.username or parsed.password):
            raise ClientError("Only https://graph.facebook.com or https://graph-video.facebook.com URLs are allowed.")
        kwargs["allow_redirects"] = False
        send = lambda: super(GraphSession, self).request(method, url, **kwargs)
        read_only = (method.upper() == "GET" and not has_method_override(parsed.query)
                     and not has_method_override(kwargs.get("params")))
        response = request_with_retry(send, self.policy) if read_only else send()
        if 300 <= response.status_code < 400:
            raise ClientError("Graph API redirect refused.")
        try:
            response_data(response.json())
        except (ValueError, TypeError):
            raise ClientError("Graph API returned invalid JSON.") from None
        return response


def redact(data):
    """Remove credential values from returned paging URLs and token fields."""
    if isinstance(data, dict):
        return {key: "[REDACTED]" if key in SENSITIVE_KEYS
                else redact(value) for key, value in data.items()}
    if isinstance(data, list):
        return [redact(value) for value in data]
    if isinstance(data, str) and data.startswith("https://"):
        parsed = urlsplit(data)
        return urlunsplit(parsed._replace(query=urlencode([
            (key, "[REDACTED]" if key in SENSITIVE_KEYS else value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)])))
    if isinstance(data, str):
        keys = "|".join(sorted(SENSITIVE_KEYS))
        data = re.sub(rf"\b({keys})(\s*(?:=|:)\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;&]+)",
                      lambda match: f"{match[1]}{match[2]}[REDACTED]", data)
    return data


def native_filters(filters):
    """Translate supported CLI filters to Marketing API filtering clauses."""
    operators = {"eq": "EQUAL", "ne": "NOT_EQUAL", "gt": "GREATER_THAN",
                 "gte": "GREATER_THAN_OR_EQUAL", "lt": "LESS_THAN",
                 "lte": "LESS_THAN_OR_EQUAL", "in": "IN", "nin": "NOT_IN",
                 "contains": "CONTAIN"}
    validate_filters(filters or [])
    result = []
    for expression in filters or []:
        for field, op, value in parse_filter_string(expression):
            if op not in operators:
                raise ClientError(f"Filter operator '{op}' has no supported Meta translation. Use --params with native filtering.")
            if op in ("in", "nin"):
                value = value.split("|")
            else:
                try:
                    value = json.loads(value)
                except (ValueError, TypeError):
                    pass
            result.append({"field": field, "operator": operators[op], "value": value})
    return result


def mutation_guard(method, yes=False, dry_run=False):
    if method != "GET" and not yes and not dry_run:
        raise ClientError("Mutation requires --yes or --dry-run.")


class FacebookAdsClient:
    def __init__(self, config=None, api=None):
        self.config = config or get_config()
        if api is not None:
            self.api = api
            return
        if not self.config.personal_access_token:
            raise ClientError("Missing Meta access token. Run facebook-ads auth login.")
        version = self.config.api_version
        if not re.fullmatch(r"v[0-9]+\.[0-9]+", version):
            raise ClientError("API_VERSION must have form v26.0.")
        defaults = RequestsRetryPolicy()
        overrides = {}
        for field, name in (("max_retries", "MAX_RETRIES"), ("base_delay", "BASE_DELAY"),
                            ("max_delay", "MAX_DELAY"), ("jitter", "RETRY_JITTER")):
            raw = self.config._get(name)
            value = finite_number(raw if raw is not None else getattr(defaults, field), name)
            if field == "max_retries":
                if not value.is_integer():
                    raise ClientError("MAX_RETRIES must be an integer.")
                value = int(value)
            overrides[field] = value
        policy = RequestsRetryPolicy(**overrides)
        timeout = finite_number(self.config._get("HTTP_TIMEOUT") or 60, "HTTP_TIMEOUT", positive=True)
        session = FacebookSession(access_token=self.config.personal_access_token,
                                  app_secret=self.config._get("APP_SECRET"), timeout=timeout)
        session.requests = GraphSession(policy)
        session.requests.headers["Authorization"] = f"Bearer {self.config.personal_access_token}"
        if session.app_secret:
            session.requests.params["appsecret_proof"] = session._gen_appsecret_proof()
        self.api = FacebookAdsApi(session, api_version=version)

    def _run(self, action):
        try:
            return action()
        except FacebookRequestError as exc:
            message = exc.api_error_message() or "Graph API request failed"
            session = getattr(self.api, "_session", None)
            secrets = {self.config.personal_access_token, getattr(session, "app_secret", None)}
            if session is not None:
                secrets.add(getattr(getattr(session, "requests", None), "params", {}).get("appsecret_proof"))
            for secret in secrets:
                if secret:
                    message = message.replace(secret, "[REDACTED]")
            raise ClientError(f"Meta API error {exc.api_error_code()}: {redact(message)}") from None
        except requests.RequestException:
            raise ClientError("Graph API transport failed; check connection and timeout.") from None

    def graph(self, method, path, params=None, files=None, yes=False, dry_run=False, video_host=False):
        validate_json_numbers(params or {})
        method = method.upper()
        if method not in {"GET", "POST", "DELETE", "PUT", "PATCH"}:
            raise ClientError("Unsupported HTTP method.")
        mutation_guard("POST" if has_method_override(params) else method, yes, dry_run)
        if not isinstance(path, str) or any(char in path for char in "?#\\") or ":" in path:
            raise ClientError("Graph path must be a relative node/edge path without a query or URL.")
        tokens = path.strip("/").split("/") if path.strip("/") else []
        if any(token in {".", ".."} or not token for token in tokens):
            raise ClientError("Invalid Graph path.")
        if dry_run:
            return {"method": method, "path": path, "params": redact(params or {}), "files": files or {}, "host": "graph-video.facebook.com" if video_host else "graph.facebook.com"}
        with ExitStack() as stack:
            handles = {key: stack.enter_context(open(value, "rb")) for key, value in (files or {}).items()}
            result = self._run(lambda: self.api.call(method, tuple(tokens), params=params, files=handles,
                                                     url_override="https://graph-video.facebook.com" if video_host else None).json())
        return redact(response_data(result))

    def call(self, resource, method, object_id, params=None, fields=None, files=None,
             all_pages=False, max_items=100, yes=False, dry_run=False):
        record = operation(resource, method)
        mutation_guard("POST" if has_method_override(params) else record["method"], yes, dry_run)
        if not object_id or any(char in object_id for char in "/?#\\:"):
            raise ClientError("Object ID must be a nonempty Graph node ID.")
        params = dict(params or {})
        validate_json_numbers(params)
        if record["method"] == "GET":
            params.setdefault("limit", min(max_items, 100))
        if all_pages and record["method"] != "GET":
            raise ClientError("--all-pages supports GET operations only.")
        if max_items < 1:
            raise ClientError("--limit must be positive.")
        obj = resource_class(resource)(object_id, api=self.api)
        kwargs = {"params": params, "pending": True}
        if fields:
            kwargs["fields"] = fields
        request = getattr(obj, method)(**kwargs)
        if files:
            if not request._allow_file_upload:
                raise ClientError("This SDK operation does not support file uploads; use graph request for other upload protocols.")
            request._file_params.update(files)
        if dry_run:
            return {"resource": resource, "operation": method, "method": record["method"],
                    "path": list(request._path), "params": redact(params), "fields": fields or [], "files": files or {}}
        request._response_parser = RawResponseParser()
        value = self._run(request.execute)
        if isinstance(value, Cursor):
            rows, seen = [], set()
            while True:
                cursor = value.params.get("after")
                if cursor and not value._finished_iteration:
                    if cursor in seen:
                        raise ClientError("Graph API repeated a paging cursor.")
                    seen.add(cursor)
                while value._queue and len(rows) < max_items:
                    row = value._queue.pop(0)
                    rows.append(row.export_all_data() if hasattr(row, "export_all_data") else row)
                if not all_pages or len(rows) >= max_items or value._finished_iteration:
                    break
                self._run(value.load_next_page)
            return redact(rows)
        if hasattr(value, "export_all_data"):
            return redact(value.export_all_data())
        return redact(value.json() if hasattr(value, "json") else value)

    def list_edge(self, parent, edge, limit=100, filters=None, fields=None, params=None):
        params = dict(params or {})
        params["limit"] = min(limit, 100)
        if fields:
            params["fields"] = fields
        if filters:
            params["filtering"] = native_filters(filters)
        rows, seen = [], set()
        while len(rows) < limit:
            params["limit"] = min(100, limit - len(rows))
            page = self.graph("GET", f"{parent}/{edge}", params)
            if not isinstance(page, dict) or not isinstance(page.get("data"), list):
                raise ClientError("Expected Graph edge response with data array.")
            rows.extend(page["data"][:limit - len(rows)])
            paging = page.get("paging", {})
            cursor = paging.get("cursors", {}).get("after")
            if not paging.get("next") or not cursor:
                break
            if cursor in seen:
                raise ClientError("Graph API repeated a paging cursor.")
            seen.add(cursor)
            params["after"] = cursor
        return rows

    def batch(self, operations, files=None, yes=False, dry_run=False):
        if not isinstance(operations, list) or not 1 <= len(operations) <= 50:
            raise ClientError("Batch must contain 1..50 operation objects.")
        for item in operations:
            if not isinstance(item, dict) or not isinstance(item.get("method"), str) or item["method"].upper() not in {"GET", "POST", "DELETE"}:
                raise ClientError("Each batch operation requires GET, POST, or DELETE method.")
            url = item.get("relative_url", "")
            if not isinstance(url, str) or not url or ":" in url.split("?", 1)[0] or url.startswith("/") or "\\" in url:
                raise ClientError("Batch relative_url must be a Graph relative path.")
            if "omit_response_on_success" in item and not isinstance(item["omit_response_on_success"], bool):
                raise ClientError("omit_response_on_success must be a JSON boolean.")
            overridden = has_method_override(urlsplit(url).query) or has_method_override(item.get("body"))
            mutation_guard("POST" if overridden else item["method"].upper(), yes, dry_run)
        result = self.graph("POST", "", {"batch": operations}, files, yes=True, dry_run=dry_run)
        if dry_run:
            return result, False
        if not isinstance(result, list):
            raise ClientError("Expected Graph batch response array.")
        failed = False
        if len(result) != len(operations):
            raise ClientError("Graph batch response length differs from submitted operations.")
        for index, item in enumerate(result):
            if item is None:
                if not operations[index].get("omit_response_on_success"):
                    raise ClientError("Unexpected omitted Graph batch response entry.")
                continue
            if not isinstance(item, dict) or not isinstance(item.get("code"), int):
                raise ClientError("Invalid Graph batch response entry.")
            body = item.get("body")
            if isinstance(body, str):
                try:
                    item["body"] = json.loads(body)
                except ValueError:
                    pass
            failed |= not 200 <= item["code"] < 300 or isinstance(item.get("body"), dict) and "error" in item["body"]
        return redact(result), failed

    def report_status(self, report_id):
        return self.graph("GET", report_id, {"fields": "id,async_status,async_percent_completion"})

    def wait_report(self, report_id, timeout=600, interval=5):
        timeout = finite_number(timeout, "Report timeout", positive=True)
        interval = finite_number(interval, "Report interval", positive=True)
        deadline = time.monotonic() + timeout
        while True:
            status = self.report_status(report_id)
            state = status.get("async_status")
            if state == "Job Completed":
                return status
            if state in {"Job Failed", "Job Skipped"}:
                raise ClientError(f"Insights report ended: {state}.")
            if time.monotonic() >= deadline:
                raise ClientError("Insights report wait timed out; report remains available for later status/results.")
            time.sleep(min(interval, max(0, deadline - time.monotonic())))


def get_client(profile=None, dry_run=False):
    config = get_config(profile)
    api = FacebookAdsApi(FacebookSession(), api_version=config.api_version) if dry_run else None
    return FacebookAdsClient(config=config, api=api)
