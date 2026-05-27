"""Grammarly API client with OAuth 2.0 and exponential retry."""
import base64
import random
import time
from pathlib import Path
from typing import Dict, Optional

import requests

from .config import get_config
from .models import (
    PlagiarismTransaction,
    PlagiarismResult,
    create_plagiarism_transaction,
    create_plagiarism_result,
    Document,
    DocumentDetail,
    create_document,
    create_document_list,
)


# Retry configuration defaults
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 2.0  # seconds (per Grammarly docs recommendation)
DEFAULT_MAX_DELAY = 30.0  # seconds
DEFAULT_JITTER = 0.1  # 10% jitter

# HTTP status codes that trigger retry
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# MIME types for supported file formats
MIME_TYPES = {
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".txt": "text/plain",
    ".rtf": "application/rtf",
}

SUPPORTED_EXTENSIONS = set(MIME_TYPES.keys())


class ClientError(Exception):
    """Custom exception for Grammarly API errors."""
    pass


class GrammarlyClient:
    """Client for interacting with Grammarly Plagiarism Detection API.

    Features:
    - OAuth 2.0 Client Credentials authentication
    - Reactive token refresh (on 401)
    - Exponential backoff retry with jitter
    """

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
        config=None,
    ):
        """Initialize Grammarly client from configuration."""
        self.config = config if config is not None else get_config()

        if not self.config.has_api_credentials():
            missing = self.config.CUSTOM_REQUIRED_FIELDS
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'grammarly auth login --credential-type custom' to configure them."
            )

        self.base_url = self.config.base_url
        self.auth_url = self.config.auth_url

        # Retry configuration
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter

    def _get_auth_headers(self) -> Dict[str, str]:
        """Get headers with current access token."""
        token = self.config.access_token
        if not token:
            self.obtain_access_token()
            token = self.config.access_token

        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "grammarly-cli",
        }

    def obtain_access_token(self):
        """Obtain an OAuth access token with the client-credentials flow.

        POST to auth endpoint with Basic auth header and form data.
        Stores access_token and expires_at in .env.
        """
        # Create Basic auth header: base64(client_id:client_secret)
        credentials = f"{self.config.client_id}:{self.config.client_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()

        headers = {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        data = {
            "grant_type": "client_credentials",
            "scope": "plagiarism-api:read plagiarism-api:write",
        }

        response = requests.post(self.auth_url, headers=headers, data=data)

        if not response.ok:
            try:
                error = response.json()
                error_msg = error.get("error_description", error.get("error", response.text))
            except Exception:
                error_msg = response.text
            raise ClientError(f"Authentication failed ({response.status_code}): {error_msg}")

        token_data = response.json()
        access_token = token_data.get("access_token")
        expires_in = token_data.get("expires_in", 3600)  # Default 1 hour

        if not access_token:
            raise ClientError("Authentication failed: no access_token in response")

        # Calculate expiration timestamp
        expires_at = str(time.time() + expires_in)

        # Save tokens to .env
        self.config.save_tokens(access_token, expires_at)

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        """Calculate delay before next retry using exponential backoff with jitter."""
        if retry_after is not None:
            return min(retry_after, self.max_delay)

        delay = self.base_delay * (2 ** attempt)
        jitter_range = delay * self.jitter
        delay += random.uniform(-jitter_range, jitter_range)
        return min(delay, self.max_delay)

    def _is_retryable(self, response: Optional[requests.Response], exception: Optional[Exception]) -> bool:
        """Determine if a request should be retried."""
        if exception is not None:
            return isinstance(exception, (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError,
            ))

        if response is not None:
            return response.status_code in RETRYABLE_STATUS_CODES

        return False

    def _get_retry_after(self, response: requests.Response) -> Optional[float]:
        """Extract Retry-After header value from response."""
        retry_after = response.headers.get("Retry-After")
        if retry_after is None:
            return None

        try:
            return float(retry_after)
        except ValueError:
            return None

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        retry: bool = True,
    ) -> Dict:
        """Make an HTTP request to the Grammarly API with exponential retry.

        Implements reactive token refresh: on 401, re-authenticates and retries.
        """
        url = f"{self.base_url}{endpoint}"

        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None
        max_attempts = (self.max_retries + 1) if retry else 1
        token_refreshed = False

        for attempt in range(max_attempts):
            try:
                headers = self._get_auth_headers()
                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=data,
                    params=params,
                )
                last_response = response

                # Reactive token refresh on 401 (only once)
                if response.status_code == 401 and not token_refreshed:
                    self.obtain_access_token()
                    token_refreshed = True
                    # Retry with new token
                    headers = self._get_auth_headers()
                    response = requests.request(
                        method=method,
                        url=url,
                        headers=headers,
                        json=data,
                        params=params,
                    )
                    last_response = response

                # Check if we should retry this response
                if retry and self._is_retryable(response, None) and attempt < self.max_retries:
                    retry_after = self._get_retry_after(response)
                    delay = self._calculate_retry_delay(attempt, retry_after)
                    time.sleep(delay)
                    continue

                break

            except requests.exceptions.RequestException as e:
                last_exception = e
                if retry and self._is_retryable(None, e) and attempt < self.max_retries:
                    delay = self._calculate_retry_delay(attempt)
                    time.sleep(delay)
                    continue
                break

        # Handle the final result
        if last_exception is not None and last_response is None:
            raise ClientError(f"Request failed after {attempt + 1} attempts: {last_exception}")

        if last_response is None:
            raise ClientError("Request failed: no response received")

        if not last_response.ok:
            try:
                error_data = last_response.json()
                error_msg = error_data.get("message") or error_data.get("error") or last_response.text
            except Exception:
                error_msg = last_response.text
            raise ClientError(f"API request failed ({last_response.status_code}): {error_msg}")

        if last_response.status_code == 204:
            return {}

        return last_response.json()

    # ==================== Plagiarism Detection API Methods ====================

    def create_plagiarism_request(self, filename: str) -> PlagiarismTransaction:
        """Create a plagiarism detection transaction.

        POST /ecosystem/api/v1/plagiarism with filename.
        Returns transaction with score_request_id and pre-signed S3 upload URL.

        Args:
            filename: Name of the file to be uploaded

        Returns:
            PlagiarismTransaction with score_request_id and file_upload_url
        """
        endpoint = "/ecosystem/api/v1/plagiarism"
        data = {"filename": filename}

        response = self._make_request("POST", endpoint, data=data)
        return create_plagiarism_transaction(response)

    def upload_file_to_s3(self, upload_url: str, file_path: str) -> None:
        """Upload file to pre-signed S3 URL.

        PUT file to the pre-signed URL (no auth needed).
        Must complete within 120 seconds of receiving the URL.

        Args:
            upload_url: Pre-signed S3 URL from create_plagiarism_request
            file_path: Path to the file to upload

        Raises:
            ClientError: If file doesn't exist, unsupported format, or upload fails
        """
        path = Path(file_path)

        if not path.exists():
            raise ClientError(f"File not found: {file_path}")

        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise ClientError(
                f"Unsupported file format: {suffix}. "
                f"Supported formats: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            )

        content_type = MIME_TYPES.get(suffix, "application/octet-stream")

        with open(path, "rb") as f:
            file_data = f.read()

        # PUT to pre-signed URL (no auth header needed)
        response = requests.put(
            upload_url,
            data=file_data,
            headers={"Content-Type": content_type},
        )

        if not response.ok:
            raise ClientError(f"File upload failed ({response.status_code}): {response.text}")

    def get_plagiarism_result(self, score_request_id: str) -> PlagiarismResult:
        """Get the result of a plagiarism detection request.

        GET /ecosystem/api/v1/plagiarism/{score_request_id}
        Returns status (PENDING/FAILED/COMPLETED) and score if completed.

        Args:
            score_request_id: ID from create_plagiarism_request

        Returns:
            PlagiarismResult with status and optional originality score
        """
        endpoint = f"/ecosystem/api/v1/plagiarism/{score_request_id}"
        response = self._make_request("GET", endpoint)
        return create_plagiarism_result(response)


# Module-level client instance - singleton pattern
_client: Optional[GrammarlyClient] = None


def get_client() -> GrammarlyClient:
    """Get or create the global Grammarly client instance."""
    global _client
    if _client is None:
        _client = GrammarlyClient()
    return _client


# ==================== Docs Client (Cookie-based Authentication) ====================


class DocsClient:
    """Client for Grammarly Docs API using cookie-based authentication.

    This client uses browser session cookies to access the dox.grammarly.com API.
    Requires cookies from a logged-in browser session.

    Features:
    - Cookie-based authentication (from browser session)
    - CSRF token handling
    - Exponential backoff retry with jitter
    """

    # API endpoints
    DOX_API = "https://dox.grammarly.com"
    CODA_API = "https://coda.grammarly.com"
    AUTH_API = "https://auth.grammarly.com"

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
        config=None,
    ):
        """Initialize Docs client from configuration."""
        self.config = config if config is not None else get_config()
        self._browser = self.config.get_browser()

        if not self.config.has_cookies():
            raise ClientError(
                "No Grammarly session cookies found. "
                "Set GRAMMARLY_COOKIES env var or create ~/.grammarly_cookies file. "
                "See 'grammarly docs --help' for instructions."
            )

        # Retry configuration
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for docs API requests."""
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://app.grammarly.com",
            "Referer": "https://app.grammarly.com/",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "x-client-type": "funnel",
            "x-client-version": "0.0.0",
        }

        # Add CSRF token if available
        csrf_token = self.config.csrf_token
        if csrf_token:
            headers["X-CSRF-Token"] = csrf_token
            headers["x-csrf-token"] = csrf_token

        return headers

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        """Calculate delay before next retry using exponential backoff with jitter."""
        if retry_after is not None:
            return min(retry_after, self.max_delay)

        delay = self.base_delay * (2 ** attempt)
        jitter_range = delay * self.jitter
        delay += random.uniform(-jitter_range, jitter_range)
        return min(delay, self.max_delay)

    def _is_retryable(self, response: Optional[requests.Response], exception: Optional[Exception]) -> bool:
        """Determine if a request should be retried."""
        if exception is not None:
            return isinstance(exception, (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError,
            ))

        if response is not None:
            return response.status_code in RETRYABLE_STATUS_CODES

        return False

    def _make_request(
        self,
        method: str,
        url: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        retry: bool = True,
    ) -> Dict:
        """Make an HTTP request to Grammarly docs API with exponential retry."""
        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None
        max_attempts = (self.max_retries + 1) if retry else 1

        for attempt in range(max_attempts):
            try:
                headers = self._get_headers()
                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    cookies=self._parse_cookies(),
                    json=data,
                    params=params,
                )
                last_response = response

                # Check if we should retry this response
                if retry and self._is_retryable(response, None) and attempt < self.max_retries:
                    retry_after = response.headers.get("Retry-After")
                    delay = self._calculate_retry_delay(
                        attempt,
                        float(retry_after) if retry_after else None
                    )
                    time.sleep(delay)
                    continue

                break

            except requests.exceptions.RequestException as e:
                last_exception = e
                if retry and self._is_retryable(None, e) and attempt < self.max_retries:
                    delay = self._calculate_retry_delay(attempt)
                    time.sleep(delay)
                    continue
                break

        # Handle the final result
        if last_exception is not None and last_response is None:
            raise ClientError(f"Request failed after {attempt + 1} attempts: {last_exception}")

        if last_response is None:
            raise ClientError("Request failed: no response received")

        if not last_response.ok:
            try:
                error_data = last_response.json()
                error_msg = error_data.get("message") or error_data.get("error") or last_response.text
            except Exception:
                error_msg = last_response.text
            raise ClientError(f"API request failed ({last_response.status_code}): {error_msg}")

        if last_response.status_code == 204:
            return {}

        return last_response.json()

    def _parse_cookies(self) -> Dict[str, str]:
        """Parse cookie string into dict for requests library."""
        cookie_string = self.config.cookies
        if not cookie_string:
            return {}

        cookies = {}
        for part in cookie_string.split(";"):
            part = part.strip()
            if "=" in part:
                key, value = part.split("=", 1)
                cookies[key.strip()] = value.strip()
        return cookies

    # ==================== Docs API Methods ====================

    def list_documents(
        self,
        limit: int = 20,
        search: str = "",
        filter_docs: str = "not_deleted",
    ) -> list[Document]:
        """List user documents.

        Args:
            limit: Maximum number of documents to return
            search: Search query string
            filter_docs: Filter type (not_deleted, deleted, etc.)

        Returns:
            List of Document objects
        """
        url = f"{self.DOX_API}/documents"
        params = {
            "search": search,
            "limit": limit,
            "firstCall": "false",
            "filterDocs": filter_docs,
        }

        response = self._make_request("GET", url, params=params)

        # API returns array directly or wrapped in documents key
        if isinstance(response, list):
            docs = response
        else:
            docs = response.get("documents", [])

        return create_document_list(docs)

    def get_document(self, document_id: str) -> Document:
        """Get a single document by ID.

        Args:
            document_id: Document ID (string or int)

        Returns:
            Document object
        """
        # Convert to int for comparison (API uses int IDs)
        try:
            doc_id_int = int(document_id)
        except ValueError:
            raise ClientError(f"Invalid document ID: {document_id}")

        # List and filter - dox API doesn't have direct get endpoint
        docs = self.list_documents(limit=100)
        for doc in docs:
            if doc.id == doc_id_int:
                return doc

        raise ClientError(f"Document not found: {document_id}")

    def get_document_content(self, document_id: str) -> DocumentDetail:
        """Get document with full content.

        Uses the coda.grammarly.com initLoad API to get document content.
        Note: This API may have stricter access requirements than the list API.

        Args:
            document_id: Document ID

        Returns:
            DocumentDetail with content
        """
        url = f"{self.CODA_API}/api/initLoad"
        params = {
            "docId": str(document_id),
            "isBrainApp": "false",
        }

        try:
            response = self._make_request("GET", url, params=params)
        except ClientError as e:
            if "permission" in str(e).lower() or "404" in str(e):
                raise ClientError(
                    f"Cannot read document content for {document_id}. "
                    "The Coda API may require additional permissions. "
                    "Try using 'grammarly docs get' for metadata only."
                )
            raise

        # Extract document data from initLoad response
        doc_data = response.get("document", {})
        content = doc_data.get("text", "")

        return DocumentDetail(
            id=int(document_id),
            title=doc_data.get("title"),
            content=content,
            revision_id=doc_data.get("revisionId"),
        )

    def get_user(self) -> Dict:
        """Get current user info to verify authentication.

        Returns:
            User info dict
        """
        url = f"{self.AUTH_API}/v3/user"
        params = {"app": "webeditor_chrome"}
        return self._make_request("GET", url, params=params)


# Module-level docs client instance - singleton pattern
_docs_client: Optional[DocsClient] = None


def get_docs_client() -> DocsClient:
    """Get or create the global Docs client instance."""
    global _docs_client
    if _docs_client is None:
        _docs_client = DocsClient()
    return _docs_client
