"""Plain-HTTP BrickLink marketplace client (searchproduct + catalogifs)."""

from __future__ import annotations

import logging
from typing import Any, Mapping
from urllib.parse import urlencode

import requests

from cli_tools_shared.http_session import (
    BrowserAuthState,
    BrowserAuthStateError,
    RequestsRetryPolicy,
    build_requests_session,
)

from .classify import (
    BrickLinkAjaxError,
    BrickLinkThrottleError,
    ResponseClass,
    classify_response,
)
from .host_queue import HostRequestQueue, get_bricklink_queue

logger = logging.getLogger("bricklink.buy.http")

BRICKLINK_ORIGIN = "https://www.bricklink.com"
SEARCH_PRODUCT_PATH = "/ajax/clone/search/searchproduct.ajax"
CATALOGIFS_PATH = "/ajax/clone/catalogifs.ajax"
ALLOWED_COOKIE_DOMAINS = ("bricklink.com", ".bricklink.com", "www.bricklink.com")

AJAX_HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://www.bricklink.com/",
    "X-Requested-With": "XMLHttpRequest",
}


class BrickLinkBuyHttpClient:
    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        queue: HostRequestQueue | None = None,
        auth_state: BrowserAuthState | None = None,
        cookie_jar_path: str | None = None,
        timeout: float = 30.0,
    ):
        if session is not None:
            self.session = session
        else:
            try:
                self.session = build_requests_session(
                    auth_state=auth_state,
                    allowed_domains=ALLOWED_COOKIE_DOMAINS if auth_state else (),
                    headers=AJAX_HEADERS,
                    cookie_jar_path=cookie_jar_path,
                )
            except BrowserAuthStateError:
                self.session = build_requests_session(
                    headers=AJAX_HEADERS,
                    cookie_jar_path=cookie_jar_path,
                )
        self.session.headers.update(AJAX_HEADERS)
        self.queue = queue or get_bricklink_queue()
        self.timeout = timeout
        self._policy = RequestsRetryPolicy()

    def close(self) -> None:
        jar = self.session.cookies
        save = getattr(jar, "save", None)
        if callable(save):
            try:
                save(ignore_discard=True, ignore_expires=True)
            except OSError:
                pass
        self.session.close()

    def search_product(self, *, query: str, item_type: str, page: int = 1, rpp: int = 25) -> dict[str, Any]:
        params = {"q": query, "type": item_type, "rpp": rpp, "pi": page}
        return self._get_json(SEARCH_PRODUCT_PATH, params)

    def catalogifs(
        self,
        *,
        item_id: int,
        page: int = 1,
        rpp: int = 500,
        color_id: int | None = None,
        condition: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "itemid": int(item_id),
            "rpp": int(rpp),
            "pi": int(page),
            "iconly": 0,
        }
        if color_id is not None:
            params["color"] = int(color_id)
        if condition:
            params["cond"] = condition.upper()
        return self._get_json(CATALOGIFS_PATH, params)

    def _get_json(self, path: str, params: Mapping[str, Any]) -> dict[str, Any]:
        url = f"{BRICKLINK_ORIGIN}{path}?{urlencode(params)}"

        def _once() -> dict[str, Any]:
            try:
                response = self.session.get(url, timeout=self.timeout)
            except requests.exceptions.Timeout as exc:
                raise TimeoutError(str(exc)) from exc
            except requests.exceptions.ConnectionError as exc:
                raise ConnectionError(str(exc)) from exc

            classified = classify_response(
                status_code=response.status_code,
                content=response.content or b"",
                headers=dict(response.headers),
            )
            if classified.classification == ResponseClass.THROTTLE:
                logger.warning("BrickLink throttle: %s (%s)", classified.detail, url)
                raise BrickLinkThrottleError(classified)
            if classified.classification == ResponseClass.TRANSIENT:
                raise ConnectionError(classified.detail or f"HTTP {response.status_code}")
            if classified.classification == ResponseClass.BL_ERROR:
                raise BrickLinkAjaxError(classified)
            if classified.classification != ResponseClass.OK_JSON:
                if response.status_code == 403 or self._policy.is_empty_forbidden(response):
                    raise BrickLinkThrottleError(classified)
                raise BrickLinkAjaxError(classified)
            if not isinstance(classified.payload, dict):
                raise BrickLinkAjaxError(classified)
            return classified.payload

        return self.queue.submit(_once)
