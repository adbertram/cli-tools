"""InvoiceDesk API transport preserving the established accounting command contract."""
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path
from urllib.parse import quote
import time
import requests
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.http_session import RequestsRetryPolicy
from .config import get_config
PAGE_SIZE = 100

class InvoicedeskClient:
    def __init__(self, config=None, max_retries=3, base_delay=1.0, max_delay=30.0, jitter=0.1):
        self.config = config or get_config()
        if not self.config.api_key:
            raise ClientError("Missing API token. Run 'invoicedesk auth login'.")
        self.base_url = self.config.base_url.rstrip('/')
        self.headers = {"Authorization": f"Bearer {self.config.api_key}", "Accept": "application/json"}
        self.max_retries, self.base_delay, self.max_delay, self.jitter = max_retries, base_delay, max_delay, jitter

    def _make_request(self, method, endpoint, data=None, params=None, retry=True, raw_response=False, extra_headers=None, files=None):
        if not endpoint.startswith('/api/') or '..' in endpoint:
            raise ClientError("Unsafe API endpoint")
        # Retrying an unconfirmed mutation can duplicate payments or emails.
        policy = RequestsRetryPolicy(self.max_retries, self.base_delay, self.max_delay, self.jitter)
        attempts = policy.max_retries + 1 if retry and method == 'GET' else 1
        for attempt in range(attempts):
            try:
                response = requests.request(method, self.base_url + endpoint, headers={**self.headers, **(extra_headers or {})}, json=data, params=params, files=files, timeout=60)
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt + 1 == attempts:
                    raise ClientError(f"Request failed: {exc}") from exc
                response = None
            if response is not None and response.status_code not in policy.retryable_status_codes:
                break
            if attempt + 1 == attempts:
                break
            retry_after = policy.retry_after_seconds(response) if response is not None else None
            if retry_after is not None:
                retry_after = max(0.0, retry_after)
            time.sleep(max(0.0, policy.calculate_delay(attempt, retry_after)))
        if not response.ok:
            raise ClientError(f"API request failed: {response.status_code} - {response.text}")
        if raw_response:
            return response
        if response.status_code == 204:
            return {}
        try:
            result = response.json()
        except ValueError as exc:
            raise ClientError("API returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise ClientError("API returned an unexpected JSON shape")
        return result

    def mark_invoice_sent(self, invoice_id):
        result = self._make_request('POST', f'/api/compat/invoices/{quote(str(invoice_id), safe="")}/mark-sent', data={})
        return result['response']['result']['invoice']

    def upload_attachment(self, file_path):
        path = Path(file_path).expanduser()
        if not path.is_file():
            raise ClientError(f"File not found: {file_path}")
        with path.open('rb') as stream:
            result = self._make_request('POST', '/api/compat/attachments', files={'content': (path.name, stream)})
        attachment = result.get('attachment')
        if not isinstance(attachment, dict) or not attachment.get('jwt') or not attachment.get('media_type'):
            raise ClientError('Attachment upload returned incomplete metadata')
        return {**attachment, 'link': result.get('link')}

    def download_invoice_pdf(self, invoice_id):
        response = self._make_request('GET', f'/api/compat/invoices/{quote(str(invoice_id), safe="")}/pdf', raw_response=True, extra_headers={'Accept':'application/pdf'})
        if response.headers.get('Content-Type','').split(';')[0] != 'application/pdf' or not response.content.startswith(b'%PDF'):
            raise ClientError('API returned an invalid PDF')
        return response.content

    def _paginated_records(
        self,
        endpoint: str,
        collection: str,
        search_params: Optional[List[tuple]] = None,
        max_records: Optional[int] = None,
    ) -> List[Dict]:
        """
        Fetch every page of a paginated InvoiceDesk collection.

        Callers that filter client-side must see the whole matching collection.
        Requesting a single page sized to the caller's ``--limit`` and then
        filtering that page reports an empty result whenever the match happens to
        live on a later page, which reads as "no such record".

        Args:
            endpoint: API endpoint path
            collection: Key holding the records inside ``response.result``
            search_params: Extra query parameters as (key, value) tuples
            max_records: Stop once this many records are collected. Only safe
                when no further filtering is applied to the result.

        Returns:
            List of raw records
        """
        records: List[Dict] = []
        page = 1

        while True:
            params = list(search_params or [])
            params.append(("per_page", min(PAGE_SIZE, max_records) if max_records is not None else PAGE_SIZE))
            params.append(("page", page))

            result = self._make_request("GET", endpoint, params=params)
            payload = result.get("response", {}).get("result")
            if not isinstance(payload, dict) or not isinstance(payload.get(collection), list):
                raise ClientError(f"API response lacks {collection} collection")
            batch = payload[collection]
            records.extend(batch)

            if max_records is not None and len(records) >= max_records:
                return records[:max_records]

            # ``pages`` is absent on responses that are not paginated; treat the
            # current page as the last one rather than looping forever.
            total_pages = payload.get("pages")
            if not isinstance(total_pages, int) or total_pages < page:
                raise ClientError("API returned invalid pagination metadata")
            if not batch or page >= total_pages:
                return records

            page += 1

    def get_invoices(
        self,
        status: Optional[List[str]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        max_records: Optional[int] = None,
    ) -> List[Dict]:
        """
        Get list of invoices with optional status and date filters.

        Args:
            status: List of invoice statuses to filter by
            date_from: Filter invoices created on or after this date (YYYY-MM-DD)
            date_to: Filter invoices created on or before this date (YYYY-MM-DD)
            max_records: Stop after this many records. Pass ``None`` whenever the
                caller applies further filtering to the result.

        Returns:
            List of invoice records
        """
        endpoint = f"/api/compat/invoices"

        # Build params as list of tuples to support multiple values with same key
        params: List[tuple] = []
        if status:
            for s in status:
                params.append(("search[v3_status][]", s))
        if date_from:
            params.append(("search[date_min]", date_from))
        if date_to:
            params.append(("search[date_max]", date_to))

        return self._paginated_records(
            endpoint, "invoices", search_params=params, max_records=max_records
        )

    def get_invoice(self, invoice_id: str) -> Dict:
        """
        Get detailed information about a specific invoice.

        Args:
            invoice_id: The ID of the invoice to retrieve

        Returns:
            Invoice record with line items
        """
        endpoint = f"/api/compat/invoices/{invoice_id}"
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
        endpoint = f"/api/compat/invoices"

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
        if terms is not None:
            invoice_data["invoice"]["terms"] = terms
        if po_number:
            invoice_data["invoice"]["po_number"] = po_number
        if attachments:
            invoice_data["invoice"]["attachments"] = attachments

        result = self._make_request("POST", endpoint, data=invoice_data)
        return result.get("response", {}).get("result", {}).get("invoice", {})

    def delete_invoice(self, invoice_id: str) -> Dict:
        """
        Delete/void an invoice.

        Args:
            invoice_id: ID of the invoice to delete

        Returns:
            Response data
        """
        endpoint = f"/api/compat/invoices/{invoice_id}"

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
        endpoint = f"/api/compat/payments"

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

    def get_clients(
        self,
        search_params: Optional[List[tuple]] = None,
        max_records: Optional[int] = None,
    ) -> List[Dict]:
        """
        Get list of clients, following pagination.

        Args:
            search_params: Server-side ``search[...]`` narrowing as (key, value)
                tuples. These must only ever return a superset of the caller's
                real matches; see ``filter_map.search_literal``.
            max_records: Stop after this many records. Pass ``None`` whenever the
                caller applies further filtering to the result.

        Returns:
            List of client records
        """
        endpoint = f"/api/compat/customers"

        return self._paginated_records(
            endpoint, "clients", search_params=search_params, max_records=max_records
        )

    def get_client(self, client_id: str) -> Dict:
        """
        Get a specific client by ID.

        Args:
            client_id: The client ID

        Returns:
            Client record
        """
        endpoint = f"/api/compat/customers/{client_id}"

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
        clients = self.get_clients(search_params=[("search[email]", email)])
        target = email.casefold()
        return next((record for record in clients if str(record.get("email", "")).casefold() == target), None)

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
        endpoint = f"/api/compat/customers"

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
        endpoint = f"/api/compat/customers/{client_id}"

        data = {"client": kwargs}

        result = self._make_request("PUT", endpoint, data=data)
        return result.get("response", {}).get("result", {}).get("client", {})

    def update_invoice(
        self,
        invoice_id: str,
        attachments: Optional[List[Dict]] = None,
        notes: Optional[str] = None,
        terms: Optional[str] = None,
        po_number: Optional[str] = None,
        lines: Optional[List[Dict]] = None,
    ) -> Dict:
        """
        Update an existing invoice.

        Args:
            invoice_id: ID of the invoice to update
            attachments: List of attachment dicts with jwt and media_type
            notes: Optional notes for the invoice
            terms: Optional payment terms
            po_number: Optional purchase order number
            lines: Complete replacement lines array (the API replaces all lines)

        Returns:
            Updated invoice record
        """
        endpoint = f"/api/compat/invoices/{invoice_id}"

        invoice_data: Dict[str, Any] = {}

        if attachments:
            invoice_data["attachments"] = attachments
        if notes is not None:
            invoice_data["notes"] = notes
        if terms is not None:
            invoice_data["terms"] = terms
        if po_number is not None:
            invoice_data["po_number"] = po_number
        if lines is not None:
            invoice_data["lines"] = lines

        if not invoice_data:
            raise ClientError("No update fields provided")

        data = {"invoice": invoice_data}
        result = self._make_request("PUT", endpoint, data=data)
        return result.get("response", {}).get("result", {}).get("invoice", {})

def get_client():
    return InvoicedeskClient()
