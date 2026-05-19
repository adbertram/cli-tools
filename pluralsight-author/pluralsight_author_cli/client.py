from __future__ import annotations

import json
import re
from typing import Optional

from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from .config import get_config
from .parsers import (
    extract_current_page,
    extract_learning_objectives_from_snapshot,
    extract_opportunities_from_snapshot,
    extract_total_pages,
)

SNAPSHOT_JS = r"""() => {
  const skip = "script,style,noscript,button,[role='button'],input[type='button'],input[type='submit'],select,option,[role='combobox'],[aria-haspopup='listbox']";
  const visible = el => { const s = getComputedStyle(el); return s.display !== "none" && s.visibility !== "hidden"; };
  const texts = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, { acceptNode(node) {
    const value = (node.textContent || "").replace(/\s+/g, " ").trim();
    const parent = node.parentElement;
    return value && parent && !parent.closest(skip) && visible(parent) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
  }});
  while (walker.nextNode()) texts.push(walker.currentNode.textContent.replace(/\s+/g, " ").trim());
  const buttons = Array.from(document.querySelectorAll("button,[role='button'],input[type='button'],input[type='submit']"))
    .map(el => (el.getAttribute("aria-label") || el.textContent || el.value || "").replace(/\s+/g, " ").trim())
    .filter(Boolean);
  return {texts, buttons};
}"""

OPPORTUNITY_DETAIL_IDS_JS = r"""() => Array.from(
  document.querySelectorAll(".opportunity-item[data-testid]")
).map((element) => element.getAttribute("data-testid"))"""

DETAIL_URL_TEMPLATE = "https://app.pluralsight.com/author-home/opportunity/{opportunity_detail_id}"
APPLICATION_FIELD_LABELS = {
    "start_date": "When could you start?",
    "estimated_completion_weeks": "How many weeks will it take you to finish this opportunity?",
    "experience": "What prior experience do you have using this skill?",
}
APPLICATION_FIELD_SELECTORS = {
    "experience": "[data-testid='apply-description-textarea']",
}
APPLICATION_OPEN_MARKERS = (
    "Application for:",
    "Tell us about your availability and domain expertise.",
    "Send application",
)
APPLICATION_CLOSED_MARKERS = (
    "Application for:",
    "When could you start?",
    "How many weeks will it take you to finish this opportunity?",
    "What prior experience do you have using this skill?",
    "Send application",
)
FILL_FIELD_BY_LABEL_JS = r"""({label, value}) => {
  const setNativeValue = (control, nextValue) => {
    const prototype = control instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
    const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
    if (!descriptor || typeof descriptor.set !== "function") {
      throw new Error("Native value setter not found");
    }
    descriptor.set.call(control, nextValue);
    control.dispatchEvent(new Event("input", { bubbles: true }));
    control.dispatchEvent(new Event("change", { bubbles: true }));
    control.dispatchEvent(new Event("blur", { bubbles: true }));
  };
  const normalize = input => (input || "").replace(/\s+/g, " ").trim();
  const labels = Array.from(document.querySelectorAll("label"));
  const match = labels.find(el => normalize(el.textContent) === label);
  if (!match) {
    throw new Error(`Label not found: ${label}`);
  }
  const targetId = match.getAttribute("for");
  const control = targetId
    ? document.getElementById(targetId)
    : match.querySelector("input, textarea");
  if (!control) {
    throw new Error(`Form control not found for label: ${label}`);
  }
  control.focus();
  setNativeValue(control, value);
  return true;
}"""
FILL_FIELD_BY_SELECTOR_JS = r"""({selector, value}) => {
  const setNativeValue = (control, nextValue) => {
    const prototype = control instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
    const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
    if (!descriptor || typeof descriptor.set !== "function") {
      throw new Error("Native value setter not found");
    }
    descriptor.set.call(control, nextValue);
    control.dispatchEvent(new Event("input", { bubbles: true }));
    control.dispatchEvent(new Event("change", { bubbles: true }));
    control.dispatchEvent(new Event("blur", { bubbles: true }));
  };
  const control = document.querySelector(selector);
  if (!control) {
    throw new Error(`Form control not found for selector: ${selector}`);
  }
  control.focus();
  setNativeValue(control, value);
  return true;
}"""


class PluralsightAuthorClient:
    def __init__(self):
        self.config = get_config()
        self._browser_instance = None

    @property
    def _browser(self):
        if self._browser_instance is None:
            self._browser_instance = self.config.get_browser()
        return self._browser_instance

    def _require_authenticated_session(self) -> None:
        if not self._browser.is_authenticated().authenticated:
            raise ClientError("Saved browser session is not authenticated.")

    def _get_page(self, url: str, settle_ms: int = 2000):
        page = self._browser.get_page(url)
        if settle_ms:
            page.wait_for_timeout(settle_ms)
        return page

    def _snapshot(self, page) -> str:
        data = page.evaluate(SNAPSHOT_JS)
        texts = data["texts"]
        buttons = data["buttons"]
        if not isinstance(texts, list) or not isinstance(buttons, list):
            raise ClientError("Snapshot data must include list-valued texts and buttons.")
        if not all(isinstance(value, str) for value in texts + buttons):
            raise ClientError("Snapshot texts and buttons must contain only strings.")
        texts = [text.strip() for text in texts if text.strip()]
        buttons = [button.strip() for button in buttons if button.strip()]
        controls = {
            label.removeprefix("sort opportunities").strip()
            for label in buttons
            if label.startswith("sort opportunities")
        }
        page_button_re = re.compile(r"^Page \d+(?: is your current page)?$")
        lines = ["- generic:"]
        lines.extend(
            f"  - text: {json.dumps(text)}"
            for text in texts
            if text not in controls
            and text not in {"Next page", "Previous page"}
            and not page_button_re.fullmatch(text)
        )
        lines.extend(
            f"  - button {json.dumps(label)}"
            for label in buttons
        )
        return "\n".join(lines)

    def _opportunity_detail_ids(self, page) -> list[str]:
        detail_ids = page.evaluate(OPPORTUNITY_DETAIL_IDS_JS)
        if not isinstance(detail_ids, list):
            raise ClientError("Opportunity detail ids must be returned as a list.")
        if not all(isinstance(detail_id, str) and detail_id.strip() for detail_id in detail_ids):
            raise ClientError("Opportunity detail ids must contain only non-empty strings.")
        return [detail_id.strip() for detail_id in detail_ids]

    def _with_detail_ids(self, rows: list[dict], detail_ids: list[str], page_number: int) -> list[dict]:
        if len(rows) != len(detail_ids):
            raise ClientError(
                f"Expected {len(rows)} opportunity detail ids on page {page_number}, got {len(detail_ids)}."
            )
        return [
            {**row, "opportunity_detail_id": detail_id}
            for row, detail_id in zip(rows, detail_ids, strict=True)
        ]

    def _public_opportunity(self, item: dict) -> dict:
        return {key: value for key, value in item.items() if key != "opportunity_detail_id"}

    def _detail_url(self, opportunity_detail_id: str) -> str:
        return DETAIL_URL_TEMPLATE.format(opportunity_detail_id=opportunity_detail_id)

    def _go_to_page(self, page, page_number: int) -> str:
        locator = page.get_by_role("button", name=re.compile(rf"^Page {page_number}(?:\b| )"))
        if locator.count() != 1:
            raise ClientError(f"Expected exactly one pagination button for page {page_number}.")
        locator.first.click()
        page.wait_for_timeout(2000)
        snapshot = self._snapshot(page)
        if extract_current_page(snapshot) != page_number:
            raise ClientError(f"Pagination did not reach page {page_number}.")
        return snapshot

    def _list_opportunity_dicts(self, limit: int) -> list[dict]:
        if limit < 1:
            return []
        self._require_authenticated_session()
        page = self._get_page(self.config.base_url)
        snapshot = self._snapshot(page)
        if extract_current_page(snapshot) != 1:
            raise ClientError("Expected to start on page 1.")
        rows = []
        for page_number in range(1, extract_total_pages(snapshot) + 1):
            if page_number > 1:
                snapshot = self._go_to_page(page, page_number)
            page_rows = extract_opportunities_from_snapshot(snapshot, page_number)
            page_rows = self._with_detail_ids(page_rows, self._opportunity_detail_ids(page), page_number)
            for row in page_rows:
                rows.append(row)
                if len(rows) == limit:
                    return rows
        return rows

    def _get_item_record(self, item_id: str) -> dict:
        for item in self._list_opportunity_dicts(limit=1000):
            if item["id"] == item_id:
                return item
        raise ClientError(f"Opportunity not found: {item_id}")

    def _verify_application_opened(self, snapshot: str) -> list[str]:
        missing = [marker for marker in APPLICATION_OPEN_MARKERS if marker not in snapshot]
        if missing:
            raise ClientError(
                "Apply button click did not open the application form. "
                f"Missing markers: {', '.join(missing)}"
            )
        return list(APPLICATION_OPEN_MARKERS)

    def _verify_application_closed(self, snapshot: str) -> str:
        remaining = [marker for marker in APPLICATION_CLOSED_MARKERS if marker in snapshot]
        if remaining:
            raise ClientError(
                "Application form remained visible after clicking Send application. "
                f"Remaining markers: {', '.join(remaining)}"
            )
        return "application_form_closed"

    def _fill_application_field_by_label(self, page, label: str, value: str) -> None:
        try:
            page.evaluate(FILL_FIELD_BY_LABEL_JS, {"label": label, "value": value})
        except Exception as exc:
            raise ClientError(f"Failed to fill application field {label!r}: {exc}") from exc

    def _fill_application_field_by_selector(self, page, selector: str, value: str) -> None:
        try:
            page.evaluate(FILL_FIELD_BY_SELECTOR_JS, {"selector": selector, "value": value})
        except Exception as exc:
            raise ClientError(f"Failed to fill application field selector {selector!r}: {exc}") from exc

    def _get_learning_objectives(self, opportunity_detail_id: str) -> list[str]:
        detail_page = self._get_page(
            self._detail_url(opportunity_detail_id),
            settle_ms=3000,
        )
        return extract_learning_objectives_from_snapshot(self._snapshot(detail_page))

    def close(self):
        if self._browser_instance is not None:
            self._browser_instance.close()
            self._browser_instance = None

    @cached
    def list_opportunities(self, limit: int = 100) -> list[dict]:
        return [self._public_opportunity(item) for item in self._list_opportunity_dicts(limit)]

    @cached
    def search(self, query: str, limit: int = 100) -> list[dict]:
        needle = query.casefold()
        return [
            item
            for item in self.list_opportunities(limit=1000)
            if needle in f"{item['title']} {item['opportunity_type']} {item['category']}".casefold()
        ][:limit]

    @cached
    def get_item(self, item_id: str) -> dict:
        item = self._get_item_record(item_id)
        result = self._public_opportunity(item)
        result["learning_objectives"] = self._get_learning_objectives(item["opportunity_detail_id"])
        return result

    def apply(self, item_id: str, params: dict[str, str]) -> dict:
        item = self._get_item_record(item_id)
        detail_url = self._detail_url(item["opportunity_detail_id"])
        page = self._get_page(detail_url, settle_ms=3000)
        apply_button = page.get_by_role("button", name=re.compile(r"^Apply$"))
        if apply_button.count() != 1:
            raise ClientError(f"Expected exactly one visible Apply button for opportunity: {item_id}")
        apply_button.first.click()
        page.wait_for_timeout(3000)
        snapshot = self._snapshot(page)
        form_markers = self._verify_application_opened(snapshot)
        for key, label in APPLICATION_FIELD_LABELS.items():
            if key in APPLICATION_FIELD_SELECTORS:
                self._fill_application_field_by_selector(page, APPLICATION_FIELD_SELECTORS[key], params[key])
            else:
                self._fill_application_field_by_label(page, label, params[key])
        send_button = page.get_by_role("button", name=re.compile(r"^Send application$"))
        if send_button.count() != 1:
            raise ClientError(f"Expected exactly one visible Send application button for opportunity: {item_id}")
        send_button.first.click()
        page.wait_for_timeout(3000)
        post_submit_snapshot = self._snapshot(page)
        return {
            "id": item["id"],
            "title": item["title"],
            "detail_url": detail_url,
            "submitted_param_keys": sorted(params.keys()),
            "form_markers": form_markers,
            "post_submit_state": self._verify_application_closed(post_submit_snapshot),
        }


def get_client() -> PluralsightAuthorClient:
    return PluralsightAuthorClient()
