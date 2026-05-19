"""Apple purchase history client backed by the private reportaproblem API."""

from __future__ import annotations

import json
from typing import Any

import requests
from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from .config import get_config
from .parsers import (
    match_purchase_records,
    normalize_purchase_batch,
    validate_request_context,
)

PURCHASE_SEARCH_URL = "https://reportaproblem.apple.com/api/purchase/search"
FORBIDDEN_CAPTURED_HEADERS = {"content-length", "cookie", "host"}
STATIC_REQUEST_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Referer": "https://reportaproblem.apple.com/",
    "x-apple-rap2-api": "3.0.0",
}


class AppleClient:
    """Read Apple purchase and subscription history via the private JSON API."""

    def __init__(self):
        self.config = get_config()
        self.browser = self.config.get_browser()

    def close(self) -> None:
        self.browser.close()

    def _load_request_context(self) -> dict[str, Any]:
        return _load_request_context(self.config)

    def _build_session(
        self,
        captured_headers: dict[str, str],
        captured_cookies: list[dict[str, Any]],
    ) -> requests.Session:
        return _build_session(captured_headers, captured_cookies)

    def _post_purchase_search(
        self,
        session: requests.Session,
        payload: dict[str, str],
    ) -> dict[str, Any]:
        return _post_purchase_search(session, payload)

    def _iter_purchase_batches(self):
        request_context = self._load_request_context()
        session = self._build_session(request_context["headers"], request_context["cookies"])
        dsid = request_context["dsid"]

        try:
            next_batch_id = ""
            initial_request = True
            while True:
                payload = {"dsid": dsid} if initial_request else {"batchId": next_batch_id, "dsid": dsid}
                response = self._post_purchase_search(session, payload)
                yield normalize_purchase_batch(response)
                next_batch_id = response.get("nextBatchId")
                if not isinstance(next_batch_id, str):
                    raise ClientError("Apple purchase history response did not include string nextBatchId.")
                if next_batch_id == "":
                    break
                initial_request = False
        finally:
            session.close()

    @cached
    def _list_all_purchase_records(self, stop_after: int | None = None) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for batch in self._iter_purchase_batches():
            records.extend(batch)
            if stop_after is not None and len(records) >= stop_after:
                return records[:stop_after]
        return records

    @cached
    def list_purchases(self, limit: int = 100) -> list[dict[str, Any]]:
        """List normalized purchase line items from Apple purchase history."""
        if limit <= 0:
            raise ClientError("Limit must be greater than zero.")
        return self._list_all_purchase_records(stop_after=limit)

    @cached
    def get_purchase_line(self, record_id: str) -> dict[str, Any]:
        """Get one purchase line item by stable record id."""
        if not isinstance(record_id, str) or not record_id:
            raise ClientError("Record id must be a non-empty string.")
        for batch in self._iter_purchase_batches():
            for record in batch:
                if record["id"] == record_id:
                    return record
        raise ClientError(f"Record not found: {record_id}")

    @cached
    def match_purchase(
        self,
        amount: str | None = None,
        date: str | None = None,
        query: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Find purchase records matching amount, date, or query."""
        return match_purchase_records(
            self._list_all_purchase_records(),
            amount=amount,
            date=date,
            query=query,
            limit=limit,
        )


_client: AppleClient | None = None


def get_client() -> AppleClient:
    """Get or create the global Apple client instance."""
    global _client
    if _client is None:
        _client = AppleClient()
    return _client


def _load_request_context(config) -> dict[str, Any]:
    path = config.request_context_path
    if not path.exists():
        raise ClientError(
            "Missing Apple purchase request context. Run 'apple auth login' to capture it."
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ClientError(
            f"Apple purchase request context file was not valid JSON: {path}"
        ) from exc
    return validate_request_context(payload)


def _build_session(
    captured_headers: dict[str, str],
    captured_cookies: list[dict[str, Any]],
) -> requests.Session:
    session = requests.Session()
    session.headers.update(STATIC_REQUEST_HEADERS)
    session.headers.update(
        {
            key: value
            for key, value in captured_headers.items()
            if key.lower() not in FORBIDDEN_CAPTURED_HEADERS
        }
    )
    for cookie in captured_cookies:
        name = cookie.get("name")
        value = cookie.get("value")
        domain = cookie.get("domain")
        path = cookie.get("path")
        if not isinstance(name, str) or not name:
            raise ClientError("Apple browser session cookie is missing a name.")
        if not isinstance(value, str):
            raise ClientError(f"Apple browser session cookie '{name}' is missing a value.")
        if not isinstance(domain, str) or not domain:
            raise ClientError(f"Apple browser session cookie '{name}' is missing a domain.")
        if not isinstance(path, str) or not path:
            raise ClientError(f"Apple browser session cookie '{name}' is missing a path.")
        session.cookies.set(name, value, domain=domain, path=path)
    return session


def _post_purchase_search(
    session: requests.Session,
    payload: dict[str, str],
) -> dict[str, Any]:
    try:
        response = session.post(
            PURCHASE_SEARCH_URL,
            json=payload,
            timeout=30,
        )
    except requests.RequestException as exc:
        raise ClientError(f"Apple purchase history request failed: {exc}") from exc

    if response.status_code != 200:
        raise ClientError(
            f"Apple purchase history request failed with status {response.status_code}."
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise ClientError("Apple purchase history response was not valid JSON.") from exc

    if not isinstance(data, dict):
        raise ClientError("Apple purchase history response was not a JSON object.")
    return data


def probe_purchase_search_context(config) -> None:
    request_context = _load_request_context(config)
    session = _build_session(request_context["headers"], request_context["cookies"])
    try:
        response = _post_purchase_search(session, {"dsid": request_context["dsid"]})
    finally:
        session.close()
    normalize_purchase_batch(response)
    next_batch_id = response.get("nextBatchId")
    if not isinstance(next_batch_id, str):
        raise ClientError("Apple purchase history response did not include string nextBatchId.")
