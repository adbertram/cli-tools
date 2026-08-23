"""Upwork jobs client — marketplace job search over the GraphQL API.

Wraps :class:`~upwork_cli.graphql.UpworkGraphQLClient` with the marketplace job
search and single-job queries, cursor pagination via ``pageInfo``, server-side
filter translation through the data-driven :mod:`upwork_cli.filters` map, and a
client-side fallback for filters the API cannot express.

The GraphQL document text and node field list are module-level constants so they
can be corrected after live schema introspection (Upwork GraphQL Explorer,
requires API keys) without changing command or client method signatures.
"""

from __future__ import annotations

from typing import Any, Optional

from cli_tools_shared.exceptions import ClientError

from .config import get_config
from .filters import (
    ALLOWED_FILTER_FIELDS,
    apply_filters,
    build_jobs_filter_input,
    split_server_and_client_filters,
    validate_jobs_filters,
)
from .graphql import UpworkGraphQLClient

# ---------------------------------------------------------------------------
# GraphQL documents (swappable after live introspection)
# ---------------------------------------------------------------------------
# Node field selection shared by search and single-job queries. Kept as one
# string constant so a schema correction is a single edit.
JOB_NODE_FIELDS = """
    id
    title
    description
    experienceLevel
    ciphertext
    recordNumber
    publishedDateTime
    preferredFreelancerLocation
    totalApplicants
    hourlyBudgetType
    amount { currency rawValue }
    hourlyBudgetMin { currency rawValue }
    hourlyBudgetMax { currency rawValue }
    skills { name prettyName highlighted }
    client { location { city country timezone } }
    occupations { category { id prefLabel } }
"""

SEARCH_JOBS_QUERY = """
query marketplaceJobPostingsSearch(
  $marketPlaceJobFilter: MarketplaceJobPostingsSearchFilter,
  $searchType: MarketplaceJobPostingSearchType,
  $sortAttributes: [MarketplaceJobPostingSearchSortAttribute],
  $after: String
) {
  marketplaceJobPostingsSearch(
    marketPlaceJobFilter: $marketPlaceJobFilter,
    searchType: $searchType,
    sortAttributes: $sortAttributes,
    after: $after
  ) {
    totalCount
    edges {
      node {
        %s
      }
    }
    pageInfo {
      endCursor
      hasNextPage
    }
  }
}
""" % JOB_NODE_FIELDS

GET_JOB_QUERY = """
query marketplaceJobPosting($id: ID!) {
  marketplaceJobPosting(id: $id) {
    %s
  }
}
""" % JOB_NODE_FIELDS

# Sort key -> GraphQL MarketplaceJobPostingSearchSortAttribute field.
SORT_ATTRIBUTES = {
    "recency": {"field": "RECENCY"},
    "relevance": {"field": "RELEVANCE"},
}

# Default marketplace search type for open job postings.
DEFAULT_SEARCH_TYPE = "USER_JOBS_SEARCH"

_PAGE_SIZE = 50


class UpworkJobsClient:
    """Search and fetch Upwork marketplace job postings via GraphQL."""

    def __init__(self, config):
        self.config = config
        self._graphql = UpworkGraphQLClient(config)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def search_jobs(
        self,
        *,
        filters: Optional[list[str]] = None,
        sort: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Search marketplace job postings.

        Args:
            filters: Standard ``field:op:value`` filter strings. Server-side
                fields translate to ``MarketplaceJobPostingsSearchFilter`` inputs;
                the rest apply client-side against normalized records.
            sort: Sort key (``recency`` or ``relevance``).
            limit: Maximum number of jobs to return. Pages are fetched via the
                ``pageInfo`` cursor until this many records are collected.

        Returns:
            List of normalized job records (full node data).

        Raises:
            FilterValidationError: On unknown filter field or invalid syntax.
            ClientError: On sort/auth/GraphQL failures.
        """
        validate_jobs_filters(filters)
        server_filters, client_filters = split_server_and_client_filters(filters)
        filter_input = build_jobs_filter_input(server_filters)
        sort_attributes = self._sort_attributes(sort)

        records = self._paginate(filter_input, sort_attributes, limit, client_filters)
        return records

    def get_job(self, job_id: str) -> dict[str, Any]:
        """Fetch a single job posting by id or ciphertext.

        Args:
            job_id: Job posting id or ciphertext (``~0abc...``).

        Returns:
            The normalized job record.

        Raises:
            ClientError: When the job is not found or the GraphQL call fails.
        """
        if not job_id or not job_id.strip():
            raise ClientError("A job id or ciphertext is required.")
        data = self._graphql.execute(
            GET_JOB_QUERY,
            {"id": job_id.strip()},
            operation_name="marketplaceJobPosting",
        )
        node = data.get("marketplaceJobPosting")
        if node is None:
            raise ClientError(f"No Upwork job found for '{job_id}'.")
        return normalize_job(node)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _sort_attributes(self, sort: Optional[str]) -> Optional[list[dict[str, Any]]]:
        if sort is None:
            return None
        key = sort.strip().lower()
        if key not in SORT_ATTRIBUTES:
            allowed = ", ".join(sorted(SORT_ATTRIBUTES))
            raise ClientError(f"Unsupported sort '{sort}'. Allowed: {allowed}.")
        return [SORT_ATTRIBUTES[key]]

    def _paginate(
        self,
        filter_input: dict[str, Any],
        sort_attributes: Optional[list[dict[str, Any]]],
        limit: int,
        client_filters: list[str],
    ) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        after: Optional[str] = None

        while len(collected) < limit:
            variables: dict[str, Any] = {"searchType": DEFAULT_SEARCH_TYPE}
            if filter_input:
                variables["marketPlaceJobFilter"] = filter_input
            if sort_attributes:
                variables["sortAttributes"] = sort_attributes
            if after:
                variables["after"] = after

            data = self._graphql.execute(
                SEARCH_JOBS_QUERY,
                variables,
                operation_name="marketplaceJobPostingsSearch",
            )
            search = data.get("marketplaceJobPostingsSearch")
            if not isinstance(search, dict):
                raise ClientError(
                    "Upwork GraphQL search response missing "
                    "'marketplaceJobPostingsSearch' object."
                )

            page_records = [
                normalize_job(edge["node"])
                for edge in search.get("edges", [])
                if isinstance(edge, dict) and isinstance(edge.get("node"), dict)
            ]
            if client_filters:
                page_records = apply_filters(page_records, client_filters, ALLOWED_FILTER_FIELDS)
            collected.extend(page_records)

            page_info = search.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                break
            next_cursor = page_info.get("endCursor")
            if not next_cursor or next_cursor == after:
                break
            after = next_cursor

        return collected[:limit]


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
def normalize_job(node: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw job node into the CLI's full-data record shape.

    Keeps every source field from the node and adds derived, filter-friendly
    fields (``job_type``, ``fixed_budget``, ``hourly_min``, ``hourly_max``,
    ``published_datetime``, ``experience_level``) used by client-side filters.
    """
    record = dict(node)

    hourly_type = node.get("hourlyBudgetType")
    record["job_type"] = "hourly" if hourly_type else "fixed"

    amount = node.get("amount") or {}
    record["fixed_budget"] = _raw_value(amount)
    record["hourly_min"] = _raw_value(node.get("hourlyBudgetMin"))
    record["hourly_max"] = _raw_value(node.get("hourlyBudgetMax"))

    record["published_datetime"] = node.get("publishedDateTime")

    level = node.get("experienceLevel")
    record["experience_level"] = level.lower() if isinstance(level, str) else level

    return record


def _raw_value(money: Any) -> Optional[float]:
    if not isinstance(money, dict):
        return None
    raw = money.get("rawValue")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def get_jobs_client(profile: Optional[str] = None) -> UpworkJobsClient:
    """Create an ``UpworkJobsClient`` for the given profile."""
    return UpworkJobsClient(get_config(profile=profile))
