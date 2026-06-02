"""Normalization helpers for Apple purchase history API responses."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from cli_tools_shared.exceptions import ClientError


@dataclass(frozen=True)
class ParsedMoney:
    """Parsed currency display string."""

    display: str
    currency_symbol: str
    value: str
    signed_value: str


@dataclass(frozen=True)
class OptionalParsedMoney:
    """Parsed currency display string or null."""

    display: str | None
    currency_symbol: str | None
    value: str | None
    signed_value: str | None


def validate_request_context(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate stored request replay context."""
    if not isinstance(raw, dict):
        raise ClientError("Apple request capture must be a JSON object.")

    dsid = raw.get("dsid")
    if not isinstance(dsid, str) or not dsid:
        raise ClientError("Apple request capture is missing string dsid.")

    headers = raw.get("headers", {})
    if not isinstance(headers, dict):
        raise ClientError("Apple request capture headers must be an object when present.")
    for key, value in headers.items():
        if not isinstance(key, str) or not key:
            raise ClientError("Apple request capture header names must be non-empty strings.")
        if not isinstance(value, str):
            raise ClientError(f"Apple request capture header '{key}' must be a string.")
    xsrf_token = headers.get("x-apple-xsrf-token")
    if not isinstance(xsrf_token, str) or not xsrf_token:
        raise ClientError("Apple request capture headers must include non-empty x-apple-xsrf-token.")
    rap2_api = headers.get("x-apple-rap2-api")
    if rap2_api != "3.0.0":
        raise ClientError("Apple request capture headers must include x-apple-rap2-api=3.0.0.")

    cookies = raw.get("cookies")
    if not isinstance(cookies, list) or not cookies:
        raise ClientError("Apple request capture cookies must be a non-empty list.")
    validated_cookies = []
    for cookie in cookies:
        if not isinstance(cookie, dict):
            raise ClientError("Apple request capture cookies must contain objects.")
        name = cookie.get("name")
        value = cookie.get("value")
        domain = cookie.get("domain")
        path = cookie.get("path")
        if not isinstance(name, str) or not name:
            raise ClientError("Apple request capture cookie name must be a non-empty string.")
        if not isinstance(value, str):
            raise ClientError(f"Apple request capture cookie '{name}' must have a string value.")
        if not isinstance(domain, str) or not domain:
            raise ClientError(f"Apple request capture cookie '{name}' must have a non-empty domain.")
        if not isinstance(path, str) or not path:
            raise ClientError(f"Apple request capture cookie '{name}' must have a non-empty path.")
        validated_cookies.append(cookie)

    return {"dsid": dsid, "headers": headers, "cookies": validated_cookies}


def normalize_purchase_batch(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize one Apple purchase-search response page into line-item records."""
    _require_string_or_none(raw, "batchId")
    next_batch_id = raw.get("nextBatchId")
    if not isinstance(next_batch_id, str):
        raise ClientError("Apple purchase history response nextBatchId must be a string.")

    query = raw.get("query")
    if not isinstance(query, dict):
        raise ClientError("Apple purchase history response query must be an object.")

    purchases = raw.get("purchases")
    if not isinstance(purchases, list):
        raise ClientError("Apple purchase history response purchases must be a list.")

    records: list[dict[str, Any]] = []
    for purchase in purchases:
        records.extend(_normalize_purchase(purchase))
    return records


def get_purchase_record(records: list[dict[str, Any]], record_id: str) -> dict[str, Any]:
    """Return the purchase record with the given stable id."""
    if not isinstance(record_id, str) or not record_id:
        raise ClientError("Record id must be a non-empty string.")
    for record in records:
        if record["id"] == record_id:
            return record
    raise ClientError(f"Record not found: {record_id}")


def match_purchase_records(
    records: list[dict[str, Any]],
    *,
    amount: str | None,
    date: str | None,
    query: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Find purchase records matching amount, date, or free-text query."""
    if amount is None and date is None and query is None:
        raise ClientError("At least one of amount, date, or query is required.")
    if limit <= 0:
        raise ClientError("Limit must be greater than zero.")

    normalized_amount = _normalize_query_amount(amount) if amount is not None else None
    normalized_query = query.casefold() if query is not None else None
    normalized_date = date.casefold() if date is not None else None

    matches: list[dict[str, Any]] = []
    for record in records:
        score = 0
        matched_terms: list[str] = []
        matched_amount = False

        if normalized_amount is not None:
            if normalized_amount not in (
                record["amount_paid_value"],
                record["signed_amount_paid_value"],
            ):
                continue
            matched_amount = True
            matched_terms.append(normalized_amount)
            score += 5

        if normalized_date is not None:
            date_hits = [
                field
                for field in ("invoice_date", "purchase_date", "pli_date")
                if _contains_casefold(record[field], normalized_date)
            ]
            if not date_hits:
                continue
            matched_terms.extend(date_hits)
            score += len(date_hits) * 2

        if normalized_query is not None:
            haystack = [
                _stringify_optional(record["title"]),
                _stringify_optional(record["name"]),
                _stringify_optional(record["detail"]),
                _stringify_optional(record["media_type"]),
                _stringify_optional(record["line_item_type"]),
                _stringify_optional(record["subscription_info"]),
                _stringify_optional(record["subscription_coverage_description"]),
                _stringify_optional(record["invoice_line_3"]),
            ]
            if not any(normalized_query in value.casefold() for value in haystack if value):
                continue
            matched_terms.append(query)
            score += 3

        match_record = dict(record)
        match_record["score"] = score
        match_record["matched_amount"] = matched_amount
        match_record["matched_terms"] = matched_terms
        matches.append(match_record)

    matches.sort(
        key=lambda item: (
            item["score"],
            _sortable_optional(item["purchase_date"]),
            _sortable_optional(item["pli_date"]),
            item["id"],
        ),
        reverse=True,
    )
    return matches[:limit]


def _normalize_purchase(raw_purchase: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_purchase, dict):
        raise ClientError("Apple purchase entry must be an object.")

    purchase_id = _require_string(raw_purchase, "purchaseId")
    dsid = _require_string(raw_purchase, "dsid")
    weborder = _require_string(raw_purchase, "weborder")
    invoice_date = _optional_string(raw_purchase, "invoiceDate")
    purchase_date = _optional_string(raw_purchase, "purchaseDate")
    invoice_amount = _optional_money(raw_purchase.get("invoiceAmount"), field_name="invoiceAmount", is_credit=False)
    estimated_total_amount = _require_string(raw_purchase, "estimatedTotalAmount")
    is_pending_purchase = _require_bool(raw_purchase, "isPendingPurchase")
    plis = raw_purchase.get("plis")
    if not isinstance(plis, list):
        raise ClientError("Apple purchase entry plis must be a list.")

    estimated_total_amount_money = _parse_money(estimated_total_amount, is_credit=False)

    records: list[dict[str, Any]] = []
    for pli in plis:
        if not isinstance(pli, dict):
            raise ClientError("Apple purchase line item must be an object.")
        records.append(
            _normalize_pli(
                purchase_id=purchase_id,
                dsid=dsid,
                weborder=weborder,
                purchase_date=purchase_date,
                invoice_date=invoice_date,
                is_pending_purchase=is_pending_purchase,
                invoice_amount=invoice_amount,
                estimated_total_amount=estimated_total_amount_money,
                raw_pli=pli,
            )
        )
    return records


def _normalize_pli(
    *,
    purchase_id: str,
    dsid: str,
    weborder: str,
    purchase_date: str | None,
    invoice_date: str | None,
    is_pending_purchase: bool,
    invoice_amount: OptionalParsedMoney,
    estimated_total_amount: ParsedMoney,
    raw_pli: dict[str, Any],
) -> dict[str, Any]:
    item_id = _require_string(raw_pli, "itemId")
    pli_purchase_id = _require_string(raw_pli, "purchaseId")
    if pli_purchase_id != purchase_id:
        raise ClientError(
            f"Apple purchase line item purchaseId '{pli_purchase_id}' did not match parent purchaseId '{purchase_id}'."
        )

    storefront_id = _require_string(raw_pli, "storefrontId")
    adam_id = _require_string(raw_pli, "adamId")
    guid = _require_string(raw_pli, "guid")
    title = _optional_string(raw_pli, "title")
    amount_paid = _optional_money(raw_pli.get("amountPaid"), field_name="amountPaid", is_credit=_require_bool(raw_pli, "isCredit"))
    pli_date = _require_string(raw_pli, "pliDate")
    is_free_purchase = _require_bool(raw_pli, "isFreePurchase")
    is_credit = _require_bool(raw_pli, "isCredit")
    line_item_type = _require_string(raw_pli, "lineItemType")
    estimated_total = _optional_money(raw_pli.get("estimatedTotal"), field_name="estimatedTotal", is_credit=is_credit)

    localized_content = raw_pli.get("localizedContent")
    if not isinstance(localized_content, dict):
        raise ClientError("Apple purchase line item localizedContent must be an object.")

    name = _require_string(localized_content, "nameForDisplay")
    detail = _optional_non_empty_string(localized_content, "detailForDisplay")
    media_type = _optional_non_empty_string(localized_content, "mediaType")

    subscription_info = raw_pli.get("subscriptionInfo")
    if subscription_info is not None and not isinstance(subscription_info, (str, dict, list)):
        raise ClientError("Apple purchase line item subscriptionInfo must be a string, object, array, or null.")

    record = {
        "id": f"{purchase_id}:{item_id}",
        "purchase_id": purchase_id,
        "item_id": item_id,
        "weborder": weborder,
        "dsid": dsid,
        "storefront_id": storefront_id,
        "adam_id": adam_id,
        "guid": guid,
        "title": title,
        "name": name,
        "detail": detail,
        "media_type": media_type,
        "line_item_type": line_item_type,
        "purchase_date": purchase_date,
        "invoice_date": invoice_date,
        "pli_date": pli_date,
        "is_pending_purchase": is_pending_purchase,
        "is_free_purchase": is_free_purchase,
        "is_credit": is_credit,
        "currency_symbol": amount_paid.currency_symbol,
        "amount_paid": amount_paid.display,
        "amount_paid_value": amount_paid.value,
        "signed_amount_paid_value": amount_paid.signed_value,
        "estimated_total": estimated_total.display,
        "estimated_total_value": estimated_total.value,
        "signed_estimated_total_value": estimated_total.signed_value,
        "invoice_amount": invoice_amount.display,
        "invoice_amount_value": invoice_amount.value,
        "estimated_total_amount": estimated_total_amount.display,
        "estimated_total_amount_value": estimated_total_amount.value,
        "subscription_info": subscription_info,
        "subscription_coverage_description": _optional_string(localized_content, "subscriptionCoverageDescription"),
        "localized_pots_end_of_commitment_date": _optional_string(
            localized_content,
            "localizedPotsEndOfCommitmentDate",
        ),
        "invoice_line_3": _optional_string(localized_content, "invoiceLine3"),
        "artwork_url": _optional_string(localized_content, "artworkURL"),
        "support_url": _optional_string(localized_content, "supportURL"),
        "image_type": _optional_string(localized_content, "imageType"),
        "complete": _optional_bool(localized_content, "complete"),
    }
    return record


def _parse_money(value: str, *, is_credit: bool) -> ParsedMoney:
    stripped = value.strip()
    if not stripped:
        raise ClientError("Apple purchase money value must be a non-empty string.")

    index = 0
    while index < len(stripped) and not stripped[index].isdigit() and stripped[index] not in "-.":
        index += 1
    if index == len(stripped):
        raise ClientError(f"Apple purchase money value '{value}' did not contain a numeric amount.")

    currency_symbol = stripped[:index].strip()
    numeric_part = stripped[index:].replace(",", "")
    try:
        amount = Decimal(numeric_part)
    except InvalidOperation as exc:
        raise ClientError(f"Apple purchase money value '{value}' was not a valid decimal amount.") from exc

    signed_amount = -amount if is_credit else amount
    return ParsedMoney(
        display=stripped,
        currency_symbol=currency_symbol,
        value=format(amount, "f"),
        signed_value=format(signed_amount, "f"),
    )


def _optional_money(value: Any, *, field_name: str, is_credit: bool) -> OptionalParsedMoney:
    if value is None:
        return OptionalParsedMoney(display=None, currency_symbol=None, value=None, signed_value=None)
    if value == "":
        return OptionalParsedMoney(display=None, currency_symbol=None, value=None, signed_value=None)
    if not isinstance(value, str):
        raise ClientError(f"Apple field '{field_name}' must be a string or null.")
    parsed = _parse_money(value, is_credit=is_credit)
    return OptionalParsedMoney(
        display=parsed.display,
        currency_symbol=parsed.currency_symbol,
        value=parsed.value,
        signed_value=parsed.signed_value,
    )


def _normalize_query_amount(value: str) -> str:
    cleaned = value.strip()
    try:
        return format(Decimal(cleaned), "f")
    except InvalidOperation as exc:
        raise ClientError(f"Invalid amount: {value}") from exc


def _stringify_optional(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_stringify_optional(item) for item in value)
    if isinstance(value, dict):
        return " ".join(_stringify_optional(item) for item in value.values())
    return str(value)


def _contains_casefold(value: Any, needle: str) -> bool:
    if not isinstance(value, str):
        return False
    return needle in value.casefold()


def _sortable_optional(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value


def _require_string(raw: dict[str, Any], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value:
        raise ClientError(f"Apple field '{field}' must be a non-empty string.")
    return value


def _require_string_or_none(raw: dict[str, Any], field: str) -> Optional[str]:
    value = raw.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ClientError(f"Apple field '{field}' must be a string or null.")
    return value


def _optional_string(raw: dict[str, Any], field: str) -> Optional[str]:
    value = raw.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ClientError(f"Apple field '{field}' must be a string or null.")
    return value


def _optional_non_empty_string(raw: dict[str, Any], field: str) -> Optional[str]:
    value = raw.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ClientError(f"Apple field '{field}' must be a string, empty string, or null.")
    if value == "":
        return None
    return value


def _require_bool(raw: dict[str, Any], field: str) -> bool:
    value = raw.get(field)
    if not isinstance(value, bool):
        raise ClientError(f"Apple field '{field}' must be a boolean.")
    return value


def _optional_bool(raw: dict[str, Any], field: str) -> Optional[bool]:
    value = raw.get(field)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ClientError(f"Apple field '{field}' must be a boolean or null.")
    return value
