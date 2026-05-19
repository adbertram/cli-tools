"""Plagiarism detection models for Grammarly CLI.

API Response Models:
- PlagiarismTransaction: Initial POST response with upload URL
- PlagiarismScore: Score object within result
- PlagiarismResult: Final GET response with status and score
"""
from enum import Enum
from typing import Optional

from pydantic import Field

from .base import CLIModel


# ==================== Enums ====================


class PlagiarismStatus(str, Enum):
    """Status values for plagiarism check requests."""

    PENDING = "PENDING"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


# ==================== Models ====================


class PlagiarismTransaction(CLIModel):
    """Initial transaction response from POST /plagiarism.

    Contains the score_request_id and pre-signed S3 URL for file upload.
    """

    score_request_id: str = Field(frozen=True)
    file_upload_url: str = Field(frozen=True)


class PlagiarismScore(CLIModel):
    """Score object within plagiarism result.

    originality: 0-1 range (higher = more original, 0 = fully plagiarized)
    """

    originality: float


class PlagiarismResult(CLIModel):
    """Final result from GET /plagiarism/{score_request_id}.

    Contains status and optional score (only present when COMPLETED).
    """

    score_request_id: str = Field(frozen=True)
    status: PlagiarismStatus
    updated_at: Optional[str] = None
    score: Optional[PlagiarismScore] = None


# ==================== Factory Functions ====================


def create_plagiarism_transaction(data: dict) -> PlagiarismTransaction:
    """Create a PlagiarismTransaction model from API response.

    Args:
        data: Raw dict from POST /plagiarism response

    Returns:
        PlagiarismTransaction model instance

    Raises:
        ValidationError: If required fields are missing
    """
    return PlagiarismTransaction(**data)


def create_plagiarism_result(data: dict) -> PlagiarismResult:
    """Create a PlagiarismResult model from API response.

    Args:
        data: Raw dict from GET /plagiarism/{id} response

    Returns:
        PlagiarismResult model instance

    Raises:
        ValidationError: If required fields are missing
    """
    # Handle nested score object
    if "score" in data and data["score"] is not None:
        data["score"] = PlagiarismScore(**data["score"])
    return PlagiarismResult(**data)
