"""Browser-backed X Developer Console client."""

import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.exceptions import CredentialError

from .config import BROWSER_AUTH_TYPE, get_config

DEVELOPER_CONSOLE_URL = "https://console.x.com/"
STRIPE_CHECKOUT_IFRAME = "embedded-checkout-inner"
ACCOUNT_ID_RE = re.compile(r"/accounts/(\d+)")
CREDITS_READY_COPY = "Manage your free and prepaid credits"
CREDIT_PURCHASE_BUTTON_STATE_JS = """() => {
    const norm = value => (value || "").replace(/\\s+/g, " ").trim();
    const visible = element => {
        const style = window.getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.visibility !== "hidden"
            && style.display !== "none"
            && rect.width > 0
            && rect.height > 0;
    };
    const text = norm(document.body ? document.body.innerText : "");
    const purchaseButtons = Array.from(document.querySelectorAll("button,[role='button']")).filter(element =>
        /Purchase credits/i.test(norm(element.innerText || element.textContent || element.getAttribute("aria-label"))) &&
        visible(element) &&
        !(element.disabled || element.getAttribute("aria-disabled") === "true")
    );
    return {
        url: window.location.href,
        title: document.title,
        rateLimited: /Rate limit exceeded/i.test(text),
        loginPage: /x\\.com\\/login/i.test(window.location.href) || /Log in to X/i.test(text),
        hasCreditsReadyCopy: text.includes("Manage your free and prepaid credits"),
        purchaseButtonCount: purchaseButtons.length,
        bodyPrefix: text.slice(0, 180)
    };
}"""


@dataclass(frozen=True)
class PaymentCard:
    number: str
    expiry: str
    cvc: str
    name: str


@dataclass(frozen=True)
class BillingAddress:
    line1: str
    line2: str
    city: str
    state: str
    postal_code: str
    country: str
    phone: str


class XBrowserClient:
    """Client for X Developer Console browser workflows."""

    def __init__(self, profile=None):
        self.config = get_config(profile=profile, profile_auth_type=BROWSER_AUTH_TYPE)
        self.browser = self.config.get_browser()

    def open_credit_purchase_flow(self) -> dict:
        auth_result = self.browser.is_authenticated()
        if not auth_result:
            raise CredentialError(
                "X browser session is not authenticated. Run "
                "`x auth login --profile <profile> --credential-type browser_session`."
            )

        page = self.browser.get_page(DEVELOPER_CONSOLE_URL)
        page.wait_for_timeout(2000)
        return page.evaluate(
            """() => ({
                url: window.location.href,
                title: document.title,
                hasCreditCopy: /credit|billing/i.test(document.body ? document.body.innerText : "")
            })"""
        )

    def purchase_credits(self, amount_usd: str) -> dict:
        auth_result = self.browser.is_authenticated()
        if not auth_result:
            raise CredentialError(
                "X browser session is not authenticated. Run "
                "`x auth login --profile <profile> --credential-type browser_session`."
            )

        page = self.browser.get_page(DEVELOPER_CONSOLE_URL)
        try:
            account_id = self._resolve_account_id(page)
            credits_url = f"{DEVELOPER_CONSOLE_URL}accounts/{account_id}/billing/credits"
            page.goto(credits_url)
            self._wait_for_purchase_page(page)
            balance_before = self._extract_balance(page)
            self._click_button(page, "Purchase credits")
            self._wait_for_text(page, "Continue to payment", "credit amount modal")
            self._fill_credit_amount(page, amount_usd)
            self._click_button(page, "Continue to payment", contains=True)
            checkout_state = self._wait_for_checkout_state(page, amount_usd)

            if checkout_state == "saved_card":
                self._complete_saved_card_payment(page)
            elif checkout_state == "stripe":
                self._complete_stripe_checkout(page)
            else:
                raise ClientError(f"Unsupported X credit checkout state: {checkout_state}")

            success_text = self._wait_for_purchase_success(page)
            balance_result = self._wait_for_balance_update(page, credits_url, balance_before)
            return {
                "action": "purchase_credits",
                "amount_usd": amount_usd,
                "currency": "USD",
                "account_id": account_id,
                "purchase_submitted": True,
                "payment_success_evidence": success_text,
                "balance_before": balance_before,
                "balance_after": balance_result.get("balance"),
                "credit_balance_verified": balance_result.get("verified"),
                "url": page.url,
                "browser_session_headless": bool(self.config.headless),
            }
        finally:
            self.browser.close()

    def _resolve_account_id(self, page) -> str:
        for _ in range(40):
            state = page.evaluate(
                """() => ({
                    url: window.location.href,
                    text: document.body ? document.body.innerText.slice(0, 1200) : "",
                    links: Array.from(document.querySelectorAll("a")).map(a => a.href)
                })"""
            )
            match = ACCOUNT_ID_RE.search(state.get("url") or "")
            if match:
                return match.group(1)
            for href in state.get("links") or []:
                match = ACCOUNT_ID_RE.search(href or "")
                if match:
                    return match.group(1)
            page.wait_for_timeout(500)
        raise ClientError("Could not resolve X Developer Console account ID from the saved browser session.")

    def _wait_for_purchase_page(self, page) -> None:
        try:
            page.wait_for_network_idle(timeout=20, idle_ms=1000)
        except Exception:
            pass

        deadline = time.monotonic() + 30
        last_state: dict = {}
        while time.monotonic() < deadline:
            state = page.evaluate(CREDIT_PURCHASE_BUTTON_STATE_JS) or {}
            last_state = state
            if state.get("loginPage"):
                raise CredentialError(
                    "X browser session reached the X login page. Re-run "
                    "`x auth login --profile <profile> --credential-type browser_session`."
                )
            if state.get("hasCreditsReadyCopy") and state.get("purchaseButtonCount") == 1:
                return
            page.wait_for_timeout(500)

        if last_state.get("rateLimited"):
            raise ClientError("X Developer Console returned: Rate limit exceeded.")
        raise ClientError(
            "X credits page did not expose exactly one enabled Purchase credits button. "
            f"Last state: {last_state!r}"
        )

    def _wait_for_text(self, page, text: str, description: str) -> None:
        for _ in range(60):
            if text in self._page_text(page):
                return
            page.wait_for_timeout(500)
        raise ClientError(f"Timed out waiting for {description}.")

    def _wait_for_checkout_state(self, page, amount_usd: str) -> str:
        amount_label = self._format_amount_label(amount_usd)
        for _ in range(80):
            state = page.evaluate(
                """() => ({
                    text: document.body ? document.body.innerText : "",
                    buttons: Array.from(document.querySelectorAll("button")).map(b => ({
                        text: (b.innerText || b.textContent || "").trim(),
                        visible: Boolean(b.offsetWidth || b.offsetHeight || b.getClientRects().length),
                        disabled: b.disabled
                    })),
                    iframes: Array.from(document.querySelectorAll("iframe")).map(f => f.src)
                })"""
            )
            text = state.get("text") or ""
            if "Rate limit exceeded" in text:
                raise ClientError("X Developer Console returned: Rate limit exceeded.")
            if any(STRIPE_CHECKOUT_IFRAME in (src or "") for src in state.get("iframes") or []):
                return "stripe"
            for button in state.get("buttons") or []:
                button_text = button.get("text") or ""
                if button.get("visible") and not button.get("disabled") and button_text.startswith("Pay"):
                    return "saved_card"
            if f"You are about to purchase {amount_label} in credits" in text:
                page.wait_for_timeout(500)
                continue
            page.wait_for_timeout(500)
        raise ClientError("Timed out waiting for X credit checkout payment controls.")

    def _complete_saved_card_payment(self, page) -> None:
        clicked = page.evaluate(
            """() => {
                const button = Array.from(document.querySelectorAll("button")).find(b => {
                    const text = (b.innerText || b.textContent || "").trim();
                    return text.startsWith("Pay") && !b.disabled &&
                        Boolean(b.offsetWidth || b.offsetHeight || b.getClientRects().length);
                });
                if (!button) return false;
                button.click();
                return true;
            }"""
        )
        if not clicked:
            raise ClientError("Saved-card payment button was not visible in X checkout.")

    def _complete_stripe_checkout(self, page) -> None:
        card = self._load_lastpass_payment_card()
        billing = self._load_billing_address()
        self._wait_for_stripe_field(page, "cardNumber")
        self._type_in_stripe_field(page, "cardNumber", card.number)
        self._type_in_stripe_field(page, "cardExpiry", card.expiry)
        self._type_in_stripe_field(page, "cardCvc", card.cvc)
        self._type_in_stripe_field(page, "billingName", card.name)
        self._select_stripe_value(page, "billingCountry", billing.country)
        self._type_in_stripe_field(page, "billingAddressLine1", billing.line1)
        if billing.line2:
            self._type_in_stripe_field(page, "billingAddressLine2", billing.line2)
        self._type_in_stripe_field(page, "billingLocality", billing.city)
        self._type_in_stripe_field(page, "billingPostalCode", billing.postal_code)
        self._select_stripe_value(page, "billingAdministrativeArea", billing.state)
        self._set_stripe_checkbox(page, "enableStripePass", False)
        self._click_stripe_pay(page)

    def _wait_for_stripe_field(self, page, name: str) -> None:
        for _ in range(60):
            present = page.evaluate_in_iframe(
                STRIPE_CHECKOUT_IFRAME,
                """(name) => Boolean(document.querySelector(`input[name="${name}"]`))""",
                name,
            )
            if present:
                return
            page.wait_for_timeout(500)
        raise ClientError(f"Stripe checkout did not expose field {name}.")

    def _type_in_stripe_field(self, page, name: str, value: str) -> None:
        focused = page.evaluate_in_iframe(
            STRIPE_CHECKOUT_IFRAME,
            """(name) => {
                const input = document.querySelector(`input[name="${name}"]`);
                if (!input) return false;
                input.scrollIntoView({block: "center"});
                input.focus();
                input.select();
                return document.activeElement === input;
            }""",
            name,
        )
        if not focused:
            raise ClientError(f"Could not focus Stripe checkout field {name}.")
        page.keyboard_press("Control+A")
        page.type_text(value)
        page.wait_for_timeout(250)
        typed = page.evaluate_in_iframe(
            STRIPE_CHECKOUT_IFRAME,
            """(name) => {
                const input = document.querySelector(`input[name="${name}"]`);
                return input ? input.value : "";
            }""",
            name,
        )
        if not typed:
            raise ClientError(f"Stripe checkout field {name} did not accept input.")

    def _select_stripe_value(self, page, name: str, value: str) -> None:
        result = page.evaluate_in_iframe(
            STRIPE_CHECKOUT_IFRAME,
            """(arg) => {
                const selectors = [
                    `select[name="${arg.name}"]`,
                    `select[autocomplete="${arg.name}"]`,
                    `input[name="${arg.name}"]`
                ];
                const field = selectors.map(s => document.querySelector(s)).find(Boolean);
                if (!field) return {present: false};
                field.scrollIntoView({block: "center"});
                if (field.tagName === "SELECT") {
                    field.value = arg.value;
                    field.dispatchEvent(new Event("input", {bubbles: true}));
                    field.dispatchEvent(new Event("change", {bubbles: true}));
                    return {present: true, value: field.value};
                }
                field.focus();
                field.value = arg.value;
                field.dispatchEvent(new Event("input", {bubbles: true}));
                field.dispatchEvent(new Event("change", {bubbles: true}));
                return {present: true, value: field.value};
            }""",
            {"name": name, "value": value},
        )
        if isinstance(result, dict) and result.get("present") and result.get("value"):
            return
        # Some Stripe embedded checkout layouts default country/state from
        # locale/address context and render custom listboxes instead of inputs.
        if name in {"billingCountry", "billingAdministrativeArea"}:
            return
        raise ClientError(f"Stripe checkout field {name} was not available.")

    def _set_stripe_checkbox(self, page, name: str, checked: bool) -> None:
        page.evaluate_in_iframe(
            STRIPE_CHECKOUT_IFRAME,
            """(arg) => {
                const input = document.querySelector(`input[name="${arg.name}"][type="checkbox"]`);
                if (!input || input.checked === arg.checked) return;
                input.click();
            }""",
            {"name": name, "checked": checked},
        )

    def _click_stripe_pay(self, page) -> None:
        clicked = page.evaluate_in_iframe(
            STRIPE_CHECKOUT_IFRAME,
            """() => {
                const button = Array.from(document.querySelectorAll("button")).find(b => {
                    const text = (b.innerText || b.textContent || "").trim();
                    return /^Pay\\b/.test(text) &&
                        Boolean(b.offsetWidth || b.offsetHeight || b.getClientRects().length) &&
                        !b.disabled;
                });
                if (!button) return false;
                button.scrollIntoView({block: "center"});
                button.click();
                return true;
            }""",
        )
        if not clicked:
            raise ClientError("Stripe checkout Pay button was not visible or enabled.")

    def _wait_for_purchase_success(self, page) -> str:
        success_markers = (
            "Payment successful",
            "Your purchase is being processed",
            "Credits will appear once the payment is confirmed",
            "credits on the way",
        )
        for _ in range(120):
            text = self._page_text(page)
            for marker in success_markers:
                if marker.lower() in text.lower():
                    return marker
            frame_text = page.evaluate_in_iframe(
                STRIPE_CHECKOUT_IFRAME,
                '() => document.body ? document.body.innerText.slice(0, 3000) : ""',
            )
            if isinstance(frame_text, str):
                for marker in success_markers:
                    if marker.lower() in frame_text.lower():
                        return marker
                if "declined" in frame_text.lower() or "invalid" in frame_text.lower():
                    raise ClientError(f"Stripe checkout returned an error: {self._compact_text(frame_text)}")
            page.wait_for_timeout(1000)
        raise ClientError("Timed out waiting for X credit purchase success evidence.")

    def _wait_for_balance_update(self, page, credits_url: str, balance_before: Optional[str]) -> dict:
        last_balance = None
        for _ in range(45):
            page.goto(credits_url)
            try:
                page.wait_for_network_idle(timeout=20, idle_ms=1000)
            except Exception:
                pass
            page.wait_for_timeout(1000)
            text = self._page_text(page)
            if "Rate limit exceeded" in text:
                page.wait_for_timeout(1000)
                continue
            balance = self._extract_balance(page)
            if balance:
                last_balance = balance
                if balance_before is None or balance != balance_before:
                    return {"balance": balance, "verified": True}
            page.wait_for_timeout(1000)

        if balance_before and last_balance == balance_before:
            raise ClientError(
                "Payment succeeded, but X credit balance did not update from "
                f"{balance_before} within 90 seconds."
            )
        return {"balance": last_balance, "verified": False}

    def _fill_credit_amount(self, page, amount_usd: str) -> None:
        focused = page.evaluate(
            """() => {
                const input = Array.from(document.querySelectorAll("input")).find(i =>
                    i.placeholder && i.placeholder.includes("5.00") &&
                    Boolean(i.offsetWidth || i.offsetHeight || i.getClientRects().length)
                );
                if (!input) return false;
                input.focus();
                input.select();
                return document.activeElement === input;
            }"""
        )
        if not focused:
            raise ClientError("Could not focus X credit amount field.")
        page.keyboard_press("Control+A")
        page.type_text(amount_usd)
        page.wait_for_timeout(500)
        values = page.evaluate(
            """() => Array.from(document.querySelectorAll("input")).map(i => ({
                value: i.value,
                visible: Boolean(i.offsetWidth || i.offsetHeight || i.getClientRects().length)
            }))"""
        )
        if not any(item.get("visible") and item.get("value") == amount_usd for item in values or []):
            raise ClientError("X credit amount field did not accept the requested amount.")

    def _click_button(self, page, text: str, *, contains: bool = False) -> None:
        clicked = page.evaluate(
            """(arg) => {
                const button = Array.from(document.querySelectorAll("button")).find(b => {
                    const label = (b.innerText || b.textContent || "").trim();
                    const matches = arg.contains ? label.includes(arg.text) : label === arg.text;
                    return matches && !b.disabled &&
                        Boolean(b.offsetWidth || b.offsetHeight || b.getClientRects().length);
                });
                if (!button) return false;
                button.click();
                return true;
            }""",
            {"text": text, "contains": contains},
        )
        if not clicked:
            raise ClientError(f"Could not click visible X checkout button: {text}")

    def _button_visible(self, page, text: str) -> bool:
        return bool(
            page.evaluate(
                """(text) => Array.from(document.querySelectorAll("button")).some(b =>
                    (b.innerText || b.textContent || "").trim() === text &&
                    Boolean(b.offsetWidth || b.offsetHeight || b.getClientRects().length) &&
                    !b.disabled
                )""",
                text,
            )
        )

    def _page_text(self, page) -> str:
        value = page.evaluate('() => document.body ? document.body.innerText : ""')
        return value if isinstance(value, str) else ""

    def _extract_balance(self, page) -> Optional[str]:
        text = self._page_text(page)
        match = re.search(r"Remaining balance:\s*\n?\s*(\$-?\d+(?:\.\d{2})?)", text)
        return match.group(1) if match else None

    def _load_lastpass_payment_card(self) -> PaymentCard:
        item_id = self.config.credit_card_lastpass_item_id
        if not item_id:
            raise ClientError(
                "Stripe checkout requires card details and no default X payment method is configured. "
                "Set X_CREDIT_CARD_LASTPASS_ITEM_ID to a LastPass Credit Card item ID."
            )
        if not shutil.which("lastpass"):
            raise ClientError("The lastpass CLI wrapper is required to read the configured payment card.")
        completed = subprocess.run(
            ["lastpass", "items", "get", item_id, "--show-password"],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise ClientError("Failed to read configured LastPass payment card entry.")
        try:
            data = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ClientError("LastPass payment card entry did not return JSON.") from exc

        number = re.sub(r"\D", "", str(data.get("Number") or ""))
        cvc = str(data.get("Security Code") or "").strip()
        name = str(data.get("Name on Card") or "").strip()
        expiry = self._parse_expiry(str(data.get("Expiration Date") or ""))
        if not number or not cvc or not name or not expiry:
            raise ClientError(
                "Configured LastPass payment card is missing Number, Expiration Date, "
                "Security Code, or Name on Card."
            )
        return PaymentCard(number=number, expiry=expiry, cvc=cvc, name=name)

    def _load_billing_address(self) -> BillingAddress:
        required = {
            "X_BILLING_ADDRESS_LINE1": self.config.billing_address_line1,
            "X_BILLING_CITY": self.config.billing_city,
            "X_BILLING_STATE": self.config.billing_state,
            "X_BILLING_POSTAL_CODE": self.config.billing_postal_code,
            "X_BILLING_PHONE": self.config.billing_phone,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ClientError(f"Stripe checkout requires billing config: {', '.join(missing)}.")
        return BillingAddress(
            line1=str(self.config.billing_address_line1),
            line2=str(self.config.billing_address_line2 or ""),
            city=str(self.config.billing_city),
            state=str(self.config.billing_state),
            postal_code=str(self.config.billing_postal_code),
            country=str(self.config.billing_country),
            phone=str(self.config.billing_phone),
        )

    def _parse_expiry(self, value: str) -> str:
        month_map = {
            "january": "01",
            "february": "02",
            "march": "03",
            "april": "04",
            "may": "05",
            "june": "06",
            "july": "07",
            "august": "08",
            "september": "09",
            "october": "10",
            "november": "11",
            "december": "12",
        }
        parts = [part.strip() for part in re.split(r"[,/ -]+", value) if part.strip()]
        if len(parts) < 2:
            return ""
        raw_month, raw_year = parts[0], parts[-1]
        month = month_map.get(raw_month.lower())
        if month is None and raw_month.isdigit():
            month = f"{int(raw_month):02d}"
        if not month:
            return ""
        year = raw_year[-2:] if raw_year.isdigit() else ""
        if len(year) != 2:
            return ""
        return f"{month}{year}"

    def _format_amount_label(self, amount_usd: str) -> str:
        amount = Decimal(amount_usd)
        if amount == amount.to_integral_value():
            return f"${int(amount)}"
        return f"${amount:.2f}"

    def _compact_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()[:300]
