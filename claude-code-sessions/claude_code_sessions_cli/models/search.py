"""Search result models for cross-project session search."""
from typing import List, Optional
from .base import CLIModel


class SearchMatch(CLIModel):
    """A single matching snippet from a session."""

    role: str  # "user" or "assistant"
    snippet: str  # Trimmed text around the match
    timestamp: str = ""


class SearchResult(CLIModel):
    """A session that matched a search query, with context snippets."""

    session_id: str
    project: str
    project_path: str = ""
    created_at: str = ""
    last_activity: str = ""
    # Model from the most recent assistant turn in the matched session
    model: Optional[str] = None
    match_count: int = 0
    matches: List[SearchMatch] = []
