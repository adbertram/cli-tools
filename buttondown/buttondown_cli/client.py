"""Buttondown API client."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Type, TypeVar
import random
import time

import requests

from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import FilterValidationError, parse_filter_string, validate_filters

from .config import get_config, set_global_profile as set_config_global_profile
from .models import (
    Account,
    ActionResult,
    Automation,
    ButtondownModel,
    Email,
    ExternalFeed,
    Newsletter,
    Render,
    Subscriber,
    Tag,
    TagAnalytics,
    create_account,
    create_automation,
    create_email,
    create_external_feed,
    create_newsletter,
    create_render,
    create_subscriber,
    create_tag,
    create_tag_analytics,
)


DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

T = TypeVar("T", bound=ButtondownModel)


SUBSCRIBER_FILTERS = {
    "id": {"eq": "ids", "in": "ids"},
    "ids": {"eq": "ids", "in": "ids"},
    "email_address": {"eq": "email_address", "like": "email_address", "ilike": "email_address"},
    "domain": {"eq": "domain", "in": "domain", "ne": "-domain", "nin": "-domain"},
    "tag": {"eq": "tag", "in": "tag", "ne": "-tag", "nin": "-tag"},
    "type": {"eq": "type", "in": "type", "ne": "-type", "nin": "-type"},
    "source": {"eq": "source", "in": "source"},
    "created": {"gte": "date__start", "lte": "date__end"},
    "creation_date": {"gte": "date__start", "lte": "date__end"},
    "churn_date": {"gte": "churn_date__start", "lte": "churn_date__end"},
    "click_rate": {"gte": "click_rate__start", "lte": "click_rate__end"},
    "current_price": {"eq": "current_price", "in": "current_price"},
    "form": {"eq": "form", "in": "form"},
    "ip_address": {"eq": "ip_address", "in": "ip_address"},
    "last_click_date": {"gte": "last_click_date__start", "lte": "last_click_date__end"},
    "last_open_date": {"gte": "last_open_date__start", "lte": "last_open_date__end"},
    "open_rate": {"gte": "open_rate__start", "lte": "open_rate__end"},
    "price": {"eq": "price", "in": "price"},
    "referral_code": {"eq": "referral_code", "in": "referral_code"},
    "referrer_url": {"eq": "referrer_url", "like": "referrer_url", "ilike": "referrer_url"},
    "risk_score": {"gte": "risk_score__start", "lte": "risk_score__end"},
    "subscriber_import": {"eq": "subscriber_import", "in": "subscriber_import"},
    "undeliverability_date": {"gte": "undeliverability_date__start", "lte": "undeliverability_date__end"},
    "undeliverability_reason": {"eq": "undeliverability_reason", "in": "undeliverability_reason"},
    "unsubscription_date": {"gte": "unsubscription_date__start", "lte": "unsubscription_date__end"},
    "unsubscription_reason": {"eq": "unsubscription_reason", "in": "unsubscription_reason"},
    "upgrade_date": {"gte": "upgrade_date__start", "lte": "upgrade_date__end"},
    "utm_campaign": {"eq": "utm_campaign", "in": "utm_campaign"},
    "utm_medium": {"eq": "utm_medium", "in": "utm_medium"},
    "utm_source": {"eq": "utm_source", "in": "utm_source"},
}

EMAIL_FILTERS = {
    "id": {"eq": "ids", "in": "ids"},
    "ids": {"eq": "ids", "in": "ids"},
    "status": {"eq": "status", "in": "status", "ne": "-status", "nin": "-status"},
    "source": {"eq": "source", "in": "source"},
    "archival_mode": {"eq": "archival_mode", "in": "archival_mode"},
    "email_type": {"eq": "email_type", "in": "email_type"},
    "subject": {"eq": "subject", "like": "subject", "ilike": "subject"},
    "attachments": {"eq": "attachments", "in": "attachments"},
    "snippet_id": {"eq": "snippet_id", "in": "snippet_id"},
    "creation_date": {"gte": "creation_date__start", "lte": "creation_date__end"},
    "publish_date": {"gte": "publish_date__start", "lte": "publish_date__end"},
    "deliveries": {"gte": "deliveries__start", "lte": "deliveries__end"},
    "click_rate": {"gte": "click_rate__start", "lte": "click_rate__end"},
    "open_rate": {"gte": "open_rate__start", "lte": "open_rate__end"},
}

TAG_FILTERS = {
    "id": {"eq": "ids", "in": "ids"},
    "ids": {"eq": "ids", "in": "ids"},
}

EXTERNAL_FEED_FILTERS: Dict[str, Dict[str, str]] = {}

AUTOMATION_FILTERS: Dict[str, Dict[str, str]] = {}

FEATURE_RSS = "rss"
FEATURE_AUTOMATIONS = "automations"

_client: Optional["ButtondownClient"] = None
_global_profile: Optional[str] = None


def set_global_profile(profile: Optional[str]) -> None:
    """Set the profile used by command-created clients."""
    global _client, _global_profile
    _global_profile = profile
    set_config_global_profile(profile)
    _client = None


class ButtondownClient:
    """Client for Buttondown's documented REST API."""

    def __init__(
        self,
        config=None,
        session: Optional[requests.Session] = None,
        profile: Optional[str] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        self.config = config if config is not None else get_config(profile=profile)
        if not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'buttondown auth login' to authenticate."
            )

        self.base_url = self.config.base_url.rstrip("/")
        self.session = session if session is not None else requests.Session()
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Token {self.config.api_key}",
            "Content-Type": "application/json",
        }

    def _url(self, endpoint: str) -> str:
        if endpoint.startswith("https://"):
            return endpoint
        return f"{self.base_url}{endpoint}"

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        if retry_after is not None:
            return min(retry_after, self.max_delay)
        delay = self.base_delay * (2**attempt)
        jitter_range = delay * self.jitter
        return min(delay + random.uniform(-jitter_range, jitter_range), self.max_delay)

    def _get_retry_after(self, response) -> Optional[float]:
        value = response.headers.get("Retry-After")
        if value is None:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    def _is_retryable(self, response=None, exception: Optional[Exception] = None) -> bool:
        if exception is not None:
            return isinstance(
                exception,
                (
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.ChunkedEncodingError,
                ),
            )
        return response is not None and response.status_code in RETRYABLE_STATUS_CODES

    def _error_detail(self, response) -> str:
        try:
            data = response.json()
        except ValueError:
            return response.text
        if "detail" not in data:
            return str(data)
        if "code" in data:
            return f"{data['code']}: {data['detail']}"
        return data["detail"]

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        retry: bool = True,
    ) -> Dict[str, Any]:
        last_exception: Optional[Exception] = None
        last_response = None
        max_attempts = self.max_retries + 1 if retry else 1

        for attempt in range(max_attempts):
            try:
                last_response = self.session.request(
                    method,
                    self._url(endpoint),
                    headers=self.headers,
                    json=data,
                    params=params,
                )
                if retry and self._is_retryable(response=last_response) and attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt, self._get_retry_after(last_response)))
                    continue
                break
            except requests.exceptions.RequestException as exc:
                last_exception = exc
                if retry and self._is_retryable(exception=exc) and attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt))
                    continue
                break

        if last_response is None:
            raise ClientError(f"Request failed after {max_attempts} attempts: {last_exception}")

        if not 200 <= last_response.status_code < 300:
            raise ClientError(f"HTTP {last_response.status_code}: {self._error_detail(last_response)}")

        if last_response.status_code == 204:
            return {}

        return last_response.json()

    def _params_from_filters(
        self,
        resource_name: str,
        filter_map: Dict[str, Dict[str, str]],
        filters: Optional[List[str]],
    ) -> Dict[str, Any]:
        if not filters:
            return {}

        try:
            validate_filters(filters)
        except FilterValidationError as exc:
            raise ClientError(f"Invalid filter: {exc}")

        params: Dict[str, Any] = {}
        for filter_string in filters:
            for field, operator, value in parse_filter_string(filter_string):
                field_map = filter_map.get(field)
                if field_map is None or operator not in field_map:
                    raise ClientError(
                        f"Filter '{field}:{operator}' is not supported for {resource_name}."
                    )
                if value is None:
                    raise ClientError(f"Filter '{field}:{operator}' requires a value for {resource_name}.")

                api_name = field_map[operator]
                api_value: Any = value.split("|") if operator in {"in", "nin"} else value
                self._add_param(params, api_name, api_value)

        return params

    def _add_param(self, params: Dict[str, Any], key: str, value: Any) -> None:
        if key not in params:
            params[key] = value
            return
        existing = params[key]
        if not isinstance(existing, list):
            existing = [existing]
        if isinstance(value, list):
            existing.extend(value)
        else:
            existing.append(value)
        params[key] = existing

    def _list_paginated(
        self,
        endpoint: str,
        model: Type[T],
        limit: int,
        params: Optional[Dict[str, Any]] = None,
        page_size_param: Optional[str] = None,
    ) -> List[T]:
        if limit < 1:
            raise ClientError("--limit must be greater than 0")

        query_params = dict(params or {})
        if page_size_param is not None:
            query_params[page_size_param] = limit

        results: List[T] = []
        next_endpoint: Optional[str] = endpoint

        while next_endpoint is not None and len(results) < limit:
            response = self._make_request("GET", next_endpoint, params=query_params)
            if "results" not in response:
                raise ClientError("Expected paginated response with a 'results' field.")
            results.extend(model(**item) for item in response["results"])
            next_endpoint = response.get("next")
            query_params = {}

        return results[:limit]

    def _payload(self, values: Dict[str, Any]) -> Dict[str, Any]:
        payload = {key: value for key, value in values.items() if value is not None}
        if not payload:
            raise ClientError("At least one field is required.")
        return payload

    def ping(self) -> Dict[str, Any]:
        return self._make_request("GET", "/ping")

    def list_subscribers(self, limit: int = 100, filters: Optional[List[str]] = None) -> List[Subscriber]:
        params = self._params_from_filters("subscribers", SUBSCRIBER_FILTERS, filters)
        return self._list_paginated("/subscribers", Subscriber, limit, params=params)

    def get_subscriber(self, id_or_email: str) -> Subscriber:
        return create_subscriber(self._make_request("GET", f"/subscribers/{id_or_email}"))

    def create_subscriber(
        self,
        email_address: str,
        notes: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        subscriber_type: Optional[str] = None,
    ) -> Subscriber:
        payload = self._payload(
            {
                "email_address": email_address,
                "notes": notes,
                "metadata": metadata,
                "tags": tags,
                "type": subscriber_type,
            }
        )
        return create_subscriber(self._make_request("POST", "/subscribers", data=payload))

    def update_subscriber(self, id_or_email: str, **values: Any) -> Subscriber:
        payload = self._payload(values)
        return create_subscriber(self._make_request("PATCH", f"/subscribers/{id_or_email}", data=payload))

    def delete_subscriber(self, id_or_email: str) -> ActionResult:
        self._make_request("DELETE", f"/subscribers/{id_or_email}")
        return ActionResult(ok=True, action="delete_subscriber", id=id_or_email)

    def send_magic_link(self, id_or_email: str) -> ActionResult:
        self._make_request("POST", f"/subscribers/{id_or_email}/send-magic-link")
        return ActionResult(ok=True, action="send_magic_link", id=id_or_email)

    def send_reminder(self, id_or_email: str) -> ActionResult:
        self._make_request("POST", f"/subscribers/{id_or_email}/send-reminder")
        return ActionResult(ok=True, action="send_reminder", id=id_or_email)

    def list_emails(self, limit: int = 100, filters: Optional[List[str]] = None) -> List[Email]:
        params = self._params_from_filters("emails", EMAIL_FILTERS, filters)
        return self._list_paginated("/emails", Email, limit, params=params)

    def get_email(self, email_id: str) -> Email:
        return create_email(self._make_request("GET", f"/emails/{email_id}"))

    def create_email(self, **values: Any) -> Email:
        payload = self._payload(values)
        return create_email(self._make_request("POST", "/emails", data=payload))

    def update_email(self, email_id: str, **values: Any) -> Email:
        payload = self._payload(values)
        return create_email(self._make_request("PATCH", f"/emails/{email_id}", data=payload))

    def delete_email(self, email_id: str) -> ActionResult:
        self._make_request("DELETE", f"/emails/{email_id}")
        return ActionResult(ok=True, action="delete_email", id=email_id)

    def send_draft(
        self,
        email_id: str,
        recipients: Optional[List[str]] = None,
        subscribers: Optional[List[str]] = None,
    ) -> ActionResult:
        self._make_request(
            "POST",
            f"/emails/{email_id}/send-draft",
            data=self._payload({"recipients": recipients, "subscribers": subscribers}),
        )
        return ActionResult(ok=True, action="send_draft", id=email_id)

    def list_tags(self, limit: int = 100, filters: Optional[List[str]] = None) -> List[Tag]:
        params = self._params_from_filters("tags", TAG_FILTERS, filters)
        return self._list_paginated("/tags", Tag, limit, params=params, page_size_param="page_size")

    def get_tag(self, tag_id: str) -> Tag:
        return create_tag(self._make_request("GET", f"/tags/{tag_id}"))

    def create_tag(
        self,
        name: str,
        color: str,
        description: Optional[str] = None,
        public_description: Optional[str] = None,
        subscriber_editable: Optional[bool] = None,
    ) -> Tag:
        payload = self._payload(
            {
                "name": name,
                "color": color,
                "description": description,
                "public_description": public_description,
                "subscriber_editable": subscriber_editable,
            }
        )
        return create_tag(self._make_request("POST", "/tags", data=payload))

    def update_tag(self, tag_id: str, **values: Any) -> Tag:
        payload = self._payload(values)
        return create_tag(self._make_request("PATCH", f"/tags/{tag_id}", data=payload))

    def delete_tag(self, tag_id: str) -> ActionResult:
        self._make_request("DELETE", f"/tags/{tag_id}")
        return ActionResult(ok=True, action="delete_tag", id=tag_id)

    def get_tag_analytics(self, tag_id: str) -> TagAnalytics:
        return create_tag_analytics(self._make_request("GET", f"/tags/{tag_id}/analytics"))

    def render_email(self, email_id: str, target: str) -> Render:
        if target not in ("email", "html"):
            raise ClientError("--target must be 'email' or 'html'")
        return create_render(
            self._make_request("GET", f"/emails/{email_id}/renders", params={"target": target})
        )

    def list_external_feeds(
        self, limit: int = 100, filters: Optional[List[str]] = None
    ) -> List[ExternalFeed]:
        self.require_feature(FEATURE_RSS, "feeds")
        params = self._params_from_filters("external_feeds", EXTERNAL_FEED_FILTERS, filters)
        return self._list_paginated("/external_feeds", ExternalFeed, limit, params=params)

    def get_external_feed(self, feed_id: str) -> ExternalFeed:
        self.require_feature(FEATURE_RSS, "feeds")
        return create_external_feed(self._make_request("GET", f"/external_feeds/{feed_id}"))

    def create_external_feed(self, **values: Any) -> ExternalFeed:
        self.require_feature(FEATURE_RSS, "feeds")
        payload = self._payload(values)
        return create_external_feed(self._make_request("POST", "/external_feeds", data=payload))

    def update_external_feed(self, feed_id: str, **values: Any) -> ExternalFeed:
        self.require_feature(FEATURE_RSS, "feeds")
        payload = self._payload(values)
        return create_external_feed(
            self._make_request("PATCH", f"/external_feeds/{feed_id}", data=payload)
        )

    def delete_external_feed(self, feed_id: str) -> ActionResult:
        self.require_feature(FEATURE_RSS, "feeds")
        self._make_request("DELETE", f"/external_feeds/{feed_id}")
        return ActionResult(ok=True, action="delete_external_feed", id=feed_id)

    def list_automations(
        self, limit: int = 100, filters: Optional[List[str]] = None
    ) -> List[Automation]:
        self.require_feature(FEATURE_AUTOMATIONS, "automations")
        params = self._params_from_filters("automations", AUTOMATION_FILTERS, filters)
        return self._list_paginated("/automations", Automation, limit, params=params)

    def get_automation(self, automation_id: str) -> Automation:
        self.require_feature(FEATURE_AUTOMATIONS, "automations")
        return create_automation(self._make_request("GET", f"/automations/{automation_id}"))

    def create_automation(self, **values: Any) -> Automation:
        self.require_feature(FEATURE_AUTOMATIONS, "automations")
        payload = self._payload(values)
        return create_automation(self._make_request("POST", "/automations", data=payload))

    def update_automation(self, automation_id: str, **values: Any) -> Automation:
        self.require_feature(FEATURE_AUTOMATIONS, "automations")
        payload = self._payload(values)
        return create_automation(
            self._make_request("PATCH", f"/automations/{automation_id}", data=payload)
        )

    def delete_automation(self, automation_id: str) -> ActionResult:
        self.require_feature(FEATURE_AUTOMATIONS, "automations")
        self._make_request("DELETE", f"/automations/{automation_id}")
        return ActionResult(ok=True, action="delete_automation", id=automation_id)

    def get_account(self) -> Account:
        return create_account(self._make_request("GET", "/accounts/me"))

    def list_newsletters(self, limit: int = 100) -> List[Newsletter]:
        return self._list_paginated("/newsletters", Newsletter, limit)

    def get_current_newsletter(self) -> Newsletter:
        account = self.get_account()
        newsletters = self.list_newsletters(limit=100)
        matches = [n for n in newsletters if n.username == account.username]
        if not matches:
            raise ClientError(
                f"Current account username {account.username!r} does not appear in the "
                f"newsletter list for this API key. The key may not be tied to any "
                f"newsletter accessible via the API."
            )
        if len(matches) > 1:
            raise ClientError(
                f"Multiple newsletters share username {account.username!r}; cannot "
                f"disambiguate the current newsletter."
            )
        return matches[0]

    def require_feature(self, feature: str, command_group: str) -> None:
        newsletter = self.get_current_newsletter()
        if feature not in newsletter.enabled_features:
            profile_name = self.config.get_active_profile_name()
            raise ClientError(
                f"Profile '{profile_name}' (newsletter '{newsletter.username}', "
                f"id {newsletter.id}) does not have the '{feature}' feature enabled. "
                f"Enabled features: {', '.join(newsletter.enabled_features) or '(none)'}. "
                f"The '{command_group}' command group requires the '{feature}' feature. "
                f"Switch to a profile whose newsletter has '{feature}' enabled, or "
                f"enable the feature for '{newsletter.username}' in Buttondown."
            )


def get_client(profile: Optional[str] = None) -> ButtondownClient:
    """Get or create the global Buttondown client."""
    global _client
    effective_profile = profile if profile is not None else _global_profile
    if profile is not None:
        return ButtondownClient(profile=effective_profile)
    if _client is None:
        _client = ButtondownClient(profile=effective_profile)
    return _client
