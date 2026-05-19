"""Models for ElevenLabs API resources."""
from typing import Any, Dict, List, Optional

from pydantic import ConfigDict, Field

from .base import CLIModel


class ElevenLabsModel(CLIModel):
    """Base model that preserves new API fields in JSON output."""

    model_config = ConfigDict(
        extra="allow",
        str_strip_whitespace=True,
        populate_by_name=True,
        validate_by_alias=True,
        validate_by_name=True,
    )


class Voice(ElevenLabsModel):
    """Voice metadata returned by voice list and get endpoints."""

    id: str = Field(frozen=True)
    voice_id: str = Field(frozen=True)
    name: str
    samples: Optional[List[Dict[str, Any]]] = None
    category: Optional[str] = None
    fine_tuning: Optional[Dict[str, Any]] = None
    labels: Optional[Dict[str, str]] = None
    description: Optional[str] = None
    preview_url: Optional[str] = None
    available_for_tiers: Optional[List[str]] = None
    settings: Optional[Dict[str, Any]] = None
    sharing: Optional[Dict[str, Any]] = None
    high_quality_base_model_ids: Optional[List[str]] = None
    verified_languages: Optional[List[Dict[str, Any]]] = None
    collection_ids: Optional[List[str]] = None
    safety_control: Optional[str] = None
    voice_verification: Optional[Dict[str, Any]] = None
    permission_on_resource: Optional[str] = None
    is_owner: Optional[bool] = None
    is_legacy: Optional[bool] = None
    is_mixed: Optional[bool] = None
    favorited_at_unix: Optional[int] = None
    created_at_unix: Optional[int] = None
    is_bookmarked: Optional[bool] = None
    recording_quality: Optional[str] = None
    labelling_status: Optional[str] = None
    recording_quality_reason: Optional[str] = None


class VoiceSettings(ElevenLabsModel):
    """Voice settings for text-to-speech generation."""

    stability: Optional[float] = None
    use_speaker_boost: Optional[bool] = None
    similarity_boost: Optional[float] = None
    style: Optional[float] = None
    speed: Optional[float] = None


class Model(ElevenLabsModel):
    """ElevenLabs model metadata."""

    id: str = Field(frozen=True)
    model_id: str = Field(frozen=True)
    name: str
    can_be_finetuned: Optional[bool] = None
    can_do_text_to_speech: Optional[bool] = None
    can_do_voice_conversion: Optional[bool] = None
    can_use_style: Optional[bool] = None
    can_use_speaker_boost: Optional[bool] = None
    serves_pro_voices: Optional[bool] = None
    token_cost_factor: Optional[float] = None
    description: Optional[str] = None
    requires_alpha_access: Optional[bool] = None
    max_characters_request_free_user: Optional[int] = None
    max_characters_request_subscribed_user: Optional[int] = None
    maximum_text_length_per_request: Optional[int] = None
    languages: Optional[List[Dict[str, Any]]] = None
    model_rates: Optional[Dict[str, Any]] = None
    concurrency_group: Optional[str] = None


class Subscription(ElevenLabsModel):
    """Current account subscription and quota state."""

    tier: str
    character_count: int
    character_limit: int
    status: str


class SpeechResult(ElevenLabsModel):
    """Metadata for a generated speech file written to disk."""

    output_path: str
    content_type: Optional[str] = None
    request_id: Optional[str] = None
    character_count: Optional[int] = None
    history_item_id: Optional[str] = None


class PronunciationDictionary(ElevenLabsModel):
    """Pronunciation dictionary metadata."""

    id: str = Field(frozen=True)
    name: str
    latest_version_id: Optional[str] = None
    latest_version_rules_num: Optional[int] = None
    version_id: Optional[str] = None
    version_rules_num: Optional[int] = None
    permission_on_resource: Optional[str] = None
    created_by: Optional[str] = None
    creation_time_unix: Optional[int] = None
    archived_time_unix: Optional[int] = None
    description: Optional[str] = None
    rules: Optional[List[Dict[str, Any]]] = None


class PronunciationDictionaryList(ElevenLabsModel):
    """Pronunciation dictionary list response with pagination metadata."""

    pronunciation_dictionaries: List[PronunciationDictionary]
    has_more: bool
    next_cursor: Optional[str] = None


class PronunciationDictionaryRulesResult(ElevenLabsModel):
    """Pronunciation dictionary version metadata after changing rules."""

    id: str = Field(frozen=True)
    version_id: str
    version_rules_num: int


class PronunciationDictionaryDownloadResult(ElevenLabsModel):
    """Metadata for a downloaded pronunciation dictionary PLS file."""

    output_path: str
    content_type: Optional[str] = None


def create_voice(data: Dict[str, Any]) -> Voice:
    """Create a Voice model from API response data."""
    return Voice(**{"id": data["voice_id"], **data})


def create_voice_settings(data: Dict[str, Any]) -> VoiceSettings:
    """Create a VoiceSettings model from API response data."""
    return VoiceSettings(**data)


def create_model(data: Dict[str, Any]) -> Model:
    """Create a Model model from API response data."""
    return Model(**{"id": data["model_id"], **data})


def create_subscription(data: Dict[str, Any]) -> Subscription:
    """Create a Subscription model from API response data."""
    return Subscription(**data)


def create_pronunciation_dictionary(data: Dict[str, Any]) -> PronunciationDictionary:
    """Create a PronunciationDictionary model from API response data."""
    return PronunciationDictionary(**data)


def create_pronunciation_dictionary_list(data: Dict[str, Any]) -> PronunciationDictionaryList:
    """Create a PronunciationDictionaryList model from API response data."""
    return PronunciationDictionaryList(
        pronunciation_dictionaries=[
            create_pronunciation_dictionary(dictionary)
            for dictionary in data["pronunciation_dictionaries"]
        ],
        has_more=data["has_more"],
        next_cursor=data["next_cursor"],
    )


def create_pronunciation_dictionary_rules_result(data: Dict[str, Any]) -> PronunciationDictionaryRulesResult:
    """Create a PronunciationDictionaryRulesResult model from API response data."""
    return PronunciationDictionaryRulesResult(**data)
