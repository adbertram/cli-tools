"""Keywords API client for querying autocomplete suggestions from search engines."""
import re
import time
import uuid
from typing import List, Optional, Set

import requests

from .config import get_config
from .models import (
    Source,
    SuggestionResult,
    RecursiveSuggestion,
    RecursiveSuggestionResult,
    create_suggestion_result,
)


# Default delay between requests to avoid rate limiting
DEFAULT_REQUEST_DELAY = 0.1  # 100ms


class ClientError(Exception):
    """Custom exception for Keywords API errors."""

    pass


class KeywordsClient:
    """Client for querying autocomplete suggestions from multiple search engines."""

    # User-Agent header to avoid being blocked
    USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    def __init__(self, request_delay: float = DEFAULT_REQUEST_DELAY):
        """Initialize Keywords client.

        Args:
            request_delay: Delay between API requests in seconds (default: 0.1)
        """
        self.config = get_config()
        self.request_delay = request_delay
        self._last_request_time: float = 0

    def _throttle(self):
        """Throttle requests to avoid rate limiting."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)
        self._last_request_time = time.time()

    def _fetch_google(self, query: str) -> List[str]:
        """Fetch autocomplete suggestions from Google.

        Args:
            query: Search query

        Returns:
            List of suggestion strings
        """
        self._throttle()

        url = "https://suggestqueries.google.com/complete/search"
        params = {"client": "chrome", "hl": "en", "q": query}

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            # Response format: ["query", ["suggestion1", "suggestion2", ...], ...]
            if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list):
                return data[1]
            return []
        except requests.RequestException as e:
            raise ClientError(f"Google autocomplete request failed: {e}")
        except (ValueError, IndexError) as e:
            raise ClientError(f"Failed to parse Google response: {e}")

    def _fetch_youtube(self, query: str) -> List[str]:
        """Fetch autocomplete suggestions from YouTube.

        Args:
            query: Search query

        Returns:
            List of suggestion strings
        """
        self._throttle()

        url = "https://suggestqueries.google.com/complete/search"
        params = {"client": "chrome", "hl": "en", "ds": "yt", "q": query}

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            # Response format: ["query", ["suggestion1", "suggestion2", ...], ...]
            if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list):
                return data[1]
            return []
        except requests.RequestException as e:
            raise ClientError(f"YouTube autocomplete request failed: {e}")
        except (ValueError, IndexError) as e:
            raise ClientError(f"Failed to parse YouTube response: {e}")

    def _fetch_bing(self, query: str) -> List[str]:
        """Fetch autocomplete suggestions from Bing.

        Args:
            query: Search query

        Returns:
            List of suggestion strings
        """
        self._throttle()

        url = "https://www.bing.com/AS/Suggestions"
        params = {"qry": query, "mkt": "en-US", "cvid": str(uuid.uuid4())}
        headers = {"User-Agent": self.USER_AGENT}

        try:
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            # Response is HTML - extract query attributes from <li> elements
            # Pattern: <li class="sa_sg" query="suggestion text">
            pattern = r'<li[^>]*\squery="([^"]+)"'
            matches = re.findall(pattern, response.text)
            return matches
        except requests.RequestException as e:
            raise ClientError(f"Bing autocomplete request failed: {e}")

    def _fetch_amazon(self, query: str) -> List[str]:
        """Fetch autocomplete suggestions from Amazon.

        Args:
            query: Search query

        Returns:
            List of suggestion strings
        """
        self._throttle()

        url = "https://completion.amazon.com/api/2017/suggestions"
        params = {
            "prefix": query,
            "alias": "aps",  # All departments
            "mid": "ATVPDKIKX0DER",  # US market
            "lop": "en_US",
            "site-variant": "desktop",
            "client-info": "amazon-search-ui",
        }
        headers = {"User-Agent": self.USER_AGENT}

        try:
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            # Response format: {"suggestions": [{"value": "..."}, ...]}
            suggestions = data.get("suggestions", [])
            return [s.get("value", "") for s in suggestions if s.get("value")]
        except requests.RequestException as e:
            raise ClientError(f"Amazon autocomplete request failed: {e}")
        except (ValueError, KeyError) as e:
            raise ClientError(f"Failed to parse Amazon response: {e}")

    def _fetch_duckduckgo(self, query: str) -> List[str]:
        """Fetch autocomplete suggestions from DuckDuckGo.

        Args:
            query: Search query

        Returns:
            List of suggestion strings
        """
        self._throttle()

        url = "https://ac.duckduckgo.com/ac/"
        params = {"q": query}

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            # Response format: [{"phrase": "..."}, ...]
            return [s.get("phrase", "") for s in data if s.get("phrase")]
        except requests.RequestException as e:
            raise ClientError(f"DuckDuckGo autocomplete request failed: {e}")
        except (ValueError, KeyError) as e:
            raise ClientError(f"Failed to parse DuckDuckGo response: {e}")

    def _fetch_for_source(self, query: str, source: Source) -> List[str]:
        """Fetch suggestions for a single source.

        Args:
            query: Search query
            source: Source to query

        Returns:
            List of suggestion strings
        """
        if source == Source.GOOGLE:
            return self._fetch_google(query)
        elif source == Source.YOUTUBE:
            return self._fetch_youtube(query)
        elif source == Source.BING:
            return self._fetch_bing(query)
        elif source == Source.AMAZON:
            return self._fetch_amazon(query)
        elif source == Source.DUCKDUCKGO:
            return self._fetch_duckduckgo(query)
        else:
            raise ClientError(f"Unknown source: {source}")

    def get_suggestions(
        self, query: str, sources: List[Source]
    ) -> List[SuggestionResult]:
        """Get autocomplete suggestions from specified sources.

        Args:
            query: Search query
            sources: List of sources to query

        Returns:
            List of SuggestionResult models, one per source
        """
        results = []

        for source in sources:
            try:
                suggestions = self._fetch_for_source(query, source)
                result = create_suggestion_result(query, source, suggestions)
                results.append(result)

            except ClientError:
                # Re-raise client errors
                raise
            except Exception as e:
                raise ClientError(f"Error fetching from {source.value}: {e}")

        return results

    def _build_recursive_suggestions(
        self,
        query: str,
        source: Source,
        current_depth: int,
        max_depth: int,
        limit_per_level: int,
        seen: Set[str],
    ) -> List[RecursiveSuggestion]:
        """Recursively build suggestion tree with deduplication.

        Args:
            query: Search query
            source: Source to query
            current_depth: Current recursion depth
            max_depth: Maximum recursion depth
            limit_per_level: Max suggestions to recurse into per level
            seen: Set of already-seen suggestion texts for deduplication

        Returns:
            List of RecursiveSuggestion with nested children (deduplicated)
        """
        try:
            suggestions = self._fetch_for_source(query, source)
        except ClientError:
            return []

        result = []
        recurse_count = 0
        for suggestion_text in suggestions:
            # Skip duplicates
            suggestion_lower = suggestion_text.lower()
            if suggestion_lower in seen:
                continue

            # Mark as seen
            seen.add(suggestion_lower)

            children = []
            # Only recurse if we haven't reached max depth and within limit
            if current_depth < max_depth and recurse_count < limit_per_level:
                children = self._build_recursive_suggestions(
                    suggestion_text,
                    source,
                    current_depth + 1,
                    max_depth,
                    limit_per_level,
                    seen,
                )
                recurse_count += 1

            result.append(RecursiveSuggestion(text=suggestion_text, children=children))

        return result

    def _count_recursive_suggestions(self, suggestions: List[RecursiveSuggestion]) -> int:
        """Count total suggestions in a recursive tree.

        Args:
            suggestions: List of recursive suggestions

        Returns:
            Total count including all nested children
        """
        count = len(suggestions)
        for suggestion in suggestions:
            count += self._count_recursive_suggestions(suggestion.children)
        return count

    def get_suggestions_recursive(
        self,
        query: str,
        source: Source,
        depth: int = 1,
        limit_per_level: int = 5,
    ) -> RecursiveSuggestionResult:
        """Get autocomplete suggestions recursively.

        Queries the initial term, then queries each suggestion to build
        a tree of related keywords. Duplicate suggestions are automatically
        removed regardless of parent query.

        Args:
            query: Search query
            source: Source to query (only one source for recursive)
            depth: How many levels deep to recurse (default: 1)
            limit_per_level: Max suggestions to recurse into per level (default: 5)

        Returns:
            RecursiveSuggestionResult with nested suggestions (deduplicated)
        """
        try:
            # Initialize seen set with the original query to avoid it appearing in results
            seen: Set[str] = {query.lower()}

            suggestions = self._build_recursive_suggestions(
                query,
                source,
                current_depth=0,
                max_depth=depth,
                limit_per_level=limit_per_level,
                seen=seen,
            )
            total_count = self._count_recursive_suggestions(suggestions)

            return RecursiveSuggestionResult(
                query=query,
                source=source,
                depth=depth,
                suggestions=suggestions,
                total_count=total_count,
            )

        except ClientError:
            raise
        except Exception as e:
            raise ClientError(f"Error fetching recursive suggestions from {source.value}: {e}")


# Module-level client instance - singleton pattern
_client: Optional[KeywordsClient] = None


def get_client() -> KeywordsClient:
    """Get or create the global Keywords client instance."""
    global _client
    if _client is None:
        _client = KeywordsClient()
    return _client
