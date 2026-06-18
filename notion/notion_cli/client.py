"""Notion API client with database query filtering."""
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.exceptions import ConnectionError, Timeout, RequestException

from .block_limits import enforce_block_limits
from .config import get_config

# Retry configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 60.0  # seconds
DEFAULT_JITTER = 0.5  # seconds
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# Parallel fetching configuration
DEFAULT_MAX_WORKERS = 25  # Max concurrent API requests for block/comment context fetching


class ClientError(Exception):
    """Custom exception for Notion API errors."""
    pass


class NotFoundError(ClientError):
    """Raised when a Notion API call returns 404 (object_not_found).

    Distinct from ClientError so callers can deterministically detect a
    not-found response (e.g. to discriminate between a database container ID
    and a data source ID under API 2025-09-03).
    """
    pass


class BlockAlreadyArchivedError(ClientError):
    """Raised when a block edit/delete is rejected because the block is already
    archived (HTTP 400, "Can't edit block that is archived.").

    Distinct from ClientError so a caller deleting a SET of blocks can treat an
    already-archived block as already-gone (success for that id) while still
    failing fast on every other error. This is the cascade case: archiving a
    parent block auto-archives its descendants, so a parallel batch that targets
    both a parent and one of its (now trashed) descendants gets this 400 for the
    descendant even though the delete is effectively complete.
    """
    pass


# Substring Notion returns in the 400 validation_error message when a block is
# already archived/in trash. Matched (not the volatile error `code`) so the
# detection survives Notion API wording-adjacent changes to the code field.
_ALREADY_ARCHIVED_MESSAGE = "block that is archived"


class NotionClient:
    """Client for interacting with Notion API."""

    def __init__(self, config=None):
        """Initialize Notion client from configuration."""
        self.config = config or get_config()

        if not self.config.api_token:
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'notion auth login' to configure credentials."
            )

        self.base_url = "https://api.notion.com/v1"
        self.headers = {
            "Authorization": f"Bearer {self.config.api_token}",
            "Content-Type": "application/json",
            "Notion-Version": self.config.api_version,
        }

        # Retry configuration
        self.max_retries = DEFAULT_MAX_RETRIES
        self.base_delay = DEFAULT_BASE_DELAY
        self.max_delay = DEFAULT_MAX_DELAY
        self.jitter = DEFAULT_JITTER

        # Cache for database container -> data_sources resolution.
        # Notion API 2025-09-03 split databases and data sources into separate
        # resources. A single CLI invocation may resolve the same ID multiple
        # times (e.g. schema fetch + query); cache to avoid extra round trips.
        # Key: input id (database_id OR data_source_id). Value: dict with
        # keys "kind" ("database" | "data_source"), "container" (full database
        # JSON or None), "data_sources" (list of {"id","name"} or None for
        # bare data_source IDs).
        self._resolution_cache: Dict[str, Dict[str, Any]] = {}

    def _calculate_retry_delay(
        self,
        attempt: int,
        retry_after: Optional[int] = None,
    ) -> float:
        """
        Calculate delay before next retry using exponential backoff with jitter.

        Args:
            attempt: Current attempt number (0-indexed)
            retry_after: Optional Retry-After header value in seconds

        Returns:
            Delay in seconds before next retry
        """
        if retry_after is not None:
            return min(float(retry_after), self.max_delay)

        # Exponential backoff: base_delay * 2^attempt
        delay = self.base_delay * (2 ** attempt)
        # Add jitter to prevent thundering herd
        delay += random.uniform(0, self.jitter)
        # Cap at max_delay
        return min(delay, self.max_delay)

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        retry: bool = True,
    ) -> Dict:
        """
        Make an HTTP request to the Notion API with exponential retry.

        Args:
            method: HTTP method (GET, POST, PUT, etc.)
            endpoint: API endpoint path
            data: Request body data
            params: Query parameters
            retry: Whether to retry on transient errors (default: True)

        Returns:
            Response JSON data

        Raises:
            ClientError: If request fails after all retries
        """
        url = f"{self.base_url}{endpoint}"
        last_exception: Optional[Exception] = None

        max_attempts = self.max_retries + 1 if retry else 1

        for attempt in range(max_attempts):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    json=data,
                    params=params,
                    timeout=30,
                )

                # Non-retryable errors - fail immediately
                if response.status_code == 401:
                    raise ClientError("Authentication failed. Please check your API token.")

                if response.status_code == 404:
                    error_data = response.json() if response.text else {}
                    error_msg = error_data.get("message", "Resource not found. Check the ID and integration permissions.")
                    raise NotFoundError(error_msg)

                # Retryable status codes
                if response.status_code in RETRYABLE_STATUS_CODES:
                    if attempt < max_attempts - 1:
                        # Get Retry-After header if present
                        retry_after = None
                        if "Retry-After" in response.headers:
                            try:
                                retry_after = int(response.headers["Retry-After"])
                            except ValueError:
                                pass

                        delay = self._calculate_retry_delay(attempt, retry_after)
                        time.sleep(delay)
                        continue

                    # Final attempt failed
                    error_data = response.json() if response.text else {}
                    error_msg = error_data.get("message", response.text)
                    raise ClientError(f"API request failed after {max_attempts} attempts: {response.status_code} - {error_msg}")

                # Other non-OK responses - fail immediately
                if not response.ok:
                    error_data = response.json() if response.text else {}
                    error_msg = error_data.get("message", response.text)
                    # Surface the already-archived 400 as a distinct error so a
                    # delete-set caller can treat an already-trashed block as
                    # already-gone instead of aborting the whole operation.
                    if (
                        response.status_code == 400
                        and isinstance(error_msg, str)
                        and _ALREADY_ARCHIVED_MESSAGE in error_msg.lower()
                    ):
                        raise BlockAlreadyArchivedError(
                            f"API request failed: {response.status_code} - {error_msg}"
                        )
                    raise ClientError(f"API request failed: {response.status_code} - {error_msg}")

                return response.json()

            except (ConnectionError, Timeout) as e:
                last_exception = e
                if attempt < max_attempts - 1:
                    delay = self._calculate_retry_delay(attempt)
                    time.sleep(delay)
                    continue
                raise ClientError(f"Connection failed after {max_attempts} attempts: {e}")

            except RequestException as e:
                raise ClientError(f"Request failed: {e}")

        # Should not reach here, but just in case
        raise ClientError(f"Request failed: {last_exception}")

    def get_current_user(self) -> Dict:
        """
        Get the current bot user information.

        Returns:
            Bot user information
        """
        return self._make_request("GET", "/users/me")

    def _resolve_id(self, database_id: str) -> Dict[str, Any]:
        """
        Resolve a user-supplied "database ID" against API 2025-09-03.

        Under API 2025-09-03 there are two distinct resource types:

        - **Database container** — `/v1/databases/{id}`. Holds metadata and
          a `data_sources[]` array. This is the ID a user typically copies
          from the Notion UI for a new/inline-shared database.
        - **Data source** — `/v1/data_sources/{id}`. Holds the property
          schema and rows. Returned by `/v1/search` with
          `filter.value == "data_source"`. The CLI's `database list`
          command emits these IDs.

        The two ID types are NOT interchangeable, and there is no reliable
        way to tell them apart from the ID string alone. This resolver
        tries the database container endpoint first (the user-facing
        concept), and if that 404s, falls forward to the data_source
        endpoint to confirm it is a bare data_source ID.

        This is not a fallback in the failure-handling sense -- both code
        paths represent valid, supported inputs per Notion's official
        upgrade guide for 2025-09-03. The resolver fails loudly if neither
        endpoint accepts the ID.

        Args:
            database_id: A database container ID OR a data_source ID

        Returns:
            Dict with:
                - "kind": "database" | "data_source"
                - "container": full database container JSON (or None if input
                   was a bare data_source ID)
                - "data_sources": list of {"id","name"} (or None if input
                   was a bare data_source ID)

        Raises:
            NotFoundError: If the ID is neither a known database container
              nor a known data source (or the integration lacks access).
        """
        if database_id in self._resolution_cache:
            return self._resolution_cache[database_id]

        # First try as a database container (the Notion-UI sense of
        # "database ID"). Returns the data_sources[] array when valid.
        try:
            container = self._make_request("GET", f"/databases/{database_id}")
            data_sources = container.get("data_sources", [])
            resolution = {
                "kind": "database",
                "container": container,
                "data_sources": data_sources,
            }
            self._resolution_cache[database_id] = resolution
            return resolution
        except NotFoundError:
            pass

        # Fall forward to data_source resource. If this also 404s, the
        # error propagates -- the ID is genuinely unknown or inaccessible.
        # This is the path used by IDs returned from `database list`
        # (which is implemented as a search with filter=data_source).
        ds_obj = self._make_request("GET", f"/data_sources/{database_id}")
        resolution = {
            "kind": "data_source",
            "container": None,
            "data_sources": None,
            "data_source": ds_obj,
        }
        self._resolution_cache[database_id] = resolution
        return resolution

    def get_data_source_id(
        self,
        database_id: str,
        data_source_id: Optional[str] = None,
    ) -> str:
        """
        Resolve a database ID (or data_source ID) to a concrete data_source ID.

        Args:
            database_id: A database container ID or a data_source ID
            data_source_id: Optional explicit data_source ID. Required when
              the database container holds multiple data sources.

        Returns:
            The data_source ID to use for schema/query/page operations.

        Raises:
            ClientError: If the database container has zero data sources,
              or has multiple and ``data_source_id`` was not provided, or
              if ``data_source_id`` was provided but doesn't belong to the
              container.
            NotFoundError: If the input ID resolves to neither a database
              nor a data source.
        """
        resolution = self._resolve_id(database_id)

        # Case 1: input was already a data_source ID. Honor it. If the
        # caller also passed --data-source, it must match.
        if resolution["kind"] == "data_source":
            if data_source_id is not None and data_source_id != database_id:
                raise ClientError(
                    f"--data-source {data_source_id} does not match the "
                    f"data_source ID {database_id} provided. The given ID "
                    f"is itself a data_source ID; either drop --data-source "
                    f"or supply the parent database container ID."
                )
            return database_id

        # Case 2: input was a database container. Resolve via data_sources[].
        data_sources = resolution["data_sources"] or []
        if not data_sources:
            raise ClientError(
                f"Database {database_id} has no data sources. This should "
                f"not happen under API 2025-09-03 -- check that the "
                f"integration has access and that the database is not "
                f"corrupt or in trash."
            )

        if data_source_id is not None:
            available_ids = {ds.get("id") for ds in data_sources}
            if data_source_id not in available_ids:
                names = ", ".join(
                    f"{ds.get('id')} ({ds.get('name','')})" for ds in data_sources
                )
                raise ClientError(
                    f"--data-source {data_source_id} is not a data source "
                    f"of database {database_id}. Available: {names}"
                )
            return data_source_id

        if len(data_sources) > 1:
            names = "\n  ".join(
                f"- {ds.get('id')}  {ds.get('name','')}" for ds in data_sources
            )
            raise ClientError(
                f"Database {database_id} has multiple data sources. "
                f"Re-run with --data-source <id>. Available:\n  {names}"
            )

        return data_sources[0]["id"]

    def get_database(
        self,
        database_id: str,
        data_source_id: Optional[str] = None,
    ) -> Dict:
        """
        Get database metadata + property schema.

        Returns a single merged object combining the database container
        (parent, is_inline, url, title, archived, ...) with the chosen
        data source's schema (``properties``).

        For inputs that are already data_source IDs (e.g. results from
        ``database list``), only the data_source object is returned; it
        carries title/properties/is_inline natively.

        Args:
            database_id: Database container ID or data_source ID
            data_source_id: Optional explicit data_source ID for the
              multi-data-source case

        Returns:
            Database metadata including ``properties`` schema and (when
            available) ``data_sources`` array.
        """
        resolution = self._resolve_id(database_id)

        if resolution["kind"] == "data_source":
            return resolution["data_source"]

        # Container kind: enrich container with the data source's schema.
        container = dict(resolution["container"])  # shallow copy
        chosen_ds_id = self.get_data_source_id(database_id, data_source_id)
        ds_obj = self._make_request("GET", f"/data_sources/{chosen_ds_id}")
        container["properties"] = ds_obj.get("properties", {})
        container["resolved_data_source_id"] = chosen_ds_id
        return container

    def update_database(
        self,
        database_id: str,
        properties: Optional[Dict] = None,
        title: Optional[List[Dict]] = None,
        data_source_id: Optional[str] = None,
    ) -> Dict:
        """
        Update database (data source) properties (schema) or title.

        Note: In API 2025-09-03+, schemas live on data sources. Title
        edits also flow through the data source endpoint.

        Args:
            database_id: Database container ID or data_source ID
            properties: Property schema updates (add, modify, or remove)
            title: Optional new title
            data_source_id: Explicit data_source ID for multi-data-source
              database containers

        Returns:
            Updated data source object
        """
        data: Dict[str, Any] = {}

        if properties is not None:
            data["properties"] = properties
        if title is not None:
            data["title"] = title

        if not data:
            raise ClientError("No update data provided. Specify properties or title.")

        ds_id = self.get_data_source_id(database_id, data_source_id)
        return self._make_request("PATCH", f"/data_sources/{ds_id}", data=data)

    def create_database(
        self,
        parent_page_id: str,
        title: str,
        properties: Dict,
        inline: bool = False,
    ) -> Dict:
        """
        Create a new database under a parent page (API 2025-09-03+).

        Under API 2025-09-03 a database is created as a container that holds
        one initial data source. The property schema is supplied via
        ``initial_data_source.properties`` (NOT at the top level), and the
        returned container exposes its data source(s) in a ``data_sources``
        array of ``{"id","name"}`` objects.

        The supplied ``properties`` object must contain exactly one property of
        type ``title`` (Notion requires it); the caller is responsible for
        including it.

        Args:
            parent_page_id: The parent page ID the database is created under.
            title: The database title (plain text).
            properties: The data source property schema, in Notion
              ``initial_data_source.properties`` format (e.g.
              ``{"Name": {"title": {}}, "Priority": {"select": {...}}}``).
            inline: When True, create the database inline in the parent page.

        Returns:
            The created database container object, including the top-level
            ``id`` (database container ID), a ``data_sources`` array, and
            ``url``.
        """
        data: Dict[str, Any] = {
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "title": [{"type": "text", "text": {"content": title}}],
            "initial_data_source": {"properties": properties},
            "is_inline": inline,
        }

        return self._make_request("POST", "/databases", data=data)

    def query_database(
        self,
        database_id: str,
        filter_obj: Optional[Dict] = None,
        sorts: Optional[List[Dict]] = None,
        page_size: int = 100,
        start_cursor: Optional[str] = None,
        data_source_id: Optional[str] = None,
    ) -> Dict:
        """
        Query a database with optional filtering and sorting.

        Note: In API 2025-09-03+, queries use the data_sources endpoint.
        This method automatically resolves database_id to data_source_id.

        Args:
            database_id: The database ID (will be resolved to data_source_id internally)
            filter_obj: Filter object following Notion filter syntax
            sorts: List of sort objects
            page_size: Number of results per page (max 100)
            start_cursor: Cursor for pagination
            data_source_id: Explicit data_source ID for multi-data-source containers

        Returns:
            Query results with pages and pagination info
        """
        # Resolve database_id to data_source_id (required in API 2025-09-03+)
        ds_id = self.get_data_source_id(database_id, data_source_id)

        data: Dict[str, Any] = {"page_size": min(page_size, 100)}

        if filter_obj:
            data["filter"] = filter_obj
        if sorts:
            data["sorts"] = sorts
        if start_cursor:
            data["start_cursor"] = start_cursor

        return self._make_request("POST", f"/data_sources/{ds_id}/query", data=data)

    def query_database_all(
        self,
        database_id: str,
        filter_obj: Optional[Dict] = None,
        sorts: Optional[List[Dict]] = None,
        limit: Optional[int] = None,
        data_source_id: Optional[str] = None,
    ) -> List[Dict]:
        """
        Query a database and return pages (handles pagination).

        Args:
            database_id: The database ID
            filter_obj: Filter object following Notion filter syntax
            sorts: List of sort objects
            limit: Maximum number of pages to return (stops pagination early)

        Returns:
            List of matching pages (up to limit if specified)
        """
        all_pages: List[Dict] = []
        start_cursor = None
        has_more = True

        # Use limit as page_size if it's <= 100, otherwise use 100
        page_size = min(limit, 100) if limit and limit <= 100 else 100

        while has_more:
            result = self.query_database(
                database_id=database_id,
                filter_obj=filter_obj,
                sorts=sorts,
                page_size=page_size,
                start_cursor=start_cursor,
                data_source_id=data_source_id,
            )
            all_pages.extend(result.get("results", []))

            # Stop if we've reached the limit
            if limit and len(all_pages) >= limit:
                return all_pages[:limit]

            has_more = result.get("has_more", False)
            start_cursor = result.get("next_cursor")

        return all_pages

    def get_page(self, page_id: str) -> Dict:
        """
        Get a specific page.

        Args:
            page_id: The page ID

        Returns:
            Page object with properties
        """
        return self._make_request("GET", f"/pages/{page_id}")

    def get_block(self, block_id: str) -> Dict:
        """
        Retrieve a single block by ID.

        Args:
            block_id: The block ID to retrieve

        Returns:
            Block object with type-specific content
        """
        return self._make_request("GET", f"/blocks/{block_id}")

    def get_block_children(
        self,
        block_id: str,
        page_size: int = 100,
        start_cursor: Optional[str] = None,
    ) -> Dict:
        """
        Get child blocks of a block (or page).

        Args:
            block_id: The block or page ID
            page_size: Number of results per page (max 100)
            start_cursor: Cursor for pagination

        Returns:
            Block children response with results and pagination info
        """
        params = {"page_size": min(page_size, 100)}
        if start_cursor:
            params["start_cursor"] = start_cursor

        return self._make_request("GET", f"/blocks/{block_id}/children", params=params)

    def get_block_children_all(
        self,
        block_id: str,
        recursive: bool = True,
        max_workers: int = DEFAULT_MAX_WORKERS,
        limit: Optional[int] = None,
    ) -> List[Dict]:
        """
        Get all child blocks of a block (handles pagination).

        Uses parallel fetching for improved performance when recursive=True.

        Args:
            block_id: The block or page ID
            recursive: If True, recursively fetch children of nested blocks
            max_workers: Max concurrent requests for parallel fetching (default: 5)
            limit: Maximum number of top-level blocks to fetch

        Returns:
            List of all child blocks (with nested children if recursive=True)
        """
        all_blocks = []
        start_cursor = None
        has_more = True

        # First, get all top-level blocks (with pagination)
        while has_more:
            page_size = 100
            if limit is not None:
                remaining = limit - len(all_blocks)
                if remaining <= 0:
                    break
                page_size = min(remaining, 100)

            result = self.get_block_children(
                block_id=block_id,
                page_size=page_size,
                start_cursor=start_cursor,
            )
            all_blocks.extend(result.get("results", []))
            if limit is not None and len(all_blocks) >= limit:
                all_blocks = all_blocks[:limit]
                break
            has_more = result.get("has_more", False)
            start_cursor = result.get("next_cursor")

        # If not recursive, return immediately
        if not recursive:
            return all_blocks

        # Parallel recursive fetching for blocks with children
        self._fetch_children_parallel(all_blocks, max_workers)

        return all_blocks

    def _fetch_children_parallel(
        self,
        blocks: List[Dict],
        max_workers: int,
    ) -> None:
        """
        Recursively fetch children for blocks in parallel (modifies blocks in-place).

        Args:
            blocks: List of blocks to process
            max_workers: Max concurrent requests
        """
        # Collect blocks that have children
        blocks_with_children = [
            block for block in blocks
            if block.get("has_children", False)
        ]

        if not blocks_with_children:
            return

        # Fetch all children in parallel
        block_to_children: Dict[str, List[Dict]] = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all fetch tasks
            future_to_block = {
                executor.submit(self._fetch_block_children_flat, block["id"]): block
                for block in blocks_with_children
            }

            # Collect results as they complete
            for future in as_completed(future_to_block):
                block = future_to_block[future]
                try:
                    children = future.result()
                    block_to_children[block["id"]] = children
                except Exception:
                    # On error, set empty children (fail gracefully)
                    block_to_children[block["id"]] = []

        # Assign children to blocks
        for block in blocks_with_children:
            block["children"] = block_to_children.get(block["id"], [])

        # Recursively process children's children (also in parallel)
        all_children = []
        for block in blocks_with_children:
            all_children.extend(block.get("children", []))

        if all_children:
            self._fetch_children_parallel(all_children, max_workers)

    def _fetch_block_children_flat(self, block_id: str) -> List[Dict]:
        """
        Fetch all children of a block (handles pagination, no recursion).

        Args:
            block_id: The block ID

        Returns:
            List of child blocks (without nested children)
        """
        all_blocks = []
        start_cursor = None
        has_more = True

        while has_more:
            result = self.get_block_children(
                block_id=block_id,
                start_cursor=start_cursor,
            )
            all_blocks.extend(result.get("results", []))
            has_more = result.get("has_more", False)
            start_cursor = result.get("next_cursor")

        return all_blocks

    def append_block_children(
        self,
        block_id: str,
        children: List[Dict],
        after: Optional[str] = None,
    ) -> Dict:
        """
        Append child blocks to a block or page.

        Note: Notion API has a limit of 100 blocks per request.
        For larger content, use append_block_children_chunked() instead.

        Args:
            block_id: The block or page ID to append children to
            children: List of block objects to append (max 100)
            after: Optional block ID to append after (for positioning)

        Returns:
            Response with the created blocks
        """
        data: Dict[str, Any] = {"children": children}
        if after:
            data["after"] = after

        return self._make_request(
            "PATCH",
            f"/blocks/{block_id}/children",
            data=data
        )

    def append_block_children_chunked(
        self,
        block_id: str,
        children: List[Dict],
        chunk_size: int = 100,
        progress_callback: Optional[callable] = None,
        after: Optional[str] = None,
    ) -> Tuple[int, List[str]]:
        """
        Append child blocks to a block or page, handling the 100-block API limit.

        Automatically splits large content into chunks and appends them sequentially
        using the 'after' parameter to maintain order.

        Args:
            block_id: The block or page ID to append children to
            children: List of block objects to append (any size)
            chunk_size: Max blocks per API call (default 100, max 100)
            progress_callback: Optional callback(chunk_num, total_chunks, blocks_sent)
            after: Optional block ID to insert after (for positioning the first chunk)

        Returns:
            Tuple of (total_blocks_created, list_of_created_block_ids)
        """
        chunk_size = min(chunk_size, 100)  # API enforces max 100

        if not children:
            return (0, [])

        # Split into chunks
        chunks = [
            children[i:i + chunk_size]
            for i in range(0, len(children), chunk_size)
        ]

        total_chunks = len(chunks)
        total_created = 0
        all_block_ids: List[str] = []
        last_block_id: Optional[str] = after

        for chunk_num, chunk in enumerate(chunks, start=1):
            # Append chunk (use 'after' for subsequent chunks to maintain order)
            result = self.append_block_children(
                block_id=block_id,
                children=chunk,
                after=last_block_id,
            )

            # Extract created block IDs from the response.
            # When 'after' is used, the API returns all children after the
            # insertion point (not just newly created ones). The newly created
            # blocks are the first len(chunk) items in the results.
            result_blocks = result.get("results", [])

            if last_block_id is None:
                # First chunk (no 'after'): response contains only created blocks
                chunk_ids = [b.get("id") for b in result_blocks if b.get("id")]
            else:
                # Subsequent chunks: created blocks are first len(chunk) in results
                created_slice = result_blocks[:len(chunk)]
                chunk_ids = [b.get("id") for b in created_slice if b.get("id")]

            total_created += len(chunk)
            all_block_ids.extend(chunk_ids)

            # Update last_block_id for next chunk's 'after' parameter
            if chunk_ids:
                last_block_id = chunk_ids[-1]

            # Progress callback
            if progress_callback:
                progress_callback(chunk_num, total_chunks, total_created)

        return (total_created, all_block_ids)

    def delete_block(self, block_id: str) -> Dict:
        """
        Delete a block (moves to trash).

        Args:
            block_id: The block ID to delete

        Returns:
            The deleted block object
        """
        return self._make_request("DELETE", f"/blocks/{block_id}")

    def delete_block_if_present(self, block_id: str) -> bool:
        """
        Delete a block, treating an already-archived block as already-gone.

        Identical to ``delete_block`` except that a Notion 400
        "Can't edit block that is archived" response is interpreted as success:
        the block is already in the trash, which is the desired end state. This
        is the idempotent delete used when removing a SET of blocks whose
        archiving can cascade (archiving a parent auto-archives its descendants),
        so a parallel batch that also targets a descendant must not abort on the
        descendant's already-archived 400.

        Every other error (auth, not-found, transport, any non-archived 400)
        still raises, preserving fail-fast behavior. Only the specific
        already-archived case is benign.

        Args:
            block_id: The block ID to delete.

        Returns:
            True if this call archived the block; False if it was already
            archived (already gone).
        """
        try:
            self.delete_block(block_id)
            return True
        except BlockAlreadyArchivedError:
            return False

    def update_block(
        self,
        block_id: str,
        block_data: Dict,
    ) -> Dict:
        """
        Update a block's content.

        Args:
            block_id: The block ID to update
            block_data: Block type-specific content to update

        Returns:
            Updated block object
        """
        return self._make_request("PATCH", f"/blocks/{block_id}", data=block_data)

    def clear_page_content(self, page_id: str) -> Dict:
        """
        Delete all block children from a page using the erase_content API flag.

        This is much more efficient than deleting blocks one-by-one as it uses
        a single API call regardless of the number of blocks.

        Note: This is a destructive action that cannot be reversed via the API.

        Args:
            page_id: The page ID to clear

        Returns:
            Updated page object
        """
        return self.update_page(page_id, erase_content=True)

    def create_page(
        self,
        database_id: str,
        properties: Dict,
        children: Optional[List[Dict]] = None,
        icon: Optional[Dict] = None,
        cover: Optional[Dict] = None,
        data_source_id: Optional[str] = None,
    ) -> Dict:
        """
        Create a new page in a database.

        Note: In API 2025-09-03+, pages use data_source_id for parent.
        This method automatically resolves database_id to data_source_id.

        Args:
            database_id: The database ID (will be resolved to data_source_id internally)
            properties: Property values for the new page (must match database schema)
            children: Optional list of block objects for initial page content
            icon: Optional icon object (emoji or external URL)
            cover: Optional cover object (external URL)
            data_source_id: Explicit data_source ID for multi-data-source containers

        Returns:
            Created page object
        """
        # Resolve database_id to data_source_id (required in API 2025-09-03+)
        ds_id = self.get_data_source_id(database_id, data_source_id)

        data: Dict[str, Any] = {
            "parent": {"data_source_id": ds_id},
            "properties": properties,
        }

        if children is not None:
            # Enforce Notion's per-block size limits so an oversize inline block
            # cannot fail the create request (same protection as the append path).
            data["children"] = enforce_block_limits(children)
        if icon is not None:
            data["icon"] = icon
        if cover is not None:
            data["cover"] = cover

        return self._make_request("POST", "/pages", data=data)

    def update_page(
        self,
        page_id: str,
        properties: Optional[Dict] = None,
        archived: Optional[bool] = None,
        icon: Optional[Dict] = None,
        cover: Optional[Dict] = None,
        erase_content: Optional[bool] = None,
    ) -> Dict:
        """
        Update a page's properties, archive status, icon, or cover.

        Args:
            page_id: The page ID to update
            properties: Property values to update (must match parent database schema)
            archived: Set to True to archive, False to restore
            icon: Icon object (emoji or external URL)
            cover: Cover object (external URL)
            erase_content: Set to True to delete all block children of the page
                          (destructive, cannot be reversed via API)

        Returns:
            Updated page object
        """
        data: Dict[str, Any] = {}

        if properties is not None:
            data["properties"] = properties
        if archived is not None:
            data["archived"] = archived
        if icon is not None:
            data["icon"] = icon
        if cover is not None:
            data["cover"] = cover
        if erase_content is not None:
            data["erase_content"] = erase_content

        if not data:
            raise ClientError("No update data provided. Specify properties, archived, icon, cover, or erase_content.")

        return self._make_request("PATCH", f"/pages/{page_id}", data=data)

    def search(
        self,
        query: Optional[str] = None,
        filter_type: Optional[str] = None,
        sort_direction: Optional[str] = None,
        page_size: int = 100,
        start_cursor: Optional[str] = None,
    ) -> Dict:
        """
        Search for pages and databases.

        Args:
            query: Text to match against page/database titles
            filter_type: Filter by object type ("page" or "data_source")
            sort_direction: Sort by last_edited_time ("ascending" or "descending")
            page_size: Number of results per page (max 100)
            start_cursor: Cursor for pagination

        Returns:
            Search results with pages/databases and pagination info
        """
        data: Dict[str, Any] = {"page_size": min(page_size, 100)}

        if query:
            data["query"] = query
        if filter_type:
            data["filter"] = {"value": filter_type, "property": "object"}
        if sort_direction:
            data["sort"] = {
                "direction": sort_direction,
                "timestamp": "last_edited_time",
            }
        if start_cursor:
            data["start_cursor"] = start_cursor

        return self._make_request("POST", "/search", data=data)

    def search_all(
        self,
        query: Optional[str] = None,
        filter_type: Optional[str] = None,
        sort_direction: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict]:
        """
        Search for pages and databases with pagination handling.

        Args:
            query: Text to match against page/database titles
            filter_type: Filter by object type ("page" or "data_source")
            sort_direction: Sort by last_edited_time ("ascending" or "descending")
            limit: Maximum number of results to return

        Returns:
            List of matching pages/databases
        """
        all_results: List[Dict] = []
        start_cursor = None
        has_more = True

        page_size = min(limit, 100) if limit and limit <= 100 else 100

        while has_more:
            result = self.search(
                query=query,
                filter_type=filter_type,
                sort_direction=sort_direction,
                page_size=page_size,
                start_cursor=start_cursor,
            )
            all_results.extend(result.get("results", []))

            if limit and len(all_results) >= limit:
                return all_results[:limit]

            has_more = result.get("has_more", False)
            start_cursor = result.get("next_cursor")

        return all_results

    def list_templates(
        self,
        database_id: str,
        name: Optional[str] = None,
        page_size: int = 100,
        start_cursor: Optional[str] = None,
        data_source_id: Optional[str] = None,
    ) -> Dict:
        """
        List templates for a database.

        Note: In API 2025-09-03+, templates belong to data sources (not databases).
        This method automatically resolves the database_id to a data_source_id.

        Args:
            database_id: The database ID (will be resolved to data_source_id internally)
            name: Optional filter by template name (case-insensitive substring match)
            page_size: Number of results per page (max 100)
            start_cursor: Cursor for pagination
            data_source_id: Explicit data_source ID for multi-data-source containers

        Returns:
            Templates response with templates array and pagination info
        """
        # Resolve database_id to data_source_id (required in API 2025-09-03+)
        ds_id = self.get_data_source_id(database_id, data_source_id)

        params: Dict[str, Any] = {"page_size": min(page_size, 100)}
        if name:
            params["name"] = name
        if start_cursor:
            params["start_cursor"] = start_cursor

        return self._make_request("GET", f"/data_sources/{ds_id}/templates", params=params)

    def list_templates_all(
        self,
        database_id: str,
        name: Optional[str] = None,
        limit: Optional[int] = None,
        data_source_id: Optional[str] = None,
    ) -> List[Dict]:
        """
        List all templates for a database (handles pagination).

        Args:
            database_id: The database ID
            name: Optional filter by template name (case-insensitive substring match)
            limit: Maximum number of templates to return

        Returns:
            List of template objects with id, name, and is_default
        """
        all_templates: List[Dict] = []
        start_cursor = None
        has_more = True

        page_size = min(limit, 100) if limit and limit <= 100 else 100

        while has_more:
            result = self.list_templates(
                database_id=database_id,
                name=name,
                page_size=page_size,
                start_cursor=start_cursor,
                data_source_id=data_source_id,
            )
            all_templates.extend(result.get("templates", []))

            if limit and len(all_templates) >= limit:
                return all_templates[:limit]

            has_more = result.get("has_more", False)
            start_cursor = result.get("next_cursor")

        return all_templates

    def create_page_from_template(
        self,
        database_id: str,
        properties: Dict,
        template_id: Optional[str] = None,
        use_default_template: bool = False,
        data_source_id: Optional[str] = None,
    ) -> Dict:
        """
        Create a new page in a database from a template.

        Note: In API 2025-09-03+, pages use data_source_id for parent.
        This method automatically resolves database_id to data_source_id.

        Args:
            database_id: The database ID (will be resolved to data_source_id internally)
            properties: Property values for the new page
            template_id: Specific template ID to use (optional)
            use_default_template: Use the database's default template (optional)
            data_source_id: Explicit data_source ID for multi-data-source containers

        Returns:
            Created page object (note: content is applied asynchronously)
        """
        # Resolve database_id to data_source_id (required in API 2025-09-03+)
        ds_id = self.get_data_source_id(database_id, data_source_id)

        data: Dict[str, Any] = {
            "parent": {"data_source_id": ds_id},
            "properties": properties,
        }

        # Add template configuration
        if template_id:
            data["template"] = {"type": "template_id", "template_id": template_id}
        elif use_default_template:
            data["template"] = {"type": "default"}
        # If neither specified, no template is used (type: "none" or omitted)

        return self._make_request("POST", "/pages", data=data)

    def create_standalone_page(
        self,
        parent_page_id: str,
        title: str,
        children: Optional[List[Dict]] = None,
        icon: Optional[Dict] = None,
        cover: Optional[Dict] = None,
    ) -> Dict:
        """
        Create a new page as a child of another page (not in a database).

        Args:
            parent_page_id: The parent page ID
            title: Page title
            children: Optional list of block objects for initial page content
            icon: Optional icon object (emoji or external URL)
            cover: Optional cover object (external URL)

        Returns:
            Created page object
        """
        data: Dict[str, Any] = {
            "parent": {"page_id": parent_page_id},
            "properties": {
                "title": {
                    "title": [{"type": "text", "text": {"content": title}}]
                }
            },
        }

        if children is not None:
            # Enforce Notion's per-block size limits so an oversize inline block
            # cannot fail the create request (same protection as the append path).
            data["children"] = enforce_block_limits(children)
        if icon is not None:
            data["icon"] = icon
        if cover is not None:
            data["cover"] = cover

        return self._make_request("POST", "/pages", data=data)

    # Comments API methods

    def list_comments(
        self,
        block_id: Optional[str] = None,
        discussion_id: Optional[str] = None,
        page_size: int = 100,
        start_cursor: Optional[str] = None,
    ) -> Dict:
        """
        List comments on a block or page, or in a discussion thread.

        Args:
            block_id: The block or page ID to get comments for
            discussion_id: The discussion thread ID to get comments for
            page_size: Number of results per page (max 100)
            start_cursor: Cursor for pagination

        Returns:
            Comments response with results and pagination info

        Note: Either block_id or discussion_id must be provided, but not both.
        """
        if not block_id and not discussion_id:
            raise ClientError("Either block_id or discussion_id must be provided")
        if block_id and discussion_id:
            raise ClientError("Only one of block_id or discussion_id should be provided")

        params: Dict[str, Any] = {"page_size": min(page_size, 100)}
        if block_id:
            params["block_id"] = block_id
        if discussion_id:
            params["discussion_id"] = discussion_id
        if start_cursor:
            params["start_cursor"] = start_cursor

        return self._make_request("GET", "/comments", params=params)

    def list_comments_all(
        self,
        block_id: Optional[str] = None,
        discussion_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict]:
        """
        List all comments on a block/page or in a discussion (handles pagination).

        Args:
            block_id: The block or page ID to get comments for
            discussion_id: The discussion thread ID to get comments for
            limit: Maximum comments to fetch before stopping pagination

        Returns:
            List of all comment objects
        """
        if limit is not None and limit <= 0:
            return []

        all_comments: List[Dict] = []
        start_cursor = None
        has_more = True

        while has_more:
            page_size = 100
            if limit is not None:
                remaining = limit - len(all_comments)
                if remaining <= 0:
                    break
                page_size = min(remaining, 100)

            result = self.list_comments(
                block_id=block_id,
                discussion_id=discussion_id,
                page_size=page_size,
                start_cursor=start_cursor,
            )
            all_comments.extend(result.get("results", []))
            if limit is not None and len(all_comments) >= limit:
                return all_comments[:limit]
            has_more = result.get("has_more", False)
            start_cursor = result.get("next_cursor")

        return all_comments

    def get_comment(self, comment_id: str) -> Dict:
        """
        Get a specific comment by ID.

        Args:
            comment_id: The comment ID

        Returns:
            Comment object
        """
        return self._make_request("GET", f"/comments/{comment_id}")

    def create_comment(
        self,
        rich_text: List[Dict],
        page_id: Optional[str] = None,
        block_id: Optional[str] = None,
        discussion_id: Optional[str] = None,
    ) -> Dict:
        """
        Create a comment on a page, block, or in a discussion thread.

        Args:
            rich_text: Array of rich text objects for the comment content
            page_id: Page ID to add comment to
            block_id: Block ID to add comment to
            discussion_id: Discussion thread ID to reply to

        Returns:
            Created comment object

        Note: Exactly one of page_id, block_id, or discussion_id must be provided.
        """
        provided = sum([bool(page_id), bool(block_id), bool(discussion_id)])
        if provided == 0:
            raise ClientError("One of page_id, block_id, or discussion_id must be provided")
        if provided > 1:
            raise ClientError("Only one of page_id, block_id, or discussion_id can be provided")

        data: Dict[str, Any] = {"rich_text": rich_text}

        if page_id:
            data["parent"] = {"page_id": page_id}
        elif block_id:
            data["parent"] = {"block_id": block_id}
        else:
            data["discussion_id"] = discussion_id

        return self._make_request("POST", "/comments", data=data)

    def list_comments_with_context(
        self,
        page_id: str,
        max_workers: int = DEFAULT_MAX_WORKERS,
        limit: Optional[int] = None,
    ) -> List[Dict]:
        """
        List all comments on a page with their parent block context.

        For each comment, fetches the parent block to provide context
        about what text the comment is attached to. Also includes page-level
        comments (comments attached to the page itself, not a specific block).

        Args:
            page_id: The page ID to get comments for
            max_workers: Max concurrent requests for fetching blocks
            limit: Maximum comments to return

        Returns:
            List of comment objects with added 'context' field containing
            the parent block's text content (or empty string for page-level comments)
        """
        if limit is not None and limit <= 0:
            return []
        if max_workers <= 0:
            raise ClientError("max_workers must be greater than 0")

        all_comments: List[Dict] = []
        block_texts: Dict[str, str] = {}
        block_contexts: Dict[str, Dict[str, str]] = {}

        # First, fetch page-level comments (comments attached to the page itself)
        page_size = min(limit, 100) if limit is not None else 100
        page_result = self.list_comments(block_id=page_id, page_size=page_size)
        page_comments = page_result.get("results", [])
        all_comments.extend(page_comments)

        if limit is not None and len(all_comments) >= limit:
            limited_comments = all_comments[:limit]
            for comment in limited_comments:
                comment["context"] = ""
            return limited_comments

        # Get all blocks on the page (recursive to find inline comments on nested blocks)
        blocks_tree = self.get_block_children_all(
            page_id,
            recursive=True,
            max_workers=max_workers,
        )

        # Flatten the nested block tree into a single list
        blocks = self._flatten_block_tree(blocks_tree)

        if not blocks and not all_comments:
            return []

        if not blocks:
            # Only page-level comments, no blocks
            for comment in all_comments:
                comment["context"] = ""
            return all_comments

        # Precompute readable text for every block so comments can include the
        # parent block plus nearby sibling context.
        for index, block in enumerate(blocks):
            block_id = block.get("id", "")
            block_texts[block_id] = self._get_block_context_text(block)

            before = [
                self._get_block_context_text(b)
                for b in blocks[max(0, index - 2):index]
            ]
            after = [
                self._get_block_context_text(b)
                for b in blocks[index + 1:index + 3]
            ]
            context_lines = [text for text in [*before, block_texts[block_id], *after] if text]
            block_contexts[block_id] = {
                "context_before": "\n".join(text for text in before if text),
                "context_after": "\n".join(text for text in after if text),
                "context_around": "\n".join(context_lines),
            }

        # Fetch comments for all blocks in parallel

        def fetch_block_comments(block: Dict) -> Tuple[List[Dict], str]:
            """Fetch comments for a single block."""
            block_id = block.get("id", "")

            # Get comments for this block
            result = self.list_comments(block_id=block_id)
            comments = result.get("results", [])

            return (comments, block_id)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(fetch_block_comments, block) for block in blocks]

            for future in as_completed(futures):
                comments, block_id = future.result()
                all_comments.extend(comments)

        # Deduplicate comments by ID
        seen_ids: set = set()
        unique_comments: List[Dict] = []
        for comment in all_comments:
            cid = comment.get("id", "")
            if cid not in seen_ids:
                seen_ids.add(cid)
                unique_comments.append(comment)

        # Add context to each comment
        for comment in unique_comments:
            parent = comment.get("parent", {})
            if parent.get("type") == "block_id":
                block_id = parent.get("block_id")
                comment["context"] = block_texts.get(block_id, "[No context]")
                comment.update(block_contexts.get(block_id, {}))
            elif parent.get("type") == "page_id":
                comment["context"] = ""
                comment["context_before"] = ""
                comment["context_after"] = ""
                comment["context_around"] = ""
            else:
                raise ClientError(f"Unknown comment parent type: {parent.get('type', '')}")

        if limit is not None:
            unique_comments = unique_comments[:limit]

        return unique_comments

    @staticmethod
    def _plain_rich_text(rich_text: List[Dict]) -> str:
        """Extract plain text from a Notion rich_text array."""
        return "".join(rt.get("plain_text", "") for rt in rich_text)

    @classmethod
    def _get_block_context_text(cls, block: Dict) -> str:
        """
        Return readable text for a block when presenting comment context.

        Notion comments identify the parent block, not the highlighted text
        range. This method extracts the best available parent-block text for
        block types used in review workflows.
        """
        block_type = block.get("type", "")
        type_content = block.get(block_type, {})

        rich_text = type_content.get("rich_text", [])
        if rich_text:
            return cls._plain_rich_text(rich_text)

        if block_type == "table_row":
            cells = type_content.get("cells", [])
            return " | ".join(cls._plain_rich_text(cell) for cell in cells)

        if block_type in {"child_page", "child_database"}:
            return type_content.get("title", f"[{block_type} block]")

        if block_type == "equation":
            return type_content.get("expression", "[equation block]")

        for nested_type in ("bookmark", "embed", "link_preview"):
            if block_type == nested_type:
                return type_content.get("url", f"[{block_type} block]")

        return f"[{block_type} block]"

    @staticmethod
    def _flatten_block_tree(blocks: List[Dict]) -> List[Dict]:
        """
        Flatten a nested block tree into a single list.

        The recursive fetch stores children in block["children"].
        This walks the tree and returns all blocks at every level.
        """
        flat: List[Dict] = []
        for block in blocks:
            flat.append(block)
            children = block.get("children", [])
            if children:
                flat.extend(NotionClient._flatten_block_tree(children))
        return flat

    def _get_block_text(self, block_id: str) -> str:
        """
        Get the text content of a block.

        Args:
            block_id: The block ID

        Returns:
            Plain text content of the block
        """
        block = self.get_block(block_id)
        block_type = block.get("type", "")

        # Get the type-specific content
        type_content = block.get(block_type, {})

        # Extract rich_text if present
        rich_text = type_content.get("rich_text", [])
        if rich_text:
            return "".join(
                rt.get("plain_text", "") for rt in rich_text
            )

        # For some block types, try other text fields
        if block_type == "child_page":
            return type_content.get("title", "[Child page]")
        if block_type == "child_database":
            return type_content.get("title", "[Child database]")

        return f"[{block_type} block]"

    # File Upload API methods

    def create_file_upload(
        self,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> Dict:
        """
        Create a file upload object to initiate file upload.

        Args:
            filename: Optional filename for the upload
            content_type: Optional MIME content type (e.g., "image/png")

        Returns:
            File upload object with id and upload_url
        """
        data: Dict[str, Any] = {}
        if filename:
            data["filename"] = filename
        if content_type:
            data["content_type"] = content_type

        return self._make_request("POST", "/file_uploads", data=data if data else None)

    def send_file_upload(
        self,
        file_upload_id: str,
        file_path: str,
    ) -> Dict:
        """
        Send file contents to complete a file upload.

        Uses multipart/form-data instead of JSON.

        Args:
            file_upload_id: The file upload ID from create_file_upload()
            file_path: Path to the local file to upload

        Returns:
            Updated file upload object with status "uploaded"

        Raises:
            ClientError: If file doesn't exist, upload fails, or file too large
        """
        import mimetypes
        from pathlib import Path

        path = Path(file_path)
        if not path.exists():
            raise ClientError(f"File not found: {file_path}")

        # Check file size (max 20MB for single-part upload)
        file_size = path.stat().st_size
        max_size = 20 * 1024 * 1024  # 20 MB
        if file_size > max_size:
            raise ClientError(
                f"File too large: {file_size / (1024*1024):.1f} MB. "
                f"Maximum for single-part upload is 20 MB."
            )

        # Determine content type
        content_type, _ = mimetypes.guess_type(str(path))
        if not content_type:
            content_type = "application/octet-stream"

        url = f"{self.base_url}/file_uploads/{file_upload_id}/send"

        # Use multipart/form-data (don't set Content-Type header, requests will set it)
        headers = {
            "Authorization": f"Bearer {self.config.api_token}",
            "Notion-Version": self.config.api_version,
        }

        with open(path, "rb") as f:
            files = {
                "file": (path.name, f, content_type)
            }

            response = requests.post(
                url,
                headers=headers,
                files=files,
                timeout=120,  # Longer timeout for file uploads
            )

        if response.status_code == 401:
            raise ClientError("Authentication failed. Please check your API token.")

        if not response.ok:
            error_data = response.json() if response.text else {}
            error_msg = error_data.get("message", response.text)
            raise ClientError(f"File upload failed: {response.status_code} - {error_msg}")

        return response.json()

    # =========================================================================
    # Block cleaning and duplication utilities
    # =========================================================================

    # Read-only fields that must be stripped before creating blocks
    _BLOCK_READONLY_FIELDS = {
        "id", "created_time", "last_edited_time", "created_by",
        "last_edited_by", "parent", "has_children", "archived",
        "in_trash", "request_id", "object",
    }

    # Block types that cannot be created via append_block_children
    _UNCREATABLE_BLOCK_TYPES = {
        "child_page", "child_database", "link_preview", "unsupported",
    }

    def _clean_block_for_creation(self, block: Dict) -> Optional[Dict]:
        """
        Strip read-only API fields from a block, preserving type-specific content and children.

        Returns None for blocks that cannot be created via the API (child_page, etc.)
        or blocks with invalid data (embed with empty URL, etc.).
        """
        block_type = block.get("type", "")

        # Skip block types that cannot be created via API
        if block_type in self._UNCREATABLE_BLOCK_TYPES:
            return None

        # Skip embed blocks with empty URLs (Notion rejects these)
        if block_type == "embed":
            embed_data = block.get("embed", {})
            if not embed_data.get("url", "").strip():
                return None

        cleaned = {
            k: v for k, v in block.items()
            if k not in self._BLOCK_READONLY_FIELDS
        }
        # Strip fields Notion may return in context-specific block payloads but
        # rejects when the block is recreated under a regular page parent.
        if block_type and isinstance(cleaned.get(block_type), dict):
            type_data = cleaned[block_type]
            for rejected_key in ("icon",):
                type_data.pop(rejected_key, None)
        # Convert image.file blocks to image.external (API doesn't allow creating file-type images)
        if block_type == "image":
            image_data = cleaned.get("image", {})
            if image_data.get("type") == "file":
                file_info = image_data.get("file", {})
                url = file_info.get("url", "")
                # Preserve caption if present
                caption = image_data.get("caption", [])
                cleaned["image"] = {
                    "type": "external",
                    "external": {"url": url},
                }
                if caption:
                    cleaned["image"]["caption"] = caption
        # Same conversion for file blocks (pdf, video, etc.)
        elif block_type in ("file", "video", "pdf"):
            type_data = cleaned.get(block_type, {})
            if type_data.get("type") == "file":
                file_info = type_data.get("file", {})
                url = file_info.get("url", "")
                caption = type_data.get("caption", [])
                cleaned[block_type] = {
                    "type": "external",
                    "external": {"url": url},
                }
                if caption:
                    cleaned[block_type]["caption"] = caption
        # Recursively clean children if present
        if "children" in cleaned and isinstance(cleaned["children"], list):
            cleaned_children = self._clean_blocks_recursive(cleaned["children"])
            if not cleaned_children and block_type == "column":
                # Column blocks MUST have non-empty children per the Notion API.
                # If original children were all uncreatable or the column was empty,
                # insert a single empty paragraph as the minimum valid content.
                cleaned_children = [{"type": "paragraph", "paragraph": {"rich_text": []}}]
            if cleaned_children:
                # API 2025-09-03+: children must be inside the type-specific object,
                # not at the block level
                if block_type and block_type in cleaned:
                    cleaned[block_type]["children"] = cleaned_children
                    del cleaned["children"]
                else:
                    cleaned["children"] = cleaned_children
            else:
                # Remove empty children array (Notion API rejects it)
                del cleaned["children"]
        elif block_type == "column":
            # Column blocks MUST have non-empty children per the Notion API,
            # even if the source column had no children fetched (has_children=False).
            placeholder = [{"type": "paragraph", "paragraph": {"rich_text": []}}]
            if block_type in cleaned:
                cleaned[block_type]["children"] = placeholder
            else:
                cleaned["children"] = placeholder
        return cleaned

    def _clean_blocks_recursive(self, blocks: List[Dict]) -> List[Dict]:
        """Clean a list of blocks recursively (removes API metadata, keeps structure).
        Filters out blocks that cannot be created (child_page, etc.)."""
        return [b for b in (self._clean_block_for_creation(b) for b in blocks) if b is not None]

    def _prepare_blocks_for_upload(
        self,
        blocks: List[Dict],
        max_depth: int = 2,
        _current_depth: int = 1,
    ) -> Tuple[List[Dict], List[Tuple[int, List[Dict]]]]:
        """
        Split blocks into uploadable chunks respecting Notion's nesting limit.

        Notion only allows 2 levels of nesting per append_block_children call.
        This strips children beyond max_depth and returns them separately.

        Args:
            blocks: List of cleaned blocks to prepare
            max_depth: Maximum nesting depth allowed (default 2)
            _current_depth: Internal tracker for recursion depth

        Returns:
            Tuple of (blocks_for_upload, deferred_children)
            where deferred_children is list of (block_index, children) pairs
        """
        deferred: List[Tuple[int, List[Dict]]] = []

        for i, block in enumerate(blocks):
            if "children" not in block:
                continue

            if _current_depth >= max_depth:
                # Strip children at this level — they need a separate upload
                deferred.append((i, block.pop("children")))
            else:
                # Recurse into children to check deeper levels
                child_deferred = []
                for ci, child in enumerate(block["children"]):
                    if "children" in child:
                        if _current_depth + 1 >= max_depth:
                            child_deferred.append((ci, child.pop("children")))
                        else:
                            sub_blocks = [child]
                            _, sub_deferred = self._prepare_blocks_for_upload(
                                sub_blocks, max_depth, _current_depth + 1
                            )
                            # sub_deferred indices are relative to sub_blocks
                            for si, sc in sub_deferred:
                                child_deferred.append((ci, sc))
                # Store child deferred items tagged with parent index
                for ci, children in child_deferred:
                    deferred.append((i, [(ci, children)]))

        return (blocks, deferred)

    # Block types that REQUIRE direct children at creation time per the Notion API.
    # column_list needs >=2 columns; column needs >=1 child block; table needs table_row children.
    _CHILD_REQUIRED_TYPES = frozenset(["column_list", "column", "table"])

    def _upload_blocks_with_nesting(
        self,
        parent_id: str,
        blocks: List[Dict],
        progress_callback=None,
        after: Optional[str] = None,
        _depth: int = 1,
    ) -> Tuple[int, List[str]]:
        """
        Upload blocks supporting arbitrary nesting depth.

        Strategy: pop each block's children before uploading, then for every created
        block recurse to upload its saved children using the new block ID as parent.
        This trades extra API calls for guaranteed correctness at any depth (the
        prior 2-level approach lost the grandchild→parent linkage when stripping
        deeper subtrees, re-attaching grandchildren to the wrong block).

        Block types that require direct children at creation (column_list, column,
        table) keep their direct children inline; only their grandchildren are
        recursed (we look up the created child IDs via a follow-up children fetch).

        Args:
            parent_id: Page or block ID to append children under
            blocks: Block list with arbitrary nesting depth
            progress_callback: Optional callback(stage, message)
            after: Optional block ID to insert after (for positioning the first chunk)
            _depth: Internal recursion depth (for progress reporting)

        Returns:
            Tuple of (total_blocks_created, list_of_top_level_created_block_ids)
        """
        import copy

        if not blocks:
            return (0, [])

        # Enforce Notion's per-block size limits once, at the top of the upload
        # tree. enforce_block_limits returns a new structure (no input mutation)
        # whose nested children are already normalized, so deeper recursion does
        # not need to re-run it. This guarantees no rich_text text.content > 2000
        # chars and no rich_text array > 100 elements ever reaches the network,
        # which is what makes the clear-then-set flow non-destructive: an oversize
        # block is reshaped here, before any page clear, instead of failing the
        # PATCH after the page has been emptied.
        if _depth == 1:
            blocks = enforce_block_limits(blocks)
        else:
            blocks = copy.deepcopy(blocks)

        # For each block, decide what to send up now and what to recurse later.
        # mode is one of:
        #   ("simple", saved_children_list)            -- normal block, children stripped before send
        #   ("inline", [(child_index, grandchildren)]) -- child-required type, direct children
        #                                                 sent inline, grandchildren recursed
        upload_payloads: List[Dict] = []
        deferred: List[Tuple[str, object]] = []

        for block in blocks:
            block_type = block.get("type", "")
            if block_type in self._CHILD_REQUIRED_TYPES:
                # Keep direct children in the payload but pop their grandchildren
                # so we can attach them after the API call returns.
                grandchildren_by_child_idx: List[Tuple[int, List[Dict]]] = []
                for ci, child in enumerate(self._get_children(block)):
                    grandkids = self._pop_children(child)
                    if grandkids:
                        grandchildren_by_child_idx.append((ci, grandkids))
                upload_payloads.append(block)
                deferred.append(("inline", grandchildren_by_child_idx))
            else:
                kids = self._pop_children(block)
                upload_payloads.append(block)
                deferred.append(("simple", kids))

        if progress_callback:
            progress_callback(
                _depth,
                f"Uploading {len(upload_payloads)} block(s) at depth {_depth}...",
            )

        count, created_ids = self.append_block_children_chunked(
            parent_id, upload_payloads, chunk_size=50, after=after,
        )
        total_created = count
        all_ids: List[str] = list(created_ids)

        # Recurse into each created block's saved children
        for created_id, (mode, payload) in zip(created_ids, deferred):
            if not payload:
                continue
            if mode == "simple":
                sub_count, _sub_ids = self._upload_blocks_with_nesting(
                    created_id,
                    payload,
                    progress_callback=progress_callback,
                    _depth=_depth + 1,
                )
                total_created += sub_count
            else:  # inline (column_list / column / table)
                # Direct children went up with the parent; we need their server IDs
                # to attach grandchildren. Fetch them and index by position.
                immediate = self._fetch_block_children_flat(created_id)
                for child_index, grandkids in payload:
                    if child_index >= len(immediate):
                        continue
                    sub_count, _sub_ids = self._upload_blocks_with_nesting(
                        immediate[child_index]["id"],
                        grandkids,
                        progress_callback=progress_callback,
                        _depth=_depth + 1,
                    )
                    total_created += sub_count

        return (total_created, all_ids)

    @staticmethod
    def _get_block_children_key(block: Dict) -> Optional[str]:
        """
        Find where children are stored in a block.

        In API 2025-09-03+, children are inside the type-specific object
        (e.g., block["heading_2"]["children"]). In older formats, they may
        be at the block level (block["children"]).

        Returns the key path as a string: "children" or the block type name
        if children are inside the type object. Returns None if no children.
        """
        block_type = block.get("type", "")
        # Check inside type-specific object first (API 2025-09-03+)
        if block_type and block_type in block:
            type_data = block[block_type]
            if isinstance(type_data, dict) and "children" in type_data:
                return block_type
        # Fall back to block-level children
        if "children" in block:
            return "children"
        return None

    @staticmethod
    def _get_children(block: Dict) -> List[Dict]:
        """Get children from a block, checking both type-specific and block-level locations."""
        block_type = block.get("type", "")
        if block_type and block_type in block:
            type_data = block[block_type]
            if isinstance(type_data, dict) and "children" in type_data:
                return type_data["children"]
        return block.get("children", [])

    @staticmethod
    def _pop_children(block: Dict) -> List[Dict]:
        """Pop children from a block, checking both type-specific and block-level locations."""
        block_type = block.get("type", "")
        if block_type and block_type in block:
            type_data = block[block_type]
            if isinstance(type_data, dict) and "children" in type_data:
                return type_data.pop("children")
        if "children" in block:
            return block.pop("children")
        return []

    def _reupload_file_blocks(
        self,
        blocks: List[Dict],
        progress_callback=None,
    ) -> int:
        """
        Walk blocks recursively and re-upload file-type images/files via File Upload API.

        Converts image.file, video.file, pdf.file, and file.file blocks to use
        file_upload references so they can be duplicated. Modifies blocks in place.

        Args:
            blocks: Raw block list (before cleaning)
            progress_callback: Optional progress callback

        Returns:
            Number of files re-uploaded
        """
        import tempfile
        import requests as req_lib

        count = 0
        file_block_types = ("image", "video", "pdf", "file")

        for block in blocks:
            block_type = block.get("type", "")

            if block_type in file_block_types:
                type_data = block.get(block_type, {})
                if type_data.get("type") == "file":
                    file_info = type_data.get("file", {})
                    url = file_info.get("url", "")
                    if not url:
                        continue

                    try:
                        # Download the file
                        resp = req_lib.get(url, timeout=30)
                        resp.raise_for_status()

                        # Determine extension from content type
                        content_type = resp.headers.get("content-type", "application/octet-stream")
                        ext_map = {
                            "image/jpeg": ".jpg", "image/png": ".png",
                            "image/gif": ".gif", "image/webp": ".webp",
                            "video/mp4": ".mp4", "application/pdf": ".pdf",
                        }
                        ext = ext_map.get(content_type, ".bin")

                        # Save to temp file and upload
                        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
                            f.write(resp.content)
                            temp_path = f.name

                        try:
                            file_upload_id = self.upload_file(temp_path)

                            # Convert block to use file_upload reference
                            caption = type_data.get("caption", [])
                            block[block_type] = {
                                "type": "file_upload",
                                "file_upload": {"id": file_upload_id},
                            }
                            if caption:
                                block[block_type]["caption"] = caption

                            count += 1
                        finally:
                            import os as _os
                            _os.unlink(temp_path)

                    except Exception:
                        # If re-upload fails, leave as-is (will be converted to
                        # external in _clean_block_for_creation as fallback)
                        pass

            # Recurse into children
            children = block.get("children", [])
            if children:
                count += self._reupload_file_blocks(children, progress_callback)

        return count

    def _apply_text_replacements(
        self,
        blocks: List[Dict],
        replacements: List[Tuple[str, str]],
    ) -> None:
        """
        Find/replace text in all rich_text fields recursively (modifies in place).

        Walks all blocks and their children, replacing text in rich_text arrays
        for all block types that contain them.

        Args:
            blocks: List of blocks to process
            replacements: List of (old_text, new_text) tuples
        """
        for block in blocks:
            block_type = block.get("type", "")
            type_content = block.get(block_type, {})

            # Process rich_text arrays
            if isinstance(type_content, dict):
                rich_text = type_content.get("rich_text", [])
                if isinstance(rich_text, list):
                    for rt in rich_text:
                        for old, new in replacements:
                            # Replace in text.content
                            text_obj = rt.get("text", {})
                            if isinstance(text_obj, dict) and "content" in text_obj:
                                text_obj["content"] = text_obj["content"].replace(old, new)
                            # Replace in plain_text
                            if "plain_text" in rt:
                                rt["plain_text"] = rt["plain_text"].replace(old, new)
                            # Replace in text.link if present
                            if isinstance(text_obj, dict) and "link" in text_obj and text_obj["link"]:
                                link_url = text_obj["link"].get("url", "")
                                for old, new in replacements:
                                    text_obj["link"]["url"] = link_url.replace(old, new)

                # Handle caption fields (images, embeds, etc.)
                caption = type_content.get("caption", [])
                if isinstance(caption, list):
                    for rt in caption:
                        for old, new in replacements:
                            text_obj = rt.get("text", {})
                            if isinstance(text_obj, dict) and "content" in text_obj:
                                text_obj["content"] = text_obj["content"].replace(old, new)
                            if "plain_text" in rt:
                                rt["plain_text"] = rt["plain_text"].replace(old, new)

            # Recurse into children
            if "children" in block and isinstance(block["children"], list):
                self._apply_text_replacements(block["children"], replacements)

    def get_blocks_as_notion_json(self, page_id: str) -> List[Dict]:
        """
        Get all blocks from a page as clean Notion JSON ready for re-import.

        Fetches all blocks recursively and strips read-only fields.

        Args:
            page_id: The page ID to export blocks from

        Returns:
            Clean block array compatible with append_block_children / create_page
        """
        blocks = self.get_block_children_all(page_id, recursive=True)
        return self._clean_blocks_recursive(blocks)

    def duplicate_page(
        self,
        page_id: str,
        title: Optional[str] = None,
        property_overrides: Optional[Dict] = None,
        target_database_id: Optional[str] = None,
        replacements: Optional[List[Tuple[str, str]]] = None,
        progress_callback=None,
    ) -> Dict:
        """
        Duplicate a page including all blocks and formatting.

        Args:
            page_id: Source page ID to duplicate
            title: New page title (defaults to "Copy of {original}")
            property_overrides: Raw Notion API property overrides to merge
            target_database_id: Target database ID (defaults to same database)
            replacements: List of (old_text, new_text) for find/replace in block content
            progress_callback: Optional callback(stage, message)

        Returns:
            Created page object
        """
        # Step 1: Get source page
        if progress_callback:
            progress_callback(1, "Fetching source page...")
        source_page = self.get_page(page_id)

        # Step 2: Get source blocks (raw, then re-upload images, then clean)
        if progress_callback:
            progress_callback(2, "Fetching page blocks...")
        raw_blocks = self.get_block_children_all(page_id, recursive=True)

        # Step 2b: Re-upload file-type images/files via Notion File Upload API
        image_count = self._reupload_file_blocks(raw_blocks, progress_callback)
        if image_count > 0 and progress_callback:
            progress_callback(2, f"Re-uploaded {image_count} file(s)")

        # Step 2c: Clean blocks for creation
        blocks = self._clean_blocks_recursive(raw_blocks)

        # Step 3: Apply text replacements if any
        if replacements:
            if progress_callback:
                progress_callback(3, f"Applying {len(replacements)} text replacement(s)...")
            self._apply_text_replacements(blocks, replacements)

        # Step 4: Determine parent type and target
        parent = source_page.get("parent", {})
        parent_type = parent.get("type", "")
        is_page_parent = False

        if target_database_id:
            db_id = target_database_id
        elif "database_id" in parent:
            db_id = parent["database_id"]
        elif "data_source_id" in parent:
            db_id = parent["data_source_id"]
        elif parent_type == "page_id" or "page_id" in parent:
            is_page_parent = True
            parent_page_id = parent.get("page_id", "")
        else:
            raise ClientError(
                "Source page has an unsupported parent type and no --to-database was specified. "
                "Supported parent types: database, page."
            )

        # Step 5: Determine title for the new page
        source_props = source_page.get("properties", {})
        original_title = ""
        for prop_name, prop_value in source_props.items():
            if prop_value.get("type") == "title":
                title_arr = prop_value.get("title", [])
                original_title = "".join(t.get("plain_text", "") for t in title_arr)
                break

        effective_title = title if title else f"Copy of {original_title}"

        # Step 6: Create the new page (without children — nesting limits)
        if progress_callback:
            progress_callback(4, "Creating new page...")

        # Copy icon and cover if present
        icon = source_page.get("icon")
        cover = source_page.get("cover")

        if is_page_parent:
            # Page parent: use create_standalone_page
            new_page = self.create_standalone_page(
                parent_page_id=parent_page_id,
                title=effective_title,
                icon=icon,
                cover=cover,
            )
        else:
            # Database parent: copy properties and use create_page
            new_props = {}
            for prop_name, prop_value in source_props.items():
                prop_type = prop_value.get("type", "")
                # Skip computed/read-only property types
                if prop_type in ("formula", "rollup", "created_time", "created_by",
                                 "last_edited_time", "last_edited_by", "unique_id", "verification", "button"):
                    continue
                # Copy the property value
                new_props[prop_name] = prop_value

            # Set the title
            for prop_name, prop_value in new_props.items():
                if prop_value.get("type") == "title":
                    new_props[prop_name] = {
                        "title": [{"type": "text", "text": {"content": effective_title}}]
                    }
                    break

            # Merge property overrides
            if property_overrides:
                new_props.update(property_overrides)

            new_page = self.create_page(
                database_id=db_id,
                properties=new_props,
                icon=icon,
                cover=cover,
            )

        new_page_id = new_page["id"]

        # Step 7: Upload blocks with nesting handling
        if blocks:
            if progress_callback:
                progress_callback(5, f"Uploading {len(blocks)} blocks...")

            self._upload_blocks_with_nesting(
                new_page_id,
                blocks,
                progress_callback=progress_callback,
            )

        return new_page

    def upload_file(self, file_path: str) -> str:
        """
        Convenience method to upload a file in one step.

        Creates a file upload object and sends the file contents.

        Args:
            file_path: Path to the local file to upload

        Returns:
            The file_upload ID (use this to attach the file to blocks/pages)

        Raises:
            ClientError: If upload fails
        """
        import mimetypes
        from pathlib import Path

        path = Path(file_path)
        if not path.exists():
            raise ClientError(f"File not found: {file_path}")

        # Determine content type
        content_type, _ = mimetypes.guess_type(str(path))

        # Step 1: Create file upload object
        upload_obj = self.create_file_upload(
            filename=path.name,
            content_type=content_type,
        )
        file_upload_id = upload_obj["id"]

        # Step 2: Send file contents
        self.send_file_upload(file_upload_id, file_path)

        return file_upload_id


# Module-level client instance
_client: Optional[NotionClient] = None


def get_client() -> NotionClient:
    """Get or create the global Notion client instance."""
    global _client
    if _client is None:
        _client = NotionClient()
    return _client
