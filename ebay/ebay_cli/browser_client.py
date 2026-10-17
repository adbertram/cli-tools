"""Browser-based eBay client for single-item detail.

Uses the shared stealth persistent-Chromium browser (``cli_tools_shared``) to
scrape the public ``/itm/<id>`` page, which the public Sell API does not expose:

* ``get_item`` — detail for a single active ``/itm/<id>`` page, parsed from
  the page's schema.org ``Product`` JSON-LD plus DOM supplements.
* ``get_item_status`` — availability for one ``/itm/<id>`` page without
  requiring shipping or local-pickup rows.

Marketplace SEARCH no longer lives here: it runs on the SoldComps API (see
``soldcomps_client.py``), which removed the browser session, the CAPTCHA and
interstitial walls, and the search-results markup dependency from that path.
``/itm/<id>`` pages are public, so item detail needs no session either.
"""
import re
from typing import Any, Optional
from urllib.parse import urlsplit

from .browser import BrowserError, EbayBrowser
from .config import get_config
from .models.item_detail import ItemDetail


# JavaScript to extract a single item's detail from its /itm/<id> page.
# Returns the raw schema.org JSON-LD blocks plus DOM supplements (bid count,
# time-left, quantity, seller) and page-state flags (ended/captcha).
ITEM_DETAIL_JS = """() => {
    const jsonld = [];
    for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
        try { jsonld.push(JSON.parse(s.textContent)); } catch (e) {}
    }
    const q = (sel) => {
        const el = document.querySelector(sel);
        return el ? el.textContent.replace(/\\s+/g, ' ').trim() : null;
    };
    const bodyText = document.body ? document.body.innerText : '';
    const low = bodyText.toLowerCase();
    return {
        jsonld,
        url: location.href,
        doc_title: document.title,
        dom_title: q('h1.x-item-title__mainTitle .ux-textspans')
            || q('.x-item-title__mainTitle')
            || q('h1 .ux-textspans'),
        price_primary: q('.x-price-primary .ux-textspans') || q('.x-price-primary'),
        bin_price: q('.x-bin-price__content .ux-textspans') || q('.x-bin-price__content'),
        bid_count: q('.x-bid-count .ux-textspans') || q('.x-bid-count'),
        time_left: q('.ux-timer__text') || q('.x-timeleft .ux-timer') || q('.x-timeleft'),
        timer_text: q('.ux-timer__text') || q('.ux-timer'),
        // First value span of the shipping row -- 'US $5.58 '. Deliberately
        // has no fallback selector: '.d-shipping-minview .ux-textspans' also
        // matches the 'Shipping, returns, and payments' section heading on
        // listings with no shipping row, which is not a rate.
        shipping_dom: q('.ux-labels-values--shipping .ux-labels-values__values .ux-textspans'),
        // eBay's own fulfillment label rows. Their PRESENCE is the signal:
        // a listing offering local pickup renders a 'Pickup:' row, one that
        // ships renders a 'Shipping:' row, and a listing can have either,
        // both, or (never, on a real page) neither. The shipping row's values
        // also carry the 'Located in: <city, state, country>' origin line.
        pickup_dom: q('.ux-labels-values--localPickup .ux-labels-values__values'),
        shipping_values_dom: q('.ux-labels-values--shipping .ux-labels-values__values'),
        condition: q('.x-item-condition-text .ux-textspans')
            || q('.x-item-condition-value .ux-textspans'),
        quantity: q('.x-quantity__availability .ux-textspans') || q('.x-quantity__availability'),
        seller: q('.x-sellercard-atf__info__about-seller a .ux-textspans')
            || q('.x-store-information__header .ux-textspans')
            || q('.x-sellercard-atf__info a'),
        image: (document.querySelector(
            '.ux-image-carousel-item img, .ux-image-magnify__container img, img.ux-image-carousel-item__image'
        ) || {}).src || null,
        has_bid: !!document.querySelector('.x-bid-count, [data-testid="x-bid-action"]')
            || /place bid/i.test(bodyText),
        has_best_offer: /make (an )?offer/i.test(bodyText),
        // eBay words the end-of-listing banner several ways. A BIN listing that
        // sold shows "This listing sold on <date>" with no "ended" anywhere on
        // the page (verified against item 227445045390), so matching only on
        // "ended" reported a sold listing as still live.
        ended_banner: /this (listing|auction) (sold|has ended|was ended|ended)|listing (has )?ended|bidding (has )?ended|is no longer available|no longer available/i.test(low)
            || /^ended\\b/i.test((q('.ux-timer__text') || q('.ux-timer') || '').trim()),
        error_page: /discover error|the listing you'?re looking for/i.test(low),
        captcha: /splashui\\/captcha|are you a human|please verify yourself|hcaptcha|recaptcha/i.test(
            (location.href + ' ' + document.title + ' ' + bodyText.slice(0, 600)).toLowerCase()
        ),
    };
}"""


# ---- schema.org condition mapping ----
_SCHEMA_CONDITION = {
    "NewCondition": "New",
    "UsedCondition": "Used",
    "RefurbishedCondition": "Refurbished",
    "DamagedCondition": "For parts or not working",
}


def _numeric_price(text: Optional[str]) -> Optional[str]:
    """Pull a numeric price string (no currency symbol / suffix) from text.

    The match must start with a digit so ordinary prose punctuation (e.g. the
    comma in 'Shipping, returns, and payments') cannot be read as a price.
    """
    if not text:
        return None
    match = re.search(r"\d[\d,]*(?:\.\d{2})?", text)
    return match.group(0).replace(",", "") if match else None


def _detect_currency(text: Optional[str]) -> Optional[str]:
    """Detect a currency code from a price string's symbol."""
    if not text:
        return None
    if "£" in text:
        return "GBP"
    if "€" in text:
        return "EUR"
    if "$" in text:
        return "USD"
    return None


def _parse_shipping_dom(text: Optional[str]) -> Optional[str]:
    """Parse a shipping cost from the item page's shipping DOM value.

    Examples: 'US $6.25 USPS Ground Advantage' -> '6.25', 'Free shipping' ->
    '0.00'.
    """
    if not text:
        return None
    if "free" in text.lower():
        return "0.00"
    return _numeric_price(text)


# A monetary amount ('US $5.58'), an explicit free-fulfillment phrase, or a
# delivery estimate in the shipping row's values -- any of these means eBay is
# quoting shipping for this listing. The bare word "shipping" is deliberately
# NOT a signal: the row always ends with a clipped "See details for shipping"
# link, even on listings that do not ship to the buyer.
_SHIPPING_RATE_RE = re.compile(r"\d[\d,]*\.\d{2}")
_FREE_FULFILLMENT_RE = re.compile(r"free\s+(?:shipping|delivery|postage)", re.I)
_DELIVERY_ESTIMATE_RE = re.compile(r"\bdeliver(?:y|s|ed)\b|get it (?:by|between)", re.I)

# 'Located in: Owensboro, Kentucky, United States' -- the last line of the
# shipping row's values.
_LOCATED_IN_RE = re.compile(r"Located in:\s*(.+?)\s*$")


def _quotes_shipping(shipping_values: Optional[str]) -> bool:
    """True when the shipping row actually quotes a rate or a delivery estimate."""
    if not shipping_values:
        return False
    return bool(
        _SHIPPING_RATE_RE.search(shipping_values)
        or _FREE_FULFILLMENT_RE.search(shipping_values)
        or _DELIVERY_ESTIMATE_RE.search(shipping_values)
    )


def _parse_item_location(shipping_values: Optional[str]) -> Optional[str]:
    """Pull the item's origin out of the shipping row's 'Located in:' line."""
    if not shipping_values:
        return None
    match = _LOCATED_IN_RE.search(shipping_values)
    return match.group(1) if match else None


def _iter_jsonld_objects(blocks):
    """Yield every dict object contained in the JSON-LD blocks (flattened)."""
    for block in blocks:
        items = block if isinstance(block, list) else [block]
        for item in items:
            if isinstance(item, dict):
                yield item


def _find_product(blocks) -> Optional[dict]:
    for obj in _iter_jsonld_objects(blocks):
        if obj.get("@type") == "Product":
            return obj
    return None


def _first_offer(product: dict) -> Optional[dict]:
    offers = product.get("offers")
    if isinstance(offers, list):
        return offers[0] if offers else None
    if isinstance(offers, dict):
        return offers
    return None


_UNAVAILABLE_AVAILABILITIES = {"SoldOut", "OutOfStock", "Discontinued"}


def _parse_item_availability(offer: Optional[dict], data: dict) -> Optional[str]:
    """Read listing availability without inspecting fulfillment rows."""
    if offer:
        availability = offer.get("availability")
        if availability:
            return str(availability).rsplit("/", 1)[-1]
    if data.get("ended_banner"):
        return "SoldOut"
    if data.get("quantity"):
        return "InStock"
    return None


def parse_item_status(item_id: str, data: dict) -> dict[str, Any]:
    """Return availability for one item without requiring fulfillment data."""
    if data.get("captcha"):
        raise BrowserError(
            "eBay item page is blocked by a CAPTCHA/security-verification page. "
            f"url={data.get('url')!r}"
        )

    # A catalog or different-item redirect cannot establish this listing's state.
    page_url = urlsplit(data.get("url") or "")
    if (page_url.hostname not in {"www.ebay.com", "ebay.com"}
            or not re.fullmatch(r"/itm/(?:[^/]+/)?" + re.escape(item_id) + r"/?", page_url.path)):
        raise BrowserError(
            f"eBay item {item_id} page does not identify the requested listing. "
            f"url={data.get('url')!r}"
        )

    product = _find_product(data.get("jsonld") or [])
    offer = _first_offer(product) if product else None
    if data.get("error_page"):
        return {
            "item_id": item_id,
            "availability": None,
            "ended": True,
            "url": f"https://www.ebay.com/itm/{item_id}",
        }

    availability = _parse_item_availability(offer, data)
    ended = bool(data.get("ended_banner")) or availability in _UNAVAILABLE_AVAILABILITIES
    if availability is None:
        raise BrowserError(
            f"eBay item {item_id} page carries no availability evidence. "
            f"url={data.get('url')!r} title={data.get('doc_title')!r}"
        )

    return {
        "item_id": item_id,
        "availability": availability,
        "ended": ended,
        "url": f"https://www.ebay.com/itm/{item_id}",
    }


def parse_item_detail(item_id: str, data: dict) -> ItemDetail:
    """Build an :class:`ItemDetail` from :data:`ITEM_DETAIL_JS` page data.

    Prefers the schema.org ``Product`` JSON-LD for price/currency/condition/
    availability/shipping and supplements with DOM values (bids, time-left,
    quantity, seller). Raises :class:`BrowserError` for a CAPTCHA wall or a
    removed/invalid item.
    """
    if data.get("captcha"):
        raise BrowserError(
            "eBay item page is blocked by a CAPTCHA/security-verification page. "
            f"url={data.get('url')!r}"
        )

    product = _find_product(data.get("jsonld") or [])
    offer = _first_offer(product) if product else None

    title = (product or {}).get("name") or data.get("dom_title")
    if data.get("error_page") or (not title and not offer):
        raise BrowserError(
            f"eBay item {item_id} was not found or the listing was removed. "
            f"url={data.get('url')!r} title={data.get('doc_title')!r}"
        )

    # ---- fulfillment (local pickup / shipping / origin) ----
    # Every real item page renders at least one of eBay's fulfillment label
    # rows. Neither one present means the page did not load as expected or
    # eBay changed the markup -- fail rather than report "no pickup, no
    # shipping", which a caller would read as a real fulfillment answer.
    pickup_values = data.get("pickup_dom")
    shipping_values = data.get("shipping_values_dom")
    if pickup_values is None and shipping_values is None:
        raise BrowserError(
            f"eBay item {item_id} page has neither a local-pickup nor a shipping "
            "fulfillment row, so pickup/shipping availability cannot be determined "
            "(the item DOM no longer matches the expected selectors). "
            f"url={data.get('url')!r} title={data.get('doc_title')!r}"
        )

    local_pickup = pickup_values is not None
    ships = _quotes_shipping(shipping_values)
    item_location = _parse_item_location(shipping_values)

    # ---- price / currency ----
    currency = "USD"
    price = None
    availability = _parse_item_availability(offer, data)
    condition = data.get("condition")
    shipping_price = None
    brand = None
    image_url = data.get("image")

    if offer:
        price = _numeric_price(offer.get("price"))
        currency = offer.get("priceCurrency") or "USD"
        cond = offer.get("itemCondition")
        if cond and not condition:
            condition = _SCHEMA_CONDITION.get(str(cond).rsplit("/", 1)[-1])
        ship = offer.get("shippingDetails")
        if isinstance(ship, list) and ship:
            rate = ship[0].get("shippingRate") if isinstance(ship[0], dict) else None
            if isinstance(rate, dict):
                shipping_price = _numeric_price(rate.get("value"))

    if price is None:
        price = _numeric_price(data.get("price_primary"))

    # DOM fallbacks when the page had no (or partial) Product JSON-LD. eBay
    # serves the Product JSON-LD inconsistently, so the DOM is the reliable
    # source for shipping/currency/availability.
    if not offer:
        detected = _detect_currency(data.get("price_primary"))
        if detected:
            currency = detected
    if shipping_price is None:
        shipping_price = _parse_shipping_dom(data.get("shipping_dom"))
    if product:
        brand_obj = product.get("brand")
        if isinstance(brand_obj, dict):
            brand = brand_obj.get("name")
        elif isinstance(brand_obj, str):
            brand = brand_obj
        images = product.get("image")
        if not image_url and isinstance(images, list) and images:
            first_img = images[0]
            image_url = first_img.get("url") if isinstance(first_img, dict) else first_img
        elif not image_url and isinstance(images, str):
            image_url = images

    # ---- format / bids / auction vs BIN ----
    bids = None
    if data.get("bid_count"):
        bid_match = re.search(r"\d+", data["bid_count"])
        if bid_match:
            bids = int(bid_match.group(0))

    is_auction = bool(data.get("has_bid")) or bids is not None
    current_bid = None
    bin_price = None
    if is_auction:
        fmt = "Auction"
        current_bid = price
    elif data.get("has_best_offer"):
        fmt = "Best Offer"
        bin_price = price
    else:
        fmt = "Buy It Now"
        bin_price = price or _numeric_price(data.get("bin_price"))

    ended = bool(data.get("ended_banner")) or (
        availability in _UNAVAILABLE_AVAILABILITIES
    )

    return ItemDetail(
        item_id=item_id,
        title=title,
        price=price,
        currency=currency,
        format=fmt,
        bin_price=bin_price,
        current_bid=current_bid,
        bids=bids,
        time_left=data.get("time_left"),
        shipping_price=shipping_price,
        local_pickup=local_pickup,
        ships=ships,
        item_location=item_location,
        condition=condition,
        availability=availability,
        ended=ended,
        quantity=data.get("quantity"),
        seller=data.get("seller"),
        brand=brand,
        url=f"https://www.ebay.com/itm/{item_id}",
        image_url=image_url,
    )


class EbayBrowserClient:
    """Browser-based eBay client for single-item detail."""

    BASE_URL = "https://www.ebay.com"
    ITEM_PATH = "/itm"

    def __init__(self, profile: Optional[str] = None, config: Optional[Any] = None):
        self.config = config or get_config(profile=profile)
        self._browser: Optional[EbayBrowser] = None

    @property
    def browser(self) -> EbayBrowser:
        """Lazy-initialize browser service."""
        if self._browser is None:
            self._browser = self.config.get_browser()
        return self._browser

    def close(self):
        """Close browser service."""
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False

    def get_item(self, item_id: str) -> ItemDetail:
        """Fetch detail for a single active eBay listing by item ID.

        Navigates the public ``/itm/<id>`` page directly and parses the
        schema.org ``Product`` JSON-LD plus DOM supplements. Raises
        :class:`BrowserError` on a CAPTCHA wall or a removed/invalid item.
        """
        item_id, data = self._read_item_page(item_id)
        return parse_item_detail(item_id, data)

    def get_item_status(self, item_id: str) -> dict[str, Any]:
        """Fetch item availability without parsing fulfillment details."""
        item_id, data = self._read_item_page(item_id, original_listing=True)
        return parse_item_status(item_id, data)

    def _read_item_page(
        self,
        item_id: str,
        *,
        original_listing: bool = False,
    ) -> tuple[str, dict]:
        """Read the public item page once and return its normalized item ID and DOM data."""
        item_id = str(item_id).strip()
        if not item_id or not item_id.isdigit():
            raise BrowserError(f"Invalid eBay item ID: {item_id!r}")

        # Open the browser directly at the public item page. Navigating there
        # from another eBay page (e.g. the My-eBay summary) suppresses the
        # server-rendered Product JSON-LD, so a fresh open is what yields the
        # structured price/condition/availability/shipping data.
        url = f"{self.BASE_URL}{self.ITEM_PATH}/{item_id}"
        if original_listing:
            url = f"{url}?orig_cvip=true"
        page = self.browser.get_page(url)
        page.wait_for_timeout(3000)
        return item_id, page.evaluate(ITEM_DETAIL_JS)


def get_browser_client(profile: Optional[str] = None, config: Optional[Any] = None) -> EbayBrowserClient:
    """Get an EbayBrowserClient instance."""
    return EbayBrowserClient(profile=profile, config=config)
