"""Shared visible-page evidence extraction for browser-backed CLIs."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Sequence

from .exceptions import ClientError


VISIBLE_TEXT_SNAPSHOT_JS = r"""() => {
  const skip = "script,style,noscript,svg,canvas,input,textarea,select,option";
  const visible = element => {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none"
      && style.visibility !== "hidden"
      && rect.width > 0
      && rect.height > 0;
  };
  const texts = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement;
      const value = (node.textContent || "").replace(/\s+/g, " ").trim();
      return value && parent && !parent.closest(skip) && visible(parent)
        ? NodeFilter.FILTER_ACCEPT
        : NodeFilter.FILTER_REJECT;
    }
  });
  while (walker.nextNode()) {
    texts.push(walker.currentNode.textContent.replace(/\s+/g, " ").trim());
  }
  return {
    url: location.href,
    title: document.title,
    texts
  };
}"""

MONEY_RE = re.compile(r"[-+]?\$?\s*\d[\d,]*(?:\.\d{2})?")


def visible_text_snapshot(page) -> dict[str, Any]:
    """Return validated visible text from the current browser page."""
    data = page.evaluate(VISIBLE_TEXT_SNAPSHOT_JS)
    if not isinstance(data, dict):
        raise ClientError("Visible text snapshot must be an object.")
    _require_str(data, "url")
    _require_str(data, "title")
    texts = data.get("texts")
    if not isinstance(texts, list) or not all(isinstance(item, str) for item in texts):
        raise ClientError("Visible text snapshot texts must be a list of strings.")
    return {
        "url": data["url"],
        "title": data["title"],
        "texts": [item.strip() for item in texts if item.strip()],
    }


def text_records(snapshot: Mapping[str, Any], limit: int) -> list[dict[str, Any]]:
    """Convert snapshot text lines into stable line records."""
    if limit < 1:
        raise ClientError("Limit must be greater than zero.")
    texts = snapshot.get("texts")
    if not isinstance(texts, list):
        raise ClientError("Snapshot texts must be a list.")
    return [
        {
            "id": f"line-{index}",
            "line": index,
            "text": text,
            "url": snapshot["url"],
            "title": snapshot["title"],
        }
        for index, text in enumerate(texts[:limit], start=1)
    ]


def get_text_record(snapshot: Mapping[str, Any], record_id: str) -> dict[str, Any]:
    """Return one text record by ``line-N`` id."""
    match = re.fullmatch(r"line-(\d+)", record_id)
    if match is None:
        raise ClientError("Record id must use the line-N format.")
    line = int(match.group(1))
    records = text_records(snapshot, line)
    if line > len(records):
        raise ClientError(f"Record not found: {record_id}")
    return records[line - 1]


def evidence_matches(
    snapshot: Mapping[str, Any],
    *,
    amount: str | None,
    date: str | None,
    query: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Find visible text lines matching supplied transaction evidence."""
    if amount is None and date is None and query is None:
        raise ClientError("At least one of amount, date, or query is required.")
    records = text_records(snapshot, 1000)
    amount_value = _parse_amount(amount) if amount is not None else None
    terms = _terms(date, query)
    matches = []
    for record in records:
        text = record["text"]
        matched_terms = [term for term in terms if term.lower() in text.lower()]
        amount_match = amount_value is not None and _contains_amount(text, amount_value)
        if amount_match or matched_terms:
            score = (3 if amount_match else 0) + len(matched_terms)
            matches.append({
                **record,
                "score": score,
                "matched_amount": amount_match,
                "matched_terms": matched_terms,
            })
    matches.sort(key=lambda item: (-item["score"], item["line"]))
    return matches[:limit]


def _require_str(data: Mapping[str, Any], key: str) -> None:
    if not isinstance(data.get(key), str):
        raise ClientError(f"Visible text snapshot {key} must be a string.")


def _terms(*values: str | None) -> tuple[str, ...]:
    terms = []
    for value in values:
        if value is None:
            continue
        stripped = value.strip()
        if stripped:
            terms.append(stripped)
    return tuple(terms)


def _parse_amount(value: str) -> Decimal:
    try:
        return abs(Decimal(value.replace("$", "").replace(",", "").strip()))
    except (AttributeError, InvalidOperation) as exc:
        raise ClientError(f"Invalid amount: {value}") from exc


def _contains_amount(text: str, target: Decimal) -> bool:
    for raw in MONEY_RE.findall(text):
        try:
            amount = abs(Decimal(raw.replace("$", "").replace(",", "").replace(" ", "")))
        except InvalidOperation:
            continue
        if amount == target:
            return True
    return False
