"""Parse AuctionZip server-rendered HTML into public command records.

AuctionZip search-results and lot-detail pages are server-rendered HTML with no
JSON search API (validated live: the only network call behind a search is the
`GET /search-results` document itself). Every selector, class, and id below was
validated against real DOM captured live via a Cloudflare-cleared browser
session during CLI creation; the same captures back the hermetic fixtures under
`tests/fixtures/`. None of this is guessed.

Two robust data sources on a lot page:
  1. ``#lotData[data-ga-data]`` — a JSON blob the page ships with the lot's
     brand (auction house), currency, name (title), id (lot ref), price
     (current bid at render), expirationDate, and a status ``variant``
     (e.g. ``active-lot-timed``). Used as the structured primary source.
  2. The visible DOM — bid count, next-minimum-bid, buyer's premium, auction
     type, close time, location, and the Payment/Shipping + Conditions panels
     (server-rendered into collapsed ``#payPanel`` / ``#termsPanel`` divs).

We return a flat, explicit record (not the raw DOM) because the external output
contract is a small fixed set of fields; genuinely-absent optional fields
(estimate, time-remaining vs. scheduled date) are ``None``, never faked.
"""

import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

# Lot ref is the alphanumeric token after the final underscore in a lot slug,
# e.g. ".../lego-storage-..._9295BB0625" -> "9295BB0625".
LOT_REF_RE = re.compile(r"_([0-9A-Za-z]+)(?:[#?].*)?$")
LOT_NUMBER_RE = re.compile(r"Lot\s*#?\s*(\w+)", re.IGNORECASE)
MONEY_RE = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)")
BIDS_RE = re.compile(r"\(?\s*(\d+)\s*Bid", re.IGNORECASE)
# Apostrophe-agnostic: matches "buyer's premium of 10%" AND "10% buyers premium".
PREMIUM_OF_RE = re.compile(r"premium\s+of\s+([\d.]+)\s*%", re.IGNORECASE)
PREMIUM_PREFIX_RE = re.compile(r"([\d.]+)\s*%\s*buyer", re.IGNORECASE)
CATALOG_REF_RE = re.compile(r"catalogRef=([0-9A-Za-z]+)", re.IGNORECASE)
CATALOG_SLUG_REF_RE = re.compile(r"/auction-catalog/[^\"']*_([0-9A-Za-z]+)(?:[#?]|$)")


def _clean(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    collapsed = re.sub(r"\s+", " ", text).strip()
    return collapsed or None


def _money(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    match = MONEY_RE.search(text)
    if not match:
        return None
    return float(match.group(1).replace(",", ""))


def _first_int(regex: re.Pattern, text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    match = regex.search(text)
    return int(match.group(1)) if match else None


def _text_with_breaks(node, sep: str = ", ") -> Optional[str]:
    """get_text for a node where ``<br>`` should become ``sep`` (e.g. address)."""
    if node is None:
        return None
    for br in node.find_all("br"):
        br.replace_with("\n")
    parts = [p.strip() for p in node.get_text("\n").split("\n") if p.strip()]
    return sep.join(parts) or None


def _ref_from_href(href: str) -> Optional[str]:
    match = LOT_REF_RE.search(href.split("/")[-1])
    return match.group(1) if match else None


# ---------------------------------------------------------------------------
# Search results
# ---------------------------------------------------------------------------


def _parse_search_card(card, base_url: str) -> Optional[Dict[str, Any]]:
    link = card.select_one("a.linkToLot") or card.select_one('a[href*="/auction-lot/"]')
    if link is None or not link.get("href"):
        return None
    href = link["href"]
    ref = card.get("id") or _ref_from_href(href)
    if not ref:
        return None

    title_el = card.select_one(".search-lot-title")
    title = _clean(title_el.get_text()) if title_el else None

    lot_number = None
    link_text = link.get_text(" ", strip=True)
    lot_match = LOT_NUMBER_RE.search(link_text)
    if lot_match:
        lot_number = lot_match.group(1)

    house = None
    title_h2 = card.select_one("h2.lot-title")
    if title_h2:
        house_el = title_h2.find_next_sibling("div")
        if house_el:
            house = _clean(re.sub(r"^\s*by\s+", "", house_el.get_text(), flags=re.IGNORECASE))

    bid_el = card.select_one(".auction-current-bid .bold")
    current_bid = _clean(bid_el.get_text()) if bid_el else None

    bids_el = card.select_one(".auction-current-bid .text-muted")
    bids = _first_int(BIDS_RE, bids_el.get_text()) if bids_el else None

    time_el = card.select_one(".auction-time-remaining")
    time_remaining = _clean(time_el.get_text(" ")) if time_el else None

    date_el = card.select_one(".lot-date-time")
    close_time = _clean(date_el.get_text()) if date_el else None

    est_el = card.select_one(".lot-estimate")
    estimate = None
    if est_el:
        estimate = _clean(re.sub(r"^\s*Estimate:\s*", "", est_el.get_text(" "), flags=re.IGNORECASE))

    return {
        "ref": ref,
        "lot_number": lot_number,
        "title": title,
        "auction_house": house,
        "current_bid": current_bid,
        "current_bid_amount": _money(current_bid),
        "bids": bids,
        "time_remaining": time_remaining,
        "close_time": close_time,
        "estimate": estimate,
        "url": urljoin(base_url, href),
    }


def parse_search_results(html: str, base_url: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Parse an AuctionZip `/search-results` page into lot summary records."""
    soup = BeautifulSoup(html, "html.parser")
    records: List[Dict[str, Any]] = []
    seen = set()
    for card in soup.select(".lotListItem"):
        record = _parse_search_card(card, base_url)
        if record is None or record["ref"] in seen:
            continue
        seen.add(record["ref"])
        records.append(record)
        if limit is not None and len(records) >= limit:
            break
    return records


# ---------------------------------------------------------------------------
# Lot detail
# ---------------------------------------------------------------------------


def _ga_product(lot_data) -> Dict[str, Any]:
    """Return the first ga-data product dict, or {} if absent/malformed."""
    if lot_data is None:
        return {}
    raw = lot_data.get("data-ga-data")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    products = data.get("ecommerce", {}).get("detail", {}).get("products", [])
    return products[0] if products else {}


def _panel_sections(panel) -> Dict[str, str]:
    """Map each ``<h4>`` heading in a panel to the text that follows it.

    Used for #payPanel, which renders "Accepted Forms of Payment:" and
    "Shipping" as h4 headings each followed by paragraph text (the shipping
    heading's body carries the pickup/shipping terms).
    """
    sections: Dict[str, str] = {}
    if panel is None:
        return sections
    for heading in panel.find_all("h4"):
        label = _clean(heading.get_text()) or ""
        label = label.rstrip(":")
        parts = []
        sib = heading.find_next_sibling()
        while sib is not None and sib.name != "h4":
            text = _text_with_breaks(sib, sep="\n")
            if text:
                parts.append(text)
            sib = sib.find_next_sibling()
        if label:
            sections[label] = "\n".join(parts).strip()
    return sections


def _lot_images(soup) -> List[str]:
    """The lot's OWN gallery photos, full size, in the page's own order.

    `a.carousel-link` is the desktop gallery: one anchor per photo, each with
    `data-image` and `data-linknum` pointing at the `_original.jpg`. That class
    is the whole reason this is not a bare `img[src*=housePhotos]` scan.

    A lot page ALSO renders the previous and next lots' thumbnails, tagged
    `prev-next-image`, plus tooltip previews of them. A loose scan picks those
    up and attributes a neighbouring lot's photos to this one -- the exact
    failure the appraiser's catalog-image comparison exists to catch, arriving
    from the one direction the comparison cannot see. `a.carousel-link` never
    matches them.

    Falls back to the mobile gallery (`a.mobile-carousel-link`), which carries
    the same photos at a smaller size, when the desktop block is absent.
    Returns `[]` for a genuinely photo-less lot; a lot with no photos is a real
    thing and is not an error.
    """
    urls: List[str] = []
    for selector in ("a.carousel-link[data-image]", "a.mobile-carousel-link[data-image]"):
        anchors = soup.select(selector)
        if not anchors:
            continue

        def _order(anchor):
            raw = anchor.get("data-linknum")
            try:
                return int(raw)
            except (TypeError, ValueError):
                # An anchor the page did not number sorts last rather than
                # crashing the whole lot read over gallery ordering.
                return len(anchors)

        for anchor in sorted(anchors, key=_order):
            url = (anchor.get("data-image") or anchor.get("href") or "").strip()
            if url and url not in urls:
                urls.append(url)
        if urls:
            break
    return urls


def _lot_status(lot_data, soup, variant: str) -> str:
    """Return 'closed' or 'open' from the closed-marker visibility + ga variant."""
    closed_marker = soup.select_one("#lotClosedText")
    if closed_marker is not None:
        classes = closed_marker.get("class", [])
        if "d-none" not in classes:
            return "closed"
    lowered = (variant or "").lower()
    if any(token in lowered for token in ("closed", "ended", "sold", "unsold", "passed")):
        return "closed"
    return "open"


def parse_lot_detail(html: str, url: Optional[str] = None) -> Dict[str, Any]:
    """Parse an AuctionZip `/auction-lot/...` page into a lot detail record.

    ``url`` is the resolved page URL the client navigated to; it is preferred
    over the page's own canonical link when present.
    """
    soup = BeautifulSoup(html, "html.parser")
    lot_data = soup.select_one("#lotData")
    product = _ga_product(lot_data)

    ref = None
    if lot_data is not None:
        ref = lot_data.get("data-lot-ref")
    ref = ref or product.get("id")

    title_el = soup.select_one("#lotTitleBlock") or soup.select_one("#mobileLotTitle") or soup.select_one("h1")
    title = _clean(title_el.get_text()) if title_el else product.get("name")

    if not ref and not title:
        raise ValueError("Not an AuctionZip lot page (no #lotData and no title found)")

    # Lot number: "Lot 244" in the title-row heading (avoid "Lot is closed").
    lot_number = None
    heading = soup.select_one("#pdpTitleRow h3") or soup.select_one("h3.notranslate")
    if heading:
        heading_text = heading.get_text(" ", strip=True)
        match = re.search(r"Lot\s*#?\s*(\d+)", heading_text)
        if match:
            lot_number = match.group(1)

    # Current bid (DOM is authoritative for the live value; ga price is fallback).
    bid_el = soup.select_one(".lot-current-bid .font-weight-bold") or soup.select_one("#bidPrefix .font-weight-bold")
    current_bid = _clean(bid_el.get_text()) if bid_el else None
    current_bid_amount = _money(current_bid)
    if current_bid_amount is None and product.get("price") is not None:
        current_bid_amount = float(product["price"])
        current_bid = f"${product['price']}"

    bids_el = soup.select_one(".num-bids") or soup.select_one(".lot-current-bid .text-muted")
    bids = _first_int(BIDS_RE, bids_el.get_text()) if bids_el else None

    next_bid_el = soup.select_one("#select-dropdown-options li")
    next_bid = _clean(next_bid_el.get_text()) if next_bid_el else None

    time_el = soup.select_one(".timedAuctionCountdown")
    time_remaining = _clean(time_el.get_text(" ")) if time_el else None

    # The clock <i> also carries .text-muted, so scope to a <span>.
    type_el = soup.select_one(".auction-type span.text-muted")
    auction_type = _clean(type_el.get_text()) if type_el else None

    date_el = soup.select_one("span.dateTime")
    close_time = _clean(date_el.get_text()) if date_el else None

    location = _text_with_breaks(soup.select_one("#catalogLocationBlock"), sep=", ")

    catalog_el = soup.select_one("#catalogTitleBlock a")
    category = _clean(catalog_el.get_text()) if catalog_el else None

    # House: ga brand, else #termsHouseName, else the descGroup "by ..." line.
    house = product.get("brand")
    if not house:
        terms_house = soup.select_one("#termsHouseName")
        if terms_house:
            house = _clean(terms_house.get_text())
    if not house:
        by_el = soup.select_one(".descGroup .mb-1")
        if by_el:
            house = _clean(re.sub(r"^\s*by\s+", "", by_el.get_text(), flags=re.IGNORECASE))

    currency = None
    if lot_data is not None:
        currency = lot_data.get("data-currency-code")
    currency = currency or product.get("currency")

    catalog_ref = None
    if catalog_el and catalog_el.get("href"):
        match = CATALOG_SLUG_REF_RE.search(catalog_el["href"])
        if match:
            catalog_ref = match.group(1)
    if not catalog_ref:
        rfa = soup.select_one('a[href*="reqForApproval"]')
        if rfa and rfa.get("href"):
            match = CATALOG_REF_RE.search(rfa["href"])
            if match:
                catalog_ref = match.group(1)

    # Buyer's premium and conditions live in #termsPanel.
    terms_panel = soup.select_one("#termsPanel")
    terms_text = terms_panel.get_text(" ", strip=True) if terms_panel else ""
    premium_match = PREMIUM_OF_RE.search(terms_text) or PREMIUM_PREFIX_RE.search(terms_text)
    buyer_premium_pct = float(premium_match.group(1)) if premium_match else None
    buyer_premium = f"{premium_match.group(1)}%" if premium_match else None
    conditions_el = terms_panel.select_one("p.descGroup") if terms_panel else None
    conditions_of_sale = _clean(conditions_el.get_text(" ")) if conditions_el else None

    # Payment methods + shipping/pickup terms live in #payPanel.
    pay_sections = _panel_sections(soup.select_one("#payPanel"))
    accepted_payment = None
    shipping_terms = None
    for label, body in pay_sections.items():
        low = label.lower()
        if "payment" in low:
            accepted_payment = _clean(body)
        elif "shipping" in low or "pick" in low:
            shipping_terms = body.strip() or None

    overview_el = soup.select_one("#itemOverviewTranslatable") or soup.select_one("#itemOverviewPanel")
    description = _clean(overview_el.get_text(" ")) if overview_el else None

    resolved_url = url
    if not resolved_url:
        canonical = soup.select_one('link[rel="canonical"]')
        if canonical and canonical.get("href"):
            resolved_url = canonical["href"]

    status = _lot_status(lot_data, soup, product.get("variant", ""))

    return {
        "ref": ref,
        "catalog_ref": catalog_ref,
        "lot_number": lot_number,
        "title": title,
        "auction_house": house,
        "status": status,
        "auction_type": auction_type,
        "current_bid": current_bid,
        "current_bid_amount": current_bid_amount,
        "bids": bids,
        "next_bid": next_bid,
        "next_bid_amount": _money(next_bid),
        "buyer_premium": buyer_premium,
        "buyer_premium_pct": buyer_premium_pct,
        "currency": currency,
        "close_time": close_time,
        "time_remaining": time_remaining,
        "category": category,
        "location": location,
        "accepted_payment": accepted_payment,
        "shipping_terms": shipping_terms,
        "conditions_of_sale": conditions_of_sale,
        "description": description,
        "image_urls": _lot_images(soup),
        "url": resolved_url,
    }
