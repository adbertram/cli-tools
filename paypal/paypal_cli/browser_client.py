"""Browser-backed PayPal transaction and refund client."""

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote

from cli_tools_shared.exceptions import ClientError

from .config import get_config


BASE_URL = "https://www.paypal.com"
TRANSACTIONS_PATH = "/unifiedtransactions/v1/transactions"
REFUND_BASE_PATH = "/unifiedtransactions/v1/refund/"
SERVER_DATA_PATH = "/unifiedtransactions/server-data"
MATCHABLE_PAYMENT_STATUSES = {"COMPLETED", "PARTIALLY_REFUNDED"}


@dataclass(frozen=True)
class OrderMatchContext:
    order_id: str
    buyer_email: str
    buyer_name: str
    shipping_name: str
    paid_at: datetime
    amount: str
    currency: str


def _decimal(value: str, *, field_name: str) -> Decimal:
    try:
        return Decimal(str(value).replace(",", "").strip()).quantize(Decimal("0.01"))
    except (InvalidOperation, AttributeError) as exc:
        raise ClientError(f"{field_name} must be a decimal amount") from exc


def _parse_money(value: str) -> Optional[Decimal]:
    if not value:
        return None
    cleaned = "".join(ch for ch in value if ch.isdigit() or ch in ".-")
    if not cleaned:
        return None
    try:
        return Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _parse_datetime(value: str, *, field_name: str) -> datetime:
    if not value:
        raise ClientError(f"BrickLink order is missing {field_name}")
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ClientError(f"BrickLink order has invalid {field_name}: {value}") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _date_payload(value: datetime) -> Dict[str, int]:
    return {
        "year": value.year,
        "month": value.month - 1,
        "day": value.day,
        "hour": value.hour,
        "minute": value.minute,
        "second": value.second,
    }


def _unique_nonempty(values: Iterable[Optional[str]]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        text = (value or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _status_key(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", str(value or "").upper()).strip("_")


def order_match_context(order_id: str, bricklink_order: Dict[str, Any]) -> OrderMatchContext:
    payment = bricklink_order.get("payment") or {}
    method = str(payment.get("method") or "")
    if "paypal" not in method.lower():
        raise ClientError(f"BrickLink order {order_id} is not a PayPal payment; payment.method={method!r}")

    cost = bricklink_order.get("cost") or {}
    amount = str(cost.get("grand_total") or "").strip()
    currency = str(cost.get("currency_code") or payment.get("currency_code") or "").strip()
    if not amount:
        raise ClientError(f"BrickLink order {order_id} is missing cost.grand_total")
    if not currency:
        raise ClientError(f"BrickLink order {order_id} is missing currency_code")

    shipping = bricklink_order.get("shipping") or {}
    address = shipping.get("address") or {}
    name = address.get("name") or {}
    shipping_name = str(name.get("full") or "").strip()
    buyer_email = str(bricklink_order.get("buyer_email") or "").strip()
    buyer_name = str(bricklink_order.get("buyer_name") or "").strip()
    if not buyer_email:
        raise ClientError(f"BrickLink order {order_id} is missing buyer_email")
    if not shipping_name:
        raise ClientError(f"BrickLink order {order_id} is missing shipping.address.name.full")

    paid_at = _parse_datetime(
        str(payment.get("date_paid") or bricklink_order.get("date_ordered") or ""),
        field_name="payment.date_paid",
    )
    return OrderMatchContext(
        order_id=order_id,
        buyer_email=buyer_email,
        buyer_name=buyer_name,
        shipping_name=shipping_name,
        paid_at=paid_at,
        amount=f"{_decimal(amount, field_name='cost.grand_total')}",
        currency=currency,
    )


class PayPalBrowserClient:
    """Call PayPal unified-transaction endpoints through an authenticated browser."""

    def __init__(self, profile: Optional[str] = None, config: Optional[Any] = None, browser: Optional[Any] = None):
        self.config = config or get_config(profile=profile)
        self.browser = browser or self.config.get_browser()

    def close(self) -> None:
        self.browser.close()

    def _transactions_url(self, query: str) -> str:
        return f"{BASE_URL}/mep/unifiedtransactions?filter=0&query={quote(query)}"

    def _get_page(self, query: str = ""):
        page = self.browser.get_page(self._transactions_url(query))
        current_url = getattr(page, "url", "")
        if "/signin" in current_url or "/authflow" in current_url:
            raise ClientError("PayPal browser session is not authenticated. Run `paypal auth login -c browser_session`.")
        return page

    def _csrf_token(self, page) -> str:
        payload = self._evaluate(
            page,
            """
async () => {
  const response = await fetch("/unifiedtransactions/server-data", {
    method: "GET",
    credentials: "include",
    headers: {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
  });
  const text = await response.text();
  return {status: response.status, statusText: response.statusText, text};
}
""",
        )
        if int(payload.get("status", 0)) < 200 or int(payload.get("status", 0)) >= 300:
            raise ClientError(f"PayPal CSRF lookup failed with HTTP {payload.get('status')}: {payload.get('text')}")
        try:
            data = json.loads(payload.get("text") or "{}")
        except json.JSONDecodeError as exc:
            raise ClientError("PayPal CSRF lookup returned invalid JSON") from exc
        token = data.get("_csrf") or data.get("csrf")
        if not token:
            raise ClientError("PayPal CSRF lookup did not return a token")
        return str(token)

    def _evaluate(self, page, code: str, arg: Any = None) -> Any:
        try:
            return page.evaluate(code, arg)
        except Exception as exc:
            raise ClientError(f"PayPal browser evaluation failed: {exc}") from exc

    def _request_json(self, page, method: str, path: str, json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        token = self._csrf_token(page)
        payload = {
            "method": method,
            "path": path,
            "jsonBody": json_body,
            "csrf": token,
        }
        result = self._evaluate(
            page,
            """
async (request) => {
  const headers = {
    "Accept": "application/json",
    "X-Requested-With": "XMLHttpRequest",
    "x-csrf-token": request.csrf
  };
  const options = {method: request.method, credentials: "include", headers};
  if (request.jsonBody !== null) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(request.jsonBody);
  }
  const response = await fetch(request.path, options);
  const text = await response.text();
  return {status: response.status, statusText: response.statusText, text};
}
""",
            payload,
        )
        status = int(result.get("status", 0))
        text = result.get("text") or ""
        if status < 200 or status >= 300:
            detail = text[:500] if text else result.get("statusText", "")
            raise ClientError(f"PayPal browser request failed with HTTP {status}: {detail}")
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ClientError(f"PayPal browser response was not valid JSON for {method} {path}") from exc

    def search_transactions(self, search_text: str, start: datetime, end: datetime) -> List[Dict[str, Any]]:
        page = self._get_page(search_text)
        body = {
            "search_text": search_text,
            "search_field": "ANY",
            "start_time": _date_payload(start),
            "end_time": _date_payload(end),
            "userConfigUpdated": {
                "maxTransactionLimit": "ConfigFile",
                "filterDataURL": None,
                "activity_types": None,
                "filterSubTypes": None,
                "debit_credit_code": True,
                "need_primary_only": None,
                "product_flows": None,
                "product_flow": None,
                "funding_instruments": None,
                "shipping_status": None,
                "balance_affecting_status": None,
                "purposes": None,
                "role": None,
                "statuses": None,
                "fraud_management_actions": None,
                "hold_types": None,
            },
        }
        response = self._request_json(page, "POST", TRANSACTIONS_PATH, body)
        transactions = response.get("transactions")
        if not isinstance(transactions, list):
            raise ClientError("PayPal transaction search returned an unexpected JSON shape")
        return transactions

    def get_refund_details(self, transaction_id: str) -> Dict[str, Any]:
        page = self._get_page(transaction_id)
        response = self._request_json(page, "GET", f"{REFUND_BASE_PATH}edit/{transaction_id}")
        data = response.get("data")
        if not isinstance(data, dict):
            raise ClientError("PayPal refund details returned an unexpected JSON shape")
        return data

    def _candidate_matches_transaction(self, transaction: Dict[str, Any], context: OrderMatchContext) -> bool:
        status = transaction.get("status") or {}
        status_value = _status_key(status.get("value") or status.get("content") or "")
        if status_value not in MATCHABLE_PAYMENT_STATUSES:
            return False
        if str(transaction.get("type") or "").upper() != "PAYMENT":
            return False
        if _parse_money(str(transaction.get("gross") or "")) != _decimal(context.amount, field_name="order amount"):
            return False
        actions = transaction.get("actions") or []
        return any(str(action.get("name") or "").upper() == "REFUND" for action in actions if isinstance(action, dict))

    def _candidate_matches_refund_details(
        self,
        details: Dict[str, Any],
        context: OrderMatchContext,
        refund_amount: Optional[str],
    ) -> bool:
        counterparty = details.get("counterPartyData") or {}
        if str(counterparty.get("email") or "").lower() != context.buyer_email.lower():
            return False
        if str(counterparty.get("name") or "").strip().lower() != context.shipping_name.lower():
            return False

        amount = details.get("amount") or {}
        gross = amount.get("grossAmount") or {}
        max_allowed = amount.get("maxAllowedRefundAmount") or {}
        if str(gross.get("currencyCode") or "").upper() != context.currency.upper():
            return False
        if _decimal(str(gross.get("value") or ""), field_name="grossAmount.value") != _decimal(context.amount, field_name="order amount"):
            return False
        allowed = _decimal(str(max_allowed.get("value") or ""), field_name="maxAllowedRefundAmount.value")
        requested = _decimal(refund_amount or context.amount, field_name="refund amount")
        if requested > allowed:
            raise ClientError(
                f"Requested refund {requested} {context.currency} exceeds PayPal remaining refundable amount {allowed} {context.currency}"
            )
        return True

    def find_payment_for_order(
        self,
        bricklink_order: Dict[str, Any],
        order_id: str,
        refund_amount: Optional[str] = None,
    ) -> Dict[str, Any]:
        context = order_match_context(order_id, bricklink_order)
        start = (context.paid_at - timedelta(days=3)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = (context.paid_at + timedelta(days=3)).replace(hour=23, minute=59, second=59, microsecond=0)
        search_terms = _unique_nonempty([context.buyer_email, context.shipping_name, context.buyer_name])

        candidates_by_id: Dict[str, Dict[str, Any]] = {}
        for term in search_terms:
            for transaction in self.search_transactions(term, start, end):
                transaction_id = str(transaction.get("id") or "")
                if transaction_id and self._candidate_matches_transaction(transaction, context):
                    candidates_by_id[transaction_id] = transaction

        matches = []
        for transaction_id, transaction in candidates_by_id.items():
            details = self.get_refund_details(transaction_id)
            if self._candidate_matches_refund_details(details, context, refund_amount):
                matches.append({"transaction": transaction, "refund_details": details})

        if not matches:
            raise ClientError(
                "No PayPal payment matched BrickLink order "
                f"{order_id} using email/name/amount/date criteria."
            )
        if len(matches) > 1:
            ids = ", ".join(match["transaction"].get("id", "") for match in matches)
            raise ClientError(f"Multiple PayPal payments matched BrickLink order {order_id}: {ids}")

        match = matches[0]
        return {
            "order": {
                "order_id": context.order_id,
                "buyer_email": context.buyer_email,
                "buyer_name": context.buyer_name,
                "shipping_name": context.shipping_name,
                "paid_at": context.paid_at.isoformat(),
                "amount": context.amount,
                "currency": context.currency,
            },
            "transaction": match["transaction"],
            "refund_details": match["refund_details"],
            "search": {
                "terms": search_terms,
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
        }

    def refund_payment(
        self,
        *,
        transaction_id: str,
        amount: str,
        currency: str,
        invoice_number: str,
        note_to_buyer: Optional[str],
    ) -> Dict[str, Any]:
        page = self._get_page(transaction_id)
        request = {
            "currencyCode": currency,
            "totalAmt": amount,
            "invoiceNumber": invoice_number,
            "noteToBuyer": note_to_buyer or "",
            "txnId": transaction_id,
        }
        response = self._request_json(page, "POST", f"{REFUND_BASE_PATH}issue-refund/{transaction_id}", request)
        return {"request": request, "refund": response}


def get_browser_client(profile: Optional[str] = None) -> PayPalBrowserClient:
    return PayPalBrowserClient(profile=profile)
