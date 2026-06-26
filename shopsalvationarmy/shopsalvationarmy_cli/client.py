"""ShopSalvationArmy service client."""
import re
import urllib.parse
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from .config import get_config


class ClientError(Exception):
    """Custom exception for client errors."""
    pass


class ShopSalvationArmyClient:
    """Client for Shop Salvation Army official auction site."""

    BASE_URL = "https://www.shopthesalvationarmy.com"
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    # Categories available on the site
    CATEGORIES = {
        "art": "C160710",
        "books": "C160714",
        "business": "C160715",
        "cameras": "C1939715",
        "clothing": "C160719",
        "collectibles": "C160722",
        "crafts": "C465653829",
        "entertainment": "C160741",
        "health": "C160728",
        "holiday": "C19676360",
        "home": "C160729",
        "jewelry": "C160730",
        "music": "C160733",
        "sports": "C160738",
        "toys": "C160742",
    }

    def __init__(self, require_auth: bool = False, config=None):
        self.config = config if config is not None else get_config()
        self.session = requests.Session()
        self.session.headers["User-Agent"] = self.USER_AGENT

        if require_auth:
            missing = self.config.get_missing_credentials()
            if missing:
                raise ClientError(f"Missing credentials: {', '.join(missing)}")

    def login(self, username: str, password: str) -> Dict:
        """
        Authenticate with Shop Salvation Army using form-based login.

        Args:
            username: Username/email
            password: Password

        Returns:
            Dict with authentication status

        Raises:
            ClientError: If authentication fails
        """
        login_url = f"{self.BASE_URL}/Account/LogOn"

        # Prepare form data
        form_data = {
            "username": username,
            "password": password,
            "rememberMe": "true",
        }

        try:
            # First GET the login page to establish session cookies
            self.session.get(login_url)

            # POST the login form
            response = self.session.post(login_url, data=form_data, allow_redirects=True)
            response.raise_for_status()

            # Check if we got redirected away from the login page (success indicator)
            if "/Account/LogOn" not in response.url:
                # Successfully redirected away from login page
                return {
                    "authenticated": True,
                    "username": username,
                    "message": "Successfully authenticated",
                }

            # Still on login page - check for error messages
            soup = BeautifulSoup(response.text, "html.parser")

            # Look for validation errors
            error_elem = soup.find(class_="field-validation-error")
            if error_elem:
                error_msg = error_elem.get_text(strip=True)
                raise ClientError(f"Login failed: {error_msg}")

            # Look for general error messages
            error_elem = soup.find(class_=re.compile(r"error|validation", re.IGNORECASE))
            if error_elem:
                error_msg = error_elem.get_text(strip=True)
                raise ClientError(f"Login failed: {error_msg}")

            # No specific error found but still on login page
            raise ClientError("Login failed: Invalid username or password")

        except requests.RequestException as e:
            raise ClientError(f"Login request failed: {e}")

    def search(
        self,
        query: str = "",
        category: Optional[str] = None,
        page: int = 1,
        sort: str = "ending",
        listing_type: Optional[str] = None,
        status: str = "active",
        price_min: Optional[float] = None,
        price_max: Optional[float] = None,
    ) -> Dict:
        """
        Search Shop The Salvation Army listings.

        Args:
            query: Search keywords (optional)
            category: Category name or ID (optional)
            page: Page number (starts at 0 for the API, but we use 1-based)
            sort: Sort option (ending, newest, oldest, price_low, price_high)
            listing_type: Filter by type (auction, fixed_price)
            status: Listing status (active, completed, any)
            price_min: Minimum price filter
            price_max: Maximum price filter

        Returns:
            Dict with items and metadata
        """
        # Build search URL
        params = {
            "ViewStyle": "grid",
            "StatusFilter": self._get_status_filter(status),
            "SortFilterOptions": self._get_sort_param(sort),
            "page": page - 1,  # API uses 0-based pagination
        }

        # Add category if specified
        if category:
            category_id = self.CATEGORIES.get(category.lower(), category)
            url = f"{self.BASE_URL}/Browse/{category_id}"
        else:
            url = f"{self.BASE_URL}/Browse"

        # Add query parameter if searching
        if query:
            params["Keywords"] = query

        # Add listing type filter
        if listing_type:
            if listing_type.lower() == "auction":
                params["ListingType"] = "auction"
            elif listing_type.lower() == "fixed_price":
                params["ListingType"] = "fixed"

        # Add price filters
        if price_min is not None:
            params["PriceLow"] = price_min
        if price_max is not None:
            params["PriceHigh"] = price_max

        full_url = f"{url}?{urllib.parse.urlencode(params)}"

        try:
            response = self.session.get(full_url)
            response.raise_for_status()
        except requests.RequestException as e:
            raise ClientError(f"Failed to search: {e}")

        # Parse the HTML response
        soup = BeautifulSoup(response.text, "html.parser")
        items = self._parse_search_results(soup)

        return {
            "items": items,
            "page": page,
            "query": query,
            "category": category,
            "url": full_url,
        }

    def get_item(self, item_id: str) -> Dict:
        """
        Get detailed information for a specific item.

        Args:
            item_id: The item listing ID

        Returns:
            Dict with item details
        """
        url = f"{self.BASE_URL}/Listing/Details/{item_id}"

        try:
            response = self.session.get(url)
            response.raise_for_status()
        except requests.RequestException as e:
            raise ClientError(f"Failed to get item {item_id}: {e}")

        # Parse the HTML response
        soup = BeautifulSoup(response.text, "html.parser")
        item_data = self._parse_item_page(soup, item_id)

        return item_data

    def list_categories(self) -> List[Dict]:
        """
        List all available categories.

        Returns:
            List of category dicts with name and id
        """
        categories = []
        for name, cat_id in self.CATEGORIES.items():
            categories.append({
                "name": name,
                "id": cat_id,
            })
        return categories

    def _get_sort_param(self, sort: str) -> str:
        """Convert sort option to site sort parameter."""
        sort_map = {
            "ending": "0",      # Ending soonest
            "newest": "1",      # Newest listings
            "oldest": "2",      # Oldest listings
            "price_low": "3",   # Price: lowest first
            "price_high": "4",  # Price: highest first
            "title_az": "5",    # Title A-Z
            "title_za": "6",    # Title Z-A
            "id_low": "7",      # Listing ID: low to high
            "id_high": "8",     # Listing ID: high to low
            "activity": "9",    # Activity: highest
        }
        return sort_map.get(sort, "0")

    def _get_status_filter(self, status: str) -> str:
        """Convert status option to site status filter."""
        status_map = {
            "active": "active_only",
            "completed": "completed_only",
            "any": "all",
        }
        return status_map.get(status, "active_only")

    def _parse_search_results(self, soup: BeautifulSoup) -> List[Dict]:
        """Parse Shop The Salvation Army search results page."""
        items = []

        # Look for all links to /Listing/Details/
        detail_links = soup.find_all("a", href=re.compile(r"/Listing/Details/\d+"))

        # Track seen IDs to avoid duplicates
        seen_ids = set()

        for link in detail_links:
            try:
                # Extract item ID from URL
                href = link.get("href", "")
                item_id = self._extract_item_id_from_url(href)
                if not item_id:
                    continue

                # Get the link text which may contain title and bid info
                link_text = link.get_text(strip=True)

                # Try to get the title from an h2 within this link
                title = ""
                h2 = link.find("h2")
                if h2:
                    title = h2.get_text(strip=True)
                elif link_text:
                    # Extract title from link text
                    # Remove bid info at the start: "15Bid(s)"
                    title = re.sub(r'^\d+Bid\(s\)\s*', '', link_text)
                    title = title.strip()

                # Skip if no title (probably an image link)
                if not title:
                    continue

                # Skip if we've already processed this item
                if item_id in seen_ids:
                    continue

                seen_ids.add(item_id)

                # Try to find the parent container that has all the item info
                # This could be several levels up
                container = link
                for _ in range(5):  # Go up max 5 levels
                    container = container.find_parent()
                    if not container:
                        break

                if not container:
                    continue

                # Extract price - look for dollar amounts
                price = "N/A"
                # Try to find current bid or buy now price
                price_matches = container.find_all(string=re.compile(r"\$[\d,]+\.?\d*"))
                if price_matches:
                    # Get the first price found
                    for price_match in price_matches:
                        price_str = price_match.strip()
                        if '$' in price_str:
                            price = price_str
                            break

                # Extract bids if present
                bids = None
                bids_match = container.find(string=re.compile(r"\d+Bid\(s\)"))
                if bids_match:
                    bids = bids_match.strip()

                # Extract time remaining if present
                time_left = None
                time_match = container.find(string=re.compile(r"\d+\s+Days?\s+\d+:\d+:\d+"))
                if time_match:
                    time_left = time_match.strip()

                items.append({
                    "id": item_id,
                    "title": title,
                    "price": price,
                    "bids": bids,
                    "time_left": time_left,
                    "url": f"{self.BASE_URL}{href}",
                })

            except Exception:
                # Skip items that fail to parse
                continue

        return items

    def _parse_item_page(self, soup: BeautifulSoup, item_id: str) -> Dict:
        """Parse Shop The Salvation Army item detail page."""
        try:
            from datetime import datetime

            # Extract title - usually in h1 or h2
            title = "N/A"
            title_elem = soup.find("h1")
            if not title_elem:
                title_elem = soup.find("h2")
            if title_elem:
                title = title_elem.get_text(strip=True)

            # Detect auction status from closed banner or "Ended" label
            closed_msg = soup.find(class_="awe-rt-ListingClosedMessage")
            ended_label = soup.find(class_="label-default")
            if closed_msg or (ended_label and "ended" in ended_label.get_text(strip=True).lower()):
                auction_status = "ended"
            else:
                auction_status = "active"

            # Extract auction end date from data attribute on the ending DTTM span
            auction_end_date = None
            end_date_elem = soup.find(class_="awe-rt-endingDTTM")
            if end_date_elem and end_date_elem.get("data-initial-dttm"):
                raw_date = end_date_elem["data-initial-dttm"]
                try:
                    dt = datetime.strptime(raw_date, "%m/%d/%Y %H:%M:%S")
                    auction_end_date = dt.strftime("%Y-%m-%dT%H:%M:%S")
                except ValueError:
                    auction_end_date = raw_date

            # Extract winning bid (ended auctions) or current bid (active auctions)
            winning_bid = None
            current_price = None
            for li in soup.find_all("li", class_="list-group-item"):
                text = li.get_text(strip=True)
                if "Winning Bid:" in text:
                    m = re.search(r"\$(\d+(?:,\d{3})*(?:\.\d{2})?)", text)
                    if m:
                        winning_bid = float(m.group(1).replace(",", ""))
                        current_price = winning_bid
                    break

            if current_price is None:
                price_elem = soup.find(string=re.compile(r"Current Bid|Buy Now|Price"))
                if price_elem:
                    parent = price_elem.find_parent()
                    if parent:
                        price_text = parent.find(string=re.compile(r"\$[\d,]+\.?\d*"))
                        if price_text:
                            m = re.search(r"\$(\d+(?:,\d{3})*(?:\.\d{2})?)", price_text.strip())
                            if m:
                                current_price = float(m.group(1).replace(",", ""))

            # Extract buy-it-now price from JS variable
            buy_it_now_price = None
            for script in soup.find_all("script"):
                script_text = script.get_text()
                bin_match = re.search(r"buyNowPriceForJS\s*=\s*['\"]([^'\"]+)['\"]", script_text)
                if bin_match:
                    bin_str = bin_match.group(1).strip()
                    if bin_str:
                        try:
                            buy_it_now_price = float(bin_str.replace(",", ""))
                        except ValueError:
                            pass
                    break

            # Extract bids
            bids = None
            bids_elem = soup.find(string=re.compile(r"\d+\s*Bid\(s\)"))
            if bids_elem:
                bids = bids_elem.strip()

            # Extract time remaining (only meaningful for active auctions)
            time_left = None
            if auction_status == "active":
                time_elem = soup.find(string=re.compile(r"Time Remaining"))
                if time_elem:
                    parent = time_elem.find_parent()
                    if parent:
                        time_text = parent.find(string=re.compile(r"\d+\s+Days?\s+\d+:\d+:\d+"))
                        if time_text:
                            time_left = time_text.strip()

            # Extract condition/description
            description = ""
            desc_elem = soup.find("div", class_=lambda x: x and "description" in x.lower() if x else False)
            if desc_elem:
                description = desc_elem.get_text(strip=True)[:500]

            return {
                "id": item_id,
                "title": title,
                "current_price": current_price,
                "winning_bid": winning_bid,
                "buy_it_now_price": buy_it_now_price,
                "auction_status": auction_status,
                "auction_end_date": auction_end_date,
                "bids": bids,
                "time_left": time_left,
                "description": description,
                "url": f"{self.BASE_URL}/Listing/Details/{item_id}",
            }

        except Exception as e:
            raise ClientError(f"Failed to parse item page: {e}")

    def _extract_item_id_from_url(self, url: str) -> str:
        """Extract item ID from listing URL."""
        match = re.search(r"/Listing/Details/(\d+)", url)
        if match:
            return match.group(1)
        # Also try just finding any number in the URL
        match = re.search(r"/(\d+)", url)
        if match:
            return match.group(1)
        return ""


_client: Optional[ShopSalvationArmyClient] = None


def get_client(require_auth: bool = False) -> ShopSalvationArmyClient:
    """Get or create the global client instance."""
    global _client
    if _client is None:
        _client = ShopSalvationArmyClient(require_auth=require_auth)
    return _client
