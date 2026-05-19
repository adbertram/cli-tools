"""Impact Publisher API client."""
from typing import Any, Optional, Union
import random
import time

import requests

from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import FilterValidationError, apply_filters, parse_filter_string, validate_filters

from .config import get_config
from .models import ImpactDownload, ImpactResource, ImpactValue, create_resource, create_value


DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class ImpactClient:
    """Client for the Impact Publisher/MediaPartner API."""

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        self.config = get_config()
        if not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'impact auth login' to authenticate."
            )

        self.base_url = self.config.base_url.rstrip("/")
        self.account_sid = self.config.impact_account_sid
        self.auth_token = self.config.impact_auth_token
        self.headers = {"Accept": "application/json", "Content-Type": "application/json"}
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        if retry_after is not None:
            return min(retry_after, self.max_delay)
        delay = self.base_delay * (2 ** attempt)
        jitter_range = delay * self.jitter
        return min(delay + random.uniform(-jitter_range, jitter_range), self.max_delay)

    def _get_retry_after(self, response: requests.Response) -> Optional[float]:
        retry_after = response.headers.get("Retry-After")
        if retry_after is None:
            return None
        return float(retry_after)

    def _extract_error_detail(self, response: requests.Response) -> str:
        content_type = response.headers.get("Content-Type", "")
        if "application/json" in content_type:
            body = response.json()
            if "Message" in body:
                return str(body["Message"])
            if "message" in body:
                return str(body["message"])
            if "Error" in body:
                return str(body["Error"])
            if "error" in body:
                return str(body["error"])
            return str(body)[:500]
        return response.text[:500]

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
        data: Optional[dict[str, Any]] = None,
        accept: str = "application/json",
        allow_redirects: bool = True,
    ) -> requests.Response:
        if not endpoint.startswith("/"):
            raise ClientError("Impact endpoint must start with '/'")

        url = f"{self.base_url}/Mediapartners/{self.account_sid}{endpoint}"
        headers = {"Accept": accept, "Content-Type": "application/json"}
        last_exception: Optional[requests.exceptions.RequestException] = None
        last_response: Optional[requests.Response] = None

        for attempt in range(self.max_retries + 1):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    auth=(self.account_sid, self.auth_token),
                    params=params,
                    json=data,
                    timeout=30,
                    allow_redirects=allow_redirects,
                )
                last_response = response
                if response.status_code in RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt, self._get_retry_after(response)))
                    continue
                break
            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError,
            ) as exc:
                last_exception = exc
                if attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt))
                    continue
                break

        if last_response is None:
            raise ClientError(f"Request failed after {self.max_retries + 1} attempts: {last_exception}")
        if not last_response.ok:
            raise ClientError(f"HTTP {last_response.status_code}: {self._extract_error_detail(last_response)}")
        return last_response

    def _json_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
        data: Optional[dict[str, Any]] = None,
    ) -> Any:
        response = self._make_request(method, endpoint, params=params, data=data)
        if response.status_code == 204:
            return {}
        return response.json()

    def _resource(self, method: str, endpoint: str, **kwargs) -> Union[ImpactResource, ImpactValue]:
        body = self._json_request(method, endpoint, **kwargs)
        if isinstance(body, dict):
            return create_resource(body)
        return create_value(body)

    def _collection(
        self,
        endpoint: str,
        key: str,
        limit: int = 100,
        filters: Optional[list[str]] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> list[ImpactResource]:
        query = self._list_params(limit, filters)
        if params:
            self._merge_unique_params(query, params)
        body = self._json_request("GET", endpoint, params=query)
        if key not in body:
            raise ClientError(f"Impact list response did not include '{key}'")
        items = body[key]
        if not isinstance(items, list):
            raise ClientError(f"Impact response field '{key}' was not a list")
        items = apply_filters(items, filters)
        return [create_resource(item) for item in items]

    def _download(self, endpoint: str, params: Optional[dict[str, Any]] = None) -> ImpactDownload:
        response = self._make_request(
            "GET",
            endpoint,
            params=params,
            accept="application/octet-stream",
            allow_redirects=True,
        )
        return ImpactDownload(
            status_code=response.status_code,
            content_type=response.headers.get("Content-Type", ""),
            content=response.content.decode("utf-8", errors="replace"),
        )

    def _list_params(
        self,
        limit: int = 100,
        filters: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"PageSize": limit}
        params.update(self._translate_filters(filters))
        return params

    def _translate_filters(self, filters: Optional[list[str]]) -> dict[str, Any]:
        if not filters:
            return {}

        validate_filters(filters)
        params: dict[str, Any] = {}
        for filter_string in filters:
            for field, op, value in parse_filter_string(filter_string):
                if op != "eq":
                    raise FilterValidationError(
                        f"Unsupported Impact filter '{field}:{op}'. Impact API filters use equality query parameters."
                    )
                self._set_unique_param(params, field, value)
        return params

    def _merge_unique_params(self, params: dict[str, Any], extra: dict[str, Any]) -> None:
        for key, value in extra.items():
            self._set_unique_param(params, key, value)

    def _set_unique_param(self, params: dict[str, Any], key: str, value: Any) -> None:
        if key in params:
            raise ClientError(f"Duplicate Impact query parameter: {key}")
        params[key] = value

    def get_account(self):
        return self._resource("GET", "/CompanyInformation")

    def update_account(self, data: dict[str, Any]):
        return self._resource("PUT", "/CompanyInformation", data=data)

    def list_users(self, limit=100, filters=None):
        return self._collection("/Users", "Users", limit, filters)

    def get_user(self, user_id: str):
        return self._resource("GET", f"/Users/{user_id}")

    def list_invoices(self, limit=100, filters=None):
        return self._collection("/Invoices", "Invoices", limit, filters)

    def get_invoice(self, invoice_id: str):
        return self._resource("GET", f"/Invoices/{invoice_id}")

    def download_invoice(self, invoice_id: str):
        return self._download(f"/Invoices/{invoice_id}/Download")

    def list_tax_documents(self, limit=100, filters=None):
        return self._collection("/TaxDocuments", "TaxDocuments", limit, filters)

    def get_tax_document(self, tax_document_id: str):
        return self._resource("GET", f"/TaxDocument/{tax_document_id}")

    def get_latest_tax_document(self):
        return self._resource("GET", "/TaxDocument")

    def create_tax_document(self, data: dict[str, Any]):
        return self._resource("POST", "/TaxDocument", data=data)

    def complete_tax_document_submission(self, data: dict[str, Any]):
        return self._resource("POST", "/TaxDocument/Complete", data=data)

    def get_withdrawal_settings(self):
        return self._resource("GET", "/WithdrawalSettings")

    def update_withdrawal_settings(self, data: dict[str, Any]):
        return self._resource("PUT", "/WithdrawalSettings", data=data)

    def get_required_banking_fields(self, bank_country: str):
        return self._resource("GET", "/WithdrawalSettings/RequiredFields", params={"bankCountry": bank_country})

    def list_campaigns(self, limit=100, filters=None):
        return self._collection("/Campaigns", "Campaigns", limit, filters)

    def get_campaign(self, campaign_id: str):
        return self._resource("GET", f"/Campaigns/{campaign_id}")

    def get_campaign_logo(self, campaign_id: str):
        return self._download(f"/Campaigns/{campaign_id}/Logo")

    def list_contracts(self, limit=100, filters=None):
        return self._collection("/Contracts", "Contracts", limit, filters)

    def get_contract(self, contract_id: str):
        return self._resource("GET", f"/Contracts/{contract_id}")

    def download_active_contract(self, campaign_id: str):
        return self._download(f"/Campaigns/{campaign_id}/Contracts/Active")

    def download_public_terms(self, campaign_id: str):
        return self._download(f"/Campaigns/{campaign_id}/PublicTerms/Download")

    def list_promotions(self, limit=100, filters=None):
        return self._collection("/Promotions", "Promotions", limit, filters)

    def get_promotion(self, promotion_id: str):
        return self._resource("GET", f"/Promotions/{promotion_id}")

    def list_deals(self, campaign_id: str, limit=100, filters=None):
        return self._collection(f"/Campaigns/{campaign_id}/Deals", "Deals", limit, filters)

    def get_deal(self, campaign_id: str, deal_id: str):
        return self._resource("GET", f"/Campaigns/{campaign_id}/Deals/{deal_id}")

    def create_tracking_link(self, program_id: str, data: dict[str, Any]):
        return self._resource("POST", f"/Programs/{program_id}/TrackingLinks", params=data)

    def list_ads(self, limit=100, filters=None):
        return self._collection("/Ads", "Ads", limit, filters)

    def get_ad(self, ad_id: str):
        return self._resource("GET", f"/Ads/{ad_id}")

    def get_ad_code(self, ad_id: str):
        return self._resource("GET", f"/Ads/{ad_id}/Code")

    def get_ad_iframe_code(self, ad_id: str):
        return self._resource("GET", f"/Ads/{ad_id}/IFrameCode")

    def get_ad_tracking_link(self, ad_id: str):
        return self._resource("GET", f"/Ads/{ad_id}/TrackingLink")

    def list_actions(self, limit=100, filters=None):
        return self._collection("/Actions", "Actions", limit, filters)

    def get_action(self, action_id: str):
        return self._resource("GET", f"/Actions/{action_id}")

    def list_action_items(self, action_id: str, limit=100, filters=None):
        return self._collection(f"/Actions/{action_id}/Items", "Items", limit, filters)

    def get_action_item(self, action_id: str, sku: str):
        return self._resource("GET", f"/Actions/{action_id}/Items/{sku}")

    def list_action_updates(self, limit=100, filters=None):
        return self._collection("/ActionUpdates", "ActionUpdates", limit, filters)

    def get_action_update(self, update_id: str):
        return self._resource("GET", f"/ActionUpdates/{update_id}")

    def list_action_inquiries(self, limit=100, filters=None):
        return self._collection("/ActionInquiries", "ActionInquiries", limit, filters)

    def get_action_inquiry(self, inquiry_id: str):
        return self._resource("GET", f"/ActionInquiries/{inquiry_id}")

    def create_action_inquiry(self, data: dict[str, Any]):
        return self._resource("POST", "/ActionInquiries", data=data)

    def list_catalogs(self, limit=100, filters=None):
        return self._collection("/Catalogs", "Catalogs", limit, filters)

    def get_catalog(self, catalog_id: str):
        return self._resource("GET", f"/Catalogs/{catalog_id}")

    def list_catalog_items(self, catalog_id: str, limit=100, filters=None):
        return self._collection(f"/Catalogs/{catalog_id}/Items", "Items", limit, filters)

    def get_catalog_item(self, catalog_id: str, item_id: str):
        return self._resource("GET", f"/Catalogs/{catalog_id}/Items/{item_id}")

    def search_catalog_items(self, limit=100, filters=None):
        return self._collection("/Catalogs/ItemSearch", "Items", limit, filters)

    def list_stores(self, limit=100, filters=None):
        return self._collection("/Stores", "Stores", limit, filters)

    def get_store(self, store_id: str):
        return self._resource("GET", f"/Stores/{store_id}")

    def list_store_items(self, store_id: str, group_id: str, limit=100, filters=None):
        return self._collection(f"/Stores/{store_id}/Group/{group_id}/Items", "Items", limit, filters)

    def get_exception_list(self, exception_list_id: str):
        return self._resource("GET", f"/ExceptionLists/{exception_list_id}")

    def list_exception_list_items(self, exception_list_id: str, limit=100, filters=None):
        return self._collection(f"/ExceptionLists/{exception_list_id}/Items", "Items", limit, filters)

    def get_promo_code_exception_list(self, exception_list_id: str):
        return self._resource("GET", f"/PromoCodeExceptionLists/{exception_list_id}")

    def list_promo_code_exception_list_items(self, exception_list_id: str, limit=100, filters=None):
        return self._collection(f"/PromoCodeExceptionLists/{exception_list_id}/Items", "Items", limit, filters)

    def list_reports(self, limit=100, filters=None):
        return self._collection("/Reports", "Reports", limit, filters)

    def run_report(self, report_id: str, limit=100, filters=None):
        return self._collection(f"/Reports/{report_id}", "Records", limit, filters)

    def get_report_metadata(self, report_id: str):
        return self._resource("GET", f"/Reports/{report_id}/MetaData")

    def export_report(self, report_id: str, params: Optional[dict[str, Any]] = None):
        return self._resource("GET", f"/ReportExport/{report_id}", params=params)

    def get_click(self, click_id: str):
        return self._resource("GET", f"/Clicks/{click_id}")

    def export_clicks(self, params: dict[str, Any]):
        return self._resource("GET", "/ClickExport", params=params)

    def list_jobs(self, limit=100, filters=None):
        return self._collection("/Jobs", "Jobs", limit, filters)

    def get_job(self, job_id: str):
        return self._resource("GET", f"/Jobs/{job_id}")

    def download_job(self, job_id: str):
        return self._download(f"/Jobs/{job_id}/Download")

    def replay_job(self, job_id: str):
        return self._resource("PUT", f"/Jobs/{job_id}/Replay")

    def list_websites(self, limit=100, filters=None):
        return self._collection("/MediaProperties", "MediaProperties", limit, filters)

    def get_website(self, website_id: str):
        return self._resource("GET", f"/MediaProperties/{website_id}")

    def create_website(self, data: dict[str, Any]):
        return self._resource("POST", "/MediaProperties", data=data)

    def update_website(self, website_id: str, data: dict[str, Any]):
        return self._resource("PUT", f"/MediaProperties/{website_id}", data=data)

    def delete_website(self, website_id: str):
        return self._resource("DELETE", f"/MediaProperties/{website_id}")


_client: Optional[ImpactClient] = None


def get_client() -> ImpactClient:
    global _client
    if _client is None:
        _client = ImpactClient()
    return _client
