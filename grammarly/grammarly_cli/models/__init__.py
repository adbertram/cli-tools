"""Grammarly CLI models.

All command entities are defined here as Pydantic models for consistent
typing, validation, and JSON serialization.

Model Architecture:
- CLIModel: Base class with CLI-friendly configuration
- PlagiarismTransaction: Initial POST response with upload URL
- PlagiarismScore: Score object within result
- PlagiarismResult: Final GET response with status and score

Usage:
    from .models import PlagiarismResult, create_plagiarism_result

    # Create from API response
    result = create_plagiarism_result(api_response)

    # Access typed fields
    print(result.status)
    print(result.score.originality if result.score else "Pending")

    # Serialize to JSON
    print_json(result)
"""
from .base import CLIModel
from .item import (
    # Models
    PlagiarismTransaction,
    PlagiarismScore,
    PlagiarismResult,
    # Enums
    PlagiarismStatus,
    # Factory functions
    create_plagiarism_transaction,
    create_plagiarism_result,
)
from .document import (
    Document,
    DocumentDetail,
    create_document,
    create_document_list,
)

__all__ = [
    # Base
    "CLIModel",
    # Plagiarism Models
    "PlagiarismTransaction",
    "PlagiarismScore",
    "PlagiarismResult",
    # Plagiarism Enums
    "PlagiarismStatus",
    # Plagiarism Factory functions
    "create_plagiarism_transaction",
    "create_plagiarism_result",
    # Document Models
    "Document",
    "DocumentDetail",
    # Document Factory functions
    "create_document",
    "create_document_list",
]
