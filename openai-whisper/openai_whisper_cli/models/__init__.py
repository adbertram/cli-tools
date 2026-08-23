"""Whisper CLI models.

All command entities are defined here as Pydantic models for consistent
typing, validation, and JSON serialization.

Model Architecture:
- CLIModel: Base class with CLI-friendly configuration
- Transcript: Full transcription result with segments
- TranscriptSegment: Individual segment with timestamps
- TranscriptSummary: Summary view for list commands

Usage:
    from .models import Transcript, TranscriptSegment, WhisperModel, create_transcript

    # Create from Whisper JSON output
    transcript = create_transcript(whisper_output, source_file="video.mp4")

    # Access typed fields
    print(transcript.text)
    print(len(transcript.segments))

    # Serialize to JSON
    print_json(transcript)
"""
from .base import CLIModel
from .transcript import (
    # Models
    Transcript,
    TranscriptSegment,
    TranscriptWord,
    TranscriptSummary,
    # Enums
    WhisperModel,
    # Factory functions
    create_transcript,
)

__all__ = [
    # Base
    "CLIModel",
    # Models
    "Transcript",
    "TranscriptSegment",
    "TranscriptWord",
    "TranscriptSummary",
    # Enums
    "WhisperModel",
    # Factory functions
    "create_transcript",
]
