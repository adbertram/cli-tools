"""FreshBooks API client with automatic token management."""
from datetime import datetime
from typing import Dict, List, Optional, Any
import random
import time
import requests

from cli_tools_shared.exceptions import ClientError

from .config import get_config

# Retry configuration defaults
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 30.0  # seconds
DEFAULT_JITTER = 0.1  # 10% jitter

# HTTP status codes that trigger retry
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class FreshBooksClient:
    """Client for interacting with FreshBooks API with automatic token management."""

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        """Initialize FreshBooks client from configuration."""
        self.config = get_config()

        if not self.config.access_token:
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Please configure your .env file."
            )

        self.account_id = self.config.account_id
        self.base_url = "https://api.freshbooks.com"
        self.token_url = "https://api.freshbooks.com/auth/oauth/token"
        self._update_headers()

        # Retry configuration
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter

    def _update_headers(self):
        """Update request headers with current access token."""
        self.headers = {
            "Authorization": f"Bearer {self.config.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    def _is_token_expired(self) -> bool:
        """Check if access token is expired or about to expire."""
        expires_at = self.config.token_expires_at
        if not expires_at:
            return True

        try:
            expires_timestamp = float(expires_at)
            # Consider expired if less than 5 minutes remaining
            return datetime.now().timestamp() > (expires_timestamp - 300)
        except (ValueError, TypeError):
            return True

    def _refresh_token(self):
        """Refresh the access token using the refresh token."""
        refresh_token = self.config.refresh_token
        if not refresh_token:
            raise ClientError(
                "No refresh token available. Please re-authenticate."
            )
        redirect_uri = self.config.redirect_uri or self.config.OAUTH_REDIRECT_URI
        if not redirect_uri:
            raise ClientError(
                "No redirect URI configured. Set REDIRECT_URI in .env or "
                "OAUTH_REDIRECT_URI on Config."
            )

        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "redirect_uri": redirect_uri,
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
        }

        response = requests.post(self.token_url, data=data)

        if response.status_code != 200:
            error_data = response.json()
            if error_data.get("error") == "invalid_grant":
                raise ClientError(
                    "Refresh token is invalid. Please re-authenticate."
                )
            response.raise_for_status()

        token_data = response.json()

        # Save new tokens
        new_access = token_data.get("access_token")
        new_refresh = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 43200)
        expires_at = str(datetime.now().timestamp() + expires_in)

        self.config.save_tokens(new_access, new_refresh, expires_at)
        self._update_headers()

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        """
        Calculate delay before next retry using exponential backoff with jitter.

        Args:
            attempt: Current retry attempt number (0-indexed)
            retry_after: Optional Retry-After header value from server

        Returns:
            Delay in seconds before next retry
        """
        # Honor Retry-After header if present
        if retry_after is not None:
            return min(retry_after, self.max_delay)

        # Exponential backoff: base_delay * 2^attempt
        delay = self.base_delay * (2 ** attempt)

        # Add random jitter to prevent thundering herd
        jitter_range = delay * self.jitter
        delay += random.uniform(-jitter_range, jitter_range)

        # Cap at max delay
        return min(delay, self.max_delay)

    def _is_retryable(self, response: Optional[requests.Response], exception: Optional[Exception]) -> bool:
        """
        Determine if a request should be retried.

        Args:
            response: Response object (if request completed)
            exception: Exception raised (if request failed)

        Returns:
            True if request should be retried
        """
        # Retry on connection errors
        if exception is not None:
            return isinstance(exception, (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
            ))

        # Retry on specific status codes
        if response is not None:
            return response.status_code in RETRYABLE_STATUS_CODES

        return False

    def _get_retry_after(self, response: requests.Response) -> Optional[float]:
        """
        Extract Retry-After header value from response.

        Args:
            response: Response object

        Returns:
            Retry delay in seconds, or None if not present
        """
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
        """
        Make an HTTP request to the FreshBooks API with retry support.

        Args:
            method: HTTP method (GET, POST, PUT, etc.)
            endpoint: API endpoint path
            data: Request body data
            params: Query parameters
            retry: Whether to retry on transient errors (default: True)

        Returns:
            Response JSON data

        Raises:
            ClientError: If request fails
        """
        url = f"{self.base_url}{endpoint}"

        # Check if token needs refresh
        if self._is_token_expired():
            try:
                self._refresh_token()
            except Exception:
                pass  # Try with existing token

        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None
        max_attempts = (self.max_retries + 1) if retry else 1

        for attempt in range(max_attempts):
            try:
                # Make the request
                response = requests.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    json=data,
                    params=params
                )
                last_response = response

                # If 401, try refreshing token and retry (doesn't count against retry limit)
                if response.status_code == 401:
                    try:
                        self._refresh_token()
                        response = requests.request(
                            method=method,
                            url=url,
                            headers=self.headers,
                            json=data,
                            params=params
                        )
                        last_response = response
                    except Exception as e:
                        raise ClientError(f"Authentication failed: {e}")

                # Check if we should retry this response
                if retry and self._is_retryable(response, None) and attempt < self.max_retries:
                    retry_after = self._get_retry_after(response)
                    delay = self._calculate_retry_delay(attempt, retry_after)
                    time.sleep(delay)
                    continue

                # Success or non-retryable error - exit loop
                break

            except requests.exceptions.RequestException as e:
                last_exception = e
                # Check if we should retry this exception
                if retry and self._is_retryable(None, e) and attempt < self.max_retries:
                    delay = self._calculate_retry_delay(attempt)
                    time.sleep(delay)
                    continue
                # Non-retryable exception or exhausted retries
                break

        # Handle the final result
        if last_exception is not None and last_response is None:
            raise ClientError(f"Request failed after {attempt + 1} attempts: {last_exception}")

        if last_response is None:
            raise ClientError("Request failed: no response received")

        if not last_response.ok:
            raise ClientError(f"API request failed: {last_response.status_code} - {last_response.text}")

        return last_response.json()

    # Invoice Methods
    def get_invoices(
        self,
        status: Optional[List[str]] = None,
        per_page: int = 100,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[Dict]:
        """
        Get list of invoices with optional status and date filters.

        Args:
            status: List of invoice statuses to filter by
            per_page: Number of results per page
            date_from: Filter invoices created on or after this date (YYYY-MM-DD)
            date_to: Filter invoices created on or before this date (YYYY-MM-DD)

        Returns:
            List of invoice records
        """
        endpoint = f"/accounting/account/{self.account_id}/invoices/invoices"

        # Build params as list of tuples to support multiple values with same key
        params = [("per_page", per_page)]
        if status:
            for s in status:
                params.append(("search[v3_status][]", s))
        if date_from:
            params.append(("search[date_min]", date_from))
        if date_to:
            params.append(("search[date_max]", date_to))

        result = self._make_request("GET", endpoint, params=params)
        return result.get("response", {}).get("result", {}).get("invoices", [])

    def get_invoice(self, invoice_id: str) -> Dict:
        """
        Get detailed information about a specific invoice.

        Args:
            invoice_id: The ID of the invoice to retrieve

        Returns:
            Invoice record with line items
        """
        endpoint = f"/accounting/account/{self.account_id}/invoices/invoices/{invoice_id}"
        params = {"include[]": "lines"}

        result = self._make_request("GET", endpoint, params=params)
        return result.get("response", {}).get("result", {}).get("invoice", {})

    def create_invoice(
        self,
        customer_id: str,
        items: List[Dict],
        notes: Optional[str] = None,
        terms: Optional[str] = None,
        po_number: Optional[str] = None,
        attachments: Optional[List[Dict]] = None,
        due_offset_days: int = 30
    ) -> Dict:
        """
        Create a new invoice.

        Args:
            customer_id: ID of the customer
            items: List of line items
            notes: Optional notes for the invoice
            terms: Optional payment terms
            po_number: Optional purchase order number
            attachments: Optional list of attachment dicts with jwt and media_type
            due_offset_days: Number of days until invoice is due (default: 30)

        Returns:
            Created invoice record
        """
        endpoint = f"/accounting/account/{self.account_id}/invoices/invoices"

        invoice_data = {
            "invoice": {
                "customerid": customer_id,
                "create_date": datetime.now().strftime("%Y-%m-%d"),
                "due_offset_days": due_offset_days,
                "currency_code": "USD",
                "language": "en",
                "lines": items,
            }
        }

        if notes:
            invoice_data["invoice"]["notes"] = notes
        if terms:
            invoice_data["invoice"]["terms"] = terms
        if po_number:
            invoice_data["invoice"]["po_number"] = po_number
        if attachments:
            invoice_data["invoice"]["attachments"] = attachments

        result = self._make_request("POST", endpoint, data=invoice_data)
        return result.get("response", {}).get("result", {}).get("invoice", {})

    def send_invoice(self, invoice_id: str, email_recipients: Optional[List[str]] = None) -> Dict:
        """
        Send an invoice via email.

        Args:
            invoice_id: ID of the invoice to send
            email_recipients: Optional list of email recipients

        Returns:
            Updated invoice record
        """
        endpoint = f"/accounting/account/{self.account_id}/invoices/invoices/{invoice_id}"

        # Get invoice details if recipients not provided
        if email_recipients is None:
            invoice = self.get_invoice(invoice_id)
            contacts = invoice.get("contacts", [])
            if contacts:
                email_recipients = [contacts[0].get("email")]
            else:
                # Fall back to customer email
                customer_id = invoice.get("customerid")
                if customer_id:
                    customer = self.get_client(str(customer_id))
                    customer_email = customer.get("email")
                    if customer_email:
                        email_recipients = [customer_email]

                if not email_recipients:
                    raise ClientError(f"No email recipients found for invoice {invoice_id}")

        data = {
            "invoice": {
                "email_recipients": email_recipients,
                "email_include_pdf": True,
                "action_email": True
            }
        }

        result = self._make_request("PUT", endpoint, data=data)
        return result.get("response", {}).get("result", {}).get("invoice", {})

    def delete_invoice(self, invoice_id: str) -> Dict:
        """
        Delete/void an invoice.

        Args:
            invoice_id: ID of the invoice to delete

        Returns:
            Response data
        """
        endpoint = f"/accounting/account/{self.account_id}/invoices/invoices/{invoice_id}"

        data = {
            "invoice": {
                "vis_state": 1  # 1 = deleted
            }
        }

        return self._make_request("PUT", endpoint, data=data)

    def mark_invoice_paid(self, invoice_id: str, payment_date: str, amount: str) -> Dict:
        """
        Mark an invoice as paid.

        Args:
            invoice_id: ID of the invoice
            payment_date: Date of payment (YYYY-MM-DD)
            amount: Payment amount

        Returns:
            Payment record
        """
        endpoint = f"/accounting/account/{self.account_id}/payments/payments"

        data = {
            "payment": {
                "invoiceid": invoice_id,
                "amount": {
                    "amount": amount,
                    "code": "USD"
                },
                "date": payment_date,
                "type": "Check"
            }
        }

        result = self._make_request("POST", endpoint, data=data)
        return result.get("response", {}).get("result", {}).get("payment", {})

    # Client/Customer Methods
    def get_clients(self, per_page: int = 100) -> List[Dict]:
        """
        Get list of all clients.

        Args:
            per_page: Number of results per page

        Returns:
            List of client records
        """
        endpoint = f"/accounting/account/{self.account_id}/users/clients"
        params = {"per_page": per_page}

        result = self._make_request("GET", endpoint, params=params)
        return result.get("response", {}).get("result", {}).get("clients", [])

    def get_client(self, client_id: str) -> Dict:
        """
        Get a specific client by ID.

        Args:
            client_id: The client ID

        Returns:
            Client record
        """
        endpoint = f"/accounting/account/{self.account_id}/users/clients/{client_id}"

        result = self._make_request("GET", endpoint)
        return result.get("response", {}).get("result", {}).get("client", {})

    def get_client_by_email(self, email: str) -> Optional[Dict]:
        """
        Get client by email address.

        Args:
            email: Client's email address

        Returns:
            Client record or None if not found
        """
        endpoint = f"/accounting/account/{self.account_id}/users/clients"
        params = {"search[email]": email}

        result = self._make_request("GET", endpoint, params=params)
        clients = result.get("response", {}).get("result", {}).get("clients", [])

        return clients[0] if clients else None

    def create_client(
        self,
        email: str,
        first_name: str,
        last_name: str,
        organization: str
    ) -> Dict:
        """
        Create a new client.

        Args:
            email: Client's email
            first_name: Client's first name
            last_name: Client's last name
            organization: Client's organization/company

        Returns:
            Created client record
        """
        endpoint = f"/accounting/account/{self.account_id}/users/clients"

        data = {
            "client": {
                "email": email,
                "fname": first_name,
                "lname": last_name,
                "organization": organization
            }
        }

        result = self._make_request("POST", endpoint, data=data)
        return result.get("response", {}).get("result", {}).get("client", {})

    def update_client(self, client_id: str, **kwargs) -> Dict:
        """
        Update an existing client.

        Args:
            client_id: ID of the client to update
            **kwargs: Fields to update

        Returns:
            Updated client record
        """
        endpoint = f"/accounting/account/{self.account_id}/users/clients/{client_id}"

        data = {"client": kwargs}

        result = self._make_request("PUT", endpoint, data=data)
        return result.get("response", {}).get("result", {}).get("client", {})

    # Upload Methods
    def upload_attachment(self, file_path: str) -> Dict:
        """
        Upload a file attachment for use with invoices.

        Args:
            file_path: Path to the file to upload

        Returns:
            Dict containing jwt token and media_type for use in invoice attachments
        """
        import os

        if not os.path.exists(file_path):
            raise ClientError(f"File not found: {file_path}")

        endpoint = f"/uploads/account/{self.account_id}/attachments"
        url = f"{self.base_url}{endpoint}"

        # Check if token needs refresh
        if self._is_token_expired():
            try:
                self._refresh_token()
            except Exception:
                pass

        # Use multipart form data for file upload
        headers = {
            "Authorization": f"Bearer {self.config.access_token}",
        }

        with open(file_path, "rb") as f:
            files = {"content": (os.path.basename(file_path), f)}
            response = requests.post(url, headers=headers, files=files)

        # Handle 401 with token refresh
        if response.status_code == 401:
            try:
                self._refresh_token()
                headers["Authorization"] = f"Bearer {self.config.access_token}"
                with open(file_path, "rb") as f:
                    files = {"content": (os.path.basename(file_path), f)}
                    response = requests.post(url, headers=headers, files=files)
            except Exception as e:
                raise ClientError(f"Authentication failed: {e}")

        if not response.ok:
            raise ClientError(f"Upload failed: {response.status_code} - {response.text}")

        result = response.json()
        attachment = result.get("attachment", {})

        return {
            "jwt": attachment.get("jwt"),
            "media_type": attachment.get("media_type"),
            "filename": attachment.get("filename"),
            "link": result.get("link")
        }

    def download_invoice_pdf(self, invoice_id: str) -> bytes:
        """
        Download an invoice as a PDF.

        Args:
            invoice_id: ID of the invoice to download

        Returns:
            PDF content as bytes
        """
        endpoint = f"/accounting/account/{self.account_id}/invoices/invoices/{invoice_id}/pdf"
        url = f"{self.base_url}{endpoint}"

        # Check if token needs refresh
        if self._is_token_expired():
            try:
                self._refresh_token()
            except Exception:
                pass

        # Request PDF with appropriate Accept header
        headers = {
            "Authorization": f"Bearer {self.config.access_token}",
            "Accept": "application/pdf"
        }

        response = requests.get(url, headers=headers)

        # Handle 401 with token refresh
        if response.status_code == 401:
            try:
                self._refresh_token()
                headers["Authorization"] = f"Bearer {self.config.access_token}"
                response = requests.get(url, headers=headers)
            except Exception as e:
                raise ClientError(f"Authentication failed: {e}")

        if not response.ok:
            raise ClientError(f"PDF download failed: {response.status_code} - {response.text}")

        # Verify we got a PDF
        if response.headers.get("Content-Type") != "application/pdf":
            raise ClientError(f"Unexpected content type: {response.headers.get('Content-Type')}")

        return response.content

    # Invoice Methods (continued)
    def update_invoice(
        self,
        invoice_id: str,
        attachments: Optional[List[Dict]] = None,
        notes: Optional[str] = None,
        terms: Optional[str] = None,
        po_number: Optional[str] = None
    ) -> Dict:
        """
        Update an existing invoice.

        Args:
            invoice_id: ID of the invoice to update
            attachments: List of attachment dicts with jwt and media_type
            notes: Optional notes for the invoice
            terms: Optional payment terms
            po_number: Optional purchase order number

        Returns:
            Updated invoice record
        """
        endpoint = f"/accounting/account/{self.account_id}/invoices/invoices/{invoice_id}"

        invoice_data: Dict[str, Any] = {}

        if attachments:
            invoice_data["attachments"] = attachments
        if notes is not None:
            invoice_data["notes"] = notes
        if terms is not None:
            invoice_data["terms"] = terms
        if po_number is not None:
            invoice_data["po_number"] = po_number

        if not invoice_data:
            raise ClientError("No update fields provided")

        data = {"invoice": invoice_data}
        result = self._make_request("PUT", endpoint, data=data)
        return result.get("response", {}).get("result", {}).get("invoice", {})


# Module-level client instance
_client: Optional[FreshBooksClient] = None


def get_client() -> FreshBooksClient:
    """Get or create the global FreshBooks client instance."""
    global _client
    if _client is None:
        _client = FreshBooksClient()
    return _client
