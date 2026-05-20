"""ElevenLabs API client with exponential retry."""
from pathlib import Path
from typing import Any, Dict, List, Optional
import random
import time

import requests
from cli_tools_shared.exceptions import ClientError

from .config import get_config
from cli_tools_shared.filters import FilterValidationError, apply_filters, validate_filters
from .models import (
    Model,
    PronunciationDictionary,
    PronunciationDictionaryDownloadResult,
    PronunciationDictionaryList,
    PronunciationDictionaryRulesResult,
    SpeechResult,
    Subscription,
    Voice,
    VoiceSettings,
    create_model,
    create_pronunciation_dictionary,
    create_pronunciation_dictionary_list,
    create_pronunciation_dictionary_rules_result,
    create_subscription,
    create_voice,
    create_voice_settings,
)


DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class ElevenlabsClient:
    """Client for the ElevenLabs REST API."""

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
                "Run 'elevenlabs auth login' to authenticate."
            )

        self.base_url = self.config.base_url.rstrip("/")
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "xi-api-key": self.config.api_key,
        }
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
        retry_after = response.headers.get("Retry-After")
        if retry_after is None:
            return None
        try:
            return float(retry_after)
        except ValueError:
            raise ClientError(f"Invalid Retry-After header: {retry_after}")

    def _extract_error_detail(self, response: requests.Response) -> str:
        if not response.text:
            return "Empty error response"
        try:
            error_body = response.json()
        except ValueError:
            return response.text[:500]

        if "detail" in error_body:
            return str(error_body["detail"])
        if "message" in error_body:
            return str(error_body["message"])
        if "error" in error_body:
            return str(error_body["error"])
        return str(error_body)[:500]

    def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        form_data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        accept: str = "application/json",
    ) -> requests.Response:
        if data is not None and (form_data is not None or files is not None):
            raise ClientError("JSON data cannot be combined with multipart form data")
        url = f"{self.base_url}{endpoint}"
        headers = dict(self.headers)
        headers["Accept"] = accept
        if files is not None:
            del headers["Content-Type"]
        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None

        for attempt in range(self.max_retries + 1):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=data,
                    data=form_data,
                    files=files,
                    params=params,
                    timeout=60,
                )
                last_response = response
                if self._is_retryable(response, None) and attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt, self._get_retry_after(response)))
                    continue
                break
            except requests.exceptions.RequestException as exc:
                last_exception = exc
                if self._is_retryable(None, exc) and attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt))
                    continue
                break

        if last_exception is not None and last_response is None:
            raise ClientError(f"Request failed after {self.max_retries + 1} attempts: {last_exception}")
        if last_response is None:
            raise ClientError("Request failed: no response received")
        if not last_response.ok:
            raise ClientError(f"HTTP {last_response.status_code}: {self._extract_error_detail(last_response)}")
        return last_response

    def _make_json_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        response = self._request(method=method, endpoint=endpoint, data=data, params=params)
        if response.status_code == 204:
            return {}
        return response.json()

    @staticmethod
    def parse_pronunciation_dictionary_locator(locator: str) -> Dict[str, str]:
        """Parse a dictionary locator in pronunciation_dictionary_id:version_id form."""
        parts = locator.split(":")
        if len(parts) != 2:
            raise ClientError("Pronunciation dictionary locators must use pronunciation_dictionary_id:version_id")
        pronunciation_dictionary_id = parts[0].strip()
        version_id = parts[1].strip()
        if not pronunciation_dictionary_id or not version_id:
            raise ClientError("Pronunciation dictionary locator id and version_id cannot be empty")
        return {
            "pronunciation_dictionary_id": pronunciation_dictionary_id,
            "version_id": version_id,
        }

    def list_voices(
        self,
        limit: int = 10,
        filters: Optional[List[str]] = None,
        search: Optional[str] = None,
        voice_type: Optional[str] = None,
        category: Optional[str] = None,
        sort: Optional[str] = None,
        sort_direction: Optional[str] = None,
    ) -> List[Voice]:
        """List voices using the ElevenLabs paginated v2 endpoint."""
        if filters:
            validate_filters(filters)

        page_size = min(limit, 100)
        params: Dict[str, Any] = {"page_size": page_size, "include_total_count": "false"}
        if search is not None:
            params["search"] = search
        if voice_type is not None:
            params["voice_type"] = voice_type
        if category is not None:
            params["category"] = category
        if sort is not None:
            params["sort"] = sort
        if sort_direction is not None:
            params["sort_direction"] = sort_direction

        voices: List[Dict[str, Any]] = []
        while len(voices) < limit:
            response = self._make_json_request("GET", "/v2/voices", params=params)
            page_voices = response["voices"]
            voices.extend(page_voices)
            if len(voices) >= limit or not response["has_more"]:
                break
            next_page_token = response["next_page_token"]
            if next_page_token is None:
                raise ClientError("ElevenLabs response has_more=true but next_page_token is null")
            params["next_page_token"] = next_page_token
            params["page_size"] = min(limit - len(voices), 100)

        limited_voices = voices[:limit]
        if filters:
            limited_voices = apply_filters(limited_voices, filters)
        return [create_voice(voice) for voice in limited_voices]

    def get_voice(self, voice_id: str) -> Voice:
        """Get a single voice by ID."""
        response = self._make_json_request("GET", f"/v1/voices/{voice_id}")
        return create_voice(response)

    def get_voice_settings(self, voice_id: str) -> VoiceSettings:
        """Get stored settings for a voice."""
        response = self._make_json_request("GET", f"/v1/voices/{voice_id}/settings")
        return create_voice_settings(response)

    def list_models(self, limit: int = 100, filters: Optional[List[str]] = None) -> List[Model]:
        """List available ElevenLabs models."""
        if filters:
            validate_filters(filters)
        response = self._make_json_request("GET", "/v1/models")
        models = response[:limit]
        if filters:
            models = apply_filters(models, filters)
        return [create_model(model) for model in models]

    def get_subscription(self) -> Subscription:
        """Get current user subscription and quota state."""
        response = self._make_json_request("GET", "/v1/user/subscription")
        return create_subscription(response)

    def create_speech(
        self,
        voice_id: str,
        text: str,
        output_path: Path,
        model_id: str,
        output_format: str,
        language_code: Optional[str] = None,
        stability: Optional[float] = None,
        similarity_boost: Optional[float] = None,
        style: Optional[float] = None,
        use_speaker_boost: Optional[bool] = None,
        speed: Optional[float] = None,
        seed: Optional[int] = None,
        apply_text_normalization: Optional[str] = None,
        enable_logging: bool = True,
        pronunciation_dictionaries: Optional[List[str]] = None,
    ) -> SpeechResult:
        """Generate speech and write the returned audio bytes to disk."""
        payload: Dict[str, Any] = {"text": text, "model_id": model_id}
        if language_code is not None:
            payload["language_code"] = language_code
        if seed is not None:
            payload["seed"] = seed
        if apply_text_normalization is not None:
            payload["apply_text_normalization"] = apply_text_normalization
        if pronunciation_dictionaries is not None:
            if len(pronunciation_dictionaries) > 3:
                raise ClientError("ElevenLabs accepts at most 3 pronunciation dictionary locators per request")
            payload["pronunciation_dictionary_locators"] = [
                self.parse_pronunciation_dictionary_locator(locator) for locator in pronunciation_dictionaries
            ]

        voice_settings: Dict[str, Any] = {}
        if stability is not None:
            voice_settings["stability"] = stability
        if similarity_boost is not None:
            voice_settings["similarity_boost"] = similarity_boost
        if style is not None:
            voice_settings["style"] = style
        if use_speaker_boost is not None:
            voice_settings["use_speaker_boost"] = use_speaker_boost
        if speed is not None:
            voice_settings["speed"] = speed
        if voice_settings:
            payload["voice_settings"] = voice_settings

        params = {"output_format": output_format, "enable_logging": str(enable_logging).lower()}
        response = self._request(
            method="POST",
            endpoint=f"/v1/text-to-speech/{voice_id}",
            data=payload,
            params=params,
            accept="audio/*",
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response.content)
        character_count = response.headers.get("x-character-count")
        return SpeechResult(
            output_path=str(output_path),
            content_type=response.headers.get("content-type"),
            request_id=response.headers.get("request-id"),
            character_count=int(character_count) if character_count is not None else None,
            history_item_id=response.headers.get("history-item-id"),
        )

    def list_pronunciation_dictionaries(
        self,
        page_size: int = 30,
        sort: str = "creation_time_unix",
        sort_direction: str = "DESCENDING",
        cursor: Optional[str] = None,
    ) -> PronunciationDictionaryList:
        """List pronunciation dictionaries."""
        params: Dict[str, Any] = {
            "page_size": page_size,
            "sort": sort,
            "sort_direction": sort_direction,
        }
        if cursor is not None:
            params["cursor"] = cursor
        response = self._make_json_request("GET", "/v1/pronunciation-dictionaries", params=params)
        return create_pronunciation_dictionary_list(response)

    def get_pronunciation_dictionary(self, pronunciation_dictionary_id: str) -> PronunciationDictionary:
        """Get pronunciation dictionary metadata and latest rules."""
        response = self._make_json_request(
            "GET",
            f"/v1/pronunciation-dictionaries/{pronunciation_dictionary_id}",
        )
        return create_pronunciation_dictionary(response)

    def create_pronunciation_dictionary_from_rules(
        self,
        name: str,
        rules: List[Dict[str, Any]],
        description: Optional[str] = None,
        workspace_access: Optional[str] = None,
    ) -> PronunciationDictionary:
        """Create a pronunciation dictionary from rules."""
        payload: Dict[str, Any] = {"name": name, "rules": rules}
        if description is not None:
            payload["description"] = description
        if workspace_access is not None:
            payload["workspace_access"] = workspace_access
        response = self._make_json_request(
            "POST",
            "/v1/pronunciation-dictionaries/add-from-rules",
            data=payload,
        )
        return create_pronunciation_dictionary(response)

    def create_pronunciation_dictionary_from_file(
        self,
        name: str,
        file_path: Path,
        description: Optional[str] = None,
        workspace_access: Optional[str] = None,
    ) -> PronunciationDictionary:
        """Create a pronunciation dictionary from a PLS file."""
        form_data: Dict[str, Any] = {"name": name}
        if description is not None:
            form_data["description"] = description
        if workspace_access is not None:
            form_data["workspace_access"] = workspace_access
        files = {"file": (file_path.name, file_path.read_bytes())}
        response = self._request(
            method="POST",
            endpoint="/v1/pronunciation-dictionaries/add-from-file",
            form_data=form_data,
            files=files,
        )
        return create_pronunciation_dictionary(response.json())

    def update_pronunciation_dictionary(
        self,
        pronunciation_dictionary_id: str,
        name: Optional[str] = None,
        archived: Optional[bool] = None,
    ) -> PronunciationDictionary:
        """Update pronunciation dictionary metadata."""
        payload: Dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if archived is not None:
            payload["archived"] = archived
        if not payload:
            raise ClientError("At least one update field is required")
        response = self._make_json_request(
            "PATCH",
            f"/v1/pronunciation-dictionaries/{pronunciation_dictionary_id}",
            data=payload,
        )
        return create_pronunciation_dictionary(response)

    def set_pronunciation_dictionary_rules(
        self,
        pronunciation_dictionary_id: str,
        rules: List[Dict[str, Any]],
    ) -> PronunciationDictionaryRulesResult:
        """Replace all rules in a pronunciation dictionary."""
        response = self._make_json_request(
            "POST",
            f"/v1/pronunciation-dictionaries/{pronunciation_dictionary_id}/set-rules",
            data={"rules": rules},
        )
        return create_pronunciation_dictionary_rules_result(response)

    def add_pronunciation_dictionary_rules(
        self,
        pronunciation_dictionary_id: str,
        rules: List[Dict[str, Any]],
    ) -> PronunciationDictionaryRulesResult:
        """Add or replace rules in a pronunciation dictionary."""
        response = self._make_json_request(
            "POST",
            f"/v1/pronunciation-dictionaries/{pronunciation_dictionary_id}/add-rules",
            data={"rules": rules},
        )
        return create_pronunciation_dictionary_rules_result(response)

    def remove_pronunciation_dictionary_rules(
        self,
        pronunciation_dictionary_id: str,
        rule_strings: List[str],
    ) -> PronunciationDictionaryRulesResult:
        """Remove rules from a pronunciation dictionary."""
        if not rule_strings:
            raise ClientError("At least one rule string is required")
        response = self._make_json_request(
            "POST",
            f"/v1/pronunciation-dictionaries/{pronunciation_dictionary_id}/remove-rules",
            data={"rule_strings": rule_strings},
        )
        return create_pronunciation_dictionary_rules_result(response)

    def download_pronunciation_dictionary(
        self,
        pronunciation_dictionary_id: str,
        version_id: str,
        output_path: Path,
    ) -> PronunciationDictionaryDownloadResult:
        """Download a pronunciation dictionary version as a PLS file."""
        response = self._request(
            method="GET",
            endpoint=f"/v1/pronunciation-dictionaries/{pronunciation_dictionary_id}/{version_id}/download",
            accept="application/pls+xml",
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response.content)
        return PronunciationDictionaryDownloadResult(
            output_path=str(output_path),
            content_type=response.headers.get("content-type"),
        )


_client: Optional[ElevenlabsClient] = None


def get_client() -> ElevenlabsClient:
    """Get or create the global ElevenLabs client instance."""
    global _client
    if _client is None:
        _client = ElevenlabsClient()
    return _client
