"""Search result models for cross-project session search."""
from typing import List, Optional

from .base import CLIModel


class SearchMatch(CLIModel):
    """A single matching snippet from a session."""

    role: str  # "user", "assistant", "tool", or "reasoning"
    snippet: str
    timestamp: str = ""


class SearchResult(CLIModel):
    """A session that matched a search query, with context snippets."""

    session_id: str
    project: str
    project_path: str = ""
    custom_title: Optional[str] = None
    created_at: str = ""
    last_activity: str = ""
    model: Optional[str] = None
    origin: Optional[str] = None
    match_count: int = 0
    matches: List[SearchMatch] = []
