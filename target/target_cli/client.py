"""Target client.

Reads (search / product detail / inventory / stores) go through the redsky JSON
API over httpx -- no browser (see ``api.py``). Cart and checkout mutations use the
logged-in browser session. Fail loud: a missing/expired redsky session or a bot
wall raises ``ClientError`` telling the user to re-run ``target auth login``. No
DOM fallback for reads.
"""

import json
import os
import re
from contextlib import contextmanager
from typing import List, Optional

import typer

from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from . import cards as card_store
from .api import RedskyAPI, get_redsky_api
from .config import get_config
from .parsers import (
    normalize_fulfillment,
    normalize_product_detail,
    normalize_search_products,
    normalize_store,
    normalize_stores,
)
from .prime import prime_redsky

# Read every variation dimension on a PDP as data (one list of chip records per
# @web/VariationComponent). Variant chips are <button>s with an href to the
# child variant's PDP; the selected chip's aria-label ends in ", selected".
_READ_VARIANTS_JS = r"""() => {
  const comps = [...document.querySelectorAll('[data-test="@web/VariationComponent"]')];
  return comps.map(comp => [...comp.querySelectorAll('button[href*="/A-"]')].map(ch => ({
    tcin: ((ch.getAttribute('href') || '').match(/A-(\d+)/) || [])[1] || null,
    selected: /,\s*selected\s*$/i.test(ch.getAttribute('aria-label') || '')
              || /styles_selected/.test(ch.getAttribute('class') || ''),
    orderable: !(ch.hasAttribute('disabled') || ch.getAttribute('aria-disabled') === 'true'),
    label: ch.getAttribute('aria-label') || '',
  })));
}"""


class TargetClient:
    """Reads via redsky (httpx); cart/checkout via the logged-in browser."""

    def __init__(self):
        self.config = get_config()
        self._api: Optional[RedskyAPI] = None
        self._browser = None

    def _get_api(self) -> RedskyAPI:
        if self._api is None:
            self._api = get_redsky_api(self.config)
        return self._api

    def _get_browser(self):
        if self._browser is None:
            self._browser = self.config.get_browser()
        return self._browser

    def close(self):
        if self._api is not None:
            self._api.close()
            self._api = None
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    # ---------- reads (redsky API) ----------

    @cached
    def search(
        self, query: str, limit: int = 24,
        store_id: Optional[str] = None, zip_code: Optional[str] = None,
    ) -> List[dict]:
        """Search for items on Target."""
        count = min(max(limit, 1), 96)
        raw = self._get_api().search(query, count=count, store_id=store_id, zip_code=zip_code)
        return normalize_search_products(raw)["products"][:limit]

    @cached
    def get_item(self, item_id: str, store_id: Optional[str] = None) -> dict:
        """Get details for a specific item."""
        raw = self._get_api().product_detail(item_id, store_id=store_id)
        detail = normalize_product_detail(raw)
        if not detail.get("title"):
            raise ClientError(f"No product found for TCIN {item_id}.")
        # pdp groups variants under a parent tcin; echo the requested id, keep the
        # group id separately.
        detail["group_id"] = detail.get("id")
        detail["id"] = item_id
        return detail

    def get_inventory(
        self, item_id: str,
        store_id: Optional[str] = None, zip_code: Optional[str] = None,
    ) -> dict:
        """Get pickup + shipping availability for an item (not cached -- live stock)."""
        raw = self._get_api().fulfillment(item_id, store_id=store_id, zip_code=zip_code)
        return normalize_fulfillment(raw, item_id)

    @cached
    def find_stores(self, zip_code: str) -> List[dict]:
        """List Target stores near a zip code."""
        return normalize_stores(self._get_api().nearby_stores(zip_code))

    @cached
    def get_store(self, store_id: str) -> dict:
        """Get a single Target store by id."""
        store = normalize_store(self._get_api().store_location(store_id))
        if not store:
            raise ClientError(f"No store found for id {store_id}.")
        return store

    # ---------- redsky session ----------

    def refresh_session(self) -> int:
        """Re-capture the redsky read session via a headed browser prime."""
        return prime_redsky(self.config)

    # ---------- cart / checkout (browser) ----------
    # Mutations run HEADED: Target's bot layer (PerimeterX) rejects headless
    # cart/checkout actions ("Item not added to cart"). Reads (cart list) work
    # headless. data-test attrs below are captured from live DOM.

    @contextmanager
    def _headed_browser(self):
        """Yield a headed browser for a mutation, restoring HEADLESS afterward."""
        prev = os.environ.get("HEADLESS")
        os.environ["HEADLESS"] = "false"
        browser = self.config.get_browser()
        try:
            yield browser
        finally:
            browser.close()
            if prev is None:
                os.environ.pop("HEADLESS", None)
            else:
                os.environ["HEADLESS"] = prev

    @staticmethod
    def _price(text: Optional[str]) -> Optional[str]:
        import re
        if not text:
            return None
        match = re.search(r"\$[\d,]+\.\d{2}", text)
        return match.group(0) if match else text.strip()

    def get_cart(self) -> dict:
        """Get cart contents (read -- headless)."""
        page = self._get_browser().get_page("https://www.target.com/cart")
        items = []
        try:
            page.wait_for_selector('[data-test="cartItem"]', timeout=10000)
            for item in page.locator('[data-test="cartItem"]').all():
                title_el = item.locator('[data-test="cartItem-title"]')
                price_el = item.locator('[data-test="cartItem-price"]')
                items.append({
                    "title": title_el.inner_text().strip() if title_el.count() > 0 else "Unknown",
                    "price": self._price(price_el.inner_text()) if price_el.count() > 0 else None,
                })
        except Exception:
            pass
        total_el = page.locator('[data-test="cart-summary-total"]')
        total = self._price(total_el.inner_text()) if total_el.count() > 0 else "$0.00"
        return {"items": items, "total": total}

    # data-test attrs for each fulfillment method: the selector cell + its add button.
    _FULFILLMENT = {
        "pickup": ("fulfillment-cell-pickup", "orderPickupButton"),
        "shipping": ("fulfillment-cell-shipping", "shipItButton"),
        "delivery": ("fulfillment-cell-delivery", "scheduledDeliveryButton"),
    }

    def add_to_cart(self, item_id: str, method: str = "pickup") -> None:
        """Add item to cart via the given fulfillment method (default pickup, headed)."""
        if method not in self._FULFILLMENT:
            raise ClientError(f"Unknown fulfillment method '{method}'. Use pickup, shipping, or delivery.")
        cell_test, button_test = self._FULFILLMENT[method]

        with self._headed_browser() as browser:
            page = browser.get_page(f"https://www.target.com/p/-/A-{item_id}")
            try:
                page.wait_for_selector(f'button[data-test="{cell_test}"]', timeout=20000)
            except Exception:
                raise ClientError(f"'{method}' is not available for item {item_id}.")

            # Variation-parent PDPs (e.g. Old Spice group 87220385) keep the
            # fulfillment button disabled until a scent/size variant is chosen.
            # Select the requested (or first orderable) variant; the PDP
            # re-renders, so re-wait for the fulfillment cell afterward. No-op
            # for single-SKU PDPs, which have no variation component.
            if self._select_variant(page, item_id):
                try:
                    page.wait_for_selector(f'button[data-test="{cell_test}"]', timeout=15000)
                except Exception:
                    raise ClientError(
                        f"'{method}' is not available for item {item_id} after selecting a variant."
                    )

            cell = page.locator(f'button[data-test="{cell_test}"]')
            if "unselected" in (cell.get_attribute("aria-label") or ""):
                cell.click()
                page.wait_for_timeout(1000)

            try:
                page.wait_for_selector(f'button[data-test="{button_test}"]:not([disabled])', timeout=12000)
            except Exception:
                raise ClientError(f"No active {method} 'Add to cart' button for item {item_id}.")
            page.locator(f'button[data-test="{button_test}"]:not([disabled])').first.click()
            self._confirm_add(page, item_id)

    def _select_variant(self, page, item_id: str) -> bool:
        """Select a scent/size variant on a variation-parent PDP (no-op for single SKUs).

        Split into READ (DOM) / DECIDE (pure Python) / ACT (click) so the choice
        is unit-testable. Target's variation parents render one or more
        ``@web/VariationComponent`` chip groups; each chip is a ``<button>``
        carrying an ``href`` to a child variant's PDP with the selected chip's
        ``aria-label`` ending in ", selected". Until a variant is chosen the
        fulfillment 'Add to cart' button stays disabled. Returns True when a chip
        was clicked (the PDP re-renders, so the caller must re-wait).
        """
        components = page.evaluate(_READ_VARIANTS_JS)
        if not components:  # single-SKU PDP has no variation component
            return False
        clicked = False
        for tcin in self._pick_variants(components, item_id):
            chip = page.locator(f'[data-test="@web/VariationComponent"] button[href*="/A-{tcin}"]')
            if chip.count() == 0:
                raise ClientError(f"Variant chip for TCIN {tcin} vanished before it could be selected.")
            chip.first.click()
            page.wait_for_timeout(1500)  # let the selected variant + fulfillment re-render
            clicked = True
        return clicked

    @staticmethod
    def _pick_variants(components: List[List[dict]], item_id: str) -> List[str]:
        """Decide which variant chip TCIN to click in each variation dimension.

        ``components`` is one list of chip dicts (``{tcin, selected, orderable}``)
        per ``@web/VariationComponent``. For each dimension: prefer the chip
        matching the requested TCIN (so the right variant is added even when
        Target auto-selected a different one); if none matches but a chip is
        already selected (e.g. the caller passed the group TCIN) leave it; else
        pick the first orderable chip. Returns only the TCINs that need a click
        (an already-correct selection yields none). Fails loud when a dimension
        has chips but none are orderable.
        """
        want = str(item_id)
        to_click: List[str] = []
        for chips in components:
            if not chips:
                continue
            wanted = next((c for c in chips if c["tcin"] == want and c["orderable"]), None)
            if wanted is not None:
                if not wanted["selected"]:
                    to_click.append(wanted["tcin"])
                continue
            if any(c["selected"] for c in chips):
                continue
            pick = next((c for c in chips if c["orderable"]), None)
            if pick is None:
                raise ClientError(
                    f"Item {item_id} is a variation group but no orderable variant is available to select."
                )
            to_click.append(pick["tcin"])
        return to_click

    def _confirm_add(self, page, item_id: str) -> None:
        """Wait for an add-to-cart success drawer, or fail loudly on Target's error."""
        js = r"""() => {
          const body = (document.body.innerText || '');
          if (/something went wrong|item not added|couldn.?t be added|unable to add/i.test(body))
            return {state: 'error'};
          const drawer = document.querySelector('[data-test="@web/AddToCart/Drawer"], [data-test*="AddToCartModal" i]');
          if (drawer || /added to cart|view cart|added to your cart/i.test(body))
            return {state: 'ok'};
          return {state: 'pending'};
        }"""
        for _ in range(20):
            page.wait_for_timeout(750)
            state = (page.evaluate(js) or {}).get("state")
            if state == "error":
                raise ClientError(f"Target rejected the add for item {item_id} (\"Something went wrong\").")
            if state == "ok":
                return
        raise ClientError(f"Timed out confirming add to cart for item {item_id}.")

    def remove_from_cart(self, item_id: str) -> None:
        """Remove an item from the cart by TCIN (headed)."""
        with self._headed_browser() as browser:
            page = browser.get_page("https://www.target.com/cart")
            try:
                page.wait_for_selector('[data-test="cartItem"]', timeout=12000)
            except Exception:
                raise ClientError("Cart is empty or did not load.")

            for item in page.locator('[data-test="cartItem"]').all():
                if item.locator(f'a[href*="A-{item_id}"]').count() == 0:
                    continue
                remove = item.locator('button[data-test="cartItem-deleteBtn"]')
                if remove.count() == 0:
                    raise ClientError(f"Found item {item_id} but no delete button.")
                remove.first.click()
                page.wait_for_timeout(2500)
                return
            raise ClientError(f"Item {item_id} not found in cart.")

    # ---------- payment methods (browser, headed) ----------
    # The CLI never handles the real card. `payment-method add` opens Target's
    # own add-card page (headed, authenticated); the HUMAN enters + saves the
    # card, and the CLI captures only a "pointer" (last4 + brand) by diffing the
    # wallet before/after. Checkout later selects that wallet card by last4.

    def capture_new_card(self) -> dict:
        """Open Target's add-card page for the human, then capture the new card's pointer.

        Returns ``{"last4", "brand"}`` for the single card that appeared in the
        wallet while the page was open. The card number/expiration/CVV are typed
        by the human into Target's form and never touch the CLI. Fails loud if no
        card (or more than one) was added.
        """
        with self._headed_browser() as browser:
            before_page = browser.get_page("https://www.target.com/account/payments")
            before = {c["id"] for c in self._read_wallet_cards(before_page) if c.get("id")}

            add_page = browser.get_page("https://www.target.com/account/payments/new")
            try:
                add_page.wait_for_selector('[data-test="creditCardInput-cardNumber"]', timeout=25000)
            except Exception:
                raise ClientError(
                    "Could not open Target's add-card page. Make sure you're signed in "
                    "(`target auth login --force`)."
                )
            # Hand off to the human: they type + save the card in the open window.
            # allow_no_tty=False -> fail loud in a non-interactive run (this step
            # is inherently interactive).
            browser._prompt_enter_eof_safe(
                "A Chrome window is open on Target's add-card page. Enter and SAVE your "
                "card there (number, expiration, CVV, billing address), then press Enter "
                "here to capture it.",
                allow_no_tty=False,
            )

            after_page = browser.get_page("https://www.target.com/account/payments")
            after = self._read_wallet_cards(after_page)
            new = [c for c in after if c.get("id") and c["id"] not in before]
            if not new:
                raise ClientError(
                    "No newly-saved card was found in your Target wallet. If you did save one, "
                    "re-run `target payment-method add`."
                )
            if len(new) > 1:
                raise ClientError(
                    "More than one new card appeared in the wallet; add cards one at a time."
                )
            return {"last4": new[0]["last4"], "brand": new[0].get("brand")}

    def _read_wallet_cards(self, page) -> List[dict]:
        """Scrape the saved Target wallet cards from an already-loaded payments page.

        Gate on the page's own chrome (title / add-card button), which renders
        whether or not any cards exist. A timeout here means the payments page
        FAILED to load (not signed in, bot wall, DOM change) -- fail loud rather
        than return ``[]``, which would masquerade as an empty wallet and produce
        false "card not found" / bad capture-diff results downstream.
        """
        try:
            page.wait_for_selector(
                '[data-test="payments-page-title"], [data-test="addNewButton-payments"]',
                timeout=15000,
            )
        except Exception:
            raise ClientError(
                "Could not load your Target wallet page. Make sure you're signed in "
                "(`target auth login --force`), then try again."
            )
        # Page loaded; zero card containers now genuinely means an empty wallet.
        return page.evaluate(r"""() => {
          const out = [];
          document.querySelectorAll('[data-test^="listCardContainer-"]').forEach(c => {
            const txt = (c.innerText||'').replace(/\s+/g,' ').trim();
            out.push({
              // The container's data-test id is unique per card -- diff on this,
              // not last4 (two cards can share a last4).
              id: c.getAttribute('data-test'),
              brand: (txt.match(/^(American Express|[A-Za-z]+)/) || [])[1] || null,
              last4: (txt.match(/ending in\s*(\d{4})/i) || [])[1] || null,
              expires: (txt.match(/exp\s*([\d/]+)/i) || [])[1] || null,
              // The default card carries a dedicated "Default" pill; non-default
              // cards only show a "Set as default" control (whose text also
              // contains "default"), so match the pill element, not the word.
              default: !!c.querySelector('[data-test="defaultPill"]'),
            });
          });
          return out;
        }""") or []

    @staticmethod
    def _type_field(page, selector: str, value: str) -> None:
        """Enter a value via real keystrokes and verify it stuck (retry on miss).

        Target's masked React inputs ignore fill()'d values and its address form
        re-renders as it hydrates, so each field is focused, cleared, typed, and
        read back; a normalized (alnum-only) compare tolerates input masking.
        """
        norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
        want = norm(value)
        sel = json.dumps(selector)
        for _ in range(4):
            page.locator(selector).first.click()
            page.evaluate(f"() => {{ const e = document.querySelector({sel}); if (e) {{ e.focus(); e.select && e.select(); }} }}")
            page.type_text(value)
            page.wait_for_timeout(200)
            got = page.evaluate(f"() => {{ const e = document.querySelector({sel}); return e ? (e.value || '') : ''; }}")
            if norm(got) == want or (want and want in norm(got)):
                return
            # clear before retrying
            page.evaluate(f"""() => {{ const e = document.querySelector({sel}); if (e) {{
              const p = e instanceof HTMLInputElement ? HTMLInputElement.prototype : null;
              const d = p ? Object.getOwnPropertyDescriptor(p, 'value') : null;
              if (d && d.set) d.set.call(e, ''); else e.value = '';
              e.dispatchEvent(new Event('input', {{bubbles: true}}));
            }} }}""")
        raise ClientError(f"Could not reliably enter a value into {selector}.")

    def list_payments(self) -> List[dict]:
        """List saved Target wallet payment cards (read -- headless)."""
        page = self._get_browser().get_page("https://www.target.com/account/payments")
        return self._read_wallet_cards(page)

    def checkout(
        self,
        place_order: bool,
        card: Optional[str] = None,
        pickup_email: Optional[str] = None,
        pickup_name: Optional[str] = None,
    ) -> dict:
        """Drive checkout (headed). Dry-run stops at the Place Order screen.

        ``card`` is the name of a saved card pointer (see ``payment-method add``);
        checkout selects that wallet card by its last4. When omitted, the profile's
        default pointer is used if one exists, else Target's currently-selected card
        is left untouched. If Target then prompts for a CVV (debit cards do), it is
        requested securely at that moment -- never stored. Accounts with no saved
        pickup contact block a pickup order with "Enter your pickup info";
        ``pickup_email`` (and optionally ``pickup_name``) fill that contact.
        """
        # Resolve --card to (last4, stored cvv) up front (pure; reads cards.json)
        # so a bad pointer name fails before we even open the browser.
        last4, stored_cvv = self._resolve_checkout_card(card)

        # Fall back to the profile's stored pickup-contact defaults when the
        # command didn't pass them (Target doesn't persist the pickup contact).
        if pickup_email is None or pickup_name is None:
            from . import prefs
            contact = prefs.get_pickup_contact(self.config)
            pickup_email = pickup_email or contact.get("email")
            pickup_name = pickup_name or contact.get("name")

        with self._headed_browser() as browser:
            page = browser.get_page("https://www.target.com/checkout")
            try:
                page.wait_for_selector('button[data-test="placeOrderButton"]', timeout=25000)
            except Exception:
                raise ClientError(
                    "Could not reach the Place Order screen. Ensure your cart has items and "
                    "your account has a pickup/shipping address and payment method saved."
                )

            summary = self._read_order_summary(page)
            if not place_order:
                summary["placed"] = False
                summary["note"] = "Dry run -- order NOT placed. Re-run with --yes to buy."
                return summary

            # Confirm completion by requiring the page to LEAVE /checkout (Target
            # redirects to an order-confirmation page). Requiring the navigation
            # prevents a stray /checkout string from reading as a placed order.
            confirm_js = r"""() => {
              const url = location.href;
              const body = (document.body.innerText || '');
              const m = body.match(/order\s*#?\s*([0-9]{6,})/i);
              const leftCheckout = !/\/checkout(\/|\?|#|$)/.test(url);
              const done = (leftCheckout && (m || /order|thank|confirmation|receipt/i.test(url)))
                           || /thanks for your order|we.?ve got your order|your order is placed/i.test(body);
              return {done, order: m ? m[1] : null, url};
            }"""

            # Target's checkout keeps its OWN selected card independent of the wallet
            # default, so switch it explicitly to the resolved pointer before placing.
            if last4:
                self._select_payment_card(page, last4, cvv=stored_cvv)
                try:
                    page.wait_for_selector('button[data-test="placeOrderButton"]', timeout=15000)
                except Exception:
                    raise ClientError("Switched the payment card but the Place Order button did not return.")

            page.locator('button[data-test="placeOrderButton"]').first.click()

            # Single robust poll: a debit card pops a "Confirm CVV" modal (which can
            # appear late), then Target redirects off /checkout. Handle the CVV modal
            # whenever it shows, and re-click Place Order if it never armed.
            confirmed = None
            handled_cvv = False
            handled_pickup = False
            nudged = False
            for i in range(70):  # ~56s
                page.wait_for_timeout(800)
                state = page.evaluate(confirm_js) or {}
                if state.get("done"):
                    confirmed = state
                    break
                # Missing pickup contact ("Enter your pickup info") — fill it once, re-place.
                if not handled_pickup and self._pickup_info_required(page):
                    self._fill_pickup_contact(page, pickup_name, pickup_email)
                    handled_pickup = True
                    btn = page.locator('button[data-test="placeOrderButton"]')
                    if btn.count() > 0:
                        btn.first.click()
                    continue
                if not handled_cvv and page.locator("#enter-cvv").count() > 0:
                    # Use the pointer's stored CVV, else prompt reactively.
                    self._type_field(page, "#enter-cvv", self._cvv_for_checkout(stored_cvv))
                    page.locator('[data-test="confirm-button"]').first.click()
                    handled_cvv = True
                    continue
                # Nudge: if nothing has happened by ~12s, re-click Place Order once.
                if i == 15 and not handled_cvv and not handled_pickup and not nudged:
                    nudged = True
                    btn = page.locator('button[data-test="placeOrderButton"]')
                    if btn.count() > 0:
                        btn.first.click()
            if confirmed is None:
                raise ClientError(
                    "Clicked Place Order but could not confirm completion. "
                    "Check your Target orders before retrying so you don't order twice."
                )
            summary["placed"] = True
            summary["order_number"] = confirmed.get("order")
            summary["confirmation_url"] = confirmed.get("url")
            return summary

    def _pickup_info_required(self, page) -> bool:
        """True when checkout is blocking on a missing pickup contact."""
        return bool(page.evaluate(r"""() => {
          const b = document.querySelector('[data-test="form-error-bucket"]');
          const t = b ? (b.innerText || '') : '';
          return /pickup info|enter your pickup/i.test(t);
        }"""))

    def _fill_pickup_contact(self, page, name: Optional[str], email: Optional[str]) -> None:
        """Fill the 'Pickup person' contact form (name prefilled by Target; email required).

        Target blocks a pickup order on a fresh account with "Enter your pickup
        info" until a pickup contact (name + email) is saved. The account holder's
        name is usually prefilled; ``email`` is required.
        """
        if not email:
            raise ClientError(
                "This account has no saved pickup contact. Re-run with "
                '--pickup-email "<email>" (optionally --pickup-name "First Last").'
            )
        # The 'Pickup person' Add/Edit control has no data-test; find it by the
        # surrounding "Pickup person" text and tag it for a reliable click.
        tagged = page.evaluate(r"""() => {
          const btns = [...document.querySelectorAll('button, a')];
          const cand = btns.find(b => {
            const t = (b.innerText || '').trim().toLowerCase();
            if (!/^(add|edit)$/.test(t)) return false;
            let n = b, hops = 0, hay = '';
            while (n && hops < 5) { hay += ' ' + (n.innerText || ''); n = n.parentElement; hops++; }
            return /pickup person|picking up|pickup info|pickup contact/i.test(hay);
          });
          if (!cand) return false;
          cand.setAttribute('data-diag-pickup', '1');
          return true;
        }""")
        if not tagged:
            raise ClientError("Could not find the 'Pickup person' editor to add contact info.")
        page.locator('[data-diag-pickup="1"]').first.click()
        try:
            page.wait_for_selector('#email-address', timeout=12000)
        except Exception:
            raise ClientError("Pickup contact form did not open.")
        page.wait_for_timeout(800)

        def field_empty(sel: str) -> bool:
            return not (page.evaluate(f"() => {{ const e = document.querySelector('{sel}'); return e ? (e.value || '') : ''; }}") or "").strip()

        if name:
            first, _, last = name.strip().partition(" ")
            if field_empty("#first-name"):
                self._type_field(page, "#first-name", first)
            if last and field_empty("#last-name"):
                self._type_field(page, "#last-name", last)
        if field_empty("#first-name"):
            raise ClientError("Pickup person first name is empty; pass --pickup-name \"First Last\".")
        self._type_field(page, "#email-address", email)

        clicked = page.evaluate(r"""() => {
          const btns = [...document.querySelectorAll('button')].filter(
            b => b.offsetParent !== null && (b.innerText || '').trim().toLowerCase() === 'save');
          if (!btns.length) return false;
          btns[0].click();
          return true;
        }""")
        if not clicked:
            raise ClientError("Could not find the pickup contact 'Save' button.")
        page.wait_for_timeout(2500)

    def _selected_card_last4(self, page) -> Optional[str]:
        """Return the last4 of the card currently selected on the checkout page."""
        txt = page.evaluate(r"""() => {
          const el = document.querySelector('[data-test^="IconPayment"]');
          return el ? (el.innerText || '') : '';
        }""") or ""
        match = re.search(r"\*\s?(\d{4})", txt)
        return match.group(1) if match else None

    def _check_radio(self, page, radio_sel: str) -> None:
        """Select a React radio, falling back to a label click + change event."""
        sel = json.dumps(radio_sel)
        page.locator(radio_sel).first.click()
        page.wait_for_timeout(300)
        checked = page.evaluate(f"() => {{ const r = document.querySelector({sel}); return r ? r.checked : false; }}")
        if not checked:
            page.evaluate(f"""() => {{
              const r = document.querySelector({sel});
              if (r) {{
                const label = r.closest('label') || r.parentElement;
                if (label) label.click();
                r.checked = true;
                r.dispatchEvent(new Event('change', {{bubbles: true}}));
              }}
            }}""")
            page.wait_for_timeout(300)

    def _visible_cvv_selector(self, page) -> Optional[str]:
        """Return a selector for a visible CVV input in the payment editor, or None."""
        return page.evaluate(r"""() => {
          const inputs = [...document.querySelectorAll('input')];
          const hit = inputs.find(i => {
            if (i.offsetParent === null) return false;  // must be visible
            const hay = ((i.id||'') + ' ' + (i.name||'') + ' ' + (i.getAttribute('data-test')||'')
              + ' ' + (i.placeholder||'') + ' ' + (i.getAttribute('aria-label')||'')).toLowerCase();
            return /cvv|cvc|security code|card code/.test(hay);
          });
          if (!hit) return null;
          if (hit.id) return '#' + hit.id;
          const dt = hit.getAttribute('data-test');
          return dt ? `[data-test="${dt}"]` : null;
        }""")

    def _select_payment_card(self, page, last4: str, cvv: Optional[str] = None) -> None:
        """Ensure the checkout's selected payment card ends in ``last4`` (headed).

        Opens the payment editor, selects that card's radio, supplies an inline
        CVV if the editor asks for one, and saves. No-op when the card is already
        selected. Fails loud if the card is not a saved checkout option.
        """
        # Wait for the payment section to finish rendering its selected-card label
        # ("<Brand> *NNNN"); reading too early returns None (just the brand icon)
        # and forces a needless, racy switch before edit-payment-button exists.
        current = None
        for _ in range(20):  # ~10s
            current = self._selected_card_last4(page)
            if current:
                break
            page.wait_for_timeout(500)
        if current == last4:
            return
        try:
            page.wait_for_selector('a[data-test="edit-payment-button"]', timeout=8000)
        except Exception:
            raise ClientError(f"Could not open the checkout payment editor to switch to the card ending {last4}.")
        page.locator('a[data-test="edit-payment-button"]').first.click()

        radio_sel = f'input[data-test="payment-card-radio-*{last4}"]'
        try:
            page.wait_for_selector(radio_sel, timeout=12000)
        except Exception:
            raise ClientError(f"Card ending {last4} is not a saved payment option at checkout.")
        self._check_radio(page, radio_sel)
        # Some debit/gift cards require their CVV inline in the editor when the
        # card is selected. Fill it with a provided CVV, else prompt reactively.
        cvv_sel = self._visible_cvv_selector(page)
        if cvv_sel:
            self._type_field(page, cvv_sel, cvv or self._prompt_cvv_reactive())

        save = page.locator('button[data-test="save_and_continue_button_step_PAYMENT"]')
        if save.count() == 0:
            raise ClientError("Could not find 'Save and continue' after selecting the payment card.")
        save.first.click()

        for _ in range(25):  # ~15s for the editor to collapse and reflect the choice
            page.wait_for_timeout(600)
            if (self._selected_card_last4(page) == last4
                    and page.locator('button[data-test="placeOrderButton"]').count() > 0):
                return
        raise ClientError(f"Selected the card ending {last4} but checkout did not confirm the switch.")

    def _resolve_checkout_card(self, card: Optional[str]) -> tuple:
        """Map a --card pointer (or the default pointer) to ``(last4, cvv)``.

        ``last4`` is ``None`` to leave Target's currently-selected card untouched
        (no --card and no default pointer). ``cvv`` is the pointer's stored CVV or
        ``None`` (then checkout prompts reactively if Target demands one). Fails
        loud if a named pointer does not exist.
        """
        if card:
            pointer = card_store.get_pointer(self.config, card)
            if pointer is None:
                raise ClientError(
                    f"No saved card pointer named '{card}'. "
                    "List them with 'target payment-method list' or add one with "
                    "'target payment-method add'."
                )
        else:
            pointer = card_store.get_default(self.config)
        if pointer is None:
            return None, None
        return pointer["last4"], pointer.get("cvv")

    def _cvv_for_checkout(self, stored_cvv: Optional[str]) -> str:
        """Use the pointer's stored CVV, else prompt reactively."""
        return stored_cvv or self._prompt_cvv_reactive()

    def _prompt_cvv_reactive(self) -> str:
        """Securely prompt for a CVV at the moment Target demands one (never stored)."""
        from cli_tools_shared.output import _stdin_is_interactive_tty

        if not _stdin_is_interactive_tty():
            raise ClientError(
                "This card needs a CVV at checkout, but there's no interactive terminal "
                "to prompt for it. Run the checkout in an interactive terminal."
            )
        entered = typer.prompt("Enter the card's security code (CVV)", hide_input=True)
        digits = re.sub(r"\D", "", entered or "")
        if not (3 <= len(digits) <= 4):
            raise ClientError("CVV must be 3 or 4 digits.")
        return digits

    def _read_order_summary(self, page) -> dict:
        def text(selector: str) -> Optional[str]:
            el = page.locator(selector)
            return el.first.inner_text().strip() if el.count() > 0 else None

        return {
            "order_total": self._price(text('[data-test="order-summary-total"], [data-test="cart-summary-total"]')),
            "subtotal": self._price(text('[data-test="cart-summary-subTotal"], [data-test="order-summary-subtotal"]')),
        }

    # ---------- orders (purchase history / cancel) ----------

    # Cancellation reasons Target offers on the reason step (canonical labels).
    CANCEL_REASONS = [
        "Chose wrong store",
        "Used wrong payment method",
        "Ordered it somewhere else",
        "Needed it sooner",
        "Ordered wrong item",
        "Purchased it at another Target store",
        "Wanted the item shipped",
        "No longer want the item",
        "Couldn’t pick up in time",
        "Store requested I cancel it",
        "Other - Please describe",
    ]

    @staticmethod
    def _norm_reason(text: str) -> str:
        return re.sub(r"[^a-z0-9]", "", (text or "").lower())

    @classmethod
    def resolve_reason(cls, text: str) -> Optional[str]:
        """Map user input to a canonical cancel reason: exact, else unique prefix,
        else unique substring (so 'other' beats the 'other' inside 'another')."""
        want = cls._norm_reason(text)
        if not want:
            return None
        norms = [(r, cls._norm_reason(r)) for r in cls.CANCEL_REASONS]
        exact = [r for r, n in norms if n == want]
        if exact:
            return exact[0]
        starts = [r for r, n in norms if n.startswith(want)]
        if len(starts) == 1:
            return starts[0]
        contains = [r for r, n in norms if want in n]
        return contains[0] if len(contains) == 1 else None

    def list_orders(self, limit: int = 10) -> List[dict]:
        """List recent orders from purchase history (read -- headless)."""
        page = self._get_browser().get_page("https://www.target.com/orders")
        try:
            page.wait_for_selector('[data-test="order-details-link"], a[href*="/orders/"]', timeout=15000)
        except Exception:
            raise ClientError(
                "Could not load your order history. Make sure you're signed in "
                "(`target auth login --force`)."
            )
        page.wait_for_timeout(2500)  # let order links + summaries hydrate
        rows = page.evaluate(r"""() => {
          const out = [], seen = new Set();
          document.querySelectorAll('a[href*="/orders/"]').forEach(a => {
            const m = (a.getAttribute('href') || '').match(/\/orders\/(\d+)/);
            if (!m || seen.has(m[1])) return;
            seen.add(m[1]);
            let box = a;
            for (let i = 0; i < 6 && box.parentElement; i++) {
              box = box.parentElement;
              if ((box.innerText || '').length > 60) break;
            }
            const txt = (box.innerText || '').replace(/\s+/g, ' ').trim();
            out.push({
              order_number: m[1],
              status: (txt.match(/(processing|ready for pickup|picked up|preparing|shipped|delivered|cancell?ed|refunded)[^.]{0,28}/i) || [])[0] || null,
              total: (txt.match(/\$\d[\d,]*\.\d{2}/) || [])[0] || null,
            });
          });
          return out;
        }""") or []
        return rows[:limit]

    def _order_status(self, page) -> Optional[str]:
        body = page.evaluate("() => document.body.innerText || ''") or ""
        m = re.search(
            r"(processing|ready for pickup|picked up|preparing|shipped|delivered|cancell?ed|refunded)",
            body, re.I,
        )
        return m.group(1) if m else None

    def cancel_order(self, order_number: str, reason: str) -> dict:
        """Cancel all items of an order via the purchase-history cancel flyout (headed).

        ``reason`` is one of ``CANCEL_REASONS`` (already resolved to a canonical
        label by the caller); it is selected on Target's reason step.
        """
        with self._headed_browser() as browser:
            page = browser.get_page(f"https://www.target.com/orders/{order_number}")
            try:
                page.wait_for_selector('[data-test="order-details-page-cdui-with-items"]', timeout=25000)
            except Exception:
                raise ClientError(f"Could not open order {order_number}. Check the order number with 'orders list'.")

            # The "Cancel items"/"Cancel order" affordance only exists while the
            # order is still cancellable (processing, not yet picked up/shipped),
            # and renders after the detail page hydrates -- poll for it.
            opened = False
            for _ in range(20):  # ~10s
                page.wait_for_timeout(500)
                opened = page.evaluate(r"""() => {
                  const b = [...document.querySelectorAll('button, a')].find(
                    e => e.offsetParent !== null && /^cancel (items|item|order)$/i.test((e.innerText || '').trim()));
                  if (!b) return false;
                  b.setAttribute('data-diag-cancel', '1');
                  return true;
                }""")
                if opened:
                    break
            if not opened:
                status = self._order_status(page)
                raise ClientError(
                    f"Order {order_number} can't be cancelled"
                    f"{f' (status: {status})' if status else ''}."
                )
            page.locator('[data-diag-cancel="1"]').first.click()

            try:
                page.wait_for_selector('input[type="checkbox"][data-test^="checkbox-"]', timeout=12000)
            except Exception:
                raise ClientError("The cancellation flyout did not open.")
            page.wait_for_timeout(1000)

            # Select every item, then the submit reads "Cancel N item(s)".
            count = page.evaluate(r"""() => {
              const boxes = [...document.querySelectorAll('input[type="checkbox"][data-test^="checkbox-"]')];
              boxes.forEach(b => { if (!b.checked) b.click(); });
              return boxes.length;
            }""")
            if not count:
                raise ClientError("No cancellable items found in the order.")
            page.wait_for_timeout(1000)

            submitted = page.evaluate(r"""() => {
              const b = [...document.querySelectorAll('button')].find(
                e => e.offsetParent !== null && /^cancel \d+ items?$/i.test((e.innerText || '').trim()));
              if (!b) return false;
              b.setAttribute('data-diag-submit', '1');
              return true;
            }""")
            if not submitted:
                raise ClientError("Could not find the 'Cancel N items' button in the flyout.")
            page.locator('[data-diag-submit="1"]').first.click()

            # Reason step: pick the cancellation reason, then Submit.
            try:
                page.wait_for_selector('[data-test^="reason-selection"], input[type="radio"]', timeout=12000)
            except Exception:
                raise ClientError("The cancellation reason step did not appear.")
            page.wait_for_timeout(1000)
            picked = page.evaluate(r"""(want) => {
              const norm = s => (s || '').toLowerCase().replace(/[^a-z0-9]/g, '');
              const w = norm(want);
              const radios = [...document.querySelectorAll('input[type="radio"], [role="radio"]')];
              const hit = radios.find(r => norm((r.closest('label') || r.parentElement || {}).innerText).includes(w));
              if (!hit) return false;
              (hit.closest('label') || hit).click();
              return true;
            }""", reason)
            if not picked:
                raise ClientError(f"Could not select the cancellation reason '{reason}' in Target's list.")
            page.wait_for_timeout(600)
            # "Other - Please describe" requires a free-text description.
            if reason.lower().startswith("other"):
                ta = page.locator('textarea')
                if ta.count() > 0:
                    ta.first.click()
                    page.type_text("No longer needed")
                    page.wait_for_timeout(300)

            reason_submit = page.evaluate(r"""() => {
              const b = [...document.querySelectorAll('button')].find(
                e => e.offsetParent !== null && !e.disabled && /^submit$/i.test((e.innerText || '').trim()));
              if (!b) return false;
              b.setAttribute('data-diag-reason-submit', '1');
              return true;
            }""")
            if not reason_submit:
                raise ClientError("Could not find the 'Submit' button on the cancellation reason step.")
            page.locator('[data-diag-reason-submit="1"]').first.click()

            for _ in range(30):  # ~24s
                page.wait_for_timeout(800)
                done = page.evaluate(r"""() => /cancell?ed|cancellation (confirmed|complete|received|request|submitted)|has been cancell?ed|items? cancell?ed|refund/i.test(document.body.innerText || '')""")
                if done:
                    return {"order_number": order_number, "cancelled": True,
                            "items_cancelled": count, "reason": reason}
            raise ClientError(
                f"Submitted the cancellation for order {order_number} but could not confirm it completed. "
                "Check 'orders list' before retrying."
            )


_client: Optional[TargetClient] = None


def get_client() -> TargetClient:
    """Get or create the global Target client instance."""
    global _client
    if _client is None:
        _client = TargetClient()
    return _client
