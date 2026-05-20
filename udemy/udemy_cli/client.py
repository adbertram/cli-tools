"""Udemy Instructor API client."""
from typing import Any, Dict, List, Optional
import random
import time
import requests

from .browser import UDEMY_ORIGIN
from cli_tools_shared.filters import validate_filters, FilterValidationError
from .config import activity, get_config
from .models import Course, create_course
from cli_tools_shared.http_session import BrowserAutomationJsonClient, required_path
from cli_tools_shared.exceptions import ClientError


DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
COURSES_ENDPOINT = "/taught-courses/courses/"
COURSE_FIELDS = "@all"
MAX_PAGE_SIZE = 100
GOALS_FIELDS = "requirements_data,what_you_will_learn_data,who_should_attend_data"
BASICS_FIELDS = (
    "title,headline,description,locale,instructional_level_id,primary_category,"
    "primary_subcategory,all_course_has_labels,image_750x422,promo_asset,"
    "intended_category,category_locked,category_applicable,label_applicable,"
    "min_summary_words,landing_preview_as_guest_url,organization_id,is_published"
)
PRICING_FIELDS = (
    "base_price_detail,is_paid,min_price,num_paid_switches,price_updated_date,_class,"
    "features,id,is_published,published_time,is_practice_test_course,"
    "num_published_practice_tests,is_owner,is_owner_opted_into_deals,"
    "owner_is_premium_instructor,url"
)
PRICING_UPDATE_FIELDS = "base_price_detail,is_paid,min_price,num_paid_switches,price_updated_date"
CAPTION_FIELDS = "asset_id,locale_id,title,url,source,status,confidence_threshold,modified,is_edit,is_edit_of_autocaption"
DRAFT_CAPTION_FIELDS = "asset_id,locale_id,source,status,published_caption_id,modified"
CAPTION_COURSE_FIELDS = (
    "can_edit,primary_subcategory,promo_asset,locale,is_published,organization_id,"
    "is_in_any_ufb_content_collection,is_language_course"
)
QUALITY_FIELDS = "quality_status,quality_review_process"
QUALITY_FEEDBACK_FIELDS = "comment_thread,is_marked_as_fixed,quality_criteria,rating"
QUALITY_CRITERIA_FIELDS = "solution_url,solution_text,title"
STUDENT_FIELDS = (
    "@default,completion_ratio,enrollment_date,is_organization_enrollment,"
    "last_accessed,question_count,question_answer_count"
)
GOALS_UPDATE_KEYS = {"requirements_data", "what_you_will_learn_data", "who_should_attend_data"}
BASICS_UPDATE_KEYS = {
    "title",
    "headline",
    "description",
    "locale",
    "instructional_level_id",
    "category_id",
    "subcategory_id",
    "labels_json",
    "promo_asset",
}
PRICING_UPDATE_KEYS = {"price_money"}
MESSAGE_UPDATE_KEYS = {"message_type", "content"}
AVAILABILITY_UPDATE_KEYS = {"status", "respond_time_frame", "available_date", "apply_to_all_courses"}
AVAILABILITY_STATUSES = {1, 2, 3}
RESPOND_TIME_FRAMES = {"12 hours", "24 hours", "48 hours", "2-4 days", "1 week", None}
ACCESSIBILITY_SETTINGS = {
    "are_captions_provided",
    "is_audio_description_included",
    "is_course_content_accessible",
}
ACCESSIBILITY_VALUES = {"on", "off"}
CAPTION_UPDATE_KEYS = {"locale", "availability"}
CAPTION_AVAILABILITIES = {"public", "restricted"}
COUPON_UPDATE_KEYS = {"code", "discount_value", "discount_strategy", "start_time"}
COURSE_MANAGEMENT_UPDATE_ORDER = (
    "goals",
    "basics",
    "pricing",
    "communications",
    "availability",
    "accessibility",
    "captions",
    "promotions",
)


class UdemyClient:
    """Client for Udemy Instructor API."""

    def __init__(
        self,
        config=None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        self.config = config or get_config()
        self.base_url = self.config.base_url.rstrip("/")
        self.session = requests.Session()
        self.browser_automation = self.config.get_browser()
        self.browser = BrowserAutomationJsonClient(self.browser_automation, UDEMY_ORIGIN)
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter

    @property
    def headers(self) -> dict[str, str]:
        """Build request headers for the configured bearer token."""
        self._require_api_credentials()
        return {
            "Authorization": f"Bearer {self.config.personal_access_token}",
            "Accept": "application/json",
        }

    def _require_api_credentials(self) -> None:
        if not self.config.has_api_credentials():
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'udemy auth login' to authenticate."
            )

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        """Calculate retry delay using exponential backoff with jitter."""
        if retry_after is not None:
            return min(retry_after, self.max_delay)
        delay = self.base_delay * (2 ** attempt)
        jitter_range = delay * self.jitter
        delay += random.uniform(-jitter_range, jitter_range)
        return min(delay, self.max_delay)

    def _is_retryable(self, response: Optional[requests.Response], exception: Optional[Exception]) -> bool:
        if exception is not None:
            return isinstance(exception, (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError,
            ))
        if response is not None:
            return response.status_code in RETRYABLE_STATUS_CODES
        return False

    def _get_retry_after(self, response: requests.Response) -> Optional[float]:
        retry_after = response.headers.get("Retry-After")
        if retry_after is None:
            return None
        try:
            return float(retry_after)
        except ValueError:
            return None

    def _extract_error_detail(self, response: requests.Response) -> str:
        """Extract error detail from an HTTP error response."""
        try:
            error_body = response.json()
            if "_error" in error_body:
                err = error_body["_error"]
                if isinstance(err, dict):
                    return err.get("Description") or err.get("Message") or err.get("Code") or str(err)
                return str(err)
            if "error" in error_body:
                err = error_body["error"]
                if isinstance(err, dict):
                    return err.get("message") or err.get("code") or err.get("description") or str(err)
                return str(err)
            if "message" in error_body:
                return error_body["message"]
            return str(error_body)[:500]
        except Exception:
            return response.text[:500] if response.text else "Unknown error"

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        retry: bool = True,
    ) -> Dict:
        """Make an HTTP request to the Udemy API with exponential retry."""
        url = f"{self.base_url}{endpoint}"
        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None
        max_attempts = (self.max_retries + 1) if retry else 1

        for attempt in range(max_attempts):
            try:
                activity.info("Request %s %s", method, endpoint)
                response = self.session.request(
                    method,
                    url,
                    headers=self.headers,
                    params=params,
                    json=data,
                    timeout=30,
                )
                last_response = response
                activity.info("Response %s %s -> %s", method, endpoint, response.status_code)

                if retry and self._is_retryable(response, None) and attempt < self.max_retries:
                    retry_after = self._get_retry_after(response)
                    delay = self._calculate_retry_delay(attempt, retry_after)
                    activity.warning("Retrying %s %s after %.2fs", method, endpoint, delay)
                    time.sleep(delay)
                    continue
                break

            except requests.exceptions.RequestException as e:
                last_exception = e
                if retry and self._is_retryable(None, e) and attempt < self.max_retries:
                    delay = self._calculate_retry_delay(attempt)
                    activity.warning("Retrying %s %s after exception: %s", method, endpoint, type(e).__name__)
                    time.sleep(delay)
                    continue
                break

        if last_exception is not None and last_response is None:
            raise ClientError(f"Request failed after {attempt + 1} attempts: {last_exception}")

        if last_response is None:
            raise ClientError("Request failed: no response received")

        if last_response.status_code < 200 or last_response.status_code >= 300:
            error_msg = self._extract_error_detail(last_response)
            raise ClientError(f"HTTP {last_response.status_code}: {error_msg}")

        if last_response.status_code == 204:
            return {}

        return last_response.json()

    def _validate_page(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        """Validate and return the paginated Udemy results array."""
        if "results" not in response:
            raise ClientError("Expected Udemy response to contain 'results'.")
        results = response["results"]
        if not isinstance(results, list):
            raise ClientError("Expected Udemy response 'results' to be a list.")
        return results

    def _get_course_page(self, page: int, page_size: int) -> dict[str, Any]:
        params = {
            "page_size": page_size,
            "fields[course]": COURSE_FIELDS,
        }
        if page > 1:
            params["page"] = page
        return self._make_request("GET", COURSES_ENDPOINT, params=params)

    def _iter_courses(self, limit: Optional[int] = None):
        """Yield courses across Udemy paginated responses."""
        remaining = limit
        page = 1

        while remaining is None or remaining > 0:
            page_size = MAX_PAGE_SIZE if remaining is None else min(remaining, MAX_PAGE_SIZE)
            response = self._get_course_page(page=page, page_size=page_size)
            results = self._validate_page(response)
            for raw_course in results:
                yield create_course(raw_course)

            if response.get("next") is None:
                break
            if not results:
                raise ClientError("Udemy returned an empty page with a next page URL.")

            if remaining is not None:
                remaining -= len(results)
            page += 1

    def list_courses(self, limit: int = 100, filters: Optional[List[str]] = None) -> List[Course]:
        """List instructor-taught Udemy courses."""
        if limit < 1:
            raise ClientError("Limit must be greater than zero.")
        if filters:
            try:
                validate_filters(filters)
            except FilterValidationError as e:
                raise ClientError(f"Invalid filter: {e}")
            raise ClientError("Udemy taught courses endpoint does not support server-side filters.")

        return list(self._iter_courses(limit=limit))

    def get_course(self, course_id: str) -> Course:
        """Get one instructor-taught course by ID."""
        for course in self._iter_courses():
            if course.id == course_id:
                return course

        raise ClientError(f"Course {course_id} was not found in the instructor course list.")

    def get_course_management(self, course_id: str) -> dict[str, Any]:
        """Get browser-backed course management data, excluding curriculum."""
        menu = self.browser.request_json("GET", f"/api-2.0/courses/{course_id}/manage-menu/")
        goals = self.browser.request_json("GET", f"/api-2.0/courses/{course_id}/?fields[course]={GOALS_FIELDS}")
        basics = self.browser.request_json(
            "GET",
            f"/api-2.0/courses/{course_id}/?fields[course]={BASICS_FIELDS}&fields[course_label]=@min",
        )
        category_id = required_path(basics, ("primary_category", "id"))
        pricing = self.browser.request_json(
            "GET",
            f"/api-2.0/courses/{course_id}/?fields[course]={PRICING_FIELDS}&fields[course_feature]=promotions_create",
        )
        captions_course = self.browser.request_json(
            "GET",
            f"/api-2.0/courses/{course_id}/?fields[caption]={CAPTION_FIELDS}"
            f"&fields[asset]=asset_type,id,captions"
            f"&fields[course]={CAPTION_COURSE_FIELDS}&fields[locale]=@default",
        )
        locale = required_path(captions_course, ("locale", "locale"), str)
        quality = self.browser.request_json(
            "GET",
            f"/api-2.0/courses/{course_id}/?fields[course]={QUALITY_FIELDS}"
            "&fields[quality_review_process]=last_submitted_date",
        )
        quality_process_id = required_path(
            quality,
            ("quality_review_process", "id"),
        )

        return {
            "course_id": course_id,
            "manage_menu": menu,
            "sections": {
                "goals": {"course": goals},
                "basics": {
                    "course": basics,
                    "categories": self.browser.request_json("GET", "/api-2.0/course-categories/"),
                    "subcategories": self.browser.request_json(
                        "GET",
                        f"/api-2.0/course-categories/{category_id}/subcategories/",
                    ),
                    "locales": self.browser.request_json("GET", "/api-2.0/locales/?page_size=200"),
                },
                "pricing": {
                    "course": pricing,
                    "price_tiers": self.browser.request_json("GET", "/api-2.0/price-tiers/"),
                    "course_price_range": self.browser.request_json(
                        "GET",
                        f"/api-2.0/pricing/{course_id}/course-price-range/get/",
                    ),
                },
                "promotions": {
                    "meta": self.browser.request_json("GET", f"/api-2.0/courses/{course_id}/coupons-v2/meta/"),
                    "active_coupons": self.browser.request_json(
                        "GET",
                        f"/api-2.0/courses/{course_id}/coupons-v2/?ordering=end_time,-created&page=1&invalid=false&page_size=10",
                    ),
                    "expired_coupons": self.browser.request_json(
                        "GET",
                        f"/api-2.0/courses/{course_id}/coupons-v2/?ordering=-created&page=1&search=&invalid=true&page_size=10",
                    ),
                },
                "communications": {
                    "messages": self.browser.request_json("GET", f"/api-2.0/courses/{course_id}/course-messages/")
                },
                "availability": {
                    "statuses": self.browser.request_json(
                        "GET",
                        f"/api-2.0/users/me/courses/{course_id}/instructor-course-statuses/",
                    ),
                    "available_statuses": [
                        {"status": 1, "name": "AVAILABLE", "respond_time_frames": sorted(RESPOND_TIME_FRAMES - {None})},
                        {"status": 2, "name": "NOT_AVAILABLE", "requires_available_date": True},
                        {"status": 3, "name": "UNSPECIFIED"},
                    ],
                },
                "accessibility": {
                    "settings": self.browser.request_json("GET", f"/api-2.0/courses/{course_id}/settings/"),
                    "available_settings": sorted(ACCESSIBILITY_SETTINGS),
                    "available_values": sorted(ACCESSIBILITY_VALUES),
                },
                "captions": {
                    "course": captions_course,
                    "translations": self.browser.request_json(
                        "GET",
                        f"/api-2.0/courses/{course_id}/translations/?page_size=50&fields[course_translation]=@all",
                    ),
                    "published_captions": self.browser.request_json(
                        "GET",
                        f"/api-2.0/courses/{course_id}/captions/?fields[caption]={CAPTION_FIELDS}&locale={locale}",
                    ),
                    "draft_captions": self.browser.request_json(
                        "GET",
                        f"/api-2.0/courses/{course_id}/draft-captions/?fields[draft_caption]={DRAFT_CAPTION_FIELDS}&locale={locale}",
                    ),
                    "available_translation_availabilities": sorted(CAPTION_AVAILABILITIES),
                },
                "feedback": {
                    "course": quality,
                    "criteria_feedbacks": self.browser.request_json(
                        "GET",
                        f"/api-2.0/quality-review-processes/{quality_process_id}/quality-criteria-feedbacks/"
                        f"?fields[quality_criteria_feedback]={QUALITY_FEEDBACK_FIELDS}"
                        f"&fields[quality_criteria]={QUALITY_CRITERIA_FIELDS}",
                    ),
                },
                "students": {
                    "course": self.browser.request_json(
                        "GET",
                        f"/api-2.0/courses/{course_id}/?fields[course]=has_students,can_invite",
                    ),
                    "students": self.browser.request_json(
                        "GET",
                        f"/api-2.0/courses/{course_id}/students/?ordering=-enrollment_date&q=&page_size=10&page=1"
                        f"&fields[user]={STUDENT_FIELDS}",
                    ),
                },
            },
        }

    def update_course_management(self, course_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update browser-backed course management fields, excluding curriculum."""
        updates = self._require_mapping(updates, "course management update")
        unsupported = set(updates) - set(COURSE_MANAGEMENT_UPDATE_ORDER)
        if unsupported:
            section = sorted(unsupported)[0]
            raise ClientError(f"Unsupported course management section: {section}")

        updated_sections = []
        for section in COURSE_MANAGEMENT_UPDATE_ORDER:
            if section not in updates:
                continue
            getattr(self, f"_update_{section}")(course_id, updates[section])
            updated_sections.append(section)

        return {"course_id": course_id, "updated_sections": updated_sections}

    def _update_goals(self, course_id: str, payload: Any) -> None:
        body = self._require_mapping_with_keys(payload, GOALS_UPDATE_KEYS, "goals update")
        self.browser.request_json("PATCH", f"/api-2.0/courses/{course_id}/?category=course-goals", json_body=body)

    def _update_basics(self, course_id: str, payload: Any) -> None:
        body = self._require_mapping_with_keys(payload, BASICS_UPDATE_KEYS, "basics update")
        self.browser.request_json("PATCH", f"/api-2.0/courses/{course_id}/?category=course-basics", json_body=body)

    def _update_pricing(self, course_id: str, payload: Any) -> None:
        body = self._require_mapping_with_keys(payload, PRICING_UPDATE_KEYS, "pricing update")
        self.browser.request_json(
            "PATCH",
            f"/api-2.0/courses/{course_id}/?fields[course]={PRICING_UPDATE_FIELDS}",
            json_body=body,
        )

    def _update_communications(self, course_id: str, payload: Any) -> None:
        messages = self._require_list(payload, "communications update")
        for message in messages:
            self._require_mapping_with_keys(message, MESSAGE_UPDATE_KEYS, "course message update")
        self.browser.request_json("POST", f"/api-2.0/courses/{course_id}/course-messages/", json_body=messages)

    def _update_availability(self, course_id: str, payload: Any) -> None:
        body = self._require_mapping_with_keys(payload, AVAILABILITY_UPDATE_KEYS, "availability update")
        status = body["status"]
        if status not in AVAILABILITY_STATUSES:
            raise ClientError(f"Unsupported availability status: {status}")
        if body["respond_time_frame"] not in RESPOND_TIME_FRAMES:
            raise ClientError(f"Unsupported respond_time_frame: {body['respond_time_frame']}")
        available_date = body["available_date"]
        if available_date is not None and not isinstance(available_date, str):
            raise ClientError("availability available_date must be a string or null.")
        apply_to_all_courses = body["apply_to_all_courses"]
        if not isinstance(apply_to_all_courses, bool):
            raise ClientError("availability apply_to_all_courses must be a boolean.")

        request_body = {
            "status": status,
            "respond_time_frame": body["respond_time_frame"],
            "available_date": available_date,
        }
        if apply_to_all_courses:
            request_body["apply_to_all_courses"] = True
            self.browser.request_json(
                "POST",
                f"/api-2.0/users/me/courses/{course_id}/instructor-course-statuses/",
                json_body=request_body,
            )
            return

        statuses = self.browser.request_json(
            "GET",
            f"/api-2.0/users/me/courses/{course_id}/instructor-course-statuses/",
        )
        results = required_path(statuses, ("results",), list)
        if len(results) != 1:
            raise ClientError("Expected one Udemy instructor course status record.")
        record_id = required_path(results, (0, "id"))
        self.browser.request_json(
            "PUT",
            f"/api-2.0/users/me/courses/{course_id}/instructor-course-statuses/{record_id}/",
            json_body=request_body,
        )

    def _update_accessibility(self, course_id: str, payload: Any) -> None:
        settings = self._require_mapping(payload, "accessibility update")
        for setting, value in settings.items():
            if setting not in ACCESSIBILITY_SETTINGS:
                raise ClientError(f"Unsupported accessibility setting: {setting}")
            if value not in ACCESSIBILITY_VALUES:
                raise ClientError(f"Unsupported accessibility setting value: {value}")
            self.browser.request_json(
                "POST",
                f"/api-2.0/courses/{course_id}/settings/",
                json_body={"setting": setting, "value": value},
            )

    def _update_captions(self, course_id: str, payload: Any) -> None:
        translations = self._require_list(payload, "captions update")
        for translation in translations:
            body = self._require_mapping_with_keys(translation, CAPTION_UPDATE_KEYS, "caption translation update")
            availability = body["availability"]
            if availability not in CAPTION_AVAILABILITIES:
                raise ClientError(f"Unsupported caption translation availability: {availability}")
            locale = body["locale"]
            if not isinstance(locale, str) or not locale:
                raise ClientError("caption translation locale must be a non-empty string.")
            self.browser.request_json(
                "PATCH",
                f"/api-2.0/courses/{course_id}/translations/{locale}/",
                json_body={"availability": availability},
            )

    def _update_promotions(self, course_id: str, payload: Any) -> None:
        coupons = self._require_list(payload, "promotions update")
        for coupon in coupons:
            body = self._require_mapping_with_keys(coupon, COUPON_UPDATE_KEYS, "coupon update")
            self.browser.request_json("POST", f"/api-2.0/courses/{course_id}/coupons-v2/", json_body=body)

    def _require_mapping(self, value: Any, label: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ClientError(f"{label} must be an object.")
        return value

    def _require_mapping_with_keys(self, value: Any, keys: set[str], label: str) -> dict[str, Any]:
        mapping = self._require_mapping(value, label)
        missing = sorted(keys - set(mapping))
        extra = sorted(set(mapping) - keys)
        if missing:
            raise ClientError(f"{label} missing fields: {', '.join(missing)}")
        if extra:
            raise ClientError(f"{label} contains unsupported fields: {', '.join(extra)}")
        return mapping

    def _require_list(self, value: Any, label: str) -> list[Any]:
        if not isinstance(value, list):
            raise ClientError(f"{label} must be a list.")
        return value



# Module-level client instance - singleton pattern
_client: Optional[UdemyClient] = None


def get_client() -> UdemyClient:
    """Get or create the global Udemy client instance."""
    global _client
    if _client is None:
        _client = UdemyClient()
    return _client
