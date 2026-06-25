"""Transcript models for Whisper CLI.

Models representing the output from OpenAI Whisper speech-to-text transcription.
"""
from enum import Enum
from typing import List, Optional

from pydantic import Field

from .base import CLIModel


class WhisperModel(str, Enum):
    """Available Whisper model sizes."""

    TINY = "tiny"
    BASE = "base"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    TURBO = "turbo"


class TranscriptSegment(CLIModel):
    """A segment of transcribed text with timestamps.

    Represents a single segment from Whisper's output.
    """

    id: int
    seek: int
    start: float
    end: float
    text: str
    tokens: List[int] = []
    temperature: float = 0.0
    avg_logprob: float = 0.0
    compression_ratio: float = 1.0
    no_speech_prob: float = 0.0


class TranscriptWord(CLIModel):
    """A word with precise timestamp (when word_timestamps enabled)."""

    word: str
    start: float
    end: float
    probability: float = 1.0


class Transcript(CLIModel):
    """Complete transcription result from Whisper.

    Contains the full text and all segments with timestamps.
    """

    text: str
    segments: List[TranscriptSegment] = []
    language: str = "en"

    # Optional metadata
    source_file: Optional[str] = None
    model: Optional[str] = None
    duration: Optional[float] = None


class TranscriptSummary(CLIModel):
    """Summary view of a transcript for list commands."""

    source_file: str
    language: str = "en"
    model: str = "turbo"
    duration: Optional[float] = None
    segment_count: int = 0
    word_count: int = 0


def create_transcript(data: dict, source_file: Optional[str] = None, model: Optional[str] = None) -> Transcript:
    """Create a Transcript model from Whisper JSON output.

    Args:
        data: Raw dict from Whisper JSON output
        source_file: Optional source file path
        model: Optional model name used for transcription

    Returns:
        Transcript model instance
    """
    # Parse segments
    segments = []
    for seg_data in data.get("segments", []):
        segments.append(TranscriptSegment(**seg_data))

    return Transcript(
        text=data.get("text", ""),
        segments=segments,
        language=data.get("language", "en"),
        source_file=source_file,
        model=model,
    )
