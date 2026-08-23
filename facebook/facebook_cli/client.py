"""Facebook client using BrowserAutomation for browser automation."""
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional
from urllib.parse import urlparse

from cli_tools_shared.http_session import (
    BrowserAuthState,
    BrowserAuthenticatedHttpClient,
    RelayFormRequest,
    RelayGraphQLClient,
    extract_embedded_define,
)
from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import print_info, print_warning
from cli_tools_shared._debug_logging import get_debug_logger

from .config import get_config
from .models import FACEBOOK_BASE_URL, MarketplaceListing, Group, GroupPost, Comment

logger = get_debug_logger("cli_tools.facebook.client")


MARKETPLACE_BASE = f"{FACEBOOK_BASE_URL}/marketplace"
MESSENGER_BASE = f"{FACEBOOK_BASE_URL}/messages/t"
GROUPS_BASE = f"{FACEBOOK_BASE_URL}/groups"
DEFAULT_LOCATION = "evansville"
FACEBOOK_DESKTOP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "Upgrade-Insecure-Requests": "1",
}
GROUP_DISCUSSION_FRIENDLY_NAME = "CometGroupDiscussionRootSuccessQuery"
GROUP_DISCUSSION_DOC_ID = "26647538378198347"
GROUP_DISCUSSION_BOOTSTRAP_MARKERS = [
    '["CurrentUserInitialData",',
    '["DTSGInitialData",',
    '["LSD",',
    f'"queryID":"{GROUP_DISCUSSION_DOC_ID}"',
    f'"queryName":"{GROUP_DISCUSSION_FRIENDLY_NAME}"',
]
GROUP_POST_THREAD_STOP_MARKERS = [
    "CometFeedStorySeoLLMCommentSummarySection_story",
]

# Facebook's own Marketplace search-results container. Captured live 2026-07-25:
# it is present on the search surface for BOTH a populated result set and a
# genuinely empty one, so its presence alone never means "there are results".
MARKETPLACE_RESULTS_CONTAINER_SELECTOR = '[aria-label="Collection of Marketplace items"]'

# The path segment Facebook rewrites a Marketplace URL to when it does not
# recognize the requested location slug. Facebook never errors on an unknown
# slug: it drops the slug and serves the LOGGED-IN ACCOUNT'S OWN home-city
# inventory instead. Measured live 2026-08-18:
#
#   /marketplace/losangeles/search/?query=lego%20bulk  ->
#       /marketplace/category/search/?query=lego%20bulk   (Evansville rows)
#   /marketplace/zzzzznotaplace/search/?query=lego%20bulk ->
#       /marketplace/category/search/?query=lego%20bulk   (Evansville rows)
#   /marketplace/losangeles/                           ->  /marketplace/
#
# while every valid slug kept its own segment and its own city's inventory
# (evansville, chicago, seattle, nyc -- each rendering
# "Location: <City>, <State>, Within 11 mi" in Facebook's own filter button).
# So the final URL's own location segment is the authoritative answer to
# "which city did Facebook actually search?".
MARKETPLACE_SLUGLESS_PATH_SEGMENT = "category"

# Inspect a loaded Marketplace list/search page before trusting an empty
# extraction. The only signal that means "this search legitimately has zero
# matches" is Facebook rendering its own results container together with the
# "No listings found for ... within N miles" heading (captured live 2026-07-25).
# Anything else -- missing page body, missing container, listing tiles present
# that the extractor could not parse, or a container that never settled -- is a
# broken read and must fail loudly instead of returning [].
MARKETPLACE_PAGE_STATE_JS = """(selector) => {
    const main = document.querySelector('[role="main"]');
    const headings = Array.from(
        document.querySelectorAll('[role="main"] h1, [role="main"] h2, [role="main"] h3')
    ).map((h) => (h.innerText || '').replace(/\\s+/g, ' ').trim()).filter(Boolean);
    const emptyHeading = headings.find((t) => /^No listings found\\b/i.test(t)) || null;
    const container = document.querySelector(selector);
    return {
        url: location.href,
        title: document.title,
        main_exists: main != null,
        container_exists: container != null,
        item_link_count: document.querySelectorAll('a[href*="/marketplace/item/"]').length,
        headings: headings.slice(0, 10),
        empty_heading: emptyHeading,
        no_results: container != null && emptyHeading != null,
    };
}"""

# Extract listings from a Marketplace list/search page, tile by tile.
#
# This reads each tile's DOM directly instead of parsing the flattened
# accessibility-tree name, because Facebook serves THREE tile variants
# (variants 1-2 captured live 2026-07-25, variant 3 captured live 2026-07-26):
#
#   1. aria-labelled:   "Arcade 1Up, $300, Newburgh, IN, listing 1356224139807798"
#   2. content-derived: "Just listed $400 Legos. Collection with instruction
#                        books Boonville, IN"
#   3. notification/prose (a "commerce_interesting_product" recommendation tile
#      Facebook injects into the grid, href carries
#      "?ref=notif&notif_t=commerce_interesting_product"):
#      "UnreadHuge Lot thousands crayons,colored pencils... listed for $50.00.
#      9h\u00b74 saved" -- rendered as a sentence with the title and price each
#      wrapped in their own <b> element instead of a dedicated span:
#      <div>Unread</div><b>Huge Lot ...</b> listed for <b>$50.00</b>.
#
# Variant 2 carries no delimiters at all, and on a discounted tile the current
# and struck-through prices are flattened together ("$50$60"), so any string
# parse of the accessible name is ambiguous or lossy -- variant 2 previously
# yielded ZERO parsed listings, which is what made an intermittently healthy
# search return []. The per-tile DOM is identical for variants 1-2: a span
# whose own text is the current price (carrying the struck-through original
# price as a nested span), followed by the title span and then the location
# span. Variant 3 has no such price/title spans at all -- the price and title
# text live inside <b> elements, so the span-own-text scan below never finds
# them and falls through to a second structural pass that reads the <b>
# elements directly. Variant 3 has no location field.
#
# ``unparsed`` reports tiles that rendered text but no usable price/title so the
# caller can fail loudly instead of under-reporting search results. Tiles that
# have not painted any text yet (scroll skeletons) are neither parsed nor
# reported.
LIST_PAGE_LISTINGS_JS = r"""() => {
    // Any Unicode currency symbol (\p{Sc}: $, \u00a3, \u20ac, ...), optionally prefixed with a
    // currency code the way Facebook renders foreign-currency listings ("CA$75").
    const PRICE = /^(?:\p{Lu}{0,3}\p{Sc}\s?[\d,]+(?:\.\d{2})?|Free|FREE)$/u;
    const ownText = (el) => {
        let text = "";
        for (const node of el.childNodes) {
            if (node.nodeType === Node.TEXT_NODE) text += node.textContent;
        }
        return text.trim();
    };
    const rows = [];
    const unparsed = [];
    const seen = new Set();
    for (const anchor of document.querySelectorAll('a[href*="/marketplace/item/"]')) {
        const match = anchor.href.match(/\/marketplace\/item\/(\d+)\//);
        if (match == null || seen.has(match[1])) continue;
        const itemId = match[1];
        seen.add(itemId);

        let price = "";
        let originalPrice = "";
        const labels = [];
        for (const span of anchor.querySelectorAll('span')) {
            const own = ownText(span);
            if (!own) continue;
            if (PRICE.test(own)) {
                // The first price span is the tile's current price; a nested
                // price span inside it is the struck-through original. Later
                // price spans are that nested element visited on its own.
                if (price !== "") continue;
                price = own;
                for (const child of span.children) {
                    const childText = (child.textContent || "").trim();
                    if (PRICE.test(childText)) { originalPrice = childText; break; }
                }
                continue;
            }
            // Title and location always follow the price span; badges that
            // precede it ("Just listed") are not listing fields.
            if (price !== "") labels.push(own);
        }

        if (price === "" || labels.length === 0) {
            // Notification/prose tile (variant 3): title and price are each
            // wrapped in a <b> element inside one sentence, e.g.
            // "<b>Title</b> listed for <b>$50.00</b>." -- not dedicated spans,
            // so the scan above never populates `price`/`labels`. Both <b>
            // elements share the same parent, and that parent's OWN text (the
            // words connecting the two <b> elements) contains "listed for",
            // which is what distinguishes this from an unrelated pair of bold
            // elements elsewhere in the tile.
            const boldEls = anchor.querySelectorAll('b');
            if (boldEls.length >= 2) {
                const titleBold = boldEls[0];
                const priceBold = boldEls[boldEls.length - 1];
                const parent = titleBold.parentElement;
                if (parent != null && parent === priceBold.parentElement
                        && /\blisted for\b/i.test(ownText(parent))) {
                    const priceText = ownText(priceBold);
                    const titleText = ownText(titleBold);
                    if (PRICE.test(priceText) && titleText !== "") {
                        price = priceText;
                        for (const child of priceBold.children) {
                            const childText = (child.textContent || "").trim();
                            if (PRICE.test(childText)) { originalPrice = childText; break; }
                        }
                        labels.push(titleText);
                    }
                }
            }
        }

        if (price === "" || labels.length === 0) {
            const tileText = (anchor.innerText || "").trim();
            if (tileText !== "") unparsed.push({item_id: itemId, text: tileText.slice(0, 200)});
            continue;
        }
        rows.push({
            item_id: itemId,
            title: labels[0],
            price: price,
            original_price: originalPrice || null,
            location: labels.length > 1 ? labels[1] : null,
            url: "/marketplace/item/" + itemId + "/",
        });
    }
    return {rows: rows, unparsed: unparsed};
}"""

# Extract the listing's CURRENT price from a Marketplace detail page.
#
# On a price-dropped listing Facebook renders the current price and the
# struck-through original price inside the SAME price element, as a leading
# text node followed by a nested element (captured live 2026-07-25):
#
#   <span dir="auto">$15<span class="..."><span class="...">$20</span></span></span>
#
# Reading that element's text (or innerText line) yields "$15$20", which the
# price normalizer then parses as 1520.0. This extractor instead reads the price
# element's OWN direct text nodes for the current price and treats a nested
# price element as the original (pre-drop) price. That split is structural, so
# it does not depend on Facebook's obfuscated CSS class names.
DETAIL_PAGE_PRICE_JS = r"""() => {
    const empty = {price: "", originalPrice: ""};
    const main = document.querySelector('[role="main"]');
    if (main == null) return empty;
    const h1 = main.querySelector('h1');
    if (h1 == null) return empty;
    // Any Unicode currency symbol (\p{Sc}: $, \u00a3, \u20ac, ...), optionally prefixed with a
    // currency code the way Facebook renders foreign-currency listings ("CA$75").
    const PRICE = /^(?:\p{Lu}{0,3}\p{Sc}\s?[\d,]+(?:\.\d{2})?|Free|FREE)$/u;
    const ownText = (el) => {
        let text = "";
        for (const node of el.childNodes) {
            if (node.nodeType === Node.TEXT_NODE) text += node.textContent;
        }
        return text.trim();
    };
    const walker = document.createTreeWalker(main, NodeFilter.SHOW_ELEMENT);
    let passedTitle = false;
    let el;
    while ((el = walker.nextNode()) !== null) {
        if (!passedTitle) {
            if (el === h1) passedTitle = true;
            continue;
        }
        if (h1.contains(el)) continue;
        const current = ownText(el);
        if (!PRICE.test(current)) continue;
        let original = "";
        for (const child of el.children) {
            const childText = (child.textContent || "").trim();
            if (PRICE.test(childText)) { original = childText; break; }
        }
        return {price: current, originalPrice: original};
    }
    return empty;
}"""

# Extract the image URLs belonging to the listing's OWN media gallery.
#
# Facebook tags every image in a listing's gallery -- the hero image and each
# thumbnail -- with alt="Product photo of <listing title>" (captured live
# 2026-07-25). Sidebar advertisement creatives (which are served from the same
# scontent CDN and live in a [role="group"][aria-label="Video player"] slot) and
# the recommended-listing grid carry different alt text, so scoping to that alt
# keeps scraped advertisements out of a listing's images.
DETAIL_PAGE_IMAGES_JS = """() => {
    const main = document.querySelector('[role="main"]');
    if (main == null) return [];
    const imgs = Array.from(main.querySelectorAll('img[alt^="Product photo of"]'));
    const urls = imgs
        .filter((i) => i.naturalWidth > 100 && i.closest('a[href*="/marketplace/item/"]') == null)
        .map((i) => i.src);
    return [...new Set(urls)];
}"""

# Capture Facebook's own per-listing fulfillment model.
#
# Marketplace models fulfillment per listing as a `delivery_types` array
# (captured live 2026-07-26): IN_PERSON, PUBLIC_MEETUP, DOOR_PICKUP,
# DOOR_DROPOFF, SHIPPING_ONSITE. NONE of it is rendered as text. The detail page
# shows only the seller's free-form meet-up prose ("Meet on Kansas Road in
# Evansville"), and a search tile shows either a location OR the string
# "Ships to you" -- and which one it shows is a DISTANCE decision, not a
# fulfillment one, so a shipping-capable listing near the viewer still renders a
# location. The rendered page therefore cannot answer "does this ship?" at all.
#
# The answer lives in the Relay payload that hydrates the page:
#
#   {"__typename":"GroupCommerceProductItem","id":"26999388286428618",
#    "location_text":{"text":"Evansville, IN"},"delivery_types":["IN_PERSON"],
#    "listing_price":{...}, ...}
#
# Two transports carry it and both are captured here, because neither alone is
# complete:
#   1. `script[type="application/json"]` blobs in the served HTML -- the detail
#      page's own listing, and a search page's FIRST batch of tiles (24 live).
#   2. Relay pagination responses -- every tile loaded by scrolling. These are
#      XHR/fetch bodies, so the hook must be installed BEFORE scrolling starts.
#
# Both `id` and the `delivery_types`/`location_text` fields are Facebook's own
# GraphQL schema names, not rendered text or CSS classes, so this does not
# depend on markup Facebook reshuffles between builds.
#
# ONE LISTING, TWO IDS (captured live 2026-08-04). Facebook identifies a listing
# by its listing id AND by a story/post id, and different surfaces link by
# different ones. A search tile links by the listing id; an injected
# "commerce_interesting_product" notification tile links by the post id. The
# listing node is always keyed by the LISTING id, and publishes the post id in
# two of its own fields:
#
#   {"id":"1533173811265557", "delivery_types":["IN_PERSON","PUBLIC_MEETUP"],
#    "story":{"post_id":"28800686242866906", ...},
#    "product_item":{"id":"28800686242866906", ...}}
#
# So `capture.aliases` maps post id -> listing id, and a lookup by either id
# reaches the same listing. Without it, `marketplace get 28800686242866906`
# failed on a page that fully described the listing under its other id.
#
# The same nodes also carry Facebook's own listing-state booleans (is_sold /
# is_pending / is_live) and, on search payloads, `primary_listing_photo`. Both
# are captured here so the list surface answers "is it still for sale?" and
# "what does it look like?" without a per-listing detail navigation.
INSTALL_DELIVERY_CAPTURE_JS = r"""() => {
    if (window.__fbDeliveryCapture != null) {
        return {installed: false, listings: Object.keys(window.__fbDeliveryCapture.deliveryTypes).length};
    }
    const capture = {
        deliveryTypes: {}, locationText: {}, availability: {}, primaryImage: {},
        seller: {},
        aliases: {}, conflicts: {}, availabilityConflicts: {}, aliasConflicts: {},
        payloads: 0, parseErrors: 0,
    };
    window.__fbDeliveryCapture = capture;

    const record = (node) => {
        const id = String(node.id);
        if (Array.isArray(node.delivery_types)) {
            const seen = capture.deliveryTypes[id];
            if (seen === undefined) {
                capture.deliveryTypes[id] = node.delivery_types;
            } else if (seen.slice().sort().join("|") !== node.delivery_types.slice().sort().join("|")) {
                // Two payloads described the same listing differently. Recorded
                // rather than resolved so the caller can fail loudly instead of
                // reporting whichever arrived first.
                capture.conflicts[id] = [seen, node.delivery_types];
            }
        }
        if (node.location_text != null && typeof node.location_text.text === "string") {
            capture.locationText[id] = node.location_text.text;
        }
        if (typeof node.is_sold === "boolean" || typeof node.is_pending === "boolean"
            || typeof node.is_live === "boolean") {
            const state = {
                is_sold: node.is_sold === true,
                is_pending: node.is_pending === true,
                is_live: node.is_live === true,
            };
            const seen = capture.availability[id];
            if (seen === undefined) {
                capture.availability[id] = state;
            } else if (seen.is_sold !== state.is_sold || seen.is_pending !== state.is_pending
                       || seen.is_live !== state.is_live) {
                // A stale payload claiming "live" alongside a fresh one claiming
                // "sold" is exactly the answer a consumer must not get wrong.
                capture.availabilityConflicts[id] = [seen, state];
            }
        }
        if (node.primary_listing_photo != null && node.primary_listing_photo.image != null
            && typeof node.primary_listing_photo.image.uri === "string") {
            capture.primaryImage[id] = node.primary_listing_photo.image.uri;
        }
        // Who is selling it, from Facebook's own listing node rather than the
        // rendered "Seller information" heading. That heading was already read
        // on the detail page -- only to mark where the description ends -- and
        // then thrown away, so every consumer got a listing with no seller.
        // Reading it here means the search surface answers too, and a listing
        // whose payload names no seller stays absent instead of guessed.
        const seller = node.marketplace_listing_seller;
        if (seller != null && (seller.id != null || typeof seller.name === "string")) {
            capture.seller[id] = {
                id: seller.id != null ? String(seller.id) : null,
                name: typeof seller.name === "string" ? seller.name : null,
            };
        }
        // Facebook's own alternate identifier for this same listing.
        const aliasSources = [
            node.story != null ? node.story.post_id : null,
            node.product_item != null ? node.product_item.id : null,
        ];
        for (const alias of aliasSources) {
            if (alias == null) continue;
            const aliasId = String(alias);
            if (aliasId === id) continue;
            const seen = capture.aliases[aliasId];
            if (seen === undefined) {
                capture.aliases[aliasId] = id;
            } else if (seen !== id) {
                capture.aliasConflicts[aliasId] = [seen, id];
            }
        }
    };
    const walk = (node) => {
        if (node === null || typeof node !== "object") return;
        if (Array.isArray(node)) { for (const value of node) walk(value); return; }
        const hasListingState = node.__typename === "GroupCommerceProductItem"
            && (typeof node.is_sold === "boolean" || typeof node.is_pending === "boolean"
                || typeof node.is_live === "boolean");
        if (node.id != null && (Array.isArray(node.delivery_types)
            || node.location_text != null || hasListingState)) {
            record(node);
        }
        for (const key of Object.keys(node)) walk(node[key]);
    };
    const hasCaptureData = (text) => Boolean(text) && (
        text.indexOf("delivery_types") !== -1
        || text.indexOf("location_text") !== -1
        || (text.indexOf("GroupCommerceProductItem") !== -1
            && (text.indexOf("is_sold") !== -1 || text.indexOf("is_pending") !== -1
                || text.indexOf("is_live") !== -1))
    );
    const harvest = (text) => {
        if (!hasCaptureData(text)) return;
        capture.payloads++;
        // Relay streams a response as several newline-separated JSON documents,
        // optionally behind Facebook's anti-JSON-hijacking prefix.
        for (const line of text.replace(/^\s*for\s*\(;;\);/, "").split("\n")) {
            const trimmed = line.trim();
            if (!hasCaptureData(trimmed)) continue;
            try { walk(JSON.parse(trimmed)); } catch (e) { capture.parseErrors++; }
        }
    };

    for (const script of document.querySelectorAll('script[type="application/json"]')) {
        const text = script.textContent || "";
        if (!hasCaptureData(text)) continue;
        try { walk(JSON.parse(text)); } catch (e) { capture.parseErrors++; }
    }

    const originalSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.send = function (...args) {
        this.addEventListener("load", () => {
            try { harvest(this.responseText); } catch (e) { capture.parseErrors++; }
        });
        return originalSend.apply(this, args);
    };
    const originalFetch = window.fetch;
    window.fetch = function (...args) {
        return originalFetch.apply(this, args).then((response) => {
            try { response.clone().text().then(harvest).catch(() => {}); } catch (e) {}
            return response;
        });
    };
    return {installed: true, listings: Object.keys(capture.deliveryTypes).length};
}"""

READ_DELIVERY_CAPTURE_JS = """() => window.__fbDeliveryCapture || null"""

# A removed listing redirects to the local Marketplace feed with Facebook's
# explicit ``unavailable_product=1`` query marker and a matching banner. This
# status-only signal was captured live from listing 1317865033763867 on
# 2026-08-15. Both indicators must agree; missing listing data alone never
# becomes an unavailable result.
MARKETPLACE_STATUS_PAGE_JS = r"""() => {
    const mainText = document.querySelector('[role="main"]')?.innerText || "";
    const unavailableMessage = mainText.split("\n")
        .some((line) => line.trim() === "This listing isn't available anymore");
    const unavailableProduct = new URL(location.href).searchParams.get("unavailable_product") === "1";
    return {
        unavailableProduct,
        unavailableMessage,
        currentUrl: location.href,
    };
}"""

# The maps INSTALL_DELIVERY_CAPTURE_JS writes, listed here so the Python reader
# fails loudly if the two ever drift apart.
CAPTURE_MAPS = ("deliveryTypes", "locationText", "availability", "primaryImage", "seller",
                "aliases")

# Conflict maps and what a conflict in each one means. A conflict is fatal: two
# payloads describing the same listing differently makes first-writer-wins a
# coin flip, and the losing answer is silently wrong.
CAPTURE_CONFLICT_MAPS = {
    "conflicts": "delivery_types",
    "availabilityConflicts": "listing-state booleans (is_sold/is_pending/is_live)",
    "aliasConflicts": "listing-id aliases",
}

# Facebook renders "Ships to you" in a search tile's location position when the
# listing is too far away to show a place name (captured live 2026-07-26). It is
# a fulfillment hint, not a location, so it must never be reported as one --
# `delivery_types` carries the fulfillment answer for that tile.
TILE_SHIPPING_PLACEHOLDER_LOCATION = "Ships to you"


class GroupDiscussionPreloadMissing(ClientError):
    """Facebook omitted the Relay request metadata needed for feed GraphQL."""


class FacebookClient:
    """Client that uses BrowserAutomation to automate Facebook."""

    COMMENT_COMPOSER_SELECTOR = '[role="textbox"][contenteditable="true"]'

    def __init__(self):
        t0 = time.monotonic()
        self.config = get_config()
        self._browser_instance = None
        self._http_client: Optional[BrowserAuthenticatedHttpClient] = None
        logger.debug("__init__: config loaded in %.2fs", time.monotonic() - t0)

    @property
    def _browser(self):
        if self._browser_instance is None:
            t0 = time.monotonic()
            from .browser import FacebookBrowser
            self._browser_instance = FacebookBrowser(self.config)
            logger.debug("_browser: FacebookBrowser created in %.2fs", time.monotonic() - t0)
        return self._browser_instance

    def _get_page(self, url: str, settle_ms: int = 3000):
        """Get a page navigated to the given URL."""
        t0 = time.monotonic()
        logger.debug("_get_page: requesting page for %s", url)
        page = self._browser.get_page(url)
        logger.debug("_get_page: get_page() returned in %.2fs", time.monotonic() - t0)
        if settle_ms:
            page.wait_for_timeout(settle_ms)
            logger.debug("_get_page: %sms wait done, total %.2fs", settle_ms, time.monotonic() - t0)
        return page

    def _snapshot(self, page) -> str:
        """Take an accessibility tree snapshot and return the YAML content.

        Uses the shared browser driver's Playwright-backed
        ``aria_snapshot()`` helper so the client stays on the
        BrowserAutomation abstraction.
        """
        t0 = time.monotonic()
        try:
            result = page.aria_snapshot(timeout=5000)
            logger.debug("_snapshot: captured in %.2fs (%d chars)", time.monotonic() - t0, len(result))
            return result
        except Exception as e:
            raise ClientError(f"Failed to capture page snapshot: {e}")

    @staticmethod
    def _visible_comment_composer_js() -> str:
        """Return JS that finds the active visible Facebook comment composer.

        Facebook changes the group post composer between Lexical builds. The
        visible contenteditable comment box can lack the old
        ``data-lexical-editor=\"true\"`` marker, so public writes locate the
        composer by the stable accessibility contract first: visible textbox +
        contenteditable, excluding obvious non-comment textboxes such as Search.
        Lexical-marked boxes are still preferred when present, but they are not
        required.
        """
        return r'''
            () => {
                const isVisible = (el) => {
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0;
                };
                const describe = (el) => {
                    const label = el.getAttribute("aria-label") || "";
                    const placeholder = el.getAttribute("aria-placeholder") || "";
                    const text = (el.innerText || el.textContent || "").trim();
                    const combined = (label + " " + placeholder + " " + text).toLowerCase();
                    return {
                        label,
                        placeholder,
                        text: text.slice(0, 80),
                        hasLexical: el.getAttribute("data-lexical-editor") === "true",
                        isCommentish: /comment|reply|answer|write/.test(combined),
                        isSearch: /search/.test(combined),
                    };
                };
                const all = Array.from(document.querySelectorAll('[role="textbox"][contenteditable="true"]'))
                    .filter(isVisible)
                    .map((el) => ({el, info: describe(el)}))
                    .filter((item) => !item.info.isSearch);
                const lexical = all.filter((item) => item.info.hasLexical);
                const commentish = all.filter((item) => item.info.isCommentish);
                const candidates = lexical.length ? lexical : (commentish.length ? commentish : all);
                return {
                    count: candidates.length,
                    totalVisibleTextboxes: all.length,
                    usedFilter: lexical.length ? "lexical" : (commentish.length ? "commentish" : "visible-contenteditable-textbox"),
                    candidates: candidates.map((item) => item.info),
                };
            }
        '''

    def _comment_composer_state(self, page) -> Dict:
        state = page.evaluate(self._visible_comment_composer_js())
        if isinstance(state, dict):
            return state
        return {"count": 0, "error": "comment composer probe returned non-dict state"}

    def _wait_for_visible_comment_composer(self, page, timeout_ms: int = 10000) -> Dict:
        deadline = time.monotonic() + (timeout_ms / 1000)
        last_state: Dict = {"count": 0}
        while time.monotonic() < deadline:
            last_state = self._comment_composer_state(page)
            if last_state.get("count") == 1:
                return last_state
            page.wait_for_timeout(250)
        raise ClientError(
            "Timed out waiting for exactly one visible Facebook comment textbox. "
            f"Last composer state: {last_state}"
        )

    def _insert_text_into_visible_comment_composer(self, page, text: str) -> Dict:
        js = (
            '(text) => {'
            ' const isVisible = (el) => {'
            '   const r = el.getBoundingClientRect();'
            '   return r.width > 0 && r.height > 0;'
            ' };'
            ' const describe = (el) => {'
            '   const label = el.getAttribute("aria-label") || "";'
            '   const placeholder = el.getAttribute("aria-placeholder") || "";'
            '   const body = (label + " " + placeholder + " " + (el.innerText || el.textContent || "")).toLowerCase();'
            '   return {'
            '     label,'
            '     placeholder,'
            '     hasLexical: el.getAttribute("data-lexical-editor") === "true",'
            '     isCommentish: /comment|reply|answer|write/.test(body),'
            '     isSearch: /search/.test(body),'
            '   };'
            ' };'
            ' const all = Array.from(document.querySelectorAll(\'[role="textbox"][contenteditable="true"]\'))'
            '   .filter(isVisible)'
            '   .map((el) => ({el, info: describe(el)}))'
            '   .filter((item) => !item.info.isSearch);'
            ' const lexical = all.filter((item) => item.info.hasLexical);'
            ' const commentish = all.filter((item) => item.info.isCommentish);'
            ' const candidates = lexical.length ? lexical : (commentish.length ? commentish : all);'
            ' if (candidates.length !== 1) {'
            '   return {'
            '     success: false,'
            '     error: "Expected exactly one visible comment textbox, found " + candidates.length,'
            '     count: candidates.length,'
            '     candidates: candidates.map((item) => item.info),'
            '   };'
            ' }'
            ' const commentBox = candidates[0].el;'
            ' commentBox.focus();'
            ' document.execCommand("insertText", false, text);'
            ' return {'
            '   success: true,'
            '   placeholder: commentBox.getAttribute("aria-placeholder") || commentBox.getAttribute("aria-label") || "",'
            '   usedFilter: lexical.length ? "lexical" : (commentish.length ? "commentish" : "visible-contenteditable-textbox"),'
            '   hasLexical: candidates[0].info.hasLexical,'
            ' };'
            ' }'
        )
        typed = page.evaluate(js, text)
        if isinstance(typed, dict):
            return typed
        return {"success": False, "error": "comment composer insert returned non-dict result"}

    def _assert_authenticated_page(self, page, requested_url: str, surface: str) -> None:
        """Fail fast when Facebook serves a login or challenge page."""
        current_url = getattr(page, "url", "") or ""
        if any(token in current_url for token in ("/login", "two_step_verification", "/checkpoint")):
            raise ClientError(
                f"Facebook redirected {surface} to {current_url} "
                f"(requested: {requested_url}). Run 'facebook auth login --force' to authenticate."
            )
        blocked = page.evaluate(
            """() => ({
                loginForm: !!document.querySelector('input[name="email"], input[name="pass"]'),
                recaptcha: !!document.querySelector('iframe[src*="recaptcha"], iframe#captcha-recaptcha')
            })"""
        )
        if isinstance(blocked, dict) and blocked.get("recaptcha"):
            raise ClientError(
                f"Facebook presented a reCAPTCHA challenge for {surface}. "
                "Complete 'facebook auth login --force' in a headed browser."
            )
        if isinstance(blocked, dict) and blocked.get("loginForm"):
            raise ClientError(
                f"Facebook served a login form for {surface} at {current_url}. "
                f"(requested: {requested_url}). Run 'facebook auth login --force' to authenticate."
            )

    @staticmethod
    def _page_has_c_user(page) -> bool:
        """Return True when the persistent profile still carries Facebook's ``c_user`` cookie.

        ``c_user`` is the single authentication cookie this CLI already treats as
        the source of truth: ``browser.py`` declares it in
        ``AUTH_COOKIE_PATTERNS = ["c_user"]`` and ``_facebook_http_client``
        requires it (``required_cookies=["c_user"]``). It is present only for a
        live logged-in session; when the session breaks, the profile drops it
        (see the CLI's Known Issue #1). This reads the cookie through the shared
        ``BrowserHarnessService.cookie_list()`` CDP accessor (``Network.getAllCookies``)
        rather than ``document.cookie`` so a future httpOnly hardening on
        Facebook's side would not blind the check.
        """
        cookies = page.cookie_list()
        if not isinstance(cookies, list):
            raise ClientError(
                "Facebook cookie probe returned a non-list cookie payload while "
                f"checking Marketplace authentication: {type(cookies).__name__}."
            )
        for cookie in cookies:
            if not isinstance(cookie, dict):
                continue
            if cookie.get("name") == "c_user" and str(cookie.get("value") or "").strip():
                return True
        return False

    @staticmethod
    def _page_has_login_form(page) -> bool:
        """Return True when a Facebook login/challenge form is present in the DOM."""
        present = page.evaluate(
            """() => !!document.querySelector('input[name="email"], input[name="pass"]')"""
        )
        return bool(present)

    def _assert_marketplace_authenticated(self, page, requested_url: str, surface: str) -> None:
        """Fail fast when Facebook serves a login-walled Marketplace page.

        Public Marketplace URLs render for logged-out visitors, but Facebook
        increasingly answers them with a login wall (an empty results shell plus
        a login dialog/redirect). Extraction against that shell silently returns
        ``[]`` / ``Unknown``, which hides a broken session. This assertion turns
        that into a loud, actionable failure.

        Detection is based on AUTH STATE, never on result count, so a genuine
        empty-but-authenticated search passes cleanly:
          - PRIMARY: the ``c_user`` cookie (see :meth:`_page_has_c_user`).
          - SECONDARY corroboration: a ``/login`` / ``/checkpoint`` /
            ``two_step_verification`` redirect URL, or a rendered login form.

        The session is authenticated only when ``c_user`` is present AND the page
        is neither on a login redirect nor showing a login form. Otherwise it
        raises ``ClientError`` with the exact re-auth remediation.
        """
        current_url = getattr(page, "url", "") or ""
        login_redirect = any(
            token in current_url
            for token in ("/login", "/checkpoint", "two_step_verification")
        )
        has_c_user = self._page_has_c_user(page)
        has_login_form = self._page_has_login_form(page)
        if has_c_user and not login_redirect and not has_login_form:
            return
        raise ClientError(
            f"Facebook served a login-walled Marketplace page for {surface} at "
            f"{current_url or requested_url} (requested: {requested_url}; "
            f"c_user cookie present: {has_c_user}; login redirect: {login_redirect}; "
            f"login form present: {has_login_form}). "
            "The saved browser session is expired or logged out. "
            "Run 'facebook auth login --force' to re-authenticate."
        )

    def _group_post_ref_parts(self, post_ref: str) -> Dict[str, str]:
        """Return canonical URL, group ID, and stable post ID for a group post ref."""
        if post_ref.startswith("http"):
            url = post_ref
        else:
            url = f"{GROUPS_BASE}/{post_ref}"

        post_match = re.search(r"/posts/(\d+)", url) or re.search(r"/permalink/(\d+)", url)
        group_match = re.search(r"/groups/([^/?]+)/", url)
        if not post_match:
            raise ClientError(f"Post URL does not contain a stable post ID: {url}")
        if not group_match:
            raise ClientError(f"Post URL does not contain a group ID: {url}")

        group_id = group_match.group(1)
        post_id = post_match.group(1)
        canonical_url = f"{GROUPS_BASE}/{group_id}/posts/{post_id}/"
        return {"url": canonical_url, "group_id": group_id, "post_id": post_id}

    def _wait_for_rendered_text(self, page, text: str, selector: str, timeout_ms: int) -> None:
        """Wait until text appears outside an editable textbox in a page region.

        Kept for backward compatibility (used by create_post). Prefer
        ``_wait_for_composer_cleared`` for comment/reply flows: Facebook strips
        Markdown (``**bold**``, link syntax) when rendering comments, so a literal
        substring search against the original input text is unreliable for any
        text containing formatting characters.
        """
        deadline = time.monotonic() + (timeout_ms / 1000)
        js = (
            '(args) => {'
            ' const root = document.querySelector(args.selector);'
            ' if (!root) return false;'
            ' const nodes = [...root.querySelectorAll("*")];'
            ' return nodes.some(el => {'
            '   if (el.closest(\'[role="textbox"][contenteditable="true"]\')) return false;'
            '   const value = (el.innerText || el.textContent || "").trim();'
            '   return value.includes(args.text);'
            ' });'
            ' }'
        )
        while time.monotonic() < deadline:
            if page.evaluate(js, {"selector": selector, "text": text}):
                return
            page.wait_for_timeout(500)
        raise ClientError(f"Timed out waiting for submitted text to render: {text[:80]}")

    def _wait_for_composer_cleared(self, page, timeout_ms: int) -> Dict:
        """Wait until the visible Lexical comment composer is empty.

        After Facebook accepts a comment/reply, it clears the composer's
        contenteditable region. This is a far more reliable success signal than
        searching for the submitted text in the rendered comments list, because:
          - Facebook strips Markdown formatting (``**bold**``, ``[text](url)``)
            when rendering comments, so the literal input substring may never
            appear in the DOM.
          - New comments may be appended via React portals or virtualized lists
            that paint outside the polled selector.
          - Whitespace and entity normalization further break naive substring
            matching for longer comments.

        Returns a status dict instead of raising; the caller decides whether a
        composer-not-cleared state is fatal or worth a secondary check (comment-
        count delta, markdown-stripped text match) before failing.

        Returns:
            {"cleared": True,  "reason": "composer-empty"|"composer-removed"} on success
            {"cleared": False, "remaining": [str, ...]}                       on timeout
        """
        deadline = time.monotonic() + (timeout_ms / 1000)
        js = (
            '() => {'
            ' const boxes = Array.from(document.querySelectorAll('
            '   \'[role="textbox"][contenteditable="true"]\''
            ' )).filter(el => {'
            '   const r = el.getBoundingClientRect();'
            '   const label = ((el.getAttribute("aria-label") || "") + " " + (el.getAttribute("aria-placeholder") || "")).toLowerCase();'
            '   return r.width > 0 && r.height > 0 && !label.includes("search");'
            ' });'
            ' if (boxes.length === 0) {'
            # Composer disappeared entirely — that also counts as cleared
            # (e.g. reply composers collapse after submit).
            '   return {cleared: true, reason: "composer-removed"};'
            ' }'
            ' const nonEmpty = boxes.filter(b => (b.textContent || "").trim().length > 0);'
            ' if (nonEmpty.length === 0) {'
            '   return {cleared: true, reason: "composer-empty"};'
            ' }'
            ' return {'
            '   cleared: false,'
            '   remaining: nonEmpty.map(b => (b.textContent || "").trim().slice(0, 80))'
            ' };'
            ' }'
        )
        last_state: Dict = {"cleared": False, "remaining": []}
        while time.monotonic() < deadline:
            state = page.evaluate(js)
            if isinstance(state, dict):
                last_state = state
                if state.get("cleared"):
                    return state
            page.wait_for_timeout(500)
        return last_state

    @staticmethod
    def _normalize_for_match(text: str) -> str:
        """Normalize text for fuzzy DOM matching.

        Strips Markdown formatting characters Facebook drops during rendering,
        collapses whitespace, and lowercases. Used as a "did our text appear
        anywhere on the page" secondary check when the primary composer-cleared
        signal is inconclusive.
        """
        if not text:
            return ""
        # Strip ``**bold**`` and ``__bold__`` markers
        cleaned = re.sub(r"\*+|_+", "", text)
        # Strip Markdown link syntax ``[label](url)`` -> ``label url``
        cleaned = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 \2", cleaned)
        # Collapse all whitespace
        cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
        return cleaned

    def _count_post_comments(self, page) -> int:
        """Count visible comment articles within the active post.

        Returns 0 if no post article is found, or -1 if the JS evaluator failed.
        Used as a delta signal: if the count goes up after submit, our comment
        landed even when the composer-cleared check is inconclusive.
        """
        js = (
            '() => {'
            ' const main = document.querySelector(\'[role="main"]\');'
            ' if (!main) return -1;'
            # The post itself is a [role=article]; nested [role=article] under
            # it are the comments. Count any nested article whose ancestor is
            # the outermost article in [role=main].
            ' const articles = Array.from(main.querySelectorAll(\'[role="article"]\'));'
            ' if (articles.length === 0) return 0;'
            # The first article in document order is typically the post; treat
            # everything else as comments.
            ' return Math.max(0, articles.length - 1);'
            ' }'
        )
        try:
            value = page.evaluate(js)
            return int(value) if isinstance(value, (int, float)) else -1
        except Exception:
            return -1

    def _text_appears_on_page(self, page, normalized: str) -> bool:
        """Check whether ``normalized`` appears anywhere outside the composer.

        Compares against a normalized snapshot of the page text so that
        Markdown-stripped content still matches. Returns False on any error so
        callers can treat it as "inconclusive, fall through to next check."
        """
        if not normalized:
            return False
        # Search a slice that's distinctive enough to avoid false positives but
        # short enough to dodge whitespace/entity drift in the rest of the body.
        needle = normalized[:120]
        if len(needle) < 20:
            return False
        js = (
            '(args) => {'
            ' const main = document.querySelector(\'[role="main"]\') || document.body;'
            ' if (!main) return false;'
            ' const raw = (main.innerText || main.textContent || "");'
            ' const cleaned = raw'
            '   .replace(/\\*+|_+/g, "")'
            '   .replace(/\\s+/g, " ")'
            '   .toLowerCase();'
            ' return cleaned.indexOf(args.needle) !== -1;'
            ' }'
        )
        try:
            return bool(page.evaluate(js, {"needle": needle}))
        except Exception:
            return False

    def _verify_comment_landed(
        self,
        page,
        text: str,
        comment_count_before: int,
        composer_timeout_ms: int = 10000,
        secondary_timeout_ms: int = 10000,
    ) -> Dict:
        """Multi-stage verification that a submitted comment/reply actually posted.

        Stage 1: composer-cleared (most reliable signal).
        Stage 2: comment-count delta (count went from N -> N+).
        Stage 3: markdown-stripped text appears on page.

        Returns:
            {"verification": "confirmed",                     "signal": "composer-cleared"|"count-delta"|"text-appeared"}
            {"verification": "render-timeout-likely-success", "signal": "composer-cleared-but-no-other-evidence", "diagnostic": ...}
        Raises ClientError only when ALL three checks fail — that means the submit truly didn't land.
        """
        composer_state = self._wait_for_composer_cleared(page, timeout_ms=composer_timeout_ms)
        composer_cleared = bool(composer_state.get("cleared"))

        normalized = self._normalize_for_match(text)

        # Stage 2 + 3: poll for count-delta or text-appeared, regardless of
        # composer state. This corroborates the composer signal AND catches
        # the rare case where the composer didn't fully clear but the comment
        # did land (e.g. FB re-focuses the composer with stale text).
        deadline = time.monotonic() + (secondary_timeout_ms / 1000)
        last_count = comment_count_before
        while time.monotonic() < deadline:
            count_now = self._count_post_comments(page)
            if count_now >= 0:
                last_count = count_now
                if comment_count_before >= 0 and count_now >= comment_count_before + 1:
                    return {"verification": "confirmed", "signal": "count-delta",
                            "commentCountBefore": comment_count_before, "commentCountAfter": count_now}
            if self._text_appears_on_page(page, normalized):
                return {"verification": "confirmed", "signal": "text-appeared",
                        "commentCountBefore": comment_count_before, "commentCountAfter": last_count}
            if composer_cleared and (time.monotonic() - (deadline - secondary_timeout_ms / 1000)) > 3.0:
                # We have one strong signal (composer cleared) and have given
                # the page a few seconds to render. That's good enough — return
                # confirmed via composer-cleared without burning the full
                # secondary timeout.
                return {"verification": "confirmed", "signal": "composer-cleared",
                        "commentCountBefore": comment_count_before, "commentCountAfter": last_count}
            page.wait_for_timeout(500)

        # Secondary timeout exhausted.
        if composer_cleared:
            # The strongest single signal fired; the corroborators were
            # inconclusive (FB likely lazy-rendering the new comment off-DOM).
            # Treat this as likely-success rather than a hard failure;
            # callers record the weaker verification signal accordingly.
            return {
                "verification": "render-timeout-likely-success",
                "signal": "composer-cleared-but-no-other-evidence",
                "diagnostic": {
                    "commentCountBefore": comment_count_before,
                    "commentCountAfter": last_count,
                    "composerReason": composer_state.get("reason"),
                },
            }

        # No signal fired at all. The submit truly didn't land.
        raise ClientError(
            "Comment submit verification failed: composer never cleared, comment "
            f"count did not increment ({comment_count_before} -> {last_count}), and "
            f"the submitted text never appeared on the page. Composer remaining text: "
            f"{composer_state.get('remaining', [])}."
        )

    def _iter_comment_tree(self, comments: Optional[List[Comment]]):
        """Yield comments and nested replies from a GroupPost comment tree."""
        for comment in comments or []:
            yield comment
            yield from self._iter_comment_tree(comment.replies)

    def _wait_for_comment_on_exact_post(
        self,
        group_id: str,
        post_id: str,
        text: str,
        timeout_ms: int,
    ) -> Dict:
        """Verify the submitted text exists on the exact requested post ID.

        Uses substring containment rather than exact equality to detect the
        posted comment.  Facebook may:
          - Truncate long comment text in the Relay payload (so comment.text is
            shorter than the submitted text).
          - Store plain text while the submitted input contained Markdown
            formatting characters that _normalize_for_match already strips.
          - Prepend a mention prefix or otherwise normalise whitespace/entities.

        We therefore check whether a distinctive prefix of the submitted
        normalized text (up to 120 chars, matching the threshold used by
        _text_appears_on_page) appears anywhere inside the normalized comment
        text, or — for very short comments where the Relay text may be slightly
        longer — vice versa.
        """
        normalized = self._normalize_for_match(text)
        if not normalized:
            raise ClientError("Cannot verify an empty comment.")
        # A needle length of 120 chars is distinctive enough to avoid false
        # positives but short enough to survive Relay truncation of long comments.
        needle = normalized[:120]

        deadline = time.monotonic() + (timeout_ms / 1000)
        last_comment_count = 0
        while time.monotonic() < deadline:
            post = self.get_group_post(f"{group_id}/posts/{post_id}")
            if post.post_id != post_id:
                raise ClientError(
                    "Fetched group post ID did not match requested post ID during "
                    f"comment verification: requested={post_id}, fetched={post.post_id}."
                )

            comments = list(self._iter_comment_tree(post.comments))
            last_comment_count = len(comments)
            for comment in comments:
                comment_normalized = self._normalize_for_match(comment.text)
                # Match if the submitted needle appears inside the stored comment
                # text (handles Facebook appending metadata) OR the stored text
                # appears inside the submitted needle (handles Relay truncation
                # of very long submitted text down to a shorter stored form).
                if needle in comment_normalized or comment_normalized in needle:
                    return {
                        "verification": "confirmed",
                        "signal": "exact-post-comment-found",
                        "groupId": group_id,
                        "postId": post_id,
                        "commentId": comment.comment_id,
                        "commentCountAfter": last_comment_count,
                    }

            time.sleep(1)

        raise ClientError(
            "Submitted comment was not found on the exact target post after submit: "
            f"group_id={group_id}, post_id={post_id}, comments_checked={last_comment_count}."
        )

    def close(self):
        """Close the browser."""
        if self._browser_instance is not None:
            self._browser_instance.close()
            self._browser_instance = None
            logger.debug("close: closed browser")

    # --- Marketplace helper methods ---

    def _extract_detail_page_image_urls(self, page) -> List[str]:
        """Extract the listing's own gallery image URLs from a detail page.

        Scoped to the listing's media gallery (see :data:`DETAIL_PAGE_IMAGES_JS`)
        so sidebar advertisement creatives are never saved as listing images.

        Returns:
            Deduplicated list of image URLs.
        """
        result = page.evaluate(DETAIL_PAGE_IMAGES_JS)
        if not isinstance(result, list):
            raise ClientError(
                "Facebook listing image extractor returned a non-list result: "
                f"{type(result).__name__}."
            )
        return result

    def _extract_detail_page_price(self, page) -> Dict:
        """Extract the current and original (pre-drop) price from a detail page.

        Returns:
            Dict with ``price`` (the current/active price) and ``originalPrice``
            (the struck-through pre-drop price, empty when the listing has not
            been discounted). Both are raw display strings.
        """
        result = page.evaluate(DETAIL_PAGE_PRICE_JS)
        if not isinstance(result, dict):
            raise ClientError(
                "Facebook listing price extractor returned a non-object result: "
                f"{type(result).__name__}."
            )
        return result

    def _install_delivery_capture(self, page) -> None:
        """Start capturing Facebook's per-listing fulfillment model on this page.

        Seeds from the Relay blobs already in the served HTML and hooks
        XHR/fetch so Relay pagination responses are captured too. Must be called
        BEFORE any scrolling, or the scroll-loaded tiles' fulfillment data is
        gone by the time it is read. See :data:`INSTALL_DELIVERY_CAPTURE_JS`.
        """
        result = page.evaluate(INSTALL_DELIVERY_CAPTURE_JS)
        if not isinstance(result, dict):
            raise ClientError(
                "Facebook delivery-type capture returned a non-object result: "
                f"{type(result).__name__}."
            )
        logger.debug(
            "_install_delivery_capture: installed=%s seeded %s listing(s)",
            result.get("installed"),
            result.get("listings"),
        )

    def _read_delivery_capture(self, page) -> Dict:
        """Read the captured listing maps back off the page.

        Raises:
            ClientError: The capture was never installed, its shape does not
                match what the capture JS writes, or two Relay payloads
                described the same listing differently (which means the capture
                cannot be trusted for any listing).
        """
        capture = page.evaluate(READ_DELIVERY_CAPTURE_JS)
        if not isinstance(capture, dict):
            raise ClientError(
                "Facebook delivery-type capture was not installed on this page, so the "
                "per-listing fulfillment model could not be read."
            )
        for key, subject in CAPTURE_CONFLICT_MAPS.items():
            conflicts = capture.get(key) or {}
            if conflicts:
                raise ClientError(
                    f"Facebook returned conflicting {subject} for {len(conflicts)} "
                    "listing(s), so the read is not trustworthy. Samples: "
                    f"{dict(list(conflicts.items())[:3])}"
                )
        wrong_shape = {
            key: type(capture.get(key)).__name__
            for key in CAPTURE_MAPS
            if not isinstance(capture.get(key), dict)
        }
        if wrong_shape:
            raise ClientError(
                f"Facebook listing capture returned an unexpected shape: {wrong_shape}."
            )
        logger.debug(
            "_read_delivery_capture: %d listing(s), %d alias(es) from %s payload(s), "
            "%s parse error(s)",
            len(capture["deliveryTypes"]),
            len(capture["aliases"]),
            capture.get("payloads"),
            capture.get("parseErrors"),
        )
        return capture

    @staticmethod
    def _resolve_captured_listing_id(
        capture: Dict,
        item_id: str,
        map_name: str = "deliveryTypes",
    ) -> Optional[str]:
        """Map a requested Marketplace id to the id Facebook described it under.

        Facebook gives one listing two ids -- a listing id and a story/post id --
        and links to it by either, so the id in a URL or a tile href is not
        always the id its own payload is keyed by. The capture records
        Facebook's own alias fields, so a request by either id resolves.

        Returns:
            The id the requested capture map is filed under, or None when this
            page never described that subject for the listing.
        """
        captured = capture[map_name]
        if captured.get(item_id):
            return item_id
        alias = capture["aliases"].get(item_id)
        if alias is not None and captured.get(alias):
            return alias
        return None

    def _extract_listing_status(self, page, item_id: str) -> Dict:
        """Read one listing's availability without requiring fulfillment data.

        The status path uses Facebook's own ``is_sold`` / ``is_pending`` /
        ``is_live`` values. It does not call the full-detail fulfillment reader,
        so absent ``delivery_types`` cannot block a current availability check.
        """
        page_state = page.evaluate(MARKETPLACE_STATUS_PAGE_JS)
        if not isinstance(page_state, dict):
            raise ClientError(
                "Facebook Marketplace status page reader returned a non-object result: "
                f"{type(page_state).__name__}."
            )
        unavailable_product = page_state.get("unavailableProduct") is True
        unavailable_message = page_state.get("unavailableMessage") is True
        if unavailable_product != unavailable_message:
            raise ClientError(
                f"Facebook returned conflicting unavailable-page evidence for listing "
                f"{item_id}: unavailable_product={unavailable_product}, "
                f"unavailable_message={unavailable_message}. Refusing to infer status."
            )
        if unavailable_product:
            return {
                "item_id": item_id,
                "status": "gone",
                "availability": "Unavailable",
                "status_source": "unavailable_product_page",
                "url": f"/marketplace/item/{item_id}/",
            }

        self._install_delivery_capture(page)
        capture = self._read_delivery_capture(page)
        described_id = self._resolve_captured_listing_id(
            capture,
            item_id,
            map_name="availability",
        )
        if described_id is None:
            raise ClientError(
                f"Facebook did not describe availability for listing {item_id}: "
                "no is_sold, is_pending, or is_live values were found under that id "
                "or under any listing id Facebook aliases to it. Refusing to infer "
                "availability from missing data. "
                f"(listings with availability on this page: "
                f"{len(capture['availability'])}, aliases: {len(capture['aliases'])})"
            )
        availability = self._derive_availability(capture["availability"][described_id])
        if availability is None:
            raise ClientError(
                f"Facebook described no usable availability state for listing {item_id}. "
                "Refusing to infer availability from false or missing state values."
            )
        return {
            "item_id": item_id,
            "status": "gone" if availability == "Sold" else "available",
            "availability": availability,
            "status_source": "listing_state",
            "url": f"/marketplace/item/{item_id}/",
        }

    def _extract_listing_fulfillment(self, page, item_id: str) -> Dict:
        """Read one listing's delivery types, location, and state from its page.

        Fails loudly rather than returning an absent value: a listing with no
        readable ``delivery_types`` is indistinguishable from one that offers no
        shipping, and a consumer reading it as "local pickup only" would be
        acting on the CLI's ignorance instead of Facebook's data.

        Returns:
            Dict with ``delivery_types`` (non-empty list of Facebook's own
            tokens), ``location`` (Facebook's ``location_text``, or None when
            the listing carries no place name), ``availability``, and
            ``seller_id`` / ``seller_name`` from Facebook's own
            ``marketplace_listing_seller`` node. The two seller fields are None
            when the payload named no seller; unlike ``delivery_types`` that is
            not fatal, because an absent seller cannot be misread as a
            different seller the way an absent fulfillment model was misread as
            "no shipping offered".
        """
        self._install_delivery_capture(page)
        capture = self._read_delivery_capture(page)
        described_id = self._resolve_captured_listing_id(capture, item_id)
        if described_id is None:
            raise ClientError(
                f"Facebook did not describe the fulfillment options for listing {item_id}: "
                "no delivery_types were found in the page's listing data, under that id or "
                "under any listing id Facebook aliases to it. Facebook changed its "
                "Marketplace payload and the CLI extractor needs updating. Refusing to "
                "report an unknown fulfillment model as 'no shipping offered'. "
                f"(listings described on this page: {len(capture['deliveryTypes'])}, "
                f"aliases: {len(capture['aliases'])})"
            )
        return {
            "delivery_types": capture["deliveryTypes"][described_id],
            "location": capture["locationText"].get(described_id),
            "availability": self._derive_availability(capture["availability"].get(described_id)),
            **self._captured_seller(capture, described_id),
        }

    def _extract_detail_page_info(self, page) -> Dict:
        """Extract the listing's title, price, and description.

        Price extraction is delegated to :meth:`_extract_detail_page_price`,
        which targets the price element itself so a struck-through pre-drop
        price cannot be concatenated into the current price. The listing's
        location is NOT read here -- it comes from Facebook's own
        ``location_text`` via :meth:`_extract_listing_fulfillment`, because the
        detail page renders the place name inside a relative-time sentence
        ("Listed 4 weeks ago in Evansville, IN") that carries no stable anchor.
        Availability is not read here either: Facebook publishes ``is_sold`` /
        ``is_pending`` / ``is_live`` in the same listing node, which is a
        stronger answer than any banner text this page renders.

        Returns:
            Dict with title, price, originalPrice, and description keys.
        """
        js = (
            '() => { const main = document.querySelector(\'[role="main"]\');'
            ' if (main == null) return {title:"",description:""};'
            ' const h1 = main.querySelector("h1");'
            ' const title = h1 ? (h1.innerText || "").trim() : "";'
            ' const text = main.innerText || "";'
            ' let description = "";'
            ' const di = text.indexOf("Details\\n"); const si = text.indexOf("Seller information");'
            ' if (di >= 0) {'
            '   const start = di + "Details\\n".length;'
            '   const end = si > start ? si : text.length;'
            '   let desc = text.substring(start, end).trim();'
            '   const cm = desc.match(/^Condition\\n[^\\n]+\\n/);'
            '   if (cm) desc = desc.substring(cm[0].length).trim();'
            '   const lm = desc.match(/\\n[A-Z][a-zA-Z ]+,\\s*[A-Z]{2}\\nLocation is approximate$/);'
            '   if (lm) desc = desc.substring(0, desc.length - lm[0].length).trim();'
            '   description = desc;'
            ' }'
            ' return {title: title, description: description}; }'
        )
        result = page.evaluate(js)
        if not isinstance(result, dict):
            raise ClientError(
                "Facebook listing detail extractor returned a non-object result: "
                f"{type(result).__name__}."
            )
        price = self._extract_detail_page_price(page)
        result["price"] = price.get("price") or ""
        result["originalPrice"] = price.get("originalPrice") or ""
        return result

    @staticmethod
    def _captured_seller(capture: Dict, described_id: str) -> Dict:
        """The listing's ``seller_id``/``seller_name``, or both None.

        Both surfaces need the same two fields off the same map, so the "no
        seller in this payload" case is written down once here rather than
        twice as an inline ``or {}``. The capture JS writes both keys whenever
        it writes the entry at all, so the entry itself is indexed directly: a
        payload change that drops one of them should raise, not report a
        listing as having no seller.
        """
        seller = capture["seller"].get(described_id)
        if seller is None:
            return {"seller_id": None, "seller_name": None}
        return {"seller_id": seller["id"], "seller_name": seller["name"]}

    @staticmethod
    def _derive_availability(state: Optional[Dict]) -> Optional[str]:
        """Map Facebook's own listing-state booleans to an availability string.

        The booleans come from the same listing node as ``delivery_types``
        (:data:`INSTALL_DELIVERY_CAPTURE_JS`), so both surfaces answer from
        Facebook's data rather than from rendered banner text. The detail page
        used to be read for phrases such as "no longer available", which only
        the detail surface renders and which no live sold listing had ever been
        checked against. Precedence:
          1. ``is_sold``    -> "Sold"
          2. ``is_pending`` -> "Pending"
          3. ``is_live``    -> "Available"
          4. otherwise      -> None (Facebook did not describe this listing)

        Args:
            state: The captured ``{is_sold, is_pending, is_live}`` booleans, or
                None when this page's payload never described the listing.
        """
        if not isinstance(state, dict):
            return None
        if state.get("is_sold"):
            return "Sold"
        if state.get("is_pending"):
            return "Pending"
        if state.get("is_live"):
            return "Available"
        return None

    def _scroll_collect(
        self,
        page,
        extract_fn: Callable,
        id_key: str,
        limit: int,
        label: str,
    ) -> List[Dict]:
        """Scroll a page and collect deduplicated items via infinite scroll.

        Args:
            page: The Playwright page to scroll.
            extract_fn: Callable that takes the page and returns a list of dicts.
            id_key: Dict key used for deduplication.
            limit: Maximum number of items to collect.
            label: Label for log/status messages.

        Returns:
            Deduplicated list of raw dicts (up to limit).
        """
        t_start = time.monotonic()
        all_items: List[Dict] = []
        seen_ids: set = set()
        scroll_count = 0

        while len(all_items) < limit:
            t_extract = time.monotonic()
            raw = extract_fn(page)
            logger.debug("_scroll_collect[%s]: scroll %d: %d raw in %.2fs (total unique: %d)",
                         label, scroll_count, len(raw), time.monotonic() - t_extract, len(all_items))

            new_count = 0
            for item in raw:
                item_id = item.get(id_key)
                if item_id and item_id not in seen_ids:
                    seen_ids.add(item_id)
                    all_items.append(item)
                    new_count += 1

            if len(all_items) >= limit:
                break

            if new_count == 0 and scroll_count > 0:
                break

            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)
            scroll_count += 1

        logger.debug("_scroll_collect[%s]: total %.2fs, %d items, %d scrolls",
                     label, time.monotonic() - t_start, len(all_items), scroll_count)
        print_info(f"Loaded {len(all_items)} {label}(s) after {scroll_count} scroll(s)")
        return all_items[:limit]

    def _dismiss_marketplace_login_dialog(self, page) -> None:
        """Close Facebook's login upsell dialog on public Marketplace pages."""
        try:
            close_button = page.get_by_role("button", name="Close")
            if close_button.count() == 0:
                return
            close_button.first.click()
            page.wait_for_timeout(1000)
        except Exception:
            logger.debug("_dismiss_marketplace_login_dialog: close button not actionable")

    def _extract_list_page_listings(self, page, settle_ms: int = 5000) -> List[Dict]:
        """Extract listing records from a Marketplace list/search page.

        Facebook's grid is virtualized, so a tile can paint its image and title
        a moment before its price. That is a transient render state, not a
        markup change, so unreadable tiles are re-checked until the grid settles.

        Raises:
            ClientError: Listing tiles were still missing a usable price/title
                after ``settle_ms``, which means Facebook changed its tile
                markup. Dropping them silently would under-report results.
        """
        deadline = time.monotonic() + (settle_ms / 1000)
        while True:
            result = page.evaluate(LIST_PAGE_LISTINGS_JS)
            if not isinstance(result, dict):
                raise ClientError(
                    "Facebook Marketplace listing extractor returned a non-object result: "
                    f"{type(result).__name__}."
                )
            rows = result.get("rows")
            if not isinstance(rows, list):
                raise ClientError("Facebook Marketplace listing extractor returned no rows array.")
            unparsed = result.get("unparsed") or []
            if not unparsed:
                for row in rows:
                    if row.get("location") == TILE_SHIPPING_PLACEHOLDER_LOCATION:
                        row["location"] = None
                return rows
            if time.monotonic() >= deadline:
                raise ClientError(
                    f"{len(unparsed)} Facebook Marketplace listing tile(s) still rendered "
                    f"without a recognizable price and title after {settle_ms}ms. Facebook "
                    "changed its tile markup and the CLI extractor needs updating. "
                    f"Samples: {unparsed[:3]}"
                )
            logger.debug(
                "_extract_list_page_listings: waiting for %d unreadable tile(s) to settle",
                len(unparsed),
            )
            page.wait_for_timeout(500)

    def _marketplace_page_state(self, page) -> Dict:
        """Read Facebook's own view of a Marketplace list/search page."""
        state = page.evaluate(MARKETPLACE_PAGE_STATE_JS, MARKETPLACE_RESULTS_CONTAINER_SELECTOR)
        if not isinstance(state, dict):
            raise ClientError(
                "Facebook Marketplace page-state probe returned a non-object result: "
                f"{type(state).__name__}."
            )
        return state

    def _wait_for_marketplace_results(self, page, timeout_ms: int = 20000) -> Dict:
        """Wait until Facebook renders listing tiles or its own zero-result message.

        Extraction used to start after a fixed settle delay, so a slow render
        produced an empty accessibility snapshot that looked exactly like a
        genuine empty search. This waits on the real readiness condition
        instead: at least one Marketplace item link, or Facebook's own
        "No listings found" state.
        """
        deadline = time.monotonic() + (timeout_ms / 1000)
        while True:
            state = self._marketplace_page_state(page)
            if state.get("item_link_count") or state.get("no_results"):
                return state
            if time.monotonic() >= deadline:
                return state
            page.wait_for_timeout(500)

    @staticmethod
    def _raise_for_empty_marketplace_results(state: Dict, surface: str) -> None:
        """Fail loudly on an empty extraction unless Facebook itself reported zero results.

        A genuine zero-result search is the ONLY empty outcome Facebook vouches
        for: its results container rendered AND it printed the
        "No listings found for ..." heading. Every other empty outcome means the
        read is broken -- the page never rendered, the results container never
        appeared, the page was blocked, or Facebook changed the listing markup
        the extractor depends on.
        """
        if state.get("no_results"):
            return

        detail = (
            f"url={state.get('url')!r} title={state.get('title')!r} "
            f"page_body_rendered={state.get('main_exists')} "
            f"results_container_rendered={state.get('container_exists')} "
            f"listing_tiles={state.get('item_link_count')} "
            f"headings={state.get('headings')}"
        )
        if not state.get("main_exists"):
            raise ClientError(
                f"Facebook never rendered a Marketplace page body for {surface}. "
                f"The page did not load. {detail}"
            )
        if state.get("item_link_count"):
            raise ClientError(
                f"Facebook rendered {state['item_link_count']} Marketplace listing tiles for "
                f"{surface}, but the accessibility-tree extractor parsed none of them. "
                f"Facebook changed its listing markup and the CLI parser needs updating. {detail}"
            )
        raise ClientError(
            f"Facebook returned no Marketplace listings for {surface} and did not report a "
            "zero-result search. The results never settled, the page was blocked, or "
            f"Facebook changed its markup. {detail}"
        )

    @staticmethod
    def _served_location_slug(current_url: str) -> Optional[str]:
        """Return the Marketplace location slug Facebook actually served.

        ``None`` means the served URL carries no location segment at all, which
        is what a rejected slug looks like on the browse surface
        (``/marketplace/losangeles/`` -> ``/marketplace/``).
        """
        segments = [segment for segment in urlparse(current_url).path.split("/") if segment]
        if len(segments) < 2 or segments[0] != "marketplace":
            return None
        return segments[1]

    @staticmethod
    def _assert_requested_location(current_url: str, location: str, requested_url: str) -> None:
        """Fail loudly when Facebook rejected the requested location slug.

        An unrecognized slug is silently downgraded by Facebook to the
        account's own home city (see ``MARKETPLACE_SLUGLESS_PATH_SEGMENT``), so
        the caller would otherwise receive a full, healthy-looking result set
        under exit 0 that describes a completely different city. Another city's
        inventory reported as the requested city's is worse than no result, so
        this raises instead.

        The literal slugless segment is rejected as a requested location too:
        ``--location category`` would otherwise satisfy a naive equality check
        while returning exactly the home-city inventory this guard exists to
        catch.
        """
        served = FacebookClient._served_location_slug(current_url)
        if served == location and location != MARKETPLACE_SLUGLESS_PATH_SEGMENT:
            return
        raise ClientError(
            f"Facebook does not recognize the Marketplace location slug {location!r}. "
            f"It served {current_url or '(no URL)'} instead of the requested "
            f"{requested_url}, which returns the logged-in account's own home-city "
            f"inventory rather than {location!r}'s. Facebook never errors on an unknown "
            "slug, so this result would otherwise be another city's listings under a "
            "clean exit. Use a slug Facebook publishes in its own Marketplace URL "
            "(for example 'evansville', 'chicago', 'seattle', 'nyc')."
        )

    def _paginated_fetch(
        self, url: str, status_msg: str, limit: int, location: str
    ) -> List[MarketplaceListing]:
        """Navigate to a Marketplace URL and scroll to collect listings."""
        print_info(status_msg)
        page = self._get_page(url)
        # An authenticated session can still show a transient login/upsell
        # dialog, so dismiss it first; the c_user check below then decides auth
        # state independently of any transient dialog.
        self._dismiss_marketplace_login_dialog(page)
        self._assert_marketplace_authenticated(page, url, f"Marketplace ({status_msg})")

        state = self._wait_for_marketplace_results(page)
        # Checked once the page has settled into results (or Facebook's own
        # zero-result state), because the slug rewrite happens during Facebook's
        # client-side routing. Checked BEFORE the zero-result return so an
        # unrecognized slug can never be reported as "this city has no matches".
        self._assert_requested_location(state.get("url") or "", location, url)
        if state.get("no_results"):
            print_info(f"Facebook reported no listings: {state.get('empty_heading')}")
            return []

        # Must be installed before the first scroll: the tiles loaded by
        # scrolling carry their fulfillment model in Relay pagination responses,
        # which are gone once the response has been consumed.
        self._install_delivery_capture(page)
        items = self._scroll_collect(
            page, self._extract_list_page_listings, "item_id", limit, "listing"
        )
        if not items:
            self._raise_for_empty_marketplace_results(
                self._marketplace_page_state(page), f"Marketplace ({status_msg})"
            )
            return []
        self._attach_captured_listing_fields(page, items)
        return [MarketplaceListing(**d) for d in items]

    def _attach_captured_listing_fields(self, page, items: List[Dict]) -> None:
        """Set each row's fulfillment, state, and tile photo from the payloads.

        A row Facebook never described keeps every captured field at None and is
        named in a warning, rather than being reported as an empty list or as an
        available listing. An empty ``delivery_types`` reads as "this seller
        offers no fulfillment at all", which is never what a missing capture
        means. The known case is Facebook's injected
        "commerce_interesting_product" notification tile: its href carries the
        listing's story/post id and its listing data comes from the
        notifications feed, which the search payload never contains under any
        id. `marketplace get` on that id reads the listing's own page and
        resolves the id alias there.
        """
        capture = self._read_delivery_capture(page)
        undescribed = []
        for item in items:
            described_id = self._resolve_captured_listing_id(capture, item["item_id"])
            if described_id is None:
                item["delivery_types"] = None
                item["availability"] = None
                item["primary_image_url"] = None
                item["seller_id"] = None
                item["seller_name"] = None
                undescribed.append(item["item_id"])
                continue
            item["delivery_types"] = capture["deliveryTypes"][described_id]
            item["availability"] = self._derive_availability(
                capture["availability"].get(described_id)
            )
            item["primary_image_url"] = capture["primaryImage"].get(described_id)
            item.update(self._captured_seller(capture, described_id))
        if undescribed:
            print_warning(
                f"Facebook described no listing data for {len(undescribed)} of "
                f"{len(items)} listing(s); those rows report delivery_types, "
                "availability, primary_image_url, and the seller as null, which means "
                "UNKNOWN. "
                "A null delivery_types must never be read as 'no shipping offered'. "
                f"Use `marketplace get <item_id>` for a definitive read. IDs: {undescribed}"
            )

    # --- Marketplace methods ---

    def search(
        self,
        query: str,
        location: str = DEFAULT_LOCATION,
        min_price: Optional[int] = None,
        max_price: Optional[int] = None,
        limit: int = 50,
        sort_by: Optional[str] = None,
        delivery_method: Optional[str] = None,
    ) -> List[MarketplaceListing]:
        """Search Facebook Marketplace for listings.

        Args:
            sort_by: Facebook Marketplace ``sortBy`` URL value
                (e.g. ``creation_time_descend`` for newest-first,
                ``price_ascend`` / ``price_descend``). When None, Facebook
                applies its own default ordering.
            delivery_method: Facebook Marketplace ``deliveryMethod`` URL value
                (``shipping`` or ``local_pick_up``). When None, no parameter is
                sent and Facebook applies its own unfiltered default. With
                ``shipping`` the ``location`` slug does not change the result
                set -- Facebook serves one nationwide shipping pool from any
                slug (measured live 2026-08-18: 60/60 identical item ids from
                ``evansville`` and ``seattle``) -- but the slug is still
                validated, because an unrecognized slug is a caller mistake
                either way.
        """
        params = [f"query={query}"]
        if min_price is not None:
            params.append(f"minPrice={min_price}")
        if max_price is not None:
            params.append(f"maxPrice={max_price}")
        if sort_by is not None:
            params.append(f"sortBy={sort_by}")
        if delivery_method is not None:
            params.append(f"deliveryMethod={delivery_method}")

        url = f"{MARKETPLACE_BASE}/{location}/search/?{'&'.join(params)}"
        return self._paginated_fetch(
            url=url,
            status_msg=f"Searching for '{query}' in {location}...",
            limit=limit,
            location=location,
        )

    def browse(
        self,
        location: str = DEFAULT_LOCATION,
        limit: int = 50,
        sort_by: Optional[str] = None,
    ) -> List[MarketplaceListing]:
        """Browse Facebook Marketplace 'Today's picks' for a location.

        Args:
            sort_by: Facebook Marketplace ``sortBy`` URL value applied to the
                category feed. When None, Facebook applies its own default
                ordering.
        """
        url = f"{MARKETPLACE_BASE}/{location}/"
        if sort_by is not None:
            url = f"{url}?sortBy={sort_by}"
        return self._paginated_fetch(
            url=url,
            status_msg=f"Browsing Marketplace in {location}...",
            limit=limit,
            location=location,
        )

    def get_item(self, item_id: str) -> MarketplaceListing:
        """Get details for a specific marketplace listing.

        Enforces the fulfillment contract on every return, cached or fresh: a
        listing whose ``delivery_types`` could not be read is an error, never a
        record that reads as "no shipping offered". The check lives outside the
        cache because a record written before the CLI captured delivery types
        would otherwise be replayed with the field silently absent.

        Raises:
            ClientError: The returned listing carries no ``delivery_types``.
        """
        listing = self._fetch_item(item_id)
        if not listing.delivery_types:
            raise ClientError(
                f"Listing {item_id} came back with no delivery_types, so its fulfillment "
                "model is unknown. If this is a cached record written before the CLI read "
                "delivery types, clear it with `facebook cache clear` and retry."
            )
        return listing

    def get_item_status(self, item_id: str) -> Dict:
        """Get current Marketplace availability without reading full details.

        This live path does not use the item cache. It reads only Facebook's
        structured listing-state booleans and keeps the full ``get`` command's
        strict fulfillment contract unchanged.
        """
        url = f"{MARKETPLACE_BASE}/item/{item_id}/"
        print_info(f"Checking listing {item_id} status...")

        page = self._get_page(url)
        self._dismiss_marketplace_login_dialog(page)
        self._assert_marketplace_authenticated(page, url, f"Marketplace item {item_id}")
        return self._extract_listing_status(page, item_id)

    @cached
    def _fetch_item(self, item_id: str) -> MarketplaceListing:
        """Read a listing's detail page. Cached; see :meth:`get_item`.

        Extracts title, price, and description directly from the detail page DOM
        rather than the snapshot parser (which picks up recommended listings
        instead of the main one). ``delivery_types`` and ``location`` come from
        Facebook's own listing data (see :meth:`_extract_listing_fulfillment`);
        neither is rendered as readable text on the page.

        Reads the gallery URLs on every call. Extracting them is one evaluate on
        a page that is already open, and a caller who wants to LOOK at a photo
        should not have to ask the CLI to WRITE it to disk first. Downloading is
        a separate concern and stays behind `--download-images`.

        Args:
            item_id: The marketplace item ID.

        Returns:
            MarketplaceListing with item details.

        Raises:
            ClientError: Facebook's listing data carried no ``delivery_types``
                for this listing, so the fulfillment model is unknown.
        """
        url = f"{MARKETPLACE_BASE}/item/{item_id}/"
        print_info(f"Getting listing {item_id}...")

        page = self._get_page(url)
        # Dismiss any transient login/upsell dialog, then assert auth by cookie
        # state before extracting so a login-walled page fails loudly instead of
        # returning an "Unknown" listing.
        self._dismiss_marketplace_login_dialog(page)
        self._assert_marketplace_authenticated(page, url, f"Marketplace item {item_id}")

        info = self._extract_detail_page_info(page)
        fulfillment = self._extract_listing_fulfillment(page, item_id)
        listing = MarketplaceListing(
            item_id=item_id,
            title=info.get("title") or "Unknown",
            price=info.get("price") or "Unknown",
            original_price=info.get("originalPrice") or None,
            url=f"/marketplace/item/{item_id}/",
            location=fulfillment["location"],
            description=info.get("description") or None,
            availability=fulfillment["availability"],
            delivery_types=fulfillment["delivery_types"],
            seller_id=fulfillment["seller_id"],
            seller_name=fulfillment["seller_name"],
        )

        listing.image_urls = self._extract_detail_page_image_urls(page)

        return listing

    # --- Messenger methods ---

    def list_conversations(self, limit: int = 20) -> List[Dict]:
        """List Messenger conversations.

        Args:
            limit: Maximum number of conversations to return.

        Returns:
            List of conversation dicts with id, name, snippet, timestamp.
        """
        from .messenger_parsers import extract_conversations_from_snapshot

        t_start = time.monotonic()
        print_info("Loading Messenger conversations...")
        requested_url = "https://www.facebook.com/messages/t/"
        page = self._get_page(requested_url)
        self._assert_authenticated_page(page, requested_url, "Messenger conversations")
        logger.debug("list_conversations: page loaded in %.2fs", time.monotonic() - t_start)
        page.wait_for_timeout(1000)  # extra wait for messenger

        snapshot = self._snapshot(page)
        conversations = extract_conversations_from_snapshot(snapshot)
        logger.debug("list_conversations: total %.2fs, %d conversations",
                     time.monotonic() - t_start, len(conversations))
        return conversations[:limit]

    def get_conversation(self, conversation_id: str, message_limit: int = 50) -> Dict:
        """Get a conversation with its messages.

        Args:
            conversation_id: The conversation/thread ID.
            message_limit: Maximum number of messages to return.

        Returns:
            Dict with conversation info and messages list.
        """
        from .messenger_parsers import extract_messages_from_snapshot

        print_info(f"Loading conversation {conversation_id}...")
        requested_url = f"{MESSENGER_BASE}/{conversation_id}/"
        page = self._get_page(requested_url)
        self._assert_authenticated_page(page, requested_url, f"Messenger conversation {conversation_id}")
        page.wait_for_timeout(1000)  # extra wait for messenger

        snapshot = self._snapshot(page)
        messages = extract_messages_from_snapshot(snapshot)

        return {
            "conversation_id": conversation_id,
            "messages": messages[-message_limit:],
        }

    def send_message(self, conversation_id: str, text: str) -> Dict:
        """Send a message in a conversation.

        Args:
            conversation_id: The conversation/thread ID.
            text: The message text to send.

        Returns:
            Dict with send status.
        """
        print_info(f"Sending message to conversation {conversation_id}...")
        requested_url = f"{MESSENGER_BASE}/{conversation_id}/"
        page = self._get_page(requested_url)
        self._assert_authenticated_page(page, requested_url, f"Messenger conversation {conversation_id}")

        # Type the message into the composer and send
        escaped_text = json.dumps(text)
        js_type = (
            '(escapedText) => {'
            ' const box = document.querySelector(\'[role="textbox"][contenteditable="true"]\');'
            ' if (!box) return {success: false, error: "Message box not found"};'
            ' box.focus();'
            ' box.textContent = "";'
            ' document.execCommand("insertText", false, escapedText);'
            ' return {success: true};'
            ' }'
        )
        typed = page.evaluate(js_type, text)
        if not isinstance(typed, dict):
            typed = {"success": False, "error": "Failed to type message"}

        if not typed.get("success"):
            raise ClientError(f"Failed to type message: {typed.get('error', 'unknown')}")

        page.wait_for_timeout(500)

        # Press Enter to send
        page.evaluate(
            '() => { document.querySelector(\'[role="textbox"]\').dispatchEvent('
            'new KeyboardEvent("keydown", {key: "Enter", code: "Enter", keyCode: 13, bubbles: true})); }'
        )
        page.wait_for_timeout(2000)

        return {"success": True, "conversation_id": conversation_id, "text": text}

    # --- Groups methods ---

    def _extract_joined_groups(self, page) -> List[Dict]:
        """Extract groups from the user's joined groups page.

        Returns:
            List of group dicts with group_id, name, url, member_count.
        """
        js = (
            '() => {'
            ' const groups = [];'
            ' const seen = new Set();'
            ' const links = document.querySelectorAll(\'a[href*="/groups/"]\');'
            ' links.forEach(a => {'
            '   const href = a.href || "";'
            '   const m = href.match(/\\/groups\\/([^/?]+)/);'
            '   if (!m) return;'
            '   const gid = m[1];'
            '   if (gid === "feed" || gid === "discover" || gid === "joins" || seen.has(gid)) return;'
            # Try to get a clean group name from an image alt text or aria-label first,
            # then fall back to the shortest meaningful text child.
            '   let name = "";'
            '   const img = a.querySelector("img[alt]");'
            '   if (img && img.alt && img.alt.length > 1 && img.alt.length < 100) {'
            '     name = img.alt.trim();'
            '   }'
            '   if (!name) {'
            '     const label = a.getAttribute("aria-label");'
            '     if (label && label.length > 1 && label.length < 100) name = label.trim();'
            '   }'
            '   if (!name) {'
            # Walk child spans/divs for the shortest non-trivial text (likely the group name)
            # Skip text containing notification indicators
            '     const candidates = [];'
            '     a.querySelectorAll("span, strong, h3").forEach(el => {'
            '       const t = (el.innerText || "").trim();'
            '       if (t.length >= 3 && t.length <= 80'
            '           && !t.includes("Unread") && !t.includes("Mark as read")'
            '           && !t.includes("posted in") && !t.includes("ago")'
            '           && !t.match(/^\\d+[hmd]$/)) {'
            '         candidates.push(t);'
            '       }'
            '     });'
            '     if (candidates.length > 0) {'
            '       candidates.sort((a, b) => a.length - b.length);'
            '       name = candidates[0];'
            '     }'
            '   }'
            '   if (!name || name.length < 2) return;'
            '   seen.add(gid);'
            '   let memberCount = "";'
            '   const fullText = (a.innerText || "");'
            '   const mMatch = fullText.match(/(\\d[\\d,.]*\\s*[KkMm]?\\s*members?)/i);'
            '   if (mMatch) memberCount = mMatch[1].trim();'
            '   groups.push({group_id: gid, name: name, url: href.split("?")[0], member_count: memberCount});'
            ' });'
            ' return groups;'
            ' }'
        )
        result = page.evaluate(js)
        return result if isinstance(result, list) else []

    def list_joined_groups(self, limit: int = 50) -> List[Group]:
        """List Facebook Groups the user has joined."""
        print_info("Loading joined groups...")
        page = self._get_page(f"{GROUPS_BASE}/joins/", settle_ms=0)
        page.wait_for_selector('a[href*="/groups/"]', timeout=15000)

        items = self._scroll_collect(page, self._extract_joined_groups, "group_id", limit, "group")
        return [Group(**g) for g in items]

    def get_group(self, group_id: str) -> Group:
        """Get a Facebook Group by ID or slug."""
        if group_id.startswith("http"):
            match = re.search(r"/groups/([^/?]+)", group_id)
            if not match:
                raise ClientError(f"Group URL does not contain a group ID: {group_id}")
            group_ref = match.group(1)
            url = group_id
        else:
            group_ref = group_id
            url = f"{GROUPS_BASE}/{group_ref}/"

        page = self._get_page(url)
        self._assert_authenticated_page(page, url, f"Facebook group {group_ref}")
        metadata = page.evaluate(
            """() => {
                const main = document.querySelector('[role="main"]') || document.body;
                const h1 = main?.querySelector('h1');
                const name = (h1?.innerText || document.title || '').trim();
                const text = main?.innerText || document.body?.innerText || '';
                const memberMatch = text.match(/\\b\\d[\\d,.]*\\s*[KkMm]?\\s+members?\\b/);
                return {
                    name,
                    memberCount: memberMatch ? memberMatch[0].trim() : ''
                };
            }"""
        )
        if not isinstance(metadata, dict):
            raise ClientError("Rendered Facebook group metadata extractor returned a non-object result.")
        name = re.sub(r"\s+", " ", str(metadata.get("name") or "")).strip()
        if not name or name in ("Facebook", "Error"):
            raise ClientError("Rendered Facebook group page did not include a group title.")
        member_count = re.sub(r"\s+", " ", str(metadata.get("memberCount") or "")).strip()

        return Group(
            group_id=group_ref,
            name=name,
            url=f"{GROUPS_BASE}/{group_ref}/",
            member_count=member_count or None,
        )

    def _facebook_http_client(self) -> BrowserAuthenticatedHttpClient:
        """Get the shared fast HTTP client for browser-authenticated reads."""
        if self._http_client is None:
            self._http_client = BrowserAuthenticatedHttpClient(
                auth_state=BrowserAuthState.from_config(self.config),
                allowed_domains=["facebook.com"],
                required_cookies=["c_user"],
                headers=FACEBOOK_DESKTOP_HEADERS,
                timeout=10,
            )
        return self._http_client

    def _fetch_authenticated_facebook_html(self, url: str) -> str:
        """Fetch enough authenticated Facebook HTML for group metadata."""
        return self._fetch_authenticated_facebook_page(
            url,
            stop_markers=[
                "</title>",
                '"group_member_profiles":{"formatted_count_text":"',
            ],
        )

    def _fetch_authenticated_facebook_full_html(self, url: str) -> str:
        """Fetch a complete authenticated Facebook page without launching Chromium."""
        return self._fetch_authenticated_facebook_page(url)

    def _fetch_authenticated_facebook_bootstrap_html(self, url: str) -> str:
        """Fetch only the Facebook Relay bootstrap slice needed for group posts."""
        return self._fetch_authenticated_facebook_page(
            url,
            stop_markers=GROUP_DISCUSSION_BOOTSTRAP_MARKERS,
        )

    def _fetch_authenticated_facebook_page(
        self,
        url: str,
        stop_markers: Optional[List[str]] = None,
    ) -> str:
        """Fetch an authenticated Facebook page without launching Chromium."""
        result = self._facebook_http_client().get_text_result(
            url,
            stop_after_markers=stop_markers or (),
        )
        logger.debug(
            "_fetch_authenticated_facebook_page: fetched in %.2fs (%d chars, %d bytes)",
            result.elapsed_seconds,
            len(result.text),
            result.bytes_read,
        )
        return result.text

    def _extract_group_name(self, body: str) -> str:
        """Extract the group name from fetched Facebook HTML."""
        title_match = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
        if not title_match:
            raise ClientError("Failed to extract group name from Facebook HTML title.")

        name = html.unescape(re.sub(r"\s+", " ", title_match.group(1))).strip()
        if not name or name == "Facebook" or name == "Error":
            raise ClientError("Facebook group page did not include a group title.")
        return name

    def _extract_group_member_count(self, body: str) -> str:
        """Extract the group member count from fetched Facebook HTML."""
        match = re.search(r'"group_member_profiles":\{"formatted_count_text":"([^"]+)"', body)
        if not match:
            raise ClientError("Failed to extract group member count from Facebook HTML.")
        return html.unescape(match.group(1))

    def _facebook_server_define(self, body: str, name: str) -> Dict:
        """Extract a ServerJS define payload from Facebook HTML."""
        return extract_embedded_define(body, name)

    def _facebook_jazoest(self, token: str) -> str:
        """Build Facebook's jazoest form value from the DTSG token."""
        return "2" + "".join(str(ord(char)) for char in token)

    def _iter_relay_prefetched_stream_results(self, body: str, allow_truncated_tail: bool = False):
        """Yield RelayPrefetchedStreamCache result objects from Facebook HTML."""
        marker = '["RelayPrefetchedStreamCache","next"'
        decoder = json.JSONDecoder()
        index = 0
        while True:
            start = body.find(marker, index)
            if start < 0:
                return
            try:
                value, index = decoder.raw_decode(body, start)
            except json.JSONDecodeError as exc:
                if allow_truncated_tail:
                    return
                raise ClientError(f"Failed to decode JSON at marker: {marker}") from exc
            if (
                not isinstance(value, list)
                or len(value) < 4
                or not isinstance(value[3], list)
                or len(value[3]) < 2
                or not isinstance(value[3][1], dict)
            ):
                raise ClientError("Facebook HTML contained invalid Relay stream data.")
            bbox = value[3][1].get("__bbox")
            if not isinstance(bbox, dict):
                raise ClientError("Facebook Relay stream payload is missing __bbox.")
            result = bbox.get("result")
            if isinstance(result, dict):
                yield result

    def _extract_text_path(self, data: Dict, path: List[str]) -> Optional[str]:
        """Extract a nested string from a dictionary."""
        value = data
        for part in path:
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ClientError(f"Expected string at {'.'.join(path)}, got {type(value).__name__}.")
        return value

    def _extract_group_post_text(self, node: Dict) -> Optional[str]:
        """Extract text from Facebook's typed group story message section."""
        message = node.get("comet_sections", {}).get("content", {}).get("story", {}).get("comet_sections", {}).get("message")
        if message is None:
            return None
        if not isinstance(message, dict):
            raise ClientError("Facebook story message section is not an object.")

        typename = message.get("__typename")
        if typename in (
            "CometFeedStoryDefaultMessageRenderingStrategy",
            "CometFeedStoryLargeMessageRenderingStrategy",
            "CometFeedStoryFormattedBackgroundMessageRenderingStrategy",
        ):
            return self._extract_text_path(message, ["story", "message", "text"])

        if typename == "CometFeedStoryRichMessageRenderingStrategy":
            container_text = self._extract_text_path(message, ["message_container", "story", "message", "text"])
            if container_text is not None:
                return container_text
            rich_message = message.get("rich_message")
            if not isinstance(rich_message, list):
                raise ClientError("Facebook rich message section is missing rich_message blocks.")
            parts = []
            for block in rich_message:
                if not isinstance(block, dict):
                    raise ClientError("Facebook rich message block is not an object.")
                block_text = block.get("text")
                if block_text is not None and not isinstance(block_text, str):
                    raise ClientError("Facebook rich message block text is not a string.")
                if block_text:
                    parts.append(block_text)
            return "\n".join(parts) if parts else None

        if not isinstance(typename, str):
            raise ClientError("Facebook story message section is missing __typename.")
        raise ClientError(f"Unsupported Facebook story message renderer: {typename}")

    @staticmethod
    def _title_from_group_post_body(body: Optional[str]) -> Optional[str]:
        """Derive a thread title from the first non-empty line of post text."""
        if body is None:
            return None
        for line in body.splitlines():
            title = line.strip()
            if title:
                return title[:160]
        return None

    def _group_post_from_story_node(self, group_id: str, node: Dict) -> Dict:
        """Convert a Facebook Story node into a GroupPost dictionary."""
        if not isinstance(node, dict):
            raise ClientError("Facebook group feed story node is not an object.")
        post_id = node.get("post_id")
        if not isinstance(post_id, str) or not post_id:
            raise ClientError("Facebook group feed story node is missing post_id.")

        created = node.get("comet_sections", {}).get("timestamp", {}).get("story", {}).get("creation_time")
        if created is not None and not isinstance(created, (int, float)):
            raise ClientError("Facebook group feed story creation_time is not numeric.")

        timestamp = None
        if created is not None:
            timestamp = datetime.fromtimestamp(created, timezone.utc).isoformat()

        body = self._extract_group_post_text(node)
        thread_url = (
            self._extract_text_path(node, ["comet_sections", "timestamp", "story", "url"])
            or f"{GROUPS_BASE}/{group_id}/posts/{post_id}/"
        )

        return {
            "post_id": post_id,
            "title": self._title_from_group_post_body(body),
            "author": self._extract_text_path(node, ["feedback", "owning_profile", "name"]),
            "text": body,
            "body": body,
            "timestamp": timestamp,
            "url": thread_url,
            "thread_url": thread_url,
            "image_urls": None,
        }

    def _extract_story_image_urls(self, node: Dict) -> List[str]:
        """Extract media URLs from a story's attachment subtree."""
        urls: List[str] = []
        seen = set()

        def visit(value) -> None:
            if isinstance(value, str):
                if not value.startswith("http"):
                    return
                if "scontent" not in value and "fbcdn" not in value:
                    return
                if any(size_token in value for size_token in ("s40x40", "s48x48", "s74x74")):
                    return
                if value in seen:
                    return
                seen.add(value)
                urls.append(value)
                return
            if isinstance(value, dict):
                for child in value.values():
                    visit(child)
                return
            if isinstance(value, list):
                for child in value:
                    visit(child)

        visit(node.get("attachments"))
        visit(node.get("attached_story", {}).get("attachments") if isinstance(node.get("attached_story"), dict) else None)
        return urls

    @staticmethod
    def _optional_text_path(data: Dict, path: List[str]) -> Optional[str]:
        value = data
        for part in path:
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ClientError(f"Expected string at {'.'.join(path)}, got {type(value).__name__}.")
        return value

    def _comment_from_relay_node(self, node: Dict) -> Optional[Dict]:
        if node.get("__typename") != "Comment":
            return None
        legacy_fbid = node.get("legacy_fbid")
        if not isinstance(legacy_fbid, str) or not legacy_fbid:
            return None
        author = self._optional_text_path(node, ["author", "name"])
        if not author:
            raise ClientError(f"Facebook comment {legacy_fbid} is missing author.name.")
        text = (
            self._optional_text_path(node, ["body", "text"])
            or self._optional_text_path(node, ["preferred_body", "text"])
        )
        if text is None or not text.strip():
            logger.debug("Skipping Facebook comment %s because it has no body text.", legacy_fbid)
            return None
        created = node.get("created_time")
        if created is not None and not isinstance(created, (int, float)):
            raise ClientError(f"Facebook comment {legacy_fbid} created_time is not numeric.")
        created_time = datetime.fromtimestamp(created, timezone.utc).isoformat() if created is not None else None
        parent = node.get("comment_direct_parent")
        parent_id = None
        if isinstance(parent, dict):
            parent_value = parent.get("legacy_fbid")
            if parent_value is not None and not isinstance(parent_value, str):
                raise ClientError(f"Facebook comment {legacy_fbid} parent legacy_fbid is not a string.")
            parent_id = parent_value
        return {
            "_parent_id": parent_id,
            "comment_id": legacy_fbid,
            "author": author,
            "text": text,
            "created_time": created_time,
            "replies": [],
        }

    def _extract_comments_from_relay_payloads(self, payloads: tuple[Dict, ...]) -> List[Dict]:
        """Extract top-level comments and replies from post Relay payloads."""
        by_id: Dict[str, Dict] = {}
        ordered: List[Dict] = []

        def visit(value) -> None:
            if isinstance(value, dict):
                comment = self._comment_from_relay_node(value)
                if comment is not None:
                    comment_id = comment["comment_id"]
                    if comment_id not in by_id:
                        by_id[comment_id] = comment
                        ordered.append(comment)
                for child in value.values():
                    visit(child)
                return
            if isinstance(value, list):
                for child in value:
                    visit(child)

        for payload in payloads:
            visit(payload)

        return self._comment_tree_from_ordered(ordered, by_id)

    def _comment_tree_from_ordered(self, ordered: List[Dict], by_id: Dict[str, Dict]) -> List[Dict]:
        """Build a nested comment tree from ordered Relay comment nodes."""
        top: List[Dict] = []
        for comment in ordered:
            parent_id = comment["_parent_id"]
            if parent_id and parent_id in by_id:
                by_id[parent_id]["replies"].append(comment)
            else:
                top.append(comment)

        def clean(entries: List[Dict]) -> List[Dict]:
            cleaned = []
            for entry in entries:
                cleaned.append({
                    "comment_id": entry["comment_id"],
                    "author": entry["author"],
                    "text": entry["text"],
                    "created_time": entry["created_time"],
                    "replies": clean(entry["replies"]),
                })
            return cleaned

        return clean(top)

    def _extract_story_and_comments_from_payloads(
        self,
        payloads: tuple[Dict, ...],
        post_id: str,
    ) -> tuple[Optional[Dict], List[Dict]]:
        """Collect the target story node and Relay comments in one traversal."""
        story_candidates: List[Dict] = []
        story_fallbacks: List[Dict] = []
        by_id: Dict[str, Dict] = {}
        ordered: List[Dict] = []

        def visit(value) -> None:
            if isinstance(value, dict):
                if value.get("post_id") == post_id:
                    story_candidates.append(value)
                elif value.get("__typename") == "Story" and value.get("post_id"):
                    story_fallbacks.append(value)
                comment = self._comment_from_relay_node(value)
                if comment is not None:
                    comment_id = comment["comment_id"]
                    if comment_id not in by_id:
                        by_id[comment_id] = comment
                        ordered.append(comment)
                for child in value.values():
                    visit(child)
                return
            if isinstance(value, list):
                for child in value:
                    visit(child)

        for payload in payloads:
            visit(payload)

        story_node = None
        for candidate in story_candidates:
            author = self._extract_text_path(candidate, ["feedback", "owning_profile", "name"])
            if author is not None:
                story_node = candidate
                break
        if story_node is None and story_candidates:
            story_node = story_candidates[0]

        # When the Relay payload for a direct post permalink does not embed a
        # Story node whose post_id matches the URL post_id (Facebook sometimes
        # uses a different internal ID in the embedded Relay data than the ID
        # visible in the permalink URL), fall back to any Story node in the
        # payload that has an author.  This is safe because we already navigated
        # to the canonical single-post permalink, so there is only one target
        # post in the payload.
        if story_node is None and story_fallbacks:
            logger.debug(
                "_extract_story_and_comments_from_payloads: post_id %s not found "
                "in Relay nodes; falling back to first Story node with post_id %s",
                post_id,
                story_fallbacks[0].get("post_id"),
            )
            for candidate in story_fallbacks:
                author = self._extract_text_path(candidate, ["feedback", "owning_profile", "name"])
                if author is not None:
                    story_node = candidate
                    break
            if story_node is None:
                story_node = story_fallbacks[0]

        return story_node, self._comment_tree_from_ordered(ordered, by_id)

    def _full_group_post_from_html(
        self,
        group_id: str,
        post_id: str,
        url: str,
        body: str,
        *,
        allow_truncated_tail: bool = False,
    ) -> GroupPost:
        """Extract a complete group post from authenticated post HTML."""
        started = time.monotonic()
        payloads = tuple(self._iter_relay_prefetched_stream_results(
            body,
            allow_truncated_tail=allow_truncated_tail,
        ))
        payload_elapsed = time.monotonic() - started
        extract_started = time.monotonic()
        story_node, comments = self._extract_story_and_comments_from_payloads(payloads, post_id)
        extract_elapsed = time.monotonic() - extract_started
        if story_node is None:
            raise ClientError(f"Failed to extract post {post_id} from {url}")

        build_started = time.monotonic()
        data = self._group_post_from_story_node(group_id, story_node)
        # The Relay Story may use an internal ID that differs from the public
        # permalink ID.  This parser is scoped to the canonical URL supplied by
        # the caller, so preserve that requested public identity in the output.
        # Downstream exact-post checks can then reject genuinely wrong results
        # instead of weakening their identity guard for Relay's internal ID.
        data["post_id"] = post_id
        data["url"] = url
        data["thread_url"] = url
        data["comments"] = comments
        data["comment_count"] = self._count_comments(comments)
        data["image_urls"] = self._extract_story_image_urls(story_node)
        logger.debug(
            "_full_group_post_from_html[%s]: payload %.2fs, extract %.2fs, build %.2fs, comments=%d, images=%d",
            post_id,
            payload_elapsed,
            extract_elapsed,
            time.monotonic() - build_started,
            data["comment_count"],
            len(data["image_urls"]),
        )
        return GroupPost(**data)

    def _extract_rendered_thread_details(self, url: str, post_id: str) -> Dict[str, List[Dict] | List[str]]:
        """Render a post permalink once and extract comments plus post images."""
        page = self._get_page(url, settle_ms=4000)
        page.wait_for_selector('[role="main"]', timeout=20000)
        page.wait_for_timeout(2500)

        image_urls = page.evaluate(
            r"""
            () => {
              const scope = document.querySelector('[role="dialog"]') || document.querySelector('[role="main"]');
              if (!scope) return [];
              const postArticle = scope.querySelector('[role="article"]');
              if (!postArticle) return [];
              const urls = [];
              const seen = new Set();
              for (const img of postArticle.querySelectorAll('img[src*="scontent"]')) {
                const src = img.getAttribute("src") || "";
                if (!src) continue;
                if (img.naturalWidth <= 100 && img.naturalHeight <= 100) continue;
                if (seen.has(src)) continue;
                seen.add(src);
                urls.push(src);
              }
              return urls;
            }
            """
        )
        if not isinstance(image_urls, list):
            raise ClientError("Rendered Facebook post image extractor did not return a list.")
        for image_url in image_urls:
            if not isinstance(image_url, str) or not image_url:
                raise ClientError("Rendered Facebook post image extractor returned a non-string URL.")

        comments = self._extract_comments_from_rendered_page(page, post_id)
        return {"comments": comments, "image_urls": image_urls}

    def _extract_initial_group_feed(self, group_id: str, body: str) -> tuple[List[Dict], str]:
        """Extract initial group feed stories and pagination cursor from group HTML."""
        posts: List[Dict] = []
        cursor = None
        for result in self._iter_relay_prefetched_stream_results(body):
            label = result.get("label")
            if not isinstance(label, str):
                continue
            data = result.get("data")
            if not isinstance(data, dict):
                raise ClientError("Facebook group feed Relay result is missing data.")
            if label.startswith("GroupsCometFeedRegularStories_paginationGroup$stream"):
                node = data.get("node")
                posts.append(self._group_post_from_story_node(group_id, node))
            if label.startswith("GroupsCometFeedRegularStories_paginationGroup$defer"):
                page_info = data.get("page_info")
                if not isinstance(page_info, dict):
                    raise ClientError("Facebook group feed page_info is missing.")
                cursor = page_info.get("end_cursor")

        if not isinstance(cursor, str) or not cursor:
            raise ClientError("Facebook group feed HTML did not include a pagination cursor.")
        return posts, cursor

    def _extract_group_discussion_request(self, body: str, group_id: str) -> tuple[Dict, str]:
        """Extract the current group discussion Relay variables and document ID."""
        friendly_marker = f'"queryName":"{GROUP_DISCUSSION_FRIENDLY_NAME}"'
        decoder = json.JSONDecoder()
        decoded_variable_keys: List[List[str]] = []
        best_variables: Optional[Dict] = None
        best_document_id: Optional[str] = None
        best_score = -1

        def contains_group_id(value) -> bool:
            if isinstance(value, str):
                return value == group_id
            if isinstance(value, dict):
                return any(contains_group_id(child) for child in value.values())
            if isinstance(value, list):
                return any(contains_group_id(child) for child in value)
            return False

        start = body.find(friendly_marker)
        while start >= 0:
            window_start = max(0, start - 6000)
            window_end = min(len(body), start + 6000)
            window = body[window_start:window_end]

            doc_matches = list(re.finditer(r'"queryID":"(\d+)"', window))
            if doc_matches:
                document_id = doc_matches[-1].group(1)
                variable_markers = [m.start() for m in re.finditer(r'"variables":', window)]
                for marker_index in variable_markers:
                    try:
                        variables, _ = decoder.raw_decode(window, marker_index + len('"variables":'))
                    except json.JSONDecodeError:
                        continue
                    if isinstance(variables, dict):
                        keys = sorted(variables.keys())
                        decoded_variable_keys.append(keys)
                        if contains_group_id(variables):
                            score = 0
                            for key in (
                                "regular_stories_count",
                                "regular_stories_stream_initial_count",
                                "feedLocation",
                                "sortingSetting",
                                "feedbackSource",
                                "groupID",
                            ):
                                if key in variables:
                                    score += 1
                            if score > best_score:
                                best_variables = variables
                                best_document_id = document_id
                                best_score = score
                        continue
                    decoded_variable_keys.append([f"<{type(variables).__name__}>"])

            start = body.find(friendly_marker, start + len(friendly_marker))

        if best_variables is not None and best_document_id is not None:
            return best_variables, best_document_id

        candidates = sorted(set(re.findall(r'"queryName":"([^"]*Group[^"]*)"', body)))[:12]
        title_match = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
        title = html.unescape(re.sub(r"\s+", " ", title_match.group(1))).strip() if title_match else None
        raise GroupDiscussionPreloadMissing(
            "Facebook group discussion Relay preloader variables were not found. "
            f"Page title: {title!r}. Candidate group queries: {candidates}. "
            f"Decoded variable keys near discussion query: {decoded_variable_keys[:8]}"
        )

    def _graphql_group_discussion_posts(
        self,
        group_id: str,
        body: str,
        count: int,
        after: Optional[str] = None,
    ) -> tuple[List[Dict], bool, Optional[str]]:
        """Fetch one group feed page through Facebook's discussion Relay query."""
        current_user = self._facebook_server_define(body, "CurrentUserInitialData")
        dtsg = self._facebook_server_define(body, "DTSGInitialData")
        lsd = self._facebook_server_define(body, "LSD")

        user_id = current_user.get("USER_ID")
        fb_dtsg = dtsg.get("token")
        lsd_token = lsd.get("token")
        if not isinstance(user_id, str) or not user_id:
            raise ClientError("Facebook CurrentUserInitialData is missing USER_ID.")
        if not isinstance(lsd_token, str) or not lsd_token:
            raise ClientError("Facebook LSD data is missing token.")

        variables, document_id = self._extract_group_discussion_request(body, group_id)
        variables["regular_stories_count"] = count
        variables["regular_stories_stream_initial_count"] = count
        if after is not None:
            variables["cursor"] = after
        headers = {
            "Origin": FACEBOOK_BASE_URL,
            "Referer": f"{GROUPS_BASE}/{group_id}/",
            "X-FB-Friendly-Name": GROUP_DISCUSSION_FRIENDLY_NAME,
            "X-FB-LSD": lsd_token,
            "Accept-Encoding": "gzip",
        }
        base_fields = {
            "av": user_id,
            "__user": user_id,
            "__a": "1",
            "lsd": lsd_token,
            "fb_api_caller_class": "RelayModern",
            "server_timestamps": "true",
        }
        # Facebook currently serves authenticated group pages where
        # DTSGInitialData is present but empty. This read-only discussion query
        # still accepts the LSD token and current user fields, so do not fail the
        # list path just because fb_dtsg is absent. Mutating actions continue to
        # use their own browser-backed composer flows.
        if isinstance(fb_dtsg, str) and fb_dtsg:
            base_fields["fb_dtsg"] = fb_dtsg
            base_fields["jazoest"] = self._facebook_jazoest(fb_dtsg)

        relay_request = RelayFormRequest(
            endpoint=f"{FACEBOOK_BASE_URL}/api/graphql/",
            operation_name=GROUP_DISCUSSION_FRIENDLY_NAME,
            document_id=document_id,
            variables=variables,
            base_fields=base_fields,
        )
        payloads = RelayGraphQLClient(self._facebook_http_client()).execute(relay_request, headers=headers)
        return self._extract_group_discussion_posts(
            group_id,
            payloads,
            document_id=document_id,
            variable_keys=sorted(variables.keys()),
        )

    def _extract_group_discussion_posts(
        self,
        group_id: str,
        payloads: tuple[Dict, ...],
        *,
        document_id: Optional[str] = None,
        variable_keys: Optional[List[str]] = None,
    ) -> tuple[List[Dict], bool, Optional[str]]:
        """Extract Story edges and next-page cursor from discussion Relay payloads."""
        posts: List[Dict] = []
        has_next_page = False
        next_cursor: Optional[str] = None
        graph_errors = []

        def update_page_info(page_info: Dict) -> None:
            nonlocal has_next_page, next_cursor
            has_next_page_value = page_info.get("has_next_page")
            if not isinstance(has_next_page_value, bool):
                raise ClientError("Facebook group feed page_info has_next_page is not boolean.")
            cursor_value = page_info.get("end_cursor")
            if cursor_value is not None and not isinstance(cursor_value, str):
                raise ClientError("Facebook group feed page_info end_cursor is not a string.")
            has_next_page = has_next_page or has_next_page_value
            if cursor_value:
                next_cursor = cursor_value

        for payload in payloads:
            errors = payload.get("errors")
            if errors:
                graph_errors.extend(errors if isinstance(errors, list) else [errors])

            data = payload.get("data")
            if isinstance(data, dict):
                streamed_node = data.get("node")
                if isinstance(streamed_node, dict) and streamed_node.get("__typename") == "Story":
                    post = self._group_post_from_story_node(group_id, streamed_node)
                    comments = self._extract_comments_from_relay_payloads((streamed_node,))
                    post["comments"] = comments
                    post["comment_count"] = self._count_comments(comments)
                    post["image_urls"] = self._extract_story_image_urls(streamed_node)
                    posts.append(post)

                group = data.get("group")
                if isinstance(group, dict):
                    group_feed = group.get("group_feed")
                    if isinstance(group_feed, dict):
                        edges = group_feed.get("edges")
                        if not isinstance(edges, list):
                            raise ClientError("Facebook group feed GraphQL edges is not a list.")
                        for edge in edges:
                            if not isinstance(edge, dict):
                                raise ClientError("Facebook group feed GraphQL edge is not an object.")
                            node = edge.get("node")
                            if isinstance(node, dict) and node.get("__typename") == "Story":
                                post = self._group_post_from_story_node(group_id, node)
                                comments = self._extract_comments_from_relay_payloads((node,))
                                post["comments"] = comments
                                post["comment_count"] = self._count_comments(comments)
                                post["image_urls"] = self._extract_story_image_urls(node)
                                posts.append(post)
                        page_info = group_feed.get("page_info")
                        if isinstance(page_info, dict):
                            update_page_info(page_info)

                page_info = data.get("page_info")
                if isinstance(page_info, dict):
                    update_page_info(page_info)

            label = payload.get("label")
            if isinstance(label, str) and label.endswith("$page_info"):
                payload_data = payload.get("data")
                if not isinstance(payload_data, dict):
                    raise ClientError("Facebook streamed group feed page_info payload is missing data.")
                page_info = payload_data.get("page_info")
                if not isinstance(page_info, dict):
                    raise ClientError("Facebook streamed group feed payload is missing page_info.")
                next_cursor_value = page_info.get("end_cursor")
                has_next_page_value = page_info.get("has_next_page")
                if next_cursor_value is not None and not isinstance(next_cursor_value, str):
                    raise ClientError("Facebook streamed group feed end_cursor is not a string.")
                if not isinstance(has_next_page_value, bool):
                    raise ClientError("Facebook streamed group feed has_next_page is not boolean.")
                has_next_page = has_next_page or has_next_page_value
                if next_cursor_value:
                    next_cursor = next_cursor_value

        if graph_errors and not posts:
            raise ClientError(
                "Facebook group feed GraphQL returned errors: "
                f"{graph_errors}. document_id={document_id!r} variable_keys={variable_keys!r}"
            )

        return posts, has_next_page, next_cursor

    @staticmethod
    def _parse_aria_label(aria: str) -> Optional[Dict[str, Optional[str]]]:
        """Classify an aria-label as a comment or reply.

        Returns None if the label is not a comment/reply (e.g. the post itself
        or an unrelated article).
        """
        if not isinstance(aria, str) or not aria:
            return None
        # Reply first — "Reply by X to Y's comment ..."
        m = re.match(r"^Reply by (.+?) to (.+?)'s comment(?:\s.*)?$", aria)
        if m:
            return {"kind": "reply", "author": m.group(1).strip(), "parent_author": m.group(2).strip()}
        m = re.match(r"^Comment by (.+?)(?:\s\d.*|\s[a-z]+ ago.*|\sjust now.*|\sEdited.*|\sYesterday.*)?$", aria)
        if m:
            return {"kind": "comment", "author": m.group(1).strip(), "parent_author": None}
        # Fallback: "Comment by X" with no age suffix
        m = re.match(r"^Comment by (.+)$", aria)
        if m:
            return {"kind": "comment", "author": m.group(1).strip(), "parent_author": None}
        return None

    def _extract_comments_from_rendered_page(self, page, post_id: str) -> List[Dict]:
        """Scrape comments from an already-rendered post page.

        Facebook lazy-loads replies. The caller is responsible for loading the
        permalink first. This method expands every "View N replies" /
        "View more replies" button until no new ones appear, then parses every
        role="article" element inside the dialog.

        Each article is classified via aria-label:
          - "Comment by X"                      -> top-level comment
          - "Reply by X to Y's comment"         -> nested reply (parent=Y)

        Parent/child linkage comes from the comment permalink href, which for
        replies contains `comment_id=PARENT_LEGACY_ID&reply_comment_id=SELF_LEGACY_ID`
        and for top-level comments contains only `comment_id=SELF_LEGACY_ID`.

        Fails loudly (raises ClientError) if:
          - The dialog cannot be located,
          - An article is missing a recognizable aria-label,
          - A reply's parent comment_id cannot be resolved.
        """
        # Iteratively expand "View N replies" / "View more replies" buttons.
        expand_js = r"""
        () => {
          const dialog = document.querySelector('[role="dialog"]') || document.body;
          const els = Array.from(dialog.querySelectorAll('div[role="button"], span, a'));
          const clicks = [];
          for (const el of els) {
            const t = (el.innerText || "").trim();
            if (/^View\s+\d+\s+repl/i.test(t) || /^View\s+more\s+repl/i.test(t)) {
              const target = el.closest('div[role="button"]') || el;
              try { target.click(); clicks.push(t); } catch(e) {}
            }
          }
          return clicks;
        }
        """
        total_clicked: List[str] = []
        for _ in range(5):
            clicked = page.evaluate(expand_js)
            if not isinstance(clicked, list):
                raise ClientError("Reply-expansion evaluator did not return a list.")
            if not clicked:
                break
            total_clicked.extend(clicked)
            page.wait_for_timeout(2000)
        logger.debug("_extract_comments_from_rendered_page: expanded %d reply threads", len(total_clicked))

        # Harvest every [role="article"] inside the dialog (or main, if permalink
        # rendered inline rather than as a dialog).
        harvest_js = r"""
        () => {
          const dialog = document.querySelector('[role="dialog"]');
          const scope = dialog || document.querySelector('[role="main"]');
          if (!scope) return {error: "no dialog or main scope"};
          const arts = Array.from(scope.querySelectorAll('[role="article"]'));
          const out = [];
          for (let i = 0; i < arts.length; i++) {
            const a = arts[i];
            const aria = a.getAttribute("aria-label");
            let permalink = null;
            const anchors = a.querySelectorAll('a[href*="comment_id="]');
            for (const anc of anchors) {
              const h = anc.getAttribute("href") || "";
              if (h.indexOf("comment_id=") !== -1) { permalink = h; break; }
            }
            // Body text: longest [dir="auto"] inside the article is the comment body.
            const autos = Array.from(a.querySelectorAll('[dir="auto"]'))
              .map(n => (n.innerText || "").trim())
              .filter(t => t.length > 0);
            autos.sort((x, y) => y.length - x.length);
            const body = autos.length ? autos[0] : null;
            // Author name — first anchor inside an h3/h4/strong is the author link.
            let authorFromDom = null;
            const h3 = a.querySelector('h3 a, h4 a, strong a');
            if (h3) authorFromDom = (h3.innerText || "").trim();
            // Timestamp — no stable ISO timestamp exposed in the DOM; leave null.
            let timeText = null;
            const timeEl = a.querySelector('a[aria-label][role="link"] abbr, [data-visualcompletion="ignore-dynamic"] abbr');
            if (timeEl) timeText = (timeEl.getAttribute("aria-label") || timeEl.innerText || "").trim() || null;
            out.push({
              domIndex: i,
              aria: aria,
              permalink: permalink,
              body: body,
              authorFromDom: authorFromDom,
              timeText: timeText,
            });
          }
          return {articles: out};
        }
        """
        harvested = page.evaluate(harvest_js)
        if not isinstance(harvested, dict):
            raise ClientError("Comment harvester did not return an object.")
        if harvested.get("error"):
            raise ClientError(f"Comment harvester failed: {harvested['error']}")
        articles = harvested.get("articles")
        if not isinstance(articles, list):
            raise ClientError("Comment harvester returned no articles array.")

        # Parse each article. Extract:
        #   self_legacy_id  = reply_comment_id or comment_id from permalink
        #   parent_legacy_id = comment_id from permalink ONLY if reply_comment_id present
        flat: List[Dict] = []
        by_self_id: Dict[str, Dict] = {}
        for art in articles:
            aria = art.get("aria")
            parsed = self._parse_aria_label(aria) if aria else None
            if parsed is None:
                # Not all [role="article"] elements inside the dialog are comments
                # (the post itself, empty wrapper articles, etc.). Skip silently
                # — we only consume articles whose aria-label identifies them.
                continue
            permalink = art.get("permalink")
            if not isinstance(permalink, str) or "comment_id=" not in permalink:
                raise ClientError(
                    f"Comment article missing permalink href: aria-label={aria!r}"
                )
            # reply_comment_id takes precedence as the "self" id for replies.
            reply_match = re.search(r"reply_comment_id=(\d+)", permalink)
            cid_match = re.search(r"comment_id=(\d+)", permalink)
            if not cid_match:
                raise ClientError(f"Permalink missing comment_id: {permalink}")
            if parsed["kind"] == "reply":
                if not reply_match:
                    raise ClientError(
                        f"Reply article permalink missing reply_comment_id: aria={aria!r} href={permalink}"
                    )
                self_id = reply_match.group(1)
                parent_id = cid_match.group(1)
            else:
                # Top-level comment — reply_comment_id must NOT be present.
                self_id = cid_match.group(1)
                parent_id = None

            author = art.get("authorFromDom") or parsed.get("author")
            if not author:
                raise ClientError(f"Comment article has no author: aria={aria!r}")
            text = art.get("body")
            if text is None:
                raise ClientError(f"Comment article has no text body: aria={aria!r}")
            # Strip a leading duplicate of the author name that Facebook renders
            # at the top of every reply (e.g. "Author Name\nReply text ...").
            if isinstance(text, str) and text.startswith(author + "\n"):
                text = text[len(author) + 1 :]
            # Some replies begin with "<ParentAuthor> " as a mention prefix;
            # the agent surface should keep it since it is user-typed content.

            entry = {
                "_self_id": self_id,
                "_parent_id": parent_id,
                "_kind": parsed["kind"],
                "_parent_author_aria": parsed.get("parent_author"),
                "comment_id": self_id,
                "author": author,
                "text": text,
                "created_time": None,  # DOM does not expose a stable ISO timestamp
                "replies": [],
            }
            # Deduplicate by self_id — Facebook sometimes renders the same
            # comment twice (e.g. a parent summary and then within a thread).
            if self_id in by_self_id:
                continue
            by_self_id[self_id] = entry
            flat.append(entry)

        # Attach replies to their parent comments. Parent linkage is the
        # reply's comment_id (parent_id) -> another entry's self_id.
        top: List[Dict] = []
        for entry in flat:
            if entry["_kind"] == "reply":
                parent = by_self_id.get(entry["_parent_id"])
                if parent is None:
                    # Fallback: DOM order — the nearest preceding top-level
                    # comment whose author matches parent_author_aria.
                    parent = self._find_parent_by_dom_order(
                        flat, entry, parent_author=entry["_parent_author_aria"]
                    )
                if parent is None:
                    raise ClientError(
                        f"Could not resolve parent for reply {entry['_self_id']} "
                        f"(aria suggested parent author {entry['_parent_author_aria']!r}, "
                        f"parent comment_id {entry['_parent_id']!r}). "
                        "Parent comment is missing from the rendered DOM — "
                        "did 'View replies' expansion complete?"
                    )
                parent["replies"].append(entry)
            else:
                top.append(entry)

        # Strip internal fields before returning.
        def clean(entries: List[Dict]) -> List[Dict]:
            out = []
            for e in entries:
                out.append({
                    "comment_id": e["comment_id"],
                    "author": e["author"],
                    "text": e["text"],
                    "created_time": e["created_time"],
                    "replies": clean(e["replies"]),
                })
            return out

        return clean(top)

    @staticmethod
    def _find_parent_by_dom_order(
        flat: List[Dict], reply_entry: Dict, parent_author: Optional[str]
    ) -> Optional[Dict]:
        """Locate the most recent preceding comment entry that matches the
        aria-label's parent author. Used only when the reply's comment_id
        does not resolve to a parent's self_id in the harvested set.
        """
        reply_index = None
        for i, e in enumerate(flat):
            if e is reply_entry:
                reply_index = i
                break
        if reply_index is None:
            return None
        for i in range(reply_index - 1, -1, -1):
            candidate = flat[i]
            if candidate["_kind"] != "comment":
                continue
            if parent_author and candidate["author"] != parent_author:
                continue
            return candidate
        return None

    def _count_comments(self, comments: List[Dict]) -> int:
        """Total comment count including replies."""
        total = 0
        for c in comments:
            total += 1 + self._count_comments(c.get("replies", []))
        return total

    def _find_story_node_by_post_id(self, value, post_id: str) -> Optional[Dict]:
        """Find a full Story node with the requested post_id inside a Relay payload."""
        matches: List[Dict] = []

        def visit(current) -> None:
            if isinstance(current, dict):
                if current.get("post_id") == post_id:
                    matches.append(current)
                for child in current.values():
                    visit(child)
            elif isinstance(current, list):
                for child in current:
                    visit(child)

        visit(value)
        for match in matches:
            author = self._extract_text_path(match, ["feedback", "owning_profile", "name"])
            if author is not None:
                return match
        return matches[0] if matches else None

    def _extract_group_posts(self, page) -> List[Dict]:
        """Extract posts from a Facebook Group feed via h2 author elements.

        Facebook's authenticated group feed renders posts inside a [role="feed"]
        container. Each post has an h2 with the author name, followed by post
        text in [dir="auto"] elements, and reaction counts in "All reactions: N"
        text. Timestamps are obfuscated (individual scrambled characters) and
        cannot be reliably extracted.

        Returns:
            List of post dicts with post_id, author, text, url,
            reactions, comments.
        """
        js = (
            '() => {'
            ' const feed = document.querySelector(\'[role="feed"]\');'
            ' if (!feed) return [];'
            ' const h2s = [...feed.querySelectorAll("h2")];'
            ' const posts = [];'
            ' const seen = new Set();'
            ' for (const h2 of h2s) {'
            '   const authorText = (h2.innerText || "").trim();'
            '   if (!authorText || authorText.length > 80'
            '       || authorText === "New posts"'
            '       || authorText.toLowerCase().includes("sort")) continue;'
            # Walk up to find the post container (has Like/Comment buttons)
            '   let container = h2;'
            '   for (let i = 0; i < 15; i++) {'
            '     container = container.parentElement;'
            '     if (!container) break;'
            '     const t = (container.innerText || "");'
            '     if (t.includes("Like") && t.includes("Comment") && t.length > 50) break;'
            '   }'
            '   if (!container) continue;'
            # Post text: longest dir="auto" block, skip scrambled timestamps
            '   let text = "";'
            '   const dirAutos = container.querySelectorAll(\'[dir="auto"]\');'
            '   for (const el of dirAutos) {'
            '     const t = (el.innerText || "").trim();'
            # Skip: author name, UI labels, scrambled timestamps (single chars with spaces)
            '     if (t === authorText || t === "Like" || t === "Share"'
            '         || t.includes("Comment as") || t.length < 3) continue;'
            # Skip scrambled timestamp text: mostly single chars with no spaces/words
            '     const lines = t.split("\\n");'
            '     const singleCharLines = lines.filter(l => l.trim().length <= 2).length;'
            '     if (lines.length > 5 && singleCharLines / lines.length > 0.5) continue;'
            # Also skip text that looks like concatenated single chars (no spaces, no real words)
            '     const words = t.split(/\\s+/).filter(w => w.length > 0);'
            '     const avgWordLen = words.reduce((s, w) => s + w.length, 0) / (words.length || 1);'
            '     if (words.length <= 3 && avgWordLen > 15 && !t.includes(" ")) continue;'
            '     if (t.length > text.length) text = t;'
            '   }'
            # Fallback: h3 strong content
            '   if (!text) {'
            '     const h3 = container.querySelector("h3 strong, h3");'
            '     if (h3) { const t = (h3.innerText||"").trim(); if (t) text = t; }'
            '   }'
            # Reactions
            '   let reactions = 0;'
            '   const allText = container.innerText || "";'
            '   const rxm = allText.match(/All reactions:[\\s\\n]*(\\d+)/);'
            '   if (rxm) reactions = parseInt(rxm[1]);'
            # Comments
            '   let comments = 0;'
            '   const cm = allText.match(/(\\d+)\\s+comments?/i);'
            '   if (cm) comments = parseInt(cm[1]);'
            # Post ID: require a stable permalink.
            '   let postId = ""; let postUrl = "";'
            '   const links = [...container.querySelectorAll("a")];'
            '   for (const a of links) {'
            '     const href = a.href || "";'
            '     const m = href.match(/\\/posts\\/(\\d+)/) || href.match(/\\/permalink\\/(\\d+)/);'
            '     if (m) { postId = m[1]; postUrl = href.split("?")[0]; break; }'
            '   }'
            '   if (!postId) continue;'
            '   if (seen.has(postId)) continue;'
            '   seen.add(postId);'
            '   const summaryText = text.substring(0, 500);'
            '   posts.push({post_id: postId, title: null, author: authorText, text: summaryText, body: summaryText,'
            '     url: postUrl, thread_url: postUrl, reactions: reactions, comment_count: comments, image_urls: null});'
            ' }'
            ' return posts;'
            ' }'
        )
        result = page.evaluate(js)
        return result if isinstance(result, list) else []

    def _list_group_post_summaries(self, group_id: str, limit: int) -> List[GroupPost]:
        """List summary posts from a rendered Facebook Group feed."""
        url = f"{GROUPS_BASE}/{group_id}/"
        page = self._get_page(url, settle_ms=5000)
        self._assert_authenticated_page(page, url, "group feed")

        collected: List[Dict] = []
        seen_post_ids: set[str] = set()
        scrolls = 0
        no_progress_scrolls = 0
        max_scrolls = 10
        while True:
            added = 0
            for item in self._extract_group_posts(page):
                post_id = item.get("post_id")
                if not isinstance(post_id, str) or not post_id or post_id in seen_post_ids:
                    continue
                seen_post_ids.add(post_id)
                collected.append(item)
                added += 1
                if len(collected) >= limit:
                    break
            if len(collected) >= limit or scrolls >= max_scrolls:
                break

            # Facebook's virtualized group feed only loads another batch after a
            # trusted user-input scroll. JavaScript window.scrollBy reaches the
            # bottom but does not trigger the loader, and rendered batches replace
            # earlier DOM nodes, so keep a deduplicated accumulator across batches.
            page.keyboard_press("End")
            scrolls += 1
            page.wait_for_timeout(2500)
            no_progress_scrolls = 0 if added else no_progress_scrolls + 1
            if no_progress_scrolls >= 2:
                break

        if not collected:
            return []
        print_info(f"Loaded {len(collected[:limit])} post(s) after {scrolls} scroll(s)")
        return [GroupPost(**p) for p in collected[:limit]]

    def list_group_posts(self, group_id: str, limit: int = 20, full_threads: bool = False) -> List[GroupPost]:
        """List posts from a Facebook Group via GraphQL (no browser scroll limit)."""
        url = f"{GROUPS_BASE}/{group_id}/"
        print_info(f"Fetching up to {limit} posts from group {group_id}...")
        body = self._fetch_authenticated_facebook_bootstrap_html(url)
        try:
            self._extract_group_discussion_request(body, group_id)
        except GroupDiscussionPreloadMissing:
            # Facebook can serve an authenticated group page without the Relay
            # discussion query preload. The rendered feed is the owning fallback
            # for that response shape; auth is checked again by that browser path.
            print_info("Group discussion preload missing; reading the rendered group feed instead")
            posts = self._list_group_post_summaries(group_id, limit)
        else:
            posts_data: List[Dict] = []
            seen_post_ids: set[str] = set()
            next_cursor: Optional[str] = None
            has_next_page = True
            page_count = 0
            max_pages = 12
            # A healthy follow-up page always adds at least one new post: we
            # request one extra story (remaining + 1) precisely to absorb the
            # single inclusive-boundary post Facebook repeats as the first edge.
            # So a *full* page that adds zero new posts is not the 1-post overlap
            # — it is a stalled cursor handing back an already-seen window. Stop
            # after a small bounded run of these instead of paging (and burning
            # GraphQL calls) until the socket read times out.
            max_consecutive_zero_add_pages = 2
            consecutive_zero_add_pages = 0
            while len(posts_data) < limit and has_next_page and page_count < max_pages:
                remaining = limit - len(posts_data)
                cursor_before = next_cursor
                # Facebook's group feed cursor is inclusive of the boundary post:
                # a follow-up page fetched with after=end_cursor repeats the
                # previous page's last post as its first edge. Request one extra
                # story past what is missing so that duplicate boundary post does
                # not consume the whole page and stall an otherwise-fillable feed.
                requested_count = remaining + 1 if cursor_before is not None else remaining
                page_posts, has_next_page, next_cursor = self._graphql_group_discussion_posts(
                    group_id,
                    body,
                    count=requested_count,
                    after=cursor_before,
                )
                page_count += 1
                _added = 0
                for post in page_posts:
                    post_id = post.get("post_id")
                    if not isinstance(post_id, str) or not post_id or post_id in seen_post_ids:
                        continue
                    seen_post_ids.add(post_id)
                    posts_data.append(post)
                    _added += 1
                    if len(posts_data) >= limit:
                        break
                logger.debug(
                    "list_group_posts: page=%d requested=%d returned=%d added=%d total=%d "
                    "has_next=%s cursor_advanced=%s",
                    page_count, requested_count, len(page_posts), _added, len(posts_data),
                    has_next_page, next_cursor != cursor_before,
                )
                # Enough posts collected to satisfy the requested limit: return
                # immediately rather than paging for a boundary post we will slice
                # off anyway.
                if len(posts_data) >= limit:
                    break
                # Stop when Facebook reports no further pages, returns no cursor,
                # or the cursor stops advancing (which would otherwise refetch the
                # same window forever).
                if not next_cursor or next_cursor == cursor_before:
                    break
                # Stall guard: a non-empty page that adds no new posts while the
                # cursor keeps advancing is Facebook handing back an already-seen
                # window. The inclusive-boundary overlap only ever repeats ONE
                # post, so a full zero-add page is not that overlap — it is a
                # stalled feed. Page past a small bounded run of these in case a
                # single batch legitimately collides, then stop and return what we
                # have instead of looping until the socket read times out and
                # burning GraphQL calls that aggravate the rate limit.
                if page_posts and _added == 0:
                    consecutive_zero_add_pages += 1
                    if consecutive_zero_add_pages >= max_consecutive_zero_add_pages:
                        break
                else:
                    consecutive_zero_add_pages = 0
            posts = [GroupPost(**p) for p in posts_data[:limit]]
        if not full_threads:
            return posts

        self._facebook_http_client()

        def fetch(post: GroupPost) -> GroupPost:
            if not post.thread_url:
                raise ClientError(f"Facebook group post {post.post_id} is missing thread_url.")
            body = self._fetch_authenticated_facebook_page(
                post.thread_url,
                stop_markers=GROUP_POST_THREAD_STOP_MARKERS,
            )
            return self._full_group_post_from_html(
                group_id,
                post.post_id,
                post.thread_url,
                body,
                allow_truncated_tail=True,
            )

        results: Dict[str, GroupPost] = {}
        with ThreadPoolExecutor(max_workers=len(posts)) as executor:
            futures = {executor.submit(fetch, post): post.post_id for post in posts}
            for future in as_completed(futures):
                post_id = futures[future]
                results[post_id] = future.result()

        return [results[post.post_id] for post in posts]

    def get_group_post(self, post_ref: str) -> GroupPost:
        """Get a specific post from a Facebook Group.

        Args:
            post_ref: Full URL or path like 'group_id/posts/post_id'.

        Returns:
            GroupPost with post details.
        """
        ref = self._group_post_ref_parts(post_ref)
        url = ref["url"]
        group_id = ref["group_id"]
        post_id = ref["post_id"]

        body = self._fetch_authenticated_facebook_page(
            url,
            stop_markers=GROUP_POST_THREAD_STOP_MARKERS,
        )
        return self._full_group_post_from_html(
            group_id,
            post_id,
            url,
            body,
            allow_truncated_tail=True,
        )

    def create_group_post(self, group_id: str, text: str) -> Dict:
        """Create a new post in a Facebook Group.

        Args:
            group_id: The group ID.
            text: The post content text.

        Returns:
            Dict with success status.
        """
        print_info(f"Creating post in group {group_id}...")
        page = self._get_page(f"{GROUPS_BASE}/{group_id}/", settle_ms=0)

        # Wait for feed to load
        page.wait_for_selector('[role="feed"]', timeout=15000)

        # Click the post composer to activate it
        js_activate = (
            '() => {'
            ' const buttons = document.querySelectorAll(\'[role="button"]\');'
            ' for (const btn of buttons) {'
            '   const t = (btn.innerText || "").toLowerCase();'
            '   if (t.includes("write something") || t.includes("what\'s on your mind")) {'
            '     btn.click();'
            '     return {success: true};'
            '   }'
            ' }'
            ' return {success: false, error: "Post composer not found"};'
            ' }'
        )
        activated = page.evaluate(js_activate)
        if not isinstance(activated, dict) or not activated.get("success"):
            raise ClientError(f"Failed to open post composer: {(activated or {}).get('error', 'unknown')}")

        page.wait_for_selector('[role="textbox"][contenteditable="true"]', timeout=10000)

        # Type text into the composer textbox
        js_type = (
            '(text) => {'
            ' const boxes = document.querySelectorAll(\'[role="textbox"][contenteditable="true"]\');'
            ' if (!boxes.length) return {success: false, error: "Composer textbox not found"};'
            # Use the last textbox (the dialog composer, not inline)
            ' const box = boxes[boxes.length - 1];'
            ' box.focus();'
            ' document.execCommand("insertText", false, text);'
            ' return {success: true};'
            ' }'
        )
        typed = page.evaluate(js_type, text)
        if not isinstance(typed, dict) or not typed.get("success"):
            raise ClientError(f"Failed to type post: {(typed or {}).get('error', 'unknown')}")

        page.wait_for_timeout(1000)

        # Click the Post button
        js_submit = (
            '() => {'
            ' const buttons = document.querySelectorAll(\'[role="button"]\');'
            ' for (const btn of buttons) {'
            '   const label = (btn.getAttribute("aria-label") || "").toLowerCase();'
            '   const text = (btn.innerText || "").trim();'
            '   if (text === "Post" || label === "post") {'
            '     btn.click();'
            '     return {success: true};'
            '   }'
            ' }'
            ' return {success: false, error: "Post button not found"};'
            ' }'
        )
        submitted = page.evaluate(js_submit)
        if not isinstance(submitted, dict) or not submitted.get("success"):
            raise ClientError(f"Failed to submit post: {(submitted or {}).get('error', 'unknown')}")

        self._wait_for_rendered_text(page, text, selector='[role="feed"]', timeout_ms=20000)

        return {"success": True, "verified": True, "group_id": group_id, "text": text}

    def comment_on_post(self, post_url: str, text: str) -> Dict:
        """Comment on a Facebook Group post.

        Args:
            post_url: Full post URL or path like 'group_id/posts/post_id'.
            text: The comment text.

        Returns:
            Dict with success status.
        """
        ref = self._group_post_ref_parts(post_url)
        url = ref["url"]
        group_id = ref["group_id"]
        post_id = ref["post_id"]

        print_info("Commenting on post...")
        page = self._get_page(url, settle_ms=0)
        page.wait_for_selector('[role="main"]', timeout=15000)
        self._assert_authenticated_page(page, url, "group post comment")

        # Activate the post's comment control if the composer is not already
        # visible. On current Facebook post pages the Lexical textbox is often
        # created lazily only after clicking Comment.
        #
        # We navigated to the canonical single-post permalink URL, so the
        # [role="main"] region isolates exactly one target post (the post body,
        # its comment composer, and the existing comments). We therefore scope
        # the activator to [role="main"] and require a UNIQUE comment surface
        # there, rather than to a [role="article"] element.
        #
        # Why not scope to a [role="article"]: Facebook moved the post-permalink
        # anchor and the comment controls OUT of the [role="article"] wrapper
        # that sits in [role="main"]. The article wrappers are now empty of the
        # post's permalink anchor and comment controls (verified against the live
        # DOM), so the old "one article containing BOTH a matching permalink link
        # AND a comment control" requirement matched 0 articles and aborted with
        # "Expected one target article ... found 0". The permalink-page scoping
        # below is the resilient replacement: post identity is already pinned by
        # the canonical URL we navigated to, and the post-write verifier
        # (_wait_for_comment_on_exact_post) confirms the comment landed on the
        # exact post id afterward.
        js_activate = (
            '(args) => {'
            ' const isVisible = (el) => {'
            '   const r = el.getBoundingClientRect();'
            '   return r.width > 0 && r.height > 0;'
            ' };'
            ' const main = document.querySelector(\'[role="main"]\');'
            ' if (!main) return {success: false, error: "Main region not found"};'
            ' const composerSelector ='
            '   \'[role="textbox"][contenteditable="true"]\';'
            # The comment composer is rendered in a React portal OUTSIDE
            # [role="main"], and current Facebook builds no longer always set
            # data-lexical-editor="true" on the visible comment box. Detect an
            # already-visible composer document-wide by the accessibility
            # textbox/contenteditable contract and exclude Search-like boxes.
            ' const visibleComposers = Array.from(document.querySelectorAll(composerSelector))'
            '   .filter(el => {'
            '     if (!isVisible(el)) return false;'
            '     const label = ((el.getAttribute("aria-label") || "") + " " + (el.getAttribute("aria-placeholder") || "")).toLowerCase();'
            '     return !label.includes("search");'
            '   });'
            ' if (visibleComposers.length === 1) {'
            '   return {success: true, alreadyVisible: true};'
            ' }'
            ' if (visibleComposers.length > 1) {'
            '   return {success: false, error: "Multiple visible comment composers on page (" + visibleComposers.length + ")"};'
            ' }'
            # No composer rendered yet — find and click the post\'s Comment
            # activator within [role="main"]. Prefer an exact "comment" text
            # control, then a comment-related aria-label. Require uniqueness so we
            # cannot click the wrong control.
            ' const clickables = Array.from(main.querySelectorAll('
            '   \'button, [role="button"], a\''
            ' )).filter(isVisible);'
            ' const exactText = clickables.filter(el => (el.innerText || "").trim().toLowerCase() === "comment");'
            ' if (exactText.length === 1) {'
            '   exactText[0].click();'
            '   return {success: true, alreadyVisible: false, activator: "exact-comment-text"};'
            ' }'
            ' if (exactText.length > 1) {'
            '   return {success: false, error: "Multiple exact Comment activators in main region (" + exactText.length + ")"};'
            ' }'
            ' const labelMatches = clickables.filter(el => {'
            '   const label = (el.getAttribute("aria-label") || "").trim().toLowerCase();'
            '   return label === "leave a comment"'
            '     || label === "write a comment"'
            '     || label.includes("comment as");'
            ' });'
            ' if (labelMatches.length === 1) {'
            '   labelMatches[0].click();'
            '   return {success: true, alreadyVisible: false, activator: "comment-label"};'
            ' }'
            ' if (labelMatches.length > 1) {'
            '   return {success: false, error: "Multiple labeled comment activators in main region (" + labelMatches.length + ")"};'
            ' }'
            ' return {success: false, error: "Comment activator not found in main region"};'
            ' }'
        )
        activated = page.evaluate(js_activate, {"groupId": group_id, "postId": post_id})
        if not isinstance(activated, dict) or not activated.get("success"):
            raise ClientError(f"Failed to activate comment composer: {(activated or {}).get('error', 'unknown')}")
        self._assert_authenticated_page(page, url, "group post comment composer")
        self._wait_for_visible_comment_composer(page, timeout_ms=10000)

        # Find and focus the comment box. Facebook personalizes the
        # aria-placeholder/aria-label and no longer guarantees the old Lexical
        # data attribute, so use the same visible contenteditable textbox probe
        # that the dry selector test uses.
        typed = self._insert_text_into_visible_comment_composer(page, text)
        if not isinstance(typed, dict) or not typed.get("success"):
            raise ClientError(f"Failed to type comment: {(typed or {}).get('error', 'unknown')}")

        page.wait_for_timeout(500)

        # Snapshot the comment count BEFORE submit so the verifier has a
        # delta signal to corroborate the composer-cleared check.
        comment_count_before = self._count_post_comments(page)

        # Press Enter to submit the comment
        js_submit = (
            '() => {'
            ' const boxes = document.querySelectorAll(\'[role="textbox"][contenteditable="true"]\');'
            ' for (const box of boxes) {'
            '   if (box.textContent && box.textContent.trim().length > 0) {'
            '     box.dispatchEvent(new KeyboardEvent("keydown",'
            '       {key: "Enter", code: "Enter", keyCode: 13, bubbles: true}));'
            '     return {success: true};'
            '   }'
            ' }'
            ' return {success: false, error: "Could not find filled comment box"};'
            ' }'
        )
        submitted = page.evaluate(js_submit)
        if not isinstance(submitted, dict) or not submitted.get("success"):
            raise ClientError(f"Failed to submit comment: {(submitted or {}).get('error', 'unknown')}")

        composer_state = self._wait_for_composer_cleared(page, timeout_ms=10000)
        if not composer_state.get("cleared"):
            raise ClientError(
                "Comment submit did not clear the composer for the exact target post "
                f"{post_id}. Composer remaining text: {composer_state.get('remaining', [])}."
            )
        verification = self._wait_for_comment_on_exact_post(
            group_id,
            post_id,
            text,
            timeout_ms=20000,
        )
        verification["composer"] = composer_state
        verification["commentCountBefore"] = comment_count_before

        return {
            "success": True,
            "verified": verification["verification"] == "confirmed",
            "verification": verification["verification"],
            "verificationDetails": verification,
            "post_url": post_url,
            "group_id": group_id,
            "post_id": post_id,
            "text": text,
        }

    def reply_to_comment(self, post_url: str, comment_index: int, text: str) -> Dict:
        """Reply to a specific comment on a Facebook Group post.

        Args:
            post_url: Full post URL or path like 'group_id/posts/post_id'.
            comment_index: 1-based index of the comment to reply to.
            text: The reply text.

        Returns:
            Dict with success status.
        """
        if post_url.startswith("http"):
            url = post_url
        else:
            url = f"https://www.facebook.com/groups/{post_url}"

        print_info(f"Replying to comment #{comment_index}...")
        page = self._get_page(url, settle_ms=0)
        page.wait_for_selector('[role="main"]', timeout=15000)

        # Click the Reply link on the Nth comment
        js_reply = (
            '(commentIndex) => {'
            # Find all "Reply" links/buttons inside the post article.
            ' const replyLinks = [];'
            ' const allEls = document.querySelectorAll(\'[role="article"] [role="button"], [role="article"] a, [role="article"] span\');'
            ' for (const el of allEls) {'
            '   const text = (el.innerText || "").trim();'
            '   if (text === "Reply" || text === "reply") {'
            '     replyLinks.push(el);'
            '   }'
            ' }'
            ' if (commentIndex < 1 || commentIndex > replyLinks.length) {'
            '   return {success: false, error: "Comment index " + commentIndex + " out of range (found " + replyLinks.length + " comments)"};'
            ' }'
            ' replyLinks[commentIndex - 1].click();'
            ' return {success: true, total_comments: replyLinks.length};'
            ' }'
        )
        clicked = page.evaluate(js_reply, comment_index)
        if not isinstance(clicked, dict) or not clicked.get("success"):
            raise ClientError(f"Failed to click Reply: {(clicked or {}).get('error', 'unknown')}")

        page.wait_for_selector('[role="textbox"][contenteditable="true"]', timeout=10000)

        # Type into the reply textbox (should be the most recently focused/appearing textbox)
        js_type = (
            '(text) => {'
            ' const boxes = document.querySelectorAll(\'[role="textbox"][contenteditable="true"]\');'
            ' if (!boxes.length) return {success: false, error: "Reply textbox not found"};'
            # The reply textbox is typically the last one that appeared
            ' const box = boxes[boxes.length - 1];'
            ' box.focus();'
            ' document.execCommand("insertText", false, text);'
            ' return {success: true};'
            ' }'
        )
        typed = page.evaluate(js_type, text)
        if not isinstance(typed, dict) or not typed.get("success"):
            raise ClientError(f"Failed to type reply: {(typed or {}).get('error', 'unknown')}")

        page.wait_for_timeout(500)

        # Press Enter to submit
        js_submit = (
            '() => {'
            ' const boxes = document.querySelectorAll(\'[role="textbox"][contenteditable="true"]\');'
            ' for (const box of boxes) {'
            '   if (box.textContent && box.textContent.trim().length > 0) {'
            '     box.dispatchEvent(new KeyboardEvent("keydown",'
            '       {key: "Enter", code: "Enter", keyCode: 13, bubbles: true}));'
            '     return {success: true};'
            '   }'
            ' }'
            ' return {success: false, error: "Could not find filled reply box"};'
            ' }'
        )
        # Snapshot count before submitting the reply (replies are nested
        # articles too, so the count delta still applies).
        comment_count_before = self._count_post_comments(page)

        submitted = page.evaluate(js_submit)
        if not isinstance(submitted, dict) or not submitted.get("success"):
            raise ClientError(f"Failed to submit reply: {(submitted or {}).get('error', 'unknown')}")

        # Same multi-stage verification as comment_on_post.
        verification = self._verify_comment_landed(
            page, text, comment_count_before,
            composer_timeout_ms=10000, secondary_timeout_ms=10000,
        )

        return {
            "success": True,
            "verified": verification["verification"] == "confirmed",
            "verification": verification["verification"],
            "verificationDetails": verification,
            "post_url": post_url,
            "comment_index": comment_index,
            "text": text,
        }

    def list_requests(self, limit: int = 20) -> List[Dict]:
        """List Messenger message requests.

        Args:
            limit: Maximum number of requests to return.

        Returns:
            List of message request dicts.
        """
        from .messenger_parsers import extract_conversations_from_snapshot

        print_info("Loading message requests...")
        requested_url = "https://www.facebook.com/messages/filtered/"
        page = self._get_page(requested_url)
        self._assert_authenticated_page(page, requested_url, "Messenger message requests")
        page.wait_for_timeout(1000)  # extra wait

        snapshot = self._snapshot(page)
        requests = extract_conversations_from_snapshot(snapshot)
        return requests[:limit]


def get_client() -> FacebookClient:
    return FacebookClient()
