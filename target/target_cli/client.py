"""Target client using BrowserAutomation from cli_tools_shared."""

from typing import List, Optional

from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from .browser import TargetBrowser
from .config import get_config
from .parsers import normalize_item_detail, normalize_items


class TargetClient:
    """Client that uses BrowserAutomation to drive Target."""

    def __init__(self):
        self.config = get_config()
        self._browser: Optional[TargetBrowser] = None

    def _get_browser(self) -> TargetBrowser:
        if self._browser is None:
            self._browser = self.config.get_browser()
        return self._browser

    def close(self):
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    @cached
    def search(self, query: str, limit: int = 100) -> List[dict]:
        """Search for items on Target."""
        url = f"https://www.target.com/s?searchTerm={query.replace(' ', '+')}"
        results = []
        page = self._get_browser().get_page(url)
        try:
            page.wait_for_selector('div[data-test="product-grid"]', timeout=15000)
        except Exception:
            pass

        for _ in range(5):
            page.evaluate("() => window.scrollBy(0, 1000)")
            page.wait_for_timeout(500)

        elements = page.locator('[data-test="product-details"]').all()
        for el in elements[:limit]:
            title_el = el.locator('a[data-test="@web/ProductCard/title"]')
            price_el = el.locator('span[data-test="current-price"]')
            if title_el.count() > 0:
                title = title_el.inner_text().strip()
                href = title_el.get_attribute("href") or ""
                url_full = f"https://www.target.com{href}" if href.startswith('/') else href
                tcin = href.split('/A-')[-1].split('?')[0] if '/A-' in href else ""
                price = price_el.inner_text().strip() if price_el.count() > 0 else "Unknown"
                results.append({
                    "id": tcin,
                    "title": title,
                    "price": price,
                    "url": url_full
                })
        return results

    @cached
    def get_item(self, item_id: str) -> dict:
        """Get details for a specific item."""
        url = f"https://www.target.com/p/-/A-{item_id}"
        page = self._get_browser().get_page(url)
        page.wait_for_selector('h1[data-test="product-title"]', timeout=15000)
        title = page.locator('h1[data-test="product-title"]').inner_text().strip()
        price_el = page.locator('span[data-test="product-price"]')
        price = price_el.inner_text().strip() if price_el.count() > 0 else "Unknown"

        return {
            "id": item_id,
            "title": title,
            "price": price,
            "url": url
        }

    @cached
    def list_items(self, limit: int = 100) -> List[dict]:
        """List items from Target."""
        return []

    def get_cart(self) -> dict:
        """Get cart contents."""
        url = "https://www.target.com/cart"
        items = []
        page = self._get_browser().get_page(url)
        try:
            page.wait_for_selector('div[data-test="cartItem"]', timeout=10000)
            cart_items = page.locator('div[data-test="cartItem"]').all()
            for item in cart_items:
                title_el = item.locator('[data-test="cartItem-title"]')
                title = title_el.inner_text().strip() if title_el.count() > 0 else "Unknown"
                items.append({"title": title})
        except Exception:
            pass

        total_el = page.locator('[data-test="cart-summary-total"]')
        total = total_el.inner_text().strip() if total_el.count() > 0 else "$0.00"
            
        return {"items": items, "total": total}

    def add_to_cart(self, item_id: str) -> None:
        """Add item to cart."""
        url = f"https://www.target.com/p/-/A-{item_id}"
        page = self._get_browser().get_page(url)
        try:
            page.wait_for_selector(
                'button[data-test="shipItButton"]:not([disabled]), button[data-test="orderPickupButton"]:not([disabled]), button:has-text("Add to cart"):not([disabled])',
                timeout=15000
            )
        except Exception:
            pass

        ship_btn = page.locator('button[data-test="shipItButton"]:not([disabled])')
        if ship_btn.count() > 0 and ship_btn.is_visible():
            ship_btn.click()
        else:
            pickup_btn = page.locator('button[data-test="orderPickupButton"]:not([disabled])')
            if pickup_btn.count() > 0 and pickup_btn.is_visible():
                pickup_btn.click()
            else:
                add_btn = page.locator('button:has-text("Add to cart"):not([disabled])')
                if add_btn.count() > 0 and add_btn.is_visible():
                    add_btn.click()
                else:
                    raise ClientError("Could not find an active Add to Cart, Ship It, or Order Pickup button.")

        try:
            page.wait_for_selector('div[role="dialog"]:has-text("Added to cart")', timeout=15000)
        except Exception:
            try:
                page.wait_for_selector('text=Added to cart', timeout=15000)
            except Exception:
                raise ClientError("Timed out waiting for 'Added to cart' confirmation drawer.")

    def remove_from_cart(self, item_id: str) -> None:
        """Remove item from cart."""
        url = "https://www.target.com/cart"
        self._get_browser().get_page(url)
        raise NotImplementedError("Cart item removal needs exact DOM mapping")

    def checkout(self, delivery: str) -> str:
        """Proceed to checkout."""
        url = "https://www.target.com/checkout"
        page = self._get_browser().get_page(url)
        try:
            page.wait_for_selector('button[data-test="placeOrderButton"]', timeout=15000)
            return "Checkout page reached successfully. Ready to place order."
        except Exception:
            raise ClientError("Could not reach checkout place order button.")

    def set_store(self, zip_code: str) -> str:
        """Set the home store using a zip code or city/state."""
        url = "https://www.target.com/"
        page = self._get_browser().get_page(url)

        try:
            page.wait_for_selector('button[data-test="@web/StoreName/Button"]', timeout=10000)
            page.locator('button[data-test="@web/StoreName/Button"]').click()
        except Exception:
            try:
                page.wait_for_selector('button[id="web-store-id-msg-btn"]', timeout=10000)
                page.locator('button[id="web-store-id-msg-btn"]').click()
            except Exception:
                page.locator('button:has-text("My store")').click()

        page.wait_for_selector('input[id="zip-code-city-or-state"]', timeout=10000)
        search_input = page.locator('input[id="zip-code-city-or-state"]')

        search_input.fill(zip_code)

        try:
            page.locator('button:has-text("Look up")').click()
        except Exception:
            search_input.press("Enter")

        page.wait_for_selector('button[data-test="@web/StoreMenu/ShopThisStoreButton"]', timeout=15000)
        page.locator('button[data-test="@web/StoreMenu/ShopThisStoreButton"]').click()

        page.wait_for_timeout(3000)
        return f"Successfully set home store near {zip_code}."


_client: Optional[TargetClient] = None


def get_client() -> TargetClient:
    """Get or create the global Target client instance."""
    global _client
    if _client is None:
        _client = TargetClient()
    return _client
