"""Browser-based eBay client for marketplace search and item detail.

Uses the shared stealth persistent-Chromium browser (``cli_tools_shared``)
to scrape eBay search results and item pages, which are not available via
the public Sell API:

* ``search_completed`` — completed/sold comps (``LH_Complete=1``).
* ``search_active`` — active, purchasable listings (BIN + auction) with
  price, current bid, time-left, shipping, and item URL.
* ``get_item`` — detail for a single active ``/itm/<id>`` page, parsed from
  the page's schema.org ``Product`` JSON-LD plus DOM supplements.
* ``get_item_status`` — availability for one ``/itm/<id>`` page without
  requiring shipping or local-pickup rows.

Active ``/sch/i.html`` searches and ``/itm/<id>`` pages are public. Completed
searches require a live browser session because eBay sends cold
``LH_Complete=1`` requests to sign-in. Every search also waits for usable
homepage content before it navigates.
"""
import json
import re
from typing import Any, Optional
from urllib.parse import urlencode

from cli_tools_shared.browser import BrowserHarnessError
from cli_tools_shared.output import print_info, print_warning

from .browser import (
    INTERSTITIAL_CAPTCHA,
    INTERSTITIAL_CHALLENGE,
    INTERSTITIAL_ERROR,
    BrowserError,
    EbayBrowser,
    classify_interstitial,
)
from .config import get_config
from .models.item_detail import ItemDetail
from .models.search_result import SearchResult


# CSS selectors for eBay search results page (2026 s-card layout).
# eBay replaced the earlier "su-item-card" card markup with "s-card" (verified
# 2026-07-23 by inspecting live search-result HTML -- see
# tests/test_browser_search_extractor.py and sources.md for details).
SELECTORS = {
    "homepage_search_input": 'input[name="_nkw"]',
    "results_container": ".srp-river-main",
    "results_heading": ".srp-controls__count-heading",
    "item": "li.s-card[data-listingid]",
    "title": ".s-card__title",
    "price": ".s-card__price",
    "caption": ".s-card__caption",
    "condition": ".s-card__subtitle",
    "image": ".s-card__image",
    "attributes_primary": ".su-card-container__attributes__primary .su-styled-text",
    "attributes_primary_rows": ".su-card-container__attributes__primary .s-card__attribute-row",
    "attributes_secondary": ".su-card-container__attributes__secondary .su-styled-text",
    "attribute_row": ".s-card__attribute-row",
    "next_page": "a.pagination__next",
}
SEARCH_RESULTS_TIMEOUT_MS = 10_000
SEARCH_PAGE_SIZE = 240
SEARCH_MAX_PAGES = 4
SEARCH_MAX_RESULTS = SEARCH_PAGE_SIZE * SEARCH_MAX_PAGES

SEARCH_CONDITION_ALIASES = {
    "new": "1000",
    "open_box": "1500",
    "refurbished": "2000",
    "used": "3000",
    "for_parts": "7000",
}
SEARCH_CONDITION_HELP = (
    "Item condition ("
    + ", ".join(SEARCH_CONDITION_ALIASES)
    + ", or eBay condition ID)"
)

# Listing-format filters for active search (--format).
LISTING_FORMATS = ("bin", "auction", "all")
LISTING_FORMAT_HELP = (
    "Active-listing format: bin (Buy It Now), auction, or all (default all)"
)

# Source-CLI Sort Standard -> eBay `_sop` sort-order codes.
#
# The meaning of the canonical `newest` field differs by listing state:
#
#   * COMPLETED comps: eBay orders already-ended listings by "ended recently";
#     it has no "newly listed" order for ended listings. So `newest` maps to
#     "Time: ended recently" (_sop=13) -- most recently ended/sold first. This
#     is the documented recency-sort exception for comps.
#   * ACTIVE listings: `newest` maps to eBay's true "newly listed" order
#     (_sop=10) -- exactly what an incremental newest-first crawler wants.
#
# eBay exposes a single directional `_sop` for each time-based order and a low/
# high pair for price, so each map is keyed by (field, descending). Combinations
# eBay cannot produce (a descending twin for `newest`/`ending`) are absent on
# purpose and rejected fail-fast rather than silently reordered.
#
# _sop reference: 10 = Time: newly listed, 13 = Time: ended recently,
# 15 = Price+Shipping lowest first, 16 = Price+Shipping highest first,
# 1 = Time: ending soonest.
SORT_SOP_COMPLETED = {
    ("newest", False): "13",
    ("price", False): "15",
    ("price", True): "16",
    ("ending", False): "1",
}
SORT_SOP_ACTIVE = {
    ("newest", False): "10",
    ("price", False): "15",
    ("price", True): "16",
    ("ending", False): "1",
}

VALID_SORT_FIELDS = ("newest", "price", "ending")

DEFAULT_SORT = "newest"


def resolve_sop(sort: str, desc: bool, active: bool = False) -> str:
    """Resolve a canonical (``--sort``, ``--desc``) pair to an eBay ``_sop`` code.

    ``active`` selects the active-listing sort map (``newest`` -> newly listed)
    versus the completed-comps map (``newest`` -> ended recently).

    Fail-fast, no silent fallback: an unknown ``--sort`` field, or a ``--desc``
    direction eBay's search cannot produce, raises ``ValueError`` with a clear,
    actionable message.
    """
    field = sort.lower()
    if field not in VALID_SORT_FIELDS:
        valid = ", ".join(VALID_SORT_FIELDS)
        raise ValueError(f"Invalid --sort '{sort}'. Valid values: {valid}")
    sop_map = SORT_SOP_ACTIVE if active else SORT_SOP_COMPLETED
    try:
        return sop_map[(field, desc)]
    except KeyError:
        raise ValueError(
            f"eBay {'active' if active else 'completed'}-listing search has no "
            f"descending order for --sort {field}; --desc is only supported with "
            f"--sort price."
        )

# JavaScript to extract search results from the page.
#
# Input is an object: {selectors, active}. When ``active`` is true the row
# status is forced to 'active' (there is no sold/ended caption on live
# listings) and ``time_left`` is read from the primary attribute rows;
# otherwise the completed-comps sold/unsold + date semantics apply.
EXTRACT_JS = """(params) => {
    const selectors = params.selectors;
    const activeMode = !!params.active;
    const cards = document.querySelectorAll(selectors.item);
    const results = [];
    const seenItemIds = new Set();

    function cleanText(el) {
        return el ? el.textContent.replace(/\\s+/g, ' ').trim() : '';
    }

    function cleanCardText(el) {
        return el ? el.innerText.replace(/\\s+/g, ' ').trim() : '';
    }

    function parsePrice(text) {
        const match = text.match(/[\\$\\u00A3\\u20AC]([\\d,]+(?:\\.\\d{2})?)/);
        return match ? match[1].replace(/,/g, '') : text.trim();
    }

    function parseCurrency(text) {
        const currMatch = text.match(/([\\$\\u00A3\\u20AC])/);
        if (!currMatch) return 'USD';
        if (currMatch[1] === '\\u00A3') return 'GBP';
        if (currMatch[1] === '\\u20AC') return 'EUR';
        return 'USD';
    }

    function normalizeDate(text) {
        const match = text.match(/\\b(?:sold|ended)\\s+(.+)/i);
        if (!match) return null;
        return match[1].replace(/\\b[A-Z]{3}\\b/g, (month) => (
            month.charAt(0) + month.slice(1).toLowerCase()
        ));
    }

    // Active listings show remaining time in one of the primary attribute
    // rows, e.g. "6d 4h", "4h 32m", "23m", "1m (Today 3:52PM)". Distinguish
    // it from the price/shipping/format rows and from a BIN card's listing
    // date ("Jul-24 15:33", which starts with a month name, not a digit).
    function parseTimeLeft(rowText) {
        const t = (rowText || '').replace(/\\s+/g, ' ').trim();
        if (!t || t.includes('$')) return null;
        const low = t.toLowerCase();
        if (low.includes('delivery') || low.includes('shipping') ||
            low.includes('located') || low.includes('offer') ||
            low.includes('buy it now') || low.includes('bid')) return null;
        if (/^\\d+\\s*[dhms]\\b/.test(t) ||
            /\\b\\d+\\s*d\\s*\\d+\\s*h\\b/.test(t) ||
            /\\bends?\\b/i.test(t) ||
            /\\((today|tomorrow)\\b/i.test(low)) {
            return t;
        }
        return null;
    }

    for (const card of cards) {
        const titleEl = card.querySelector(selectors.title);
        if (!titleEl) continue;
        // The title node wraps a "New Listing" badge and a visually-hidden
        // "Opens in a new window or tab" a11y span around the real title
        // text, so pull the primary styled-text span rather than the whole
        // node's textContent.
        const titleTextEl = titleEl.querySelector('span.su-styled-text.primary') || titleEl;
        const title = cleanText(titleTextEl);
        if (title === 'Shop on eBay' || title === 'Results matching fewer words') continue;

        const itemId = card.getAttribute('data-listingid') || '';
        if (!itemId || seenItemIds.has(itemId)) continue;
        seenItemIds.add(itemId);

        const linkEl = titleEl.closest('a');
        const url = linkEl ? linkEl.href : '';

        const priceEl = card.querySelector(selectors.price);
        const priceText = cleanText(priceEl);
        const price = parsePrice(priceText);
        const currency = parseCurrency(priceText);

        const captionEl = card.querySelector(selectors.caption);
        const captionText = cleanText(captionEl);
        const isSold = captionText.toLowerCase().includes('sold');
        const status = activeMode ? 'active' : (isSold ? 'sold' : 'unsold');
        const dateSold = activeMode ? null : normalizeDate(captionText);

        const condEl = card.querySelector(selectors.condition);
        const condition = cleanText(condEl) || null;

        const fullText = cleanCardText(card);
        const attributeEls = card.querySelectorAll(selectors.attributes_primary);
        let shippingPrice = null;
        let format = null;
        let bids = null;
        let seller = null;
        let timeLeft = null;

        for (const attrEl of attributeEls) {
            const text = cleanText(attrEl);
            const textLower = text.toLowerCase();

            if (textLower.includes('delivery') || textLower.includes('shipping')) {
                if (textLower.includes('free')) {
                    shippingPrice = '0.00';
                } else {
                    const shipMatch = text.match(/[\\$\\u00A3\\u20AC]([\\d,\\.]+)/);
                    shippingPrice = shipMatch ? shipMatch[1].replace(/,/g, '') : null;
                }
            }

            if (textLower.includes('best offer')) {
                format = 'Best Offer';
            } else if (textLower.includes('buy it now')) {
                format = 'Buy It Now';
            }
        }

        if (activeMode) {
            const attrRows = card.querySelectorAll(selectors.attributes_primary_rows);
            for (const row of attrRows) {
                // Join the row's styled-text spans with a space; adjacent spans
                // ("1m" + "(Today 4:15PM)") concatenate without whitespace in
                // textContent otherwise.
                const spans = row.querySelectorAll('.su-styled-text');
                const rowText = spans.length
                    ? Array.from(spans).map((s) => cleanText(s)).filter(Boolean).join(' ')
                    : cleanText(row);
                const candidate = parseTimeLeft(rowText);
                if (candidate) { timeLeft = candidate; break; }
            }
        }

        const bidsMatch = fullText.match(/(\\d+)\\s*bid/i);
        if (bidsMatch) {
            bids = parseInt(bidsMatch[1], 10);
            format = 'Auction';
        }

        // Seller name and feedback percentage now live in separate spans
        // within the first attribute row of the secondary attributes block,
        // so join that row's text before matching rather than reading a
        // single span.
        const secondaryContainer = card.querySelector('.su-card-container__attributes__secondary');
        const sellerRow = secondaryContainer ? secondaryContainer.querySelector(selectors.attribute_row) : null;
        const sellerText = cleanText(sellerRow);
        const sellerMatch = sellerText.match(/^(\\S+)\\s+[\\d.]+%\\s+positive/);
        if (sellerMatch) {
            seller = sellerMatch[1];
        }

        if (!format) {
            format = bids !== null ? 'Auction' : 'Buy It Now';
        }

        const imgEl = card.querySelector(selectors.image);
        const imageUrl = imgEl ? (imgEl.src || imgEl.dataset.src || null) : null;

        if (title && price && url) {
            results.push({
                item_id: itemId,
                title: title,
                price: price,
                currency: currency,
                shipping_price: shippingPrice,
                status: status,
                date_sold: dateSold,
                time_left: timeLeft,
                condition: condition,
                format: format,
                bids: bids,
                seller: seller,
                url: url,
                image_url: imageUrl,
            });
        }
    }

    return results;
}"""

# JavaScript to inspect the loaded search page before trusting an empty
# extraction. Distinguishes a genuine zero-result search (eBay's own "0
# results for ..." heading) from a page that didn't load as expected --
# a CAPTCHA/interstitial, a sign-in redirect, or a DOM structure eBay has
# changed out from under our selectors.
PAGE_STATE_JS = """(selectors) => {
    const heading = document.querySelector(selectors.results_heading);
    const headingText = heading ? heading.textContent.replace(/\\s+/g, ' ').trim() : null;
    const bodyText = document.body ? document.body.innerText.replace(/\\s+/g, ' ').trim().slice(0, 1000) : '';
    return {
        url: location.href,
        title: document.title,
        container_exists: !!document.querySelector(selectors.results_container),
        heading_text: headingText,
        zero_results: !!headingText && /^0\\s+results/i.test(headingText),
        body_text_snippet: bodyText,
    };
}"""

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
    """Browser-based eBay client for marketplace search and item detail."""

    BASE_URL = "https://www.ebay.com"
    SEARCH_PATH = "/sch/i.html"
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

    def ensure_authenticated(self):
        """Ensure the browser session is authenticated (My-eBay login).

        Completed search calls this because eBay sends cold
        ``LH_Complete=1`` requests to sign-in. Active search and item-detail
        remain public.
        """
        if not self.browser.is_authenticated():
            raise BrowserError(
                "No browser session found. Run 'ebay auth login --credential-type browser_session' first."
            )

    @staticmethod
    def _raise_for_search_blocker(state: dict) -> None:
        """Raise if the search page landed on an interstitial or sign-in page
        instead of real results, rather than letting that silently look like
        zero results.

        Interstitials are classified with the shared taxonomy in
        ``ebay_cli.browser`` so each wall gets its own accurate message.
        ``EbayBrowser.get_page`` already retries the retryable ones, so
        reaching here means the wall reappeared during this page's own
        selector wait or outlasted the retries. Sign-in is checked before the
        container so an expired session never reports as "container missing".
        """
        where = f"url={state['url']} title={state['title']!r}"
        rule = classify_interstitial(
            url=state["url"],
            title=state["title"],
            body=state["body_text_snippet"],
        )
        kind = rule.kind if rule is not None else None
        if kind == INTERSTITIAL_CAPTCHA:
            raise BrowserError(
                "eBay search is blocked by a CAPTCHA/human-verification page. "
                "This cannot be solved automatically -- run 'ebay auth login "
                "--credential-type browser_session --force' from an "
                f"interactive shell and complete the verification. {where}"
            )
        if kind == INTERSTITIAL_CHALLENGE:
            raise BrowserError(
                "eBay's browser-check interstitial ('Pardon Our Interruption') "
                "did not clear for this search. It is a transient wall, not a "
                f"CAPTCHA -- wait a minute and retry. {where}"
            )
        if kind == INTERSTITIAL_ERROR:
            raise BrowserError(
                "eBay served its 'Error Page' instead of search results, which "
                "is its request-rate wall, not a missing results container. "
                f"Wait a few minutes before retrying. {where}"
            )

        lowered = f"{state['url']} {state['title']} {state['body_text_snippet']}".lower()
        if "signin.ebay.com" in lowered or "/signin" in lowered:
            raise BrowserError(
                "eBay search redirected to sign-in instead of showing results, "
                "which means the browser session is expired or unauthenticated. "
                "Run 'ebay auth login --credential-type browser_session --force'. "
                f"{where}"
            )
        if not state["container_exists"]:
            raise BrowserError(
                "eBay search results container was not found on the page -- the page "
                f"did not load as expected. {where}"
            )

    def search_completed(
        self,
        keywords: str,
        sold_only: bool = False,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        category: Optional[str] = None,
        condition: Optional[str] = None,
        us_only: bool = False,
        limit: int = 50,
        sop: str = "13",
    ) -> list[SearchResult]:
        """Search completed/sold listings with a live browser session."""
        self.ensure_authenticated()
        return self._search(
            keywords=keywords,
            active=False,
            sold_only=sold_only,
            min_price=min_price,
            max_price=max_price,
            category=category,
            condition=condition,
            us_only=us_only,
            limit=limit,
            sop=sop,
        )

    def search_active(
        self,
        keywords: str,
        listing_format: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        category: Optional[str] = None,
        condition: Optional[str] = None,
        us_only: bool = False,
        limit: int = 50,
        sop: str = "10",
    ) -> list[SearchResult]:
        """Search eBay ACTIVE (live, purchasable) listings."""
        return self._search(
            keywords=keywords,
            active=True,
            listing_format=listing_format,
            min_price=min_price,
            max_price=max_price,
            category=category,
            condition=condition,
            us_only=us_only,
            limit=limit,
            sop=sop,
        )

    def _search(
        self,
        keywords: str,
        active: bool,
        sold_only: bool = False,
        listing_format: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        category: Optional[str] = None,
        condition: Optional[str] = None,
        us_only: bool = False,
        limit: int = 50,
        sop: str = "13",
    ) -> list[SearchResult]:
        """Shared search over active or completed listings.

        Warms the public homepage, then navigates to search without a login
        gate. Relies on :meth:`_raise_for_search_blocker` to surface a
        CAPTCHA/sign-in wall.
        """
        all_results: list[SearchResult] = []
        page_num = 1
        page = self.browser.get_page(self.BASE_URL)
        try:
            page.wait_for_selector(
                SELECTORS["homepage_search_input"],
                state="attached",
                timeout=SEARCH_RESULTS_TIMEOUT_MS,
            )
        except BrowserHarnessError:
            state = page.evaluate(PAGE_STATE_JS, SELECTORS)
            self._raise_for_search_blocker(state)

        while len(all_results) < limit and page_num <= SEARCH_MAX_PAGES:
            url = self._build_search_url(
                keywords=keywords,
                active=active,
                sold_only=sold_only,
                listing_format=listing_format,
                min_price=min_price,
                max_price=max_price,
                category=category,
                condition=condition,
                us_only=us_only,
                page=page_num,
                sop=sop,
            )

            print_info(f"Fetching page {page_num}...")

            # A new eBay profile needs the homepage request to establish its
            # guest session. Search can then show a transient "Pardon Our
            # Interruption" page before it redirects to the results.
            page = self.browser.get_page(url)
            try:
                page.wait_for_selector(
                    SELECTORS["item"],
                    state="attached",
                    timeout=SEARCH_RESULTS_TIMEOUT_MS,
                )
            except BrowserHarnessError:
                state = page.evaluate(PAGE_STATE_JS, SELECTORS)
                self._raise_for_search_blocker(state)
                if state["zero_results"]:
                    break
                raise BrowserError(
                    "eBay search result cards did not attach before the timeout even "
                    "though the page reports results. "
                    f"url={state['url']} title={state['title']!r} "
                    f"heading={state['heading_text']!r} "
                    f"container_exists={state['container_exists']}"
                )

            raw_results = page.evaluate(EXTRACT_JS, {"selectors": SELECTORS, "active": active})

            if not raw_results:
                state = page.evaluate(PAGE_STATE_JS, SELECTORS)
                self._raise_for_search_blocker(state)
                if state["zero_results"]:
                    # eBay itself reports zero matches -- a legitimate empty
                    # search, not a scraping failure.
                    break
                raise BrowserError(
                    "eBay search returned no extractable listings even though the page "
                    "does not report zero results. This means the search-results DOM "
                    "no longer matches the expected selectors (eBay likely changed its "
                    f"markup). url={state['url']} title={state['title']!r} "
                    f"heading={state['heading_text']!r} "
                    f"container_exists={state['container_exists']}"
                )

            for raw in raw_results:
                if len(all_results) >= limit:
                    break
                all_results.append(SearchResult(**raw))

            next_btn = page.locator(SELECTORS["next_page"])
            if next_btn.count() == 0:
                break

            if page_num == SEARCH_MAX_PAGES:
                if len(all_results) < limit:
                    print_warning(
                        f"eBay search provides at most four result pages. "
                        f"Returned {len(all_results)} of {limit} requested results."
                    )
                break

            page_num += 1
            page.wait_for_timeout(1000)  # Brief delay between pages

        return all_results[:limit]

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

    def _build_search_url(
        self,
        keywords: str,
        active: bool = False,
        sold_only: bool = False,
        listing_format: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        category: Optional[str] = None,
        condition: Optional[str] = None,
        us_only: bool = False,
        page: int = 1,
        sop: str = "13",
    ) -> str:
        """Build an eBay search URL with filters.

        Completed comps (``active=False``) constrain to ``LH_Complete=1`` and
        optionally ``LH_Sold=1``. Active search (``active=True``) drops those
        and optionally constrains listing format via ``LH_BIN``/``LH_Auction``.
        """
        params = {
            "_nkw": keywords,
            "_ipg": str(SEARCH_PAGE_SIZE),
            "_sop": sop,  # Sort order (see resolve_sop)
        }

        if active:
            fmt = (listing_format or "all").lower()
            if fmt == "bin":
                params["LH_BIN"] = "1"
            elif fmt == "auction":
                params["LH_Auction"] = "1"
        else:
            params["LH_Complete"] = "1"  # Completed listings
            if sold_only:
                params["LH_Sold"] = "1"

        if min_price is not None:
            params["_udlo"] = str(min_price)

        if max_price is not None:
            params["_udhi"] = str(max_price)

        if category:
            params["_sacat"] = category

        if condition:
            cond_id = SEARCH_CONDITION_ALIASES.get(condition.lower(), condition)
            params["LH_ItemCondition"] = cond_id

        if us_only:
            params["LH_PrefLoc"] = "1"

        if page > 1:
            params["_pgn"] = str(page)

        return f"{self.BASE_URL}{self.SEARCH_PATH}?{urlencode(params)}"


def get_browser_client(profile: Optional[str] = None, config: Optional[Any] = None) -> EbayBrowserClient:
    """Get an EbayBrowserClient instance."""
    return EbayBrowserClient(profile=profile, config=config)
