"""Rakuten Advertising Publisher API client.

Auth: OAuth 2.0 password grant. Tokens come from the Config helper, which
caches them in the profile env until expiry.

Base URL: https://api.linksynergy.com

Notable endpoints:

  GET /advertisersearch/1.0     Search advertisers (XML response)
  GET /coupon/1.0               Coupon feed
  GET /linklocator/getMerchByID/<mid>   Merchant detail
"""
import time
import xml.etree.ElementTree as ET
from typing import Any, List, Optional

import requests

from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    parse_filter_string,
    validate_filters,
)

from .config import get_config
from .models import Advertiser, create_advertiser


DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class RakutenClient:
    """Client for the Rakuten Advertising Publisher API."""

    def __init__(self, config=None, max_retries: int = DEFAULT_MAX_RETRIES):
        self.config = config or get_config()
        if not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'rakuten auth login' to authenticate."
            )
        self.base_url = self.config.base_url.rstrip("/")
        self.max_retries = max_retries

    def _retry_delay(self, attempt: int) -> float:
        return min(DEFAULT_BASE_DELAY * (2 ** attempt), DEFAULT_MAX_DELAY)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.config.get_access_token()}",
            "Accept": "application/json",
        }

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        accept: str = "application/json",
    ) -> requests.Response:
        if not endpoint.startswith("/"):
            raise ClientError("Rakuten endpoint must start with '/'")
        url = f"{self.base_url}{endpoint}"
        headers = self._headers()
        headers["Accept"] = accept

        last_exception: Optional[requests.exceptions.RequestException] = None
        last_response: Optional[requests.Response] = None

        for attempt in range(self.max_retries + 1):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    timeout=30,
                )
                last_response = response
                # Refresh token once on 401, then retry without counting it
                if response.status_code == 401 and attempt == 0:
                    self.config.get_access_token(force_refresh=True)
                    headers = self._headers()
                    headers["Accept"] = accept
                    continue
                if response.status_code in RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                    time.sleep(self._retry_delay(attempt))
                    continue
                break
            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError,
            ) as exc:
                last_exception = exc
                if attempt < self.max_retries:
                    time.sleep(self._retry_delay(attempt))
                    continue
                break

        if last_response is None:
            raise ClientError(f"Request failed after {self.max_retries + 1} attempts: {last_exception}")
        if not last_response.ok:
            raise ClientError(
                f"HTTP {last_response.status_code}: {last_response.text[:500]}"
            )
        return last_response

    @staticmethod
    def _xml_to_dicts(body: bytes, record_tag: Optional[str] = None) -> List[dict]:
        """Parse an XML body into a list of dicts.

        Rakuten's advertiser-search response is::

            <result>
              <midlist>
                <merchant>
                  <mid>815</mid>
                  <merchantname>Sharper Image</merchantname>
                  ...
                </merchant>
                ...
              </midlist>
            </result>

        We descend the tree and collect every element whose local-name
        matches ``record_tag`` (so ``<merchant>`` records nested under
        ``<midlist>`` are captured even though they are grandchildren of
        the root). When ``record_tag`` is omitted, every direct child of
        the root is treated as a record.
        """
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            raise ClientError(f"Rakuten returned non-XML body: {exc}: {body[:500]!r}")

        def local(tag: str) -> str:
            return tag.rsplit("}", 1)[-1]

        def record_from_element(elem) -> dict:
            record: dict[str, Any] = {}
            for field in list(elem):
                record[local(field.tag)] = (field.text or "").strip()
            return record

        records: list[dict] = []
        if record_tag:
            for elem in root.iter():
                if local(elem.tag) == record_tag:
                    records.append(record_from_element(elem))
        else:
            for child in list(root):
                records.append(record_from_element(child))
        return records

    # ---- advertisers --------------------------------------------------------

    def list_advertisers(
        self,
        status: str = "approved",
        limit: int = 100,
        filters: Optional[List[str]] = None,
    ) -> List[Advertiser]:
        """List advertisers visible to the publisher.

        GET /advertisersearch/1.0?status=...

        Rakuten's ``/advertisersearch/1.0`` endpoint only honors a small
        set of query params (``status``, ``merchantname``, ``category``,
        ``country``, ``applicationstatus``). Other filters are applied
        client-side after the response is parsed so ``--filter`` always
        narrows the result set regardless of Rakuten support.
        """
        params: dict[str, Any] = {"status": status}
        server_known = {"merchantname", "category", "country", "applicationstatus", "status"}
        if filters:
            validate_filters(filters)
            for filter_string in filters:
                for field, op, value in parse_filter_string(filter_string):
                    if op != "eq":
                        raise FilterValidationError(
                            f"Unsupported Rakuten filter '{field}:{op}'. Rakuten filters use equality."
                        )
                    if field.lower() in server_known:
                        params[field] = value

        response = self._request(
            "GET",
            "/advertisersearch/1.0",
            params=params,
            accept="application/xml",
        )
        rows = self._xml_to_dicts(response.content, record_tag="merchant")
        # Mirror merchantname -> name and mid -> id on the raw rows so client-side
        # filtering can match either the API field name or the canonical alias
        for row in rows:
            if not row.get("name") and row.get("merchantname"):
                row["name"] = row["merchantname"]
            if not row.get("id") and row.get("mid"):
                row["id"] = row["mid"]
        # Client-side filter pass -- guarantees --filter actually narrows the result
        if filters:
            rows = apply_filters(rows, filters)
        return [create_advertiser(row) for row in rows[:limit]]

    def get_advertiser(self, mid: str) -> Advertiser:
        """Get a single advertiser by merchant id (mid).

        Rakuten Advertising no longer exposes ``linklocator/getMerchByID``
        on the public OAuth API. The cheapest valid way to surface one
        record is to call ``/advertisersearch/1.0`` and filter the
        ``<midlist>`` for the requested mid client-side.
        """
        response = self._request(
            "GET",
            "/advertisersearch/1.0",
            params={"status": "approved"},
            accept="application/xml",
        )
        rows = self._xml_to_dicts(response.content, record_tag="merchant")
        match = next((row for row in rows if str(row.get("mid")) == str(mid)), None)
        if match is None:
            raise ClientError(f"Rakuten merchant {mid} not found in approved list")
        return create_advertiser(match)


_client: Optional[RakutenClient] = None


def get_client() -> RakutenClient:
    global _client
    if _client is None:
        _client = RakutenClient()
    return _client
