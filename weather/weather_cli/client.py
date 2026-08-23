"""Weather API client."""

import random
import time
from typing import Dict, List, Optional

import requests
from cli_tools_shared.activity_log import get_activity_logger
from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from .config import get_config

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
ZIP_LOOKUP_BASE_URL = "https://api.zippopotam.us/us"
DAILY_FORECAST_FIELDS = (
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "temperature_2m_mean",
    "relative_humidity_2m_mean",
    "relative_humidity_2m_max",
    "relative_humidity_2m_min",
    "precipitation_probability_max",
)
DAILY_FORECAST_FIELD_MAP = {
    "weather_code": "weather_code",
    "temperature_2m_max": "temperature_max",
    "temperature_2m_min": "temperature_min",
    "temperature_2m_mean": "temperature_mean",
    "relative_humidity_2m_mean": "humidity_mean",
    "relative_humidity_2m_max": "humidity_max",
    "relative_humidity_2m_min": "humidity_min",
    "precipitation_probability_max": "precipitation_probability_max",
}

activity = get_activity_logger("weather")


def _validate_zip_code(zip_code: str) -> str:
    value = zip_code.strip()
    if len(value) != 5 or not value.isdigit():
        raise ClientError("ZIP code must be exactly 5 digits.")
    return value


def _validate_forecast_days(days: int) -> int:
    if days < 1 or days > 16:
        raise ClientError("Forecast days must be between 1 and 16.")
    return days


def _zip_place(zip_code: str, zip_payload: dict) -> dict:
    places = zip_payload.get("places")
    if not places:
        raise ClientError(f"No location found for ZIP code {zip_code}.")
    return places[0]


def normalize_conditions(zip_code: str, zip_payload: dict, forecast_payload: dict, unit: str) -> dict:
    """Map ZIP and forecast API responses to the public CLI record shape."""
    place = _zip_place(zip_code, zip_payload)
    current = forecast_payload["current"]
    current_units = forecast_payload["current_units"]
    temperature = current["temperature_2m"]
    humidity = current["relative_humidity_2m"]
    temperature_unit = current_units["temperature_2m"]
    humidity_unit = current_units["relative_humidity_2m"]
    latitude = float(place["latitude"])
    longitude = float(place["longitude"])

    return {
        "id": zip_code,
        "zip_code": zip_code,
        "place_name": place["place name"],
        "state": place["state"],
        "state_abbreviation": place["state abbreviation"],
        "country": zip_payload["country"],
        "country_abbreviation": zip_payload["country abbreviation"],
        "latitude": latitude,
        "longitude": longitude,
        "temperature": temperature,
        "temperature_unit": temperature_unit,
        "temperature_display": f"{temperature} {temperature_unit}",
        "humidity": humidity,
        "humidity_unit": humidity_unit,
        "humidity_display": f"{humidity} {humidity_unit}",
        "observed_at": current["time"],
        "interval_seconds": current["interval"],
        "requested_temperature_unit": unit,
        "zip_lookup": zip_payload,
        "forecast": forecast_payload,
    }


def normalize_forecast(zip_code: str, zip_payload: dict, forecast_payload: dict, unit: str) -> dict:
    """Map ZIP and daily forecast API responses to the public CLI record shape."""
    place = _zip_place(zip_code, zip_payload)
    daily = forecast_payload["daily"]
    daily_units = forecast_payload["daily_units"]
    days = []

    for index, date in enumerate(daily["time"]):
        day = {"date": date}
        for api_field, output_field in DAILY_FORECAST_FIELD_MAP.items():
            day[output_field] = daily[api_field][index]
        day["temperature_unit"] = daily_units["temperature_2m_max"]
        day["humidity_unit"] = daily_units["relative_humidity_2m_mean"]
        day["precipitation_probability_unit"] = daily_units["precipitation_probability_max"]
        days.append(day)

    latitude = float(place["latitude"])
    longitude = float(place["longitude"])

    return {
        "id": zip_code,
        "zip_code": zip_code,
        "place_name": place["place name"],
        "state": place["state"],
        "state_abbreviation": place["state abbreviation"],
        "country": zip_payload["country"],
        "country_abbreviation": zip_payload["country abbreviation"],
        "latitude": latitude,
        "longitude": longitude,
        "days_count": len(days),
        "start_date": days[0]["date"] if days else None,
        "end_date": days[-1]["date"] if days else None,
        "requested_temperature_unit": unit,
        "days": days,
        "zip_lookup": zip_payload,
        "forecast": forecast_payload,
    }


class WeatherClient:
    """Client for current weather conditions by US ZIP code."""

    def __init__(
        self,
        config=None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        self.config = config or get_config()
        self.base_url = self.config.base_url
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self.headers = {"Accept": "application/json", "Content-Type": "application/json"}

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        if retry_after is not None:
            return min(retry_after, self.max_delay)
        delay = self.base_delay * (2 ** attempt)
        jitter_range = delay * self.jitter
        return min(delay + random.uniform(-jitter_range, jitter_range), self.max_delay)

    def _is_retryable(self, response: Optional[requests.Response], exception: Optional[Exception]) -> bool:
        if exception is not None:
            return isinstance(
                exception,
                (
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.ChunkedEncodingError,
                ),
            )
        if response is not None:
            return response.status_code in RETRYABLE_STATUS_CODES
        return False

    def _get_retry_after(self, response: requests.Response) -> Optional[float]:
        value = response.headers.get("Retry-After")
        if value is None:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    def _extract_error_detail(self, response: requests.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return response.text[:500]
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            error = body["error"]
            return error.get("message") or error.get("code") or str(error)
        if isinstance(body, dict) and "message" in body:
            return str(body["message"])
        return str(body)[:500]

    def _request_json(
        self,
        method: str,
        url: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        retry: bool = True,
    ) -> Dict:
        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None
        max_attempts = (self.max_retries + 1) if retry else 1

        for attempt in range(max_attempts):
            try:
                activity.info("%s %s", method, url)
                response = requests.request(method, url, headers=self.headers, json=data, params=params)
                last_response = response
                activity.info("%s %s -> %s", method, url, response.status_code)
                if retry and self._is_retryable(response, None) and attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt, self._get_retry_after(response)))
                    continue
                break
            except requests.exceptions.RequestException as exc:
                last_exception = exc
                activity.warning("%s %s failed: %s", method, url, exc)
                if retry and self._is_retryable(None, exc) and attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt))
                    continue
                break

        if last_exception is not None and last_response is None:
            raise ClientError(f"Request failed after {attempt + 1} attempts: {last_exception}")
        if last_response is None:
            raise ClientError("Request failed: no response received")
        if not last_response.ok:
            raise ClientError(f"HTTP {last_response.status_code}: {self._extract_error_detail(last_response)}")
        if last_response.status_code == 204:
            return {}
        return last_response.json()

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        retry: bool = True,
    ) -> Dict:
        return self._request_json(method, f"{self.base_url}{endpoint}", data=data, params=params, retry=retry)

    @cached
    def get_conditions(self, zip_code: str, unit: str = "fahrenheit") -> dict:
        zip_code = _validate_zip_code(zip_code)
        zip_payload = self._request_json("GET", f"{ZIP_LOOKUP_BASE_URL}/{zip_code}")
        place = _zip_place(zip_code, zip_payload)
        params = {
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": "temperature_2m,relative_humidity_2m",
            "temperature_unit": unit,
            "timezone": "auto",
        }
        forecast_payload = self._make_request("GET", "/forecast", params=params)
        return normalize_conditions(zip_code, zip_payload, forecast_payload, unit)

    @cached
    def list_conditions(self, zip_codes: List[str], limit: int = 100, unit: str = "fahrenheit") -> List[dict]:
        selected_zip_codes = zip_codes[:limit] if limit > 0 else zip_codes
        return [
            self.get_conditions(zip_code=zip_code, unit=unit)
            for zip_code in selected_zip_codes
        ]

    @cached
    def get_forecast(self, zip_code: str, days: int = 7, unit: str = "fahrenheit") -> dict:
        zip_code = _validate_zip_code(zip_code)
        days = _validate_forecast_days(days)
        zip_payload = self._request_json("GET", f"{ZIP_LOOKUP_BASE_URL}/{zip_code}")
        place = _zip_place(zip_code, zip_payload)
        params = {
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "daily": ",".join(DAILY_FORECAST_FIELDS),
            "temperature_unit": unit,
            "timezone": "auto",
            "forecast_days": days,
        }
        forecast_payload = self._make_request("GET", "/forecast", params=params)
        return normalize_forecast(zip_code, zip_payload, forecast_payload, unit)

    @cached
    def list_forecasts(
        self,
        zip_codes: List[str],
        limit: int = 100,
        days: int = 7,
        unit: str = "fahrenheit",
    ) -> List[dict]:
        selected_zip_codes = zip_codes[:limit] if limit > 0 else zip_codes
        return [
            self.get_forecast(zip_code=zip_code, days=days, unit=unit)
            for zip_code in selected_zip_codes
        ]


_client: Optional[WeatherClient] = None


def get_client() -> WeatherClient:
    """Get or create the global Weather client instance."""
    global _client
    if _client is None:
        _client = WeatherClient()
    return _client
