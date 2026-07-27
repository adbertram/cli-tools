"""ShopSalvationArmy service client."""
import json
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

    # Canonical, direction-aware sort vocabulary (Source-CLI Sort Standard),
    # keyed by (field, descending) and mapped to the site's SortFilterOptions
    # code. The natural direction is the desc=False entry; --desc selects the
    # reversed entry:
    #   newest  natural -> newest listings first (code 1); --desc -> oldest (2)
    #   price   natural -> low to high (code 3);            --desc -> high to low (4)
    #   ending  natural -> ending soonest first (code 0);   --desc -> unsupported
    # The site also defines codes 5-9 (title A-Z / Z-A, listing id low/high,
    # activity) but those are intentionally NOT exposed on the CLI sort surface.
    SORT_CODES = {
        ("newest", False): "1",
        ("newest", True): "2",
        ("price", False): "3",
        ("price", True): "4",
        ("ending", False): "0",
    }
    VALID_SORTS = ("newest", "price", "ending")

    # The listing's fulfillment panel and the one row label that is fixed
    # site-side; every other row label is seller-chosen.
    SHIPPING_PANEL_HEADING = "Shipping Options"
    LOCAL_PICKUP_LABEL = "Local Pick Up"

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
        sort: str = "newest",
        desc: bool = False,
        listing_type: Optional[str] = None,
        status: str = "active",
        price_min: Optional[float] = None,
        price_max: Optional[float] = None,
        limit: Optional[int] = None,
    ) -> Dict:
        """
        Search Shop The Salvation Army listings.

        Args:
            query: Search keywords (optional)
            category: Category name or ID (optional)
            page: Page number (starts at 0 for the API, but we use 1-based)
            sort: Canonical sort field (newest, price, ending); default newest
            desc: Reverse the sort field's natural direction
            listing_type: Filter by type (auction, fixed_price)
            status: Listing status (active, completed, any)
            price_min: Minimum price filter
            price_max: Maximum price filter
            limit: Maximum number of items to return from this page

        Returns:
            Dict with items and metadata

        Raises:
            ClientError: If ``sort``/``desc`` is not a valid canonical combination
        """
        # Build search URL
        params = {
            "ViewStyle": "grid",
            "StatusFilter": self._get_status_filter(status),
            "SortFilterOptions": self._get_sort_param(sort, desc),
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
            params["FullTextQuery"] = query

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
        if limit is not None:
            items = items[:limit]

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

    def calculate_shipping(
        self,
        item_id: str,
        zip_code: str,
        state: str,
        city: str,
        country: str = "US",
        carrier: str = "usps",
        shipping_params: Optional[Dict] = None,
    ) -> List[Dict]:
        """Calculate live shipping rates for an item."""
        if not shipping_params:
            raise ClientError(f"Item {item_id} does not expose shipping parameters")

        payload = {
            "carrier": carrier,
            "weight": shipping_params["weight"],
            "length": shipping_params["length"],
            "width": shipping_params["width"],
            "height": shipping_params["height"],
            "fromPostalCode": shipping_params["from_postal_code"],
            "toState": state,
            "toCountry": country,
            "toPostalCode": zip_code,
            "toCity": city,
            "listingId": shipping_params.get("listing_id", item_id),
        }
        try:
            response = self.session.post(
                f"{self.BASE_URL}/RealTime/GetLiveRates",
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
        except requests.RequestException as e:
            raise ClientError(f"Failed to calculate shipping for item {item_id}: {e}")

        raw = response.text
        try:
            data = json.loads(raw)
            if isinstance(data, str):
                data = json.loads(data)
        except json.JSONDecodeError as e:
            raise ClientError(f"Shipping response was not valid JSON for item {item_id}: {e}")
        if not isinstance(data, list):
            raise ClientError(f"Shipping response had unexpected shape for item {item_id}")
        return data

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

    def _get_sort_param(self, sort: str, desc: bool = False) -> str:
        """Resolve a canonical sort field (+ optional --desc) to the site sort code.

        Fail-fast: unknown fields and unsupported field/direction combinations
        raise a clear error instead of silently falling back to a default.

        Raises:
            ClientError: If ``sort`` is not in the canonical vocabulary, or the
                field/direction combination has no site equivalent (e.g.
                ``ending --desc``).
        """
        key = sort.lower()
        if key not in self.VALID_SORTS:
            valid = ", ".join(self.VALID_SORTS)
            raise ClientError(f"Invalid --sort '{sort}'. Valid values: {valid}")
        code = self.SORT_CODES.get((key, desc))
        if code is None:
            raise ClientError(
                "Shop The Salvation Army has no 'latest ending' sort order; "
                "'--sort ending' cannot be combined with --desc. Use '--sort ending' "
                "for soonest-ending-first."
            )
        return code

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

    @staticmethod
    def _is_hidden(element) -> bool:
        """Return True when a server-rendered status element is hidden."""
        classes = element.get("class", [])
        return "awe-hidden" in classes or "hidden" in classes

    @staticmethod
    def _parse_money(text: str) -> Optional[float]:
        """Parse the first dollar amount from text."""
        match = re.search(r"\$(\d+(?:,\d{3})*(?:\.\d{2})?)", text)
        if not match:
            return None
        return float(match.group(1).replace(",", ""))

    def _parse_shipping_panel(self, soup: BeautifulSoup) -> Dict:
        """Parse the listing's "Shipping Options" panel.

        The panel is the seller's own statement of WHICH fulfillment options
        exist, and it is parsed independently of what each one costs and of
        whether a live carrier quote later succeeds. Three options appear:

            Local Pick Up:      $0.00                          -> local pickup
            Standard Shipping:  $46.00 ($46.00 as additional item) -> flat rate
            [Calculate USPS Shipping Rates]                    -> calculator

        Each label and its price sit either side of a ``</strong>``, so the row
        TEXT is matched, not the markup. The flat-rate label is seller-chosen
        and varies ("Standard Shipping:", "UPS Ground:"), so any labelled money
        row other than local pickup is read as the flat rate.
        """
        summary = {
            "local_pickup_price": None,
            "standard_shipping_label": None,
            "standard_shipping_price": None,
            "standard_shipping_additional_item_price": None,
            "carriers": [],
            "options": {
                "local_pickup": False,
                "flat_rate": False,
                "carrier_calculator": False,
            },
        }

        panel = None
        for heading in soup.find_all(class_="panel-heading"):
            if self.SHIPPING_PANEL_HEADING in heading.get_text(" ", strip=True):
                panel = heading.parent
                break
        if panel is None:
            return summary

        summary["carriers"] = [
            button["data-carrier"].strip().lower()
            for button in panel.select("a.ct[data-carrier]")
            if button["data-carrier"].strip()
        ]
        summary["options"]["carrier_calculator"] = bool(summary["carriers"])

        for row in panel.find_all("li", class_="list-group-item"):
            label_elem = row.find("strong")
            if not label_elem:
                continue
            label = label_elem.get_text(" ", strip=True).rstrip(":").strip()
            text = row.get_text(" ", strip=True)

            if label == self.LOCAL_PICKUP_LABEL:
                summary["options"]["local_pickup"] = True
                summary["local_pickup_price"] = self._parse_money(text)
                continue

            if summary["standard_shipping_label"] is not None:
                continue
            # The base price always precedes the "as additional item" note, so
            # the first dollar amount in the row is the flat rate itself.
            price = self._parse_money(text)
            if price is None:
                continue
            summary["options"]["flat_rate"] = True
            summary["standard_shipping_label"] = label
            summary["standard_shipping_price"] = price
            additional = re.search(
                r"\$(\d+(?:,\d{3})*(?:\.\d{2})?)\s+as additional item", text
            )
            if additional:
                summary["standard_shipping_additional_item_price"] = float(
                    additional.group(1).replace(",", "")
                )

        return summary

    def _parse_image_urls(self, soup: BeautifulSoup) -> List[str]:
        """Extract this listing's photo URLs from the image gallery.

        The per-listing gallery lives in the ``#AllImages`` section. Each photo is
        an anchor whose ``href`` points at the full-resolution ``_largesize`` image
        (the lightbox target); the anchor also wraps a ``_thumbcrop`` thumbnail.
        The anchor ``href`` is used so the returned URLs are full resolution and
        scoped to this listing only, excluding the site logo, tracking pixels,
        footer banner, and the unrelated "similar listings" gallery.
        """
        gallery = soup.find(id="AllImages")
        if gallery is None:
            return []

        image_urls: List[str] = []
        seen: set = set()
        for anchor in gallery.find_all("a", href=True):
            href = anchor["href"].strip()
            if not href:
                continue
            absolute = urllib.parse.urljoin(self.BASE_URL, href)
            if absolute in seen:
                continue
            seen.add(absolute)
            image_urls.append(absolute)
        return image_urls

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

            # Detect auction status from the visible detail status, not hidden templates.
            status_label = soup.select_one(".detail__status-label")
            status_text = status_label.get_text(" ", strip=True).lower() if status_label else ""
            closed_msg = soup.find(class_="awe-rt-ListingClosedMessage")
            visible_closed_msg = closed_msg is not None and not self._is_hidden(closed_msg)
            ended_statuses = ("ended", "closed", "successful", "unsuccessful")
            if visible_closed_msg or any(status in status_text for status in ended_statuses):
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
                    parsed = self._parse_money(text)
                    if parsed is not None:
                        winning_bid = parsed
                        current_price = winning_bid
                    break

            if current_price is None:
                price_container = soup.select_one(".awe-rt-CurrentPrice, .Bidding_Current_Price, .detail__price--current")
                if price_container:
                    current_price = self._parse_money(price_container.get_text("", strip=True))
            if current_price is None:
                for label in soup.find_all(string=re.compile(r"Current Bid|Buy Now|Price")):
                    parent = label.find_parent()
                    parsed = self._parse_money(parent.get_text(" ", strip=True) if parent else "")
                    if parsed is not None:
                        current_price = parsed
                        break

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

            # Extract condition/description. The full text is returned: listings
            # put their structured spec fields ("Brand:", "Model:", "Includes:",
            # "Condition:") at the end of the description, so truncating here
            # would drop the data consumers need. Display-side shortening belongs
            # to the --table renderer, not the parser.
            description = ""
            desc_elem = soup.find("div", class_=lambda x: x and "description" in x.lower() if x else False)
            if desc_elem:
                description = desc_elem.get_text(strip=True)

            shipping = self._parse_shipping_panel(soup)

            shipping_additional_charge = None
            for script in soup.find_all("script"):
                charge_match = re.search(r"\bac\s*=\s*parseFloat\(['\"]([^'\"]+)['\"]\)", script.get_text())
                if charge_match:
                    shipping_additional_charge = float(charge_match.group(1).replace(",", ""))
                    break

            # `shipping_params` is only the live-quote request payload. It is
            # deliberately NOT the evidence that shipping is offered: that lives
            # in `shipping_options` / `shipping_carriers`, which survive a
            # missing or failed quote.
            shipping_params = None
            required_shipping_fields = {
                "from_postal_code": "fromPostalCode",
                "weight": "weight",
                "length": "length",
                "width": "width",
                "height": "height",
                "listing_id": "listingId",
            }
            extracted_shipping_fields = {}
            for output_key, input_id in required_shipping_fields.items():
                field = soup.find("input", {"id": input_id})
                if field and field.get("value"):
                    extracted_shipping_fields[output_key] = field["value"]
            if shipping["carriers"] and set(required_shipping_fields) <= set(extracted_shipping_fields):
                shipping_params = extracted_shipping_fields

            if shipping_params:
                shipping_quote_status = "destination_required"
            elif shipping["options"]["carrier_calculator"]:
                # A calculator exists but this page did not carry the full quote
                # payload. The rate is unknown -- that is NOT the same as the
                # seller refusing to ship.
                shipping_quote_status = "unavailable"
            else:
                # No live-rate calculator on this listing at all. Flat-rate or
                # pickup-only listings land here.
                shipping_quote_status = "not_applicable"

            image_urls = self._parse_image_urls(soup)

            return {
                "id": item_id,
                "title": title,
                "image_urls": image_urls,
                "current_price": current_price,
                "winning_bid": winning_bid,
                "buy_it_now_price": buy_it_now_price,
                "auction_status": auction_status,
                "auction_end_date": auction_end_date,
                "bids": bids,
                "time_left": time_left,
                "description": description,
                "shipping_options": shipping["options"],
                "local_pickup_price": shipping["local_pickup_price"],
                "standard_shipping_label": shipping["standard_shipping_label"],
                "standard_shipping_price": shipping["standard_shipping_price"],
                "standard_shipping_additional_item_price": shipping["standard_shipping_additional_item_price"],
                "shipping_carriers": shipping["carriers"],
                "shipping_additional_charge": shipping_additional_charge,
                "shipping_quote_status": shipping_quote_status,
                "shipping_cost": None,
                "handling_cost": None,
                "shipping_total": None,
                "shipping_price": None,
                "total_price": None,
                "shipping_params": shipping_params,
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
