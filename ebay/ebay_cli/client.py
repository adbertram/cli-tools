"""eBay Fulfillment API client with automatic token management and exponential retry."""
import random
import time
from typing import Dict, List, Optional, Any
import requests

from cli_tools_shared.token_manager import TokenManager

from .config import get_config
from cli_tools_shared.filters import parse_filter_string
from cli_tools_shared import FilterMap


# Retry configuration defaults
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 30.0  # seconds
DEFAULT_JITTER = 0.1  # 10% jitter
DEFAULT_REQUEST_TIMEOUT = (10.0, 30.0)  # (connect, read) seconds

# HTTP status codes that trigger retry
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class ClientError(Exception):
    """Custom exception for eBay API errors."""
    pass


class EbayClient:
    """Client for interacting with eBay Fulfillment API with automatic token management."""

    def __init__(
        self,
        config: Optional[Any] = None,
        profile: Optional[str] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
        request_timeout: tuple[float, float] = DEFAULT_REQUEST_TIMEOUT,
    ):
        """
        Initialize eBay client from configuration.

        Args:
            config: Optional pre-initialized configuration object
            profile: Optional profile name to load config for
            max_retries: Maximum number of retry attempts for transient errors (default: 3)
            base_delay: Base delay in seconds for exponential backoff (default: 1.0)
            max_delay: Maximum delay in seconds between retries (default: 30.0)
            jitter: Random jitter factor to prevent thundering herd (default: 0.1)
            request_timeout: Requests connect/read timeout tuple in seconds
        """
        if config:
            self.config = config
        else:
            self.config = get_config(profile=profile)

        self.base_url = self.config.api_base_url
        self.tokens = TokenManager(self.config, on_refresh=self._update_headers)
        self._update_headers()
        self._setup_filters()

        # Retry configuration
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self.request_timeout = request_timeout

    def get_browser(self):
        """Return the shared browser automation instance."""
        return self.config.get_browser()

    def _setup_filters(self):
        """Configure filter mappings."""
        self.filter_map = FilterMap()
        
        # Configure joiner for the 'filter' parameter (join with commas)
        self.filter_map.set_param_joiner('filter', lambda a, b: f"{a},{b}")
        
        # Status translator
        def translate_status(op, val):
            if op == 'eq':
                # eBay API only supports specific combinations for filtering, not single values.
                # We map single values to the containing supported set, and rely on 
                # client-side filtering to narrow it down to the exact value.
                if val == 'NOT_STARTED':
                    return {'filter': "orderfulfillmentstatus:{NOT_STARTED|IN_PROGRESS}"}
                if val == 'IN_PROGRESS':
                    # IN_PROGRESS is in both sets, defaulting to unfulfilled set
                    return {'filter': "orderfulfillmentstatus:{NOT_STARTED|IN_PROGRESS}"}
                if val == 'FULFILLED':
                    return {'filter': "orderfulfillmentstatus:{FULFILLED|IN_PROGRESS}"}
                
                # Fallback for other values or explicit sets
                return {'filter': f"orderfulfillmentstatus:{{{val}}}"}
            
            if op == 'in':
                return {'filter': f"orderfulfillmentstatus:{{{val}}}"}
            return {}
            
        self.filter_map.register_api_translator('orderfulfillmentstatus', translate_status)
        self.filter_map.register_api_translator('status', translate_status)
        
        # Date translator factory
        def create_date_translator(ebay_field):
            def translate_date(op, val):
                # Note: This simple translation doesn't handle merging min/max for the same field 
                # (e.g. created:gte:X AND created:lte:Y) perfectly if they come as separate filters.
                # The joiner will result in "creationdate:[X..],creationdate:[..Y]".
                # eBay API might accept this, or it might error.
                # If eBay requires "creationdate:[X..Y]", this logic needs to be smarter or 
                # FilterMap needs stateful aggregation.
                # Assuming eBay accepts multiple filters for same field or we just support single bounds for now.
                # Based on docs: "You can specify multiple filter criteria, separated by commas".
                # It doesn't explicitly say "creationdate:[..],creationdate:[..]" is invalid.
                if op in ('gt', 'gte'):
                    return {'filter': f"{ebay_field}:[{val}..]"}
                if op in ('lt', 'lte'):
                    return {'filter': f"{ebay_field}:[..{val}]"}
                return {}
            return translate_date
            
        self.filter_map.register_api_translator('creationdate', create_date_translator('creationdate'))
        self.filter_map.register_api_translator('created', create_date_translator('creationdate'))
        self.filter_map.register_api_translator('lastmodifieddate', create_date_translator('lastmodifieddate'))
        self.filter_map.register_api_translator('modified', create_date_translator('lastmodifieddate'))

    def _update_headers(self):
        """Update request headers with current access token."""
        self.headers = {
            "Authorization": f"Bearer {self.config.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Content-Language": "en-US",  # Required for Sell APIs
        }

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
                requests.exceptions.ChunkedEncodingError,
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
            # Try parsing as integer seconds
            return float(retry_after)
        except ValueError:
            # Could be HTTP-date format, but we'll skip that complexity
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
        Make an HTTP request to the eBay API with exponential retry.

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
        # Determine base URL. Use apiz.ebay.com for certain APIs if needed.
        if "/commerce/identity/" in endpoint:
            base_url = self.config.api_base_url.replace("api.", "apiz.")
        else:
            base_url = self.base_url

        url = f"{base_url}{endpoint}"

        # Add marketplace header for Logistics API (required)
        if "/sell/logistics/" in endpoint and "X-EBAY-C-MARKETPLACE-ID" not in self.headers:
            self.headers["X-EBAY-C-MARKETPLACE-ID"] = "EBAY_US"

        # Check if token needs refresh
        if self.tokens.is_expired():
            try:
                self.tokens.force_refresh()
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
                    params=params,
                    timeout=self.request_timeout,
                )
                last_response = response

                # If 401, try refreshing token and retry (doesn't count against retry limit)
                if response.status_code == 401:
                    try:
                        self.tokens.force_refresh()
                        response = requests.request(
                            method=method,
                            url=url,
                            headers=self.headers,
                            json=data,
                            params=params,
                            timeout=self.request_timeout,
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
            # Try to get error details from response
            try:
                error_data = last_response.json()
                errors = error_data.get("errors", [])
                if errors:
                    error_msg = errors[0].get("message", last_response.text)
                    # Substitute template parameters (e.g. {fieldName} -> actual value)
                    for param in errors[0].get("parameters", []):
                        error_msg = error_msg.replace(
                            "{" + param.get("name", "") + "}",
                            param.get("value", ""),
                        )
                else:
                    error_msg = last_response.text
            except Exception:
                error_msg = last_response.text
            raise ClientError(f"API request failed ({last_response.status_code}): {error_msg}")

        # Handle empty response (204 No Content)
        if last_response.status_code == 204:
            return {}

        return last_response.json()

    # Order Methods
    def get_orders(
        self,
        filters: Optional[List[str]] = None,
        limit: int = 50,
        offset: int = 0,
        order_ids: Optional[List[str]] = None,
    ) -> Dict:
        """
        Get list of orders.

        Args:
            filters: List of generic filter strings (e.g., "status:eq:NOT_STARTED")
            limit: Number of results per page (max 200)
            offset: Offset for pagination
            order_ids: List of specific order IDs to retrieve

        Returns:
            Orders response with 'orders' list and pagination info
        """
        endpoint = "/sell/fulfillment/v1/order"

        params = {
            "limit": min(limit, 200),  # eBay max is 200
            "offset": offset,
        }

        # Use FilterMap to generate API parameters
        if filters:
            api_params = self.filter_map.to_api_params(filters)
            params.update(api_params)

        if order_ids:
            params["orderIds"] = ",".join(order_ids)

        return self._make_request("GET", endpoint, params=params)

    def get_order(self, order_id: str) -> Dict:
        """
        Get detailed information about a specific order.

        Args:
            order_id: The eBay order ID

        Returns:
            Order details
        """
        endpoint = f"/sell/fulfillment/v1/order/{order_id}"
        return self._make_request("GET", endpoint)

    def get_shipping_fulfillments(self, order_id: str) -> Dict:
        """
        Get shipping fulfillments for an order.

        Args:
            order_id: The eBay order ID

        Returns:
            Shipping fulfillments for the order
        """
        endpoint = f"/sell/fulfillment/v1/order/{order_id}/shipping_fulfillment"
        return self._make_request("GET", endpoint)

    # Logistics Methods
    def create_shipping_quote(self, payload: Dict) -> Dict:
        """
        Create a shipping quote for a package.

        Args:
            payload: ShippingQuoteRequest dictionary

        Returns:
            Shipping quote details with available rates
        """
        endpoint = "/sell/logistics/v1_beta/shipping_quote"
        return self._make_request("POST", endpoint, data=payload)

    def create_from_shipping_quote(
        self,
        quote_id: str,
        rate_id: str,
        additional_options: Optional[List[Dict]] = None,
        label_custom_message: Optional[str] = None,
        return_to: Optional[Dict] = None,
    ) -> Dict:
        """
        Create a shipment from a previous shipping quote.

        Args:
            quote_id: The ID of the shipping quote
            rate_id: The ID of the selected rate
            additional_options: Optional add-ons (INSURANCE, SIGNATURE) from the rate
            label_custom_message: Optional custom text printed on the label
            return_to: Optional return address override (defaults to shipFrom)

        Returns:
            Shipment details including tracking number and label download URL
        """
        endpoint = "/sell/logistics/v1_beta/shipment/create_from_shipping_quote"
        payload: Dict[str, Any] = {
            "shippingQuoteId": quote_id,
            "rateId": rate_id,
        }
        if additional_options:
            payload["additionalOptions"] = additional_options
        if label_custom_message:
            payload["labelCustomMessage"] = label_custom_message
        if return_to:
            payload["returnTo"] = return_to
        return self._make_request("POST", endpoint, data=payload)

    def get_shipping_quote(self, quote_id: str) -> Dict:
        """
        Retrieve an existing shipping quote by ID.

        Args:
            quote_id: The shipping quote ID

        Returns:
            Shipping quote details with rates
        """
        endpoint = f"/sell/logistics/v1_beta/shipping_quote/{quote_id}"
        return self._make_request("GET", endpoint)

    def get_shipment(self, shipment_id: str) -> Dict:
        """
        Retrieve shipment details by ID.

        Args:
            shipment_id: The shipment ID

        Returns:
            Shipment details including tracking number and cancellation status
        """
        endpoint = f"/sell/logistics/v1_beta/shipment/{shipment_id}"
        return self._make_request("GET", endpoint)

    def cancel_shipment(self, shipment_id: str) -> Dict:
        """
        Cancel a shipment and void the shipping label.

        Args:
            shipment_id: The shipment ID

        Returns:
            Shipment details with cancellation status
        """
        endpoint = f"/sell/logistics/v1_beta/shipment/{shipment_id}/cancel"
        return self._make_request("POST", endpoint)

    def download_label_file(self, shipment_id: str) -> bytes:
        """
        Download the label PDF for a shipment.

        Args:
            shipment_id: The ID of the shipment

        Returns:
            Label file content as bytes (PDF)
        """
        endpoint = f"/sell/logistics/v1_beta/shipment/{shipment_id}/download_label_file"
        url = f"{self.base_url}{endpoint}"

        # Check if token needs refresh
        if self.tokens.is_expired():
            try:
                self.tokens.force_refresh()
            except Exception:
                pass

        headers = {
            "Authorization": f"Bearer {self.config.access_token}",
            "Accept": "application/pdf",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        }

        response = requests.get(url, headers=headers)
        if response.status_code == 401:
            self.tokens.force_refresh()
            headers["Authorization"] = f"Bearer {self.config.access_token}"
            response = requests.get(url, headers=headers)

        if not response.ok:
            raise ClientError(f"Failed to download label ({response.status_code}): {response.text}")

        return response.content

    # Identity Methods
    def get_user(self) -> Dict:
        """
        Get details for the authenticated user.

        Returns:
            User details (username, account type, etc.)
        """
        endpoint = "/commerce/identity/v1/user/"
        return self._make_request("GET", endpoint)

    # Inventory Item Methods
    def get_inventory_items(
        self,
        limit: int = 25,
        offset: int = 0,
    ) -> Dict:
        """
        Get all inventory items for the seller's account.

        Args:
            limit: Number of results per page (1-200, default 25)
            offset: Page offset for pagination

        Returns:
            InventoryItems response with 'inventoryItems' list and pagination info
        """
        endpoint = "/sell/inventory/v1/inventory_item"
        params = {
            "limit": min(limit, 200),
            "offset": offset,
        }
        return self._make_request("GET", endpoint, params=params)

    def get_inventory_item(self, sku: str) -> Dict:
        """
        Get a specific inventory item by SKU.

        Args:
            sku: The seller-defined SKU for the inventory item

        Returns:
            Inventory item details
        """
        endpoint = f"/sell/inventory/v1/inventory_item/{sku}"
        return self._make_request("GET", endpoint)

    def create_or_update_inventory_item(self, sku: str, payload: Dict) -> Dict:
        """
        Create or update an inventory item.

        Args:
            sku: The seller-defined SKU for the inventory item
            payload: InventoryItem request body

        Returns:
            Empty dict on success (204 No Content)
        """
        endpoint = f"/sell/inventory/v1/inventory_item/{sku}"
        return self._make_request("PUT", endpoint, data=payload)

    def delete_inventory_item(self, sku: str) -> Dict:
        """
        Delete an inventory item.

        Args:
            sku: The seller-defined SKU for the inventory item

        Returns:
            Empty dict on success (204 No Content)
        """
        endpoint = f"/sell/inventory/v1/inventory_item/{sku}"
        return self._make_request("DELETE", endpoint)

    def bulk_get_inventory_items(self, skus: List[str]) -> Dict:
        """
        Get multiple inventory items by SKU (up to 25).

        Args:
            skus: List of SKUs to retrieve

        Returns:
            Response with 'inventoryItems' array
        """
        endpoint = "/sell/inventory/v1/bulk_get_inventory_item"
        payload = {
            "requests": [{"sku": sku} for sku in skus[:25]]
        }
        return self._make_request("POST", endpoint, data=payload)

    # Inventory Location Methods
    def get_inventory_locations(
        self,
        limit: int = 25,
        offset: int = 0,
    ) -> Dict:
        """
        Get all merchant inventory locations.

        Args:
            limit: Number of results per page (1-100, default 25)
            offset: Page offset for pagination

        Returns:
            Response with 'locations' array and pagination info
        """
        endpoint = "/sell/inventory/v1/location"
        params = {
            "limit": min(limit, 100),
            "offset": offset,
        }
        return self._make_request("GET", endpoint, params=params)

    def get_inventory_location(self, merchant_location_key: str) -> Dict:
        """
        Get a specific merchant inventory location.

        Args:
            merchant_location_key: The merchant-defined unique identifier for the location

        Returns:
            Location details including address, hours, etc.
        """
        endpoint = f"/sell/inventory/v1/location/{merchant_location_key}"
        return self._make_request("GET", endpoint)

    def create_inventory_location(self, merchant_location_key: str, payload: Dict) -> Dict:
        """
        Create a new merchant inventory location.

        Args:
            merchant_location_key: Unique identifier for the new location
            payload: InventoryLocation request body with location details

        Returns:
            Empty dict on success (204 No Content)
        """
        endpoint = f"/sell/inventory/v1/location/{merchant_location_key}"
        return self._make_request("POST", endpoint, data=payload)

    def update_inventory_location(self, merchant_location_key: str, payload: Dict) -> Dict:
        """
        Update an existing merchant inventory location.

        Only updates: name, locationAdditionalInformation, locationInstructions,
        locationWebUrl, phone, operatingHours, specialHours.

        Args:
            merchant_location_key: The location identifier to update
            payload: Fields to update

        Returns:
            Empty dict on success (204 No Content)
        """
        endpoint = f"/sell/inventory/v1/location/{merchant_location_key}/update_location_details"
        return self._make_request("POST", endpoint, data=payload)

    def delete_inventory_location(self, merchant_location_key: str) -> Dict:
        """
        Delete a merchant inventory location.

        Args:
            merchant_location_key: The location identifier to delete

        Returns:
            Empty dict on success (204 No Content)
        """
        endpoint = f"/sell/inventory/v1/location/{merchant_location_key}"
        return self._make_request("DELETE", endpoint)

    def enable_inventory_location(self, merchant_location_key: str) -> Dict:
        """
        Enable a disabled merchant inventory location.

        Args:
            merchant_location_key: The location identifier to enable

        Returns:
            Empty dict on success (204 No Content)
        """
        endpoint = f"/sell/inventory/v1/location/{merchant_location_key}/enable"
        return self._make_request("POST", endpoint)

    def disable_inventory_location(self, merchant_location_key: str) -> Dict:
        """
        Disable a merchant inventory location.

        Args:
            merchant_location_key: The location identifier to disable

        Returns:
            Empty dict on success (204 No Content)
        """
        endpoint = f"/sell/inventory/v1/location/{merchant_location_key}/disable"
        return self._make_request("POST", endpoint)

    # Offer Methods
    def get_offers(
        self,
        sku: Optional[str] = None,
        marketplace_id: str = "EBAY_US",
        limit: int = 25,
        offset: int = 0,
    ) -> Dict:
        """
        Get offers for the seller's account.

        Args:
            sku: Filter by SKU (optional)
            marketplace_id: Filter by marketplace (default EBAY_US)
            limit: Number of results per page (1-200, default 25)
            offset: Page offset for pagination

        Returns:
            Offers response with 'offers' list and pagination info
        """
        endpoint = "/sell/inventory/v1/offer"
        params = {
            "limit": min(limit, 200),
            "offset": offset,
        }
        if sku:
            params["sku"] = sku
        if marketplace_id:
            params["marketplace_id"] = marketplace_id
        return self._make_request("GET", endpoint, params=params)

    def get_offer(self, offer_id: str) -> Dict:
        """
        Get a specific offer by ID.

        Args:
            offer_id: The eBay offer ID

        Returns:
            Offer details
        """
        endpoint = f"/sell/inventory/v1/offer/{offer_id}"
        return self._make_request("GET", endpoint)

    def create_offer(self, payload: Dict) -> Dict:
        """
        Create an offer for an inventory item.

        Args:
            payload: EbayOfferDetailsWithKeys request body

        Returns:
            Response with 'offerId'
        """
        endpoint = "/sell/inventory/v1/offer"
        return self._make_request("POST", endpoint, data=payload)

    def update_offer(self, offer_id: str, payload: Dict) -> Dict:
        """
        Update an existing offer.

        Args:
            offer_id: The eBay offer ID
            payload: EbayOfferDetailsWithId request body

        Returns:
            Response with 'offerId'
        """
        endpoint = f"/sell/inventory/v1/offer/{offer_id}"
        return self._make_request("PUT", endpoint, data=payload)

    def delete_offer(self, offer_id: str) -> Dict:
        """
        Delete an offer.

        Args:
            offer_id: The eBay offer ID

        Returns:
            Empty dict on success (204 No Content)
        """
        endpoint = f"/sell/inventory/v1/offer/{offer_id}"
        return self._make_request("DELETE", endpoint)

    def publish_offer(self, offer_id: str) -> Dict:
        """
        Publish an offer to create a live eBay listing.

        Args:
            offer_id: The eBay offer ID

        Returns:
            Response with 'listingId'
        """
        endpoint = f"/sell/inventory/v1/offer/{offer_id}/publish"
        return self._make_request("POST", endpoint)

    def withdraw_offer(self, offer_id: str) -> Dict:
        """
        Withdraw a published offer (end the listing).

        Args:
            offer_id: The eBay offer ID

        Returns:
            Response with 'listingId'
        """
        endpoint = f"/sell/inventory/v1/offer/{offer_id}/withdraw"
        return self._make_request("POST", endpoint)

    # Media API Methods - Image Upload
    def upload_image_from_file(self, file_path: str) -> Dict:
        """
        Upload an image file to eBay Media API.

        Args:
            file_path: Local path to image file

        Returns:
            Dict with image_id, imageUrl, expirationDate

        Raises:
            ClientError: If upload fails
        """
        from pathlib import Path

        endpoint = "/commerce/media/v1_beta/image/create_image_from_file"
        # Media API uses apim.ebay.com
        base_url = self.config.api_base_url.replace("api.", "apim.")
        url = f"{base_url}{endpoint}"

        # Check if token needs refresh
        if self.tokens.is_expired():
            try:
                self.tokens.force_refresh()
            except Exception:
                pass

        # Prepare headers (no Content-Type - requests sets it for multipart)
        headers = {
            "Authorization": f"Bearer {self.config.access_token}",
            "Accept": "application/json",
        }

        # Read file and detect content type
        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            raise ClientError(f"File not found: {file_path}")

        # Determine content type from extension
        ext = file_path_obj.suffix.lower()
        content_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
            ".tiff": "image/tiff",
            ".tif": "image/tiff",
            ".webp": "image/webp",
            ".avif": "image/avif",
            ".heic": "image/heic",
        }
        content_type = content_types.get(ext, "application/octet-stream")

        with open(file_path, "rb") as f:
            files = {
                "image": (file_path_obj.name, f, content_type)
            }
            response = requests.post(url, headers=headers, files=files)

        # Handle 401 - token refresh
        if response.status_code == 401:
            try:
                self.tokens.force_refresh()
                headers["Authorization"] = f"Bearer {self.config.access_token}"
                with open(file_path, "rb") as f:
                    files = {"image": (file_path_obj.name, f, content_type)}
                    response = requests.post(url, headers=headers, files=files)
            except Exception as e:
                raise ClientError(f"Authentication failed: {e}")

        if not response.ok:
            try:
                error_data = response.json()
                errors = error_data.get("errors", [])
                if errors:
                    error_msg = errors[0].get("message", response.text)
                else:
                    error_msg = response.text
            except Exception:
                error_msg = response.text
            raise ClientError(f"Image upload failed ({response.status_code}): {error_msg}")

        # Extract image_id from Location header
        location = response.headers.get("Location", "")
        # Format: https://apim.ebay.com/commerce/media/v1_beta/image/{image_id}
        image_id = location.rstrip("/").split("/")[-1]

        result = response.json()
        result["image_id"] = image_id

        return result

    def upload_image_from_url(self, image_url: str) -> Dict:
        """
        Upload an image from URL to eBay Media API.

        Args:
            image_url: HTTPS URL of image

        Returns:
            Dict with image_id, imageUrl, expirationDate

        Raises:
            ClientError: If upload fails
        """
        endpoint = "/commerce/media/v1_beta/image/create_image_from_url"
        base_url = self.config.api_base_url.replace("api.", "apim.")
        url = f"{base_url}{endpoint}"

        # Check if token needs refresh
        if self.tokens.is_expired():
            try:
                self.tokens.force_refresh()
            except Exception:
                pass

        headers = {
            "Authorization": f"Bearer {self.config.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        data = {"imageUrl": image_url}

        response = requests.post(url, headers=headers, json=data)

        # Handle 401
        if response.status_code == 401:
            try:
                self.tokens.force_refresh()
                headers["Authorization"] = f"Bearer {self.config.access_token}"
                response = requests.post(url, headers=headers, json=data)
            except Exception as e:
                raise ClientError(f"Authentication failed: {e}")

        if not response.ok:
            try:
                error_data = response.json()
                errors = error_data.get("errors", [])
                if errors:
                    error_msg = errors[0].get("message", response.text)
                else:
                    error_msg = response.text
            except Exception:
                error_msg = response.text
            raise ClientError(f"Image upload failed ({response.status_code}): {error_msg}")

        # Extract image_id from Location header
        location = response.headers.get("Location", "")
        image_id = location.rstrip("/").split("/")[-1]

        result = response.json()
        result["image_id"] = image_id

        return result

    def get_image(self, image_id: str) -> Dict:
        """
        Get image metadata from eBay Media API.

        Args:
            image_id: The eBay image ID

        Returns:
            Dict with imageUrl, expirationDate

        Raises:
            ClientError: If request fails
        """
        endpoint = f"/commerce/media/v1_beta/image/{image_id}"
        base_url = self.config.api_base_url.replace("api.", "apim.")
        url = f"{base_url}{endpoint}"

        # Check if token needs refresh
        if self.tokens.is_expired():
            try:
                self.tokens.force_refresh()
            except Exception:
                pass

        headers = {
            "Authorization": f"Bearer {self.config.access_token}",
            "Accept": "application/json",
        }

        response = requests.get(url, headers=headers)

        # Handle 401
        if response.status_code == 401:
            try:
                self.tokens.force_refresh()
                headers["Authorization"] = f"Bearer {self.config.access_token}"
                response = requests.get(url, headers=headers)
            except Exception as e:
                raise ClientError(f"Authentication failed: {e}")

        if not response.ok:
            try:
                error_data = response.json()
                errors = error_data.get("errors", [])
                if errors:
                    error_msg = errors[0].get("message", response.text)
                else:
                    error_msg = response.text
            except Exception:
                error_msg = response.text
            raise ClientError(f"Failed to get image ({response.status_code}): {error_msg}")

        return response.json()

    # Account/Policy Methods - Fulfillment
    def get_fulfillment_policies(self, marketplace_id: str = "EBAY_US") -> Dict:
        """
        Get all fulfillment policies for a marketplace.

        Args:
            marketplace_id: The eBay marketplace ID

        Returns:
            Response with 'fulfillmentPolicies' list
        """
        endpoint = "/sell/account/v1/fulfillment_policy"
        params = {"marketplace_id": marketplace_id}
        return self._make_request("GET", endpoint, params=params)

    def get_fulfillment_policy(self, policy_id: str) -> Dict:
        """Get a specific fulfillment policy."""
        endpoint = f"/sell/account/v1/fulfillment_policy/{policy_id}"
        return self._make_request("GET", endpoint)

    def create_fulfillment_policy(self, payload: Dict) -> Dict:
        """Create a fulfillment policy."""
        endpoint = "/sell/account/v1/fulfillment_policy"
        return self._make_request("POST", endpoint, data=payload)

    def update_fulfillment_policy(self, policy_id: str, payload: Dict) -> Dict:
        """Update a fulfillment policy."""
        endpoint = f"/sell/account/v1/fulfillment_policy/{policy_id}"
        return self._make_request("PUT", endpoint, data=payload)

    def delete_fulfillment_policy(self, policy_id: str) -> Dict:
        """Delete a fulfillment policy."""
        endpoint = f"/sell/account/v1/fulfillment_policy/{policy_id}"
        return self._make_request("DELETE", endpoint)

    # Account/Policy Methods - Payment
    def get_payment_policies(self, marketplace_id: str = "EBAY_US") -> Dict:
        """
        Get all payment policies for a marketplace.

        Args:
            marketplace_id: The eBay marketplace ID

        Returns:
            Response with 'paymentPolicies' list
        """
        endpoint = "/sell/account/v1/payment_policy"
        params = {"marketplace_id": marketplace_id}
        return self._make_request("GET", endpoint, params=params)

    def get_payment_policy(self, policy_id: str) -> Dict:
        """Get a specific payment policy."""
        endpoint = f"/sell/account/v1/payment_policy/{policy_id}"
        return self._make_request("GET", endpoint)

    def create_payment_policy(self, payload: Dict) -> Dict:
        """Create a payment policy."""
        endpoint = "/sell/account/v1/payment_policy"
        return self._make_request("POST", endpoint, data=payload)

    def update_payment_policy(self, policy_id: str, payload: Dict) -> Dict:
        """Update a payment policy."""
        endpoint = f"/sell/account/v1/payment_policy/{policy_id}"
        return self._make_request("PUT", endpoint, data=payload)

    def delete_payment_policy(self, policy_id: str) -> Dict:
        """Delete a payment policy."""
        endpoint = f"/sell/account/v1/payment_policy/{policy_id}"
        return self._make_request("DELETE", endpoint)

    # Account/Policy Methods - Return
    def get_return_policies(self, marketplace_id: str = "EBAY_US") -> Dict:
        """
        Get all return policies for a marketplace.

        Args:
            marketplace_id: The eBay marketplace ID

        Returns:
            Response with 'returnPolicies' list
        """
        endpoint = "/sell/account/v1/return_policy"
        params = {"marketplace_id": marketplace_id}
        return self._make_request("GET", endpoint, params=params)

    def get_return_policy(self, policy_id: str) -> Dict:
        """Get a specific return policy."""
        endpoint = f"/sell/account/v1/return_policy/{policy_id}"
        return self._make_request("GET", endpoint)

    def create_return_policy(self, payload: Dict) -> Dict:
        """Create a return policy."""
        endpoint = "/sell/account/v1/return_policy"
        return self._make_request("POST", endpoint, data=payload)

    def update_return_policy(self, policy_id: str, payload: Dict) -> Dict:
        """Update a return policy."""
        endpoint = f"/sell/account/v1/return_policy/{policy_id}"
        return self._make_request("PUT", endpoint, data=payload)

    def delete_return_policy(self, policy_id: str) -> Dict:
        """Delete a return policy."""
        endpoint = f"/sell/account/v1/return_policy/{policy_id}"
        return self._make_request("DELETE", endpoint)

    # Store Methods
    def get_store_categories(self) -> Dict:
        """
        Get all store categories for the seller's eBay store.

        Uses the Sell Stores API to retrieve the category hierarchy.
        API Docs: https://developer.ebay.com/api-docs/sell/stores/resources/store/methods/getStoreCategories

        Returns:
            Response with 'storeCategories' list (recursive with childrenCategories)
        """
        endpoint = "/sell/stores/v1/store/categories"
        return self._make_request("GET", endpoint)

    # Metadata API Methods
    def get_item_condition_policies(
        self,
        marketplace_id: str = "EBAY_US",
        category_ids: Optional[List[str]] = None,
    ) -> Dict:
        """
        Get valid item conditions for categories in a marketplace.

        Uses the Sell Metadata API to retrieve which condition enums/IDs
        are valid for specific categories.

        API Docs: https://developer.ebay.com/api-docs/sell/metadata/resources/marketplace/methods/getItemConditionPolicies

        Args:
            marketplace_id: eBay marketplace (default: EBAY_US)
            category_ids: Optional list of category IDs to filter (max 50)

        Returns:
            Response with 'itemConditionPolicies' list containing valid conditions per category
        """
        endpoint = f"/sell/metadata/v1/marketplace/{marketplace_id}/get_item_condition_policies"
        params = {}
        if category_ids:
            # Format: filter=categoryIds:{cat1|cat2|cat3}
            ids_str = "|".join(category_ids[:50])
            params["filter"] = f"categoryIds:{{{ids_str}}}"
        return self._make_request("GET", endpoint, params=params)

    # Feed API Methods
    def create_inventory_task(
        self,
        feed_type: str = "LMS_ACTIVE_INVENTORY_REPORT",
        listing_format: Optional[str] = None,
        marketplace_id: str = "EBAY_US",
    ) -> str:
        """
        Create an inventory report task.

        Args:
            feed_type: The feed type (default: LMS_ACTIVE_INVENTORY_REPORT)
            listing_format: Optional filter - AUCTION or FIXED_PRICE
            marketplace_id: The eBay marketplace ID

        Returns:
            The task_id extracted from the Location header
        """
        endpoint = "/sell/feed/v1/inventory_task"
        url = f"{self.base_url}{endpoint}"

        payload: Dict[str, Any] = {
            "schemaVersion": "1.0",
            "feedType": feed_type,
        }
        if listing_format:
            payload["filterCriteria"] = {"listingFormat": listing_format}

        headers = {
            **self.headers,
            "X-EBAY-C-MARKETPLACE-ID": marketplace_id,
        }

        response = requests.post(url, headers=headers, json=payload)

        if response.status_code == 202:
            # Extract task_id from Location header
            location = response.headers.get("Location", "")
            # Location format: /sell/feed/v1/inventory_task/{task_id}
            task_id = location.rstrip("/").split("/")[-1]
            return task_id
        else:
            try:
                error_data = response.json()
                errors = error_data.get("errors", [])
                if errors:
                    error_msg = errors[0].get("message", response.text)
                else:
                    error_msg = response.text
            except Exception:
                error_msg = response.text
            raise ClientError(f"Failed to create inventory task ({response.status_code}): {error_msg}")

    def get_inventory_task(self, task_id: str) -> Dict:
        """
        Get the status and details of an inventory task.

        Args:
            task_id: The task ID returned from create_inventory_task

        Returns:
            Task details including status (CREATED, QUEUED, IN_PROGRESS, COMPLETED, COMPLETED_WITH_ERROR, FAILED)
        """
        endpoint = f"/sell/feed/v1/inventory_task/{task_id}"
        return self._make_request("GET", endpoint)

    def download_task_result(self, task_id: str) -> bytes:
        """
        Download the result file for a completed task.

        Args:
            task_id: The task ID

        Returns:
            The raw file content (gzipped XML for inventory reports)
        """
        endpoint = f"/sell/feed/v1/task/{task_id}/download_result_file"
        url = f"{self.base_url}{endpoint}"

        # Use different Accept header for file download
        headers = {
            "Authorization": f"Bearer {self.config.access_token}",
            "Accept": "application/octet-stream",
        }

        response = requests.get(url, headers=headers)

        if response.ok:
            return response.content
        else:
            raise ClientError(f"Failed to download task result ({response.status_code}): {response.text}")

    # Trading API Methods
    def _make_trading_api_request(
        self,
        call_name: str,
        request_xml: str,
        site_id: int = 0,
    ) -> str:
        """
        Make an XML request to the eBay Trading API.

        Args:
            call_name: The Trading API call name (e.g., GetSellerList)
            request_xml: The XML request body
            site_id: eBay site ID (default: 0 for US)

        Returns:
            Response XML as string

        Raises:
            ClientError: If request fails
        """
        # Check if token needs refresh
        if self.tokens.is_expired():
            try:
                self.tokens.force_refresh()
            except Exception:
                pass  # Try with existing token

        # Trading API endpoint
        url = f"{self.base_url}/ws/api.dll"

        headers = {
            "X-EBAY-API-IAF-TOKEN": self.config.access_token,
            "X-EBAY-API-CALL-NAME": call_name,
            "X-EBAY-API-SITEID": str(site_id),
            "X-EBAY-API-COMPATIBILITY-LEVEL": "1349",
            "Content-Type": "text/xml",
        }

        response = requests.post(url, headers=headers, data=request_xml)

        # If 401, try refreshing token and retry
        if response.status_code == 401:
            try:
                self.tokens.force_refresh()
                headers["X-EBAY-API-IAF-TOKEN"] = self.config.access_token
                response = requests.post(url, headers=headers, data=request_xml)
            except Exception as e:
                raise ClientError(f"Authentication failed: {e}")

        if not response.ok:
            raise ClientError(f"Trading API request failed ({response.status_code}): {response.text}")

        # Explicitly decode as UTF-8 (eBay XML responses are UTF-8 encoded)
        return response.content.decode('utf-8')

    def get_seller_list(
        self,
        entries_per_page: int = 100,
        page_number: int = 1,
        sort: int = 2,
        granularity_level: str = "Fine",
        include_variation: bool = True,
    ) -> str:
        """
        Get active listings using the Trading API GetSellerList call.

        Args:
            entries_per_page: Number of items per page (max 200)
            page_number: Page number to retrieve
            sort: Sort order (2 = EndTimeNewest, 1 = EndTimeSoonest)
            granularity_level: Detail level - Coarse, Medium, or Fine
            include_variation: Include variation data for multi-variant listings

        Returns:
            XML response as string
        """
        # Build request XML - get active listings only
        # Use EndTimeFrom/EndTimeTo to filter active listings (end time in future)
        from datetime import datetime, timedelta

        # Active listings have EndTime in the future
        now = datetime.utcnow()
        end_time_from = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        end_time_to = (now + timedelta(days=120)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        request_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<GetSellerListRequest xmlns="urn:ebay:apis:eBLBaseComponents">
    <EndTimeFrom>{end_time_from}</EndTimeFrom>
    <EndTimeTo>{end_time_to}</EndTimeTo>
    <GranularityLevel>{granularity_level}</GranularityLevel>
    <IncludeVariations>{str(include_variation).lower()}</IncludeVariations>
    <Pagination>
        <EntriesPerPage>{min(entries_per_page, 200)}</EntriesPerPage>
        <PageNumber>{page_number}</PageNumber>
    </Pagination>
    <Sort>{sort}</Sort>
    <OutputSelector>ItemID</OutputSelector>
    <OutputSelector>Title</OutputSelector>
    <OutputSelector>SKU</OutputSelector>
    <OutputSelector>Quantity</OutputSelector>
    <OutputSelector>QuantityAvailable</OutputSelector>
    <OutputSelector>SellingStatus</OutputSelector>
    <OutputSelector>ListingType</OutputSelector>
    <OutputSelector>PictureDetails</OutputSelector>
    <OutputSelector>ListingDetails</OutputSelector>
    <OutputSelector>PaginationResult</OutputSelector>
    <OutputSelector>Variations</OutputSelector>
</GetSellerListRequest>"""

        return self._make_trading_api_request("GetSellerList", request_xml)

    def get_member_messages(
        self,
        item_id: Optional[str] = None,
        sender_id: Optional[str] = None,
        message_status: Optional[str] = None,
        start_creation_time: Optional[str] = None,
        end_creation_time: Optional[str] = None,
        entries_per_page: int = 100,
        page_number: int = 1,
    ) -> str:
        """
        Get member messages (buyer questions) using Trading API GetMemberMessages.

        Args:
            item_id: Filter by item ID
            sender_id: Filter by sender user ID
            message_status: Filter by status (Answered or Unanswered)
            start_creation_time: Start date/time in ISO format
            end_creation_time: End date/time in ISO format
            entries_per_page: Number of messages per page (max 200)
            page_number: Page number to retrieve

        Returns:
            XML response as string
        """
        # Build optional filters
        filters = []
        if item_id:
            filters.append(f"    <ItemID>{item_id}</ItemID>")
        if sender_id:
            filters.append(f"    <SenderID>{sender_id}</SenderID>")
        if message_status:
            filters.append(f"    <MessageStatus>{message_status}</MessageStatus>")
        if start_creation_time:
            filters.append(f"    <StartCreationTime>{start_creation_time}</StartCreationTime>")
        if end_creation_time:
            filters.append(f"    <EndCreationTime>{end_creation_time}</EndCreationTime>")

        filters_xml = "\n".join(filters)

        request_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<GetMemberMessagesRequest xmlns="urn:ebay:apis:eBLBaseComponents">
    <DetailLevel>ReturnMessages</DetailLevel>
    <MailMessageType>All</MailMessageType>
{filters_xml}
    <Pagination>
        <EntriesPerPage>{min(entries_per_page, 200)}</EntriesPerPage>
        <PageNumber>{page_number}</PageNumber>
    </Pagination>
</GetMemberMessagesRequest>"""

        return self._make_trading_api_request("GetMemberMessages", request_xml)

    def get_my_messages_headers(
        self,
        folder_id: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> str:
        """
        Get messages headers using Trading API GetMyMessages with ReturnHeaders.
        Returns message IDs and basic info without full message content.

        Args:
            folder_id: Filter by folder ID (0 = Inbox)
            start_time: Start date/time in ISO format
            end_time: End date/time in ISO format

        Returns:
            XML response as string
        """
        # Build optional filters
        filters = []
        if folder_id:
            filters.append(f"    <FolderID>{folder_id}</FolderID>")
        if start_time:
            filters.append(f"    <StartCreationTime>{start_time}</StartCreationTime>")
        if end_time:
            filters.append(f"    <EndCreationTime>{end_time}</EndCreationTime>")

        filters_xml = "\n".join(filters)

        request_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<GetMyMessagesRequest xmlns="urn:ebay:apis:eBLBaseComponents">
    <DetailLevel>ReturnHeaders</DetailLevel>
{filters_xml}
</GetMyMessagesRequest>"""

        return self._make_trading_api_request("GetMyMessages", request_xml)

    def get_my_messages(
        self,
        message_ids: Optional[list[str]] = None,
        folder_id: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        detail_level: str = "ReturnMessages",
        entries_per_page: int = 25,
        page_number: int = 1,
    ) -> str:
        """
        Get specific messages by ID using Trading API GetMyMessages.

        Args:
            message_ids: List of message IDs to retrieve (max 10)
            folder_id: Filter by folder ID
            start_time: Start date/time in ISO format
            end_time: End date/time in ISO format
            detail_level: Detail level (default: ReturnMessages)
            entries_per_page: Number of messages per page (max 25)
            page_number: Page number to retrieve

        Returns:
            XML response as string
        """
        # Build optional filters
        filters = []
        if message_ids:
            # MessageIDs is a container with child MessageID elements
            message_id_elements = []
            for msg_id in message_ids[:10]:  # Max 10 IDs
                message_id_elements.append(f"        <MessageID>{msg_id}</MessageID>")
            filters.append(f"    <MessageIDs>\n" + "\n".join(message_id_elements) + "\n    </MessageIDs>")
        else:
            # If no message IDs specified, use StartCreationTime/EndCreationTime instead
            if start_time:
                filters.append(f"    <StartCreationTime>{start_time}</StartCreationTime>")
            if end_time:
                filters.append(f"    <EndCreationTime>{end_time}</EndCreationTime>")

        if folder_id:
            filters.append(f"    <FolderID>{folder_id}</FolderID>")

        filters_xml = "\n".join(filters)

        request_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<GetMyMessagesRequest xmlns="urn:ebay:apis:eBLBaseComponents">
    <DetailLevel>{detail_level}</DetailLevel>
{filters_xml}
    <Pagination>
        <EntriesPerPage>{min(entries_per_page, 25)}</EntriesPerPage>
        <PageNumber>{page_number}</PageNumber>
    </Pagination>
</GetMyMessagesRequest>"""

        return self._make_trading_api_request("GetMyMessages", request_xml)

    def add_member_message_reply(
        self,
        parent_message_id: str,
        recipient_id: str,
        body: str,
        item_id: Optional[str] = None,
        display_to_public: bool = False,
        email_copy_to_sender: bool = False,
    ) -> str:
        """
        Reply to a buyer question using Trading API AddMemberMessageRTQ.

        Args:
            parent_message_id: The message ID being replied to
            recipient_id: The recipient's user ID
            body: The reply body text (max 2000 characters, HTML stripped)
            item_id: Optional item ID
            display_to_public: Whether to display the reply publicly
            email_copy_to_sender: Whether to send email copy to seller

        Returns:
            XML response as string

        Raises:
            ClientError: If body exceeds 2000 characters
        """
        # Validate body length
        if len(body) > 2000:
            raise ClientError("Message body must be 2000 characters or less")

        # Build optional elements
        optional_elements = []
        if item_id:
            optional_elements.append(f"    <ItemID>{item_id}</ItemID>")

        optional_xml = "\n".join(optional_elements)

        # Escape body for CDATA (replace ]]> with ]]]]><![CDATA[>)
        escaped_body = body.replace("]]>", "]]]]><![CDATA[>")

        request_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<AddMemberMessageRTQRequest xmlns="urn:ebay:apis:eBLBaseComponents">
{optional_xml}
    <MemberMessage>
        <Body><![CDATA[{escaped_body}]]></Body>
        <DisplayToPublic>{str(display_to_public).lower()}</DisplayToPublic>
        <EmailCopyToSender>{str(email_copy_to_sender).lower()}</EmailCopyToSender>
        <ParentMessageID>{parent_message_id}</ParentMessageID>
        <RecipientID>{recipient_id}</RecipientID>
    </MemberMessage>
</AddMemberMessageRTQRequest>"""

        return self._make_trading_api_request("AddMemberMessageRTQ", request_xml)


# Module-level client instances - keyed by profile
_clients: Dict[str, EbayClient] = {}


def get_client(profile: Optional[str] = None) -> EbayClient:
    """Get or create the eBay client instance for the given profile."""
    global _clients
    key = profile or "_default"
    if key not in _clients:
        _clients[key] = EbayClient(profile=profile)
    return _clients[key]


def reset_client():
    """Reset all client instances (for testing)."""
    global _clients
    _clients = {}
