"""Prompt models for Scrunch CLI."""
from enum import Enum
from typing import List, Optional

from .base import CLIModel


class PromptStage(str, Enum):
    """Valid prompt stages."""

    ADVICE = "Advice"
    AWARENESS = "Awareness"
    EVALUATION = "Evaluation"
    COMPARISON = "Comparison"
    OTHER = "Other"


class AIPlatform(str, Enum):
    """Valid AI platforms."""

    CHATGPT = "chatgpt"
    CLAUDE = "claude"
    GOOGLE_AI_OVERVIEWS = "google_ai_overviews"
    PERPLEXITY = "perplexity"
    META = "meta"
    GOOGLE_AI_MODE = "google_ai_mode"
    GOOGLE_GEMINI = "google_gemini"
    COPILOT = "copilot"
    GROK = "grok"


class Prompt(CLIModel):
    """Prompt model returned by the API.

    Contains full prompt details with variants and metadata.
    Uses permissive typing since the API response structure
    may include additional fields.
    """

    id: int
    text: Optional[str] = None
    stage: Optional[str] = None
    persona_id: Optional[int] = None
    tags: List[str] = []
    key_topics: List[str] = []
    platforms: List[str] = []
    variants: Optional[List[dict]] = None
    metadata: Optional[dict] = None


class CreatePrompt(CLIModel):
    """Model for creating a new prompt."""

    text: str
    stage: PromptStage
    persona_id: Optional[int] = None
    tags: Optional[List[str]] = None
    key_topics: Optional[List[str]] = None
    platforms: Optional[List[str]] = None


def create_prompt(data: dict) -> Prompt:
    """Create a Prompt model from API response data."""
    return Prompt(**data)
