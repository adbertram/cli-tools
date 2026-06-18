"""ShopGoodwill service client."""
import base64
import re
import urllib.parse
from typing import Dict, List, Optional

import requests
from Cryptodome.Cipher import AES
from Cryptodome.Util.Padding import pad

from .config import get_config


class ClientError(Exception):
    """Custom exception for client errors."""
    pass


class ShopGoodwillClient:
    """Client for ShopGoodwill API."""

    LOGIN_PAGE_URL = "https://shopgoodwill.com/signin"
    API_ROOT = "https://buyerapi.shopgoodwill.com/api"
    ENCRYPTION_INFO = {
        "key": b"6696D2E6F042FEC4D6E3F32AD541143B",
        "iv": b"0000000000000000",
        "block_size": 16,
    }
    INVALID_AUTH_MESSAGE = "The username or password are incorrect"
    SHIPPING_DESTINATION_ZIP = "47725"
    SHIPPING_DESTINATION_COUNTRY = "US"
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    def __init__(self, require_auth: bool = True, config=None):
        self.config = config if config is not None else get_config()
        self.session = requests.Session()
        self.session.headers["User-Agent"] = self.USER_AGENT

        if require_auth:
            missing = self.config.get_missing_credentials()
            if missing:
                raise ClientError(f"Missing credentials: {', '.join(missing)}")

    def _encrypt_value(self, plaintext: str) -> str:
        """
        Encrypt a value using ShopGoodwill's AES-CBC encryption.
        Returns base64-encoded, URL-encoded ciphertext.
        """
        padded = pad(plaintext.encode(), self.ENCRYPTION_INFO["block_size"])
        cipher = AES.new(
            self.ENCRYPTION_INFO["key"],
            AES.MODE_CBC,
            self.ENCRYPTION_INFO["iv"],
        )
        ciphertext = cipher.encrypt(padded)
        return urllib.parse.quote(base64.b64encode(ciphertext).decode())

    def login(self, username: str, password: str) -> Dict:
        """
        Authenticate with ShopGoodwill and return tokens.

        Args:
            username: Plaintext username/email
            password: Plaintext password

        Returns:
            Dict with accessToken and other auth info

        Raises:
            ClientError: If authentication fails
        """
        # First visit login page to get cookies
        self.session.get(self.LOGIN_PAGE_URL)

        # Encrypt credentials
        encrypted_username = self._encrypt_value(username)
        encrypted_password = self._encrypt_value(password)

        login_params = {
            "userName": encrypted_username,
            "password": encrypted_password,
            "remember": False,
            "appVersion": "00099a1be3bb023ff17d",
            "clientIpAddress": "0.0.0.4",
            "browser": "chrome",
        }

        response = self.session.post(
            f"{self.API_ROOT}/SignIn/Login",
            json=login_params,
        )

        if response.status_code != 200:
            raise ClientError(f"Login request failed with status {response.status_code}")

        result = response.json()

        if result.get("message") == self.INVALID_AUTH_MESSAGE:
            raise ClientError("Invalid username or password")

        if not result.get("accessToken"):
            raise ClientError(f"Login failed: {result.get('message', 'Unknown error')}")

        return result

    def validate_token(self, access_token: str) -> bool:
        """
        Test if an access token is valid by making an authenticated request.

        Args:
            access_token: The JWT access token to validate

        Returns:
            True if token is valid, False otherwise
        """
        headers = {"Authorization": f"Bearer {access_token}"}

        try:
            response = self.session.post(
                f"{self.API_ROOT}/SaveSearches/GetSaveSearches",
                headers=headers,
            )
            return response.status_code == 200
        except requests.RequestException:
            return False

    def search(
        self,
        query: str,
        page: int = 1,
        page_size: int = 40,
        category_id: int = 0,
        category_level: int = 0,
        low_price: Optional[float] = None,
        high_price: Optional[float] = None,
        sort_by: str = "EndingSoonest",
        sort_order: str = "a",
        closed_auctions: bool = False,
        buy_now_only: bool = False,
        pickup_only: bool = False,
        shipping_only: bool = False,
    ) -> Dict:
        """
        Search for items on ShopGoodwill.

        Args:
            query: Search text
            page: Page number (starts at 1)
            page_size: Number of results per page (max 40)
            category_id: Category ID to filter by (0 = all)
            category_level: Category level for filtering
            low_price: Minimum price filter
            high_price: Maximum price filter
            sort_by: Sort field (EndingSoonest, BidCount, Price, etc.)
            sort_order: Sort order ('a' = ascending, 'd' = descending)
            closed_auctions: Include closed auctions
            buy_now_only: Only show buy-now items
            pickup_only: Only show pickup items
            shipping_only: Only show items that ship

        Returns:
            Dict with searchResults containing items and metadata
        """
        search_params = {
            "searchText": query,
            "page": page,
            "pageSize": min(page_size, 40),
            "sortColumn": sort_by,
            "sortOrder": sort_order,
            "categoryId": category_id,
            "categoryLevel": category_level,
            "lowPrice": low_price if low_price is not None else 0,
            "highPrice": high_price if high_price is not None else 999999,
            "closedAuctionDays": 1 if closed_auctions else 0,
            "searchBuyNowOnly": buy_now_only,
            "searchPickupOnly": pickup_only,
            "searchNoPickupOnly": shipping_only,
            "searchOneCentShippingOnly": False,
            "searchDescriptions": False,
            "searchClosedAuctions": closed_auctions,
            "selectedCategoryIds": str(category_id) if category_id > 0 else "",
            "useBuyerPrefs": False,
            "savedSearchId": 0,
            "partNumber": "",
        }

        response = self.session.post(
            f"{self.API_ROOT}/Search/ItemListing",
            json=search_params,
        )

        if response.status_code != 200:
            raise ClientError(f"Search failed with status {response.status_code}")

        result = response.json()

        if not result.get("searchResults"):
            raise ClientError("Search returned no results structure")

        return result

    def get_item(self, item_id: int) -> Dict:
        """
        Get detailed information for a specific item.

        Args:
            item_id: The item ID

        Returns:
            Dict with item details
        """
        response = self.session.get(
            f"{self.API_ROOT}/itemDetail/GetItemDetailModelByItemId/{item_id}"
        )

        if response.status_code != 200:
            raise ClientError(f"Failed to get item {item_id}: status {response.status_code}")

        return response.json()

    def calculate_shipping(self, item: Dict) -> Dict:
        """
        Calculate destination-specific shipping for an item.

        ShopGoodwill returns this estimate as an HTML fragment.
        """
        shipping_params = {
            "itemId": item.get("itemId"),
            "sellerId": item.get("sellerId"),
            "zipCode": self.SHIPPING_DESTINATION_ZIP,
            "country": self.SHIPPING_DESTINATION_COUNTRY,
            "packageWeight": item.get("displayWeight"),
            "quantity": 1,
        }

        response = self.session.post(
            f"{self.API_ROOT}/ItemDetail/CalculateShipping",
            json=shipping_params,
        )

        if response.status_code != 200:
            raise ClientError(
                f"Failed to calculate shipping for item {item.get('itemId')}: "
                f"status {response.status_code}"
            )

        return self._parse_shipping_estimate(response.text)

    def _parse_shipping_estimate(self, html: str) -> Dict:
        shipping_match = re.search(r"Shipping:.*?\$([0-9]+(?:\.[0-9]{2})?)", html, re.DOTALL)
        service_match = re.search(r"Shipping:.*?\$[0-9]+(?:\.[0-9]{2})? \(([^)]+)\)", html, re.DOTALL)
        handling_match = re.search(r"Handling:\s*\$([0-9]+(?:\.[0-9]{2})?)", html)
        total_match = re.search(r"Total Shipping and Handling:\s*\$([0-9]+(?:\.[0-9]{2})?)", html)

        if not shipping_match or not handling_match or not total_match:
            raise ClientError(f"Shipping calculation failed: {html}")

        return {
            "destinationZip": self.SHIPPING_DESTINATION_ZIP,
            "country": self.SHIPPING_DESTINATION_COUNTRY,
            "shippingPrice": float(shipping_match.group(1)),
            "handlingPrice": float(handling_match.group(1)),
            "total": float(total_match.group(1)),
            "serviceDescription": service_match.group(1) if service_match else "",
        }


_client: Optional[ShopGoodwillClient] = None


def get_client(require_auth: bool = True) -> ShopGoodwillClient:
    """Get or create the global client instance."""
    global _client
    if _client is None:
        _client = ShopGoodwillClient(require_auth=require_auth)
    return _client
