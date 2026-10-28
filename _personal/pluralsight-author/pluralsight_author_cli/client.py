from __future__ import annotations

import hashlib
import json
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

from cli_tools_shared.data_cache import cache_dir_for, cached, invalidate
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
ICON_LIBRARY_URL = "https://authors.pluralsight.com/icon-library/"
ICON_ZIP_CACHE_NAME = "icon-library.zip"
OBSOLETE_ICON_METADATA_CACHE_NAME = "icon-metadata.json"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
ICON_COLOR_NAMES = {
    "Blue": "Blue",
    "Green": "Green",
    "InkyBlue": "Inky Blue",
    "Orange": "Orange",
    "Pink": "Pink",
    "Purple": "Purple",
    "White": "White",
    "Yellow": "Yellow",
}
ICON_COLOR_ALIASES = {
    re.sub(r"[^a-z0-9]+", "", value.casefold()): display
    for folder, display in ICON_COLOR_NAMES.items()
    for value in {folder, display}
}


def canonical_icon_color(color: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "", color.casefold())
    if key in ICON_COLOR_ALIASES:
        return ICON_COLOR_ALIASES[key]
    available = ", ".join(sorted(ICON_COLOR_NAMES.values()))
    raise ClientError(f"Unknown icon color: {color}. Available colors: {available}.")


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

    def _parse_icon_member(self, member: str) -> tuple[str, str, str] | None:
        parts = member.split("/")
        if len(parts) != 2 or parts[0] not in ICON_COLOR_NAMES:
            return None
        color_folder, filename = parts
        suffix = f"_{color_folder}.png"
        if not filename.endswith(suffix) or filename == suffix:
            return None
        return color_folder, filename, filename.removesuffix(suffix)

    def _icon_archive_path(self) -> Path:
        return self.config.get_profile_data_dir() / ICON_ZIP_CACHE_NAME

    def _zip_cache_path(self) -> Path:
        path = self._icon_archive_path()
        if not path.is_file():
            raise ClientError(
                f"The Author Kit PNG icon archive is missing: {path}. "
                "Run `pluralsight-author icons import <archive.zip>` to rebuild it."
            )
        if not zipfile.is_zipfile(path):
            raise ClientError(f"Icon archive is not a ZIP file: {path}")
        return path

    def _validate_icon_archive(self, path: Path) -> tuple[int, int]:
        if not zipfile.is_zipfile(path):
            raise ClientError(f"Icon archive is not a ZIP file: {path}")
        assets_by_color = {folder: set() for folder in ICON_COLOR_NAMES}
        seen_members = set()
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                member = info.filename
                if member in seen_members:
                    raise ClientError(f"Icon archive has a duplicate member: {member}")
                seen_members.add(member)
                if info.is_dir():
                    if member not in {f"{folder}/" for folder in ICON_COLOR_NAMES}:
                        raise ClientError(f"Icon archive has an invalid directory: {member}")
                    continue
                parsed = self._parse_icon_member(member)
                if parsed is None:
                    raise ClientError(
                        f"Icon archive has an invalid member path or PNG filename: {member}"
                    )
                color_folder, _filename, base_id = parsed
                with archive.open(info) as icon_file:
                    if icon_file.read(len(PNG_SIGNATURE)) != PNG_SIGNATURE:
                        raise ClientError(f"Icon archive member is not a PNG file: {member}")
                assets_by_color[color_folder].add(base_id)
            bad_member = archive.testzip()
            if bad_member is not None:
                raise ClientError(f"Icon archive has a CRC error: {bad_member}")
        reference_color = next(iter(ICON_COLOR_NAMES))
        reference_assets = assets_by_color[reference_color]
        if not reference_assets:
            raise ClientError(f"Icon archive has no assets for color: {reference_color}")
        for color_folder, assets in assets_by_color.items():
            if assets != reference_assets:
                raise ClientError(
                    f"Icon archive color set does not match {reference_color}: {color_folder}"
                )
        return len(reference_assets), sum(len(assets) for assets in assets_by_color.values())

    def import_icon_archive(self, source: Path) -> dict:
        source = Path(source).expanduser()
        if not source.is_file():
            raise ClientError(f"Icon archive file not found: {source}")
        storage_dir = self.config.get_profile_data_dir()
        storage_dir.mkdir(parents=True, exist_ok=True)
        cache_dir = cache_dir_for(self)
        target = self._icon_archive_path()
        digest = hashlib.sha256()
        with tempfile.NamedTemporaryFile(
            dir=storage_dir,
            prefix=f"{ICON_ZIP_CACHE_NAME}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            with source.open("rb") as source_file:
                while chunk := source_file.read(1024 * 1024):
                    digest.update(chunk)
                    temp_file.write(chunk)
        try:
            icon_count, asset_count = self._validate_icon_archive(temp_path)
            temp_path.replace(target)
        finally:
            if temp_path.exists():
                temp_path.unlink()
        legacy_cache_archive = cache_dir / ICON_ZIP_CACHE_NAME
        if legacy_cache_archive.is_file():
            legacy_cache_archive.unlink()
        obsolete_metadata = cache_dir / OBSOLETE_ICON_METADATA_CACHE_NAME
        if obsolete_metadata.is_file():
            obsolete_metadata.unlink()
        invalidate(self, "list_icons")
        invalidate(self, "search_icons")
        invalidate(self, "get_icon")
        return {
            "cache_path": str(target),
            "bytes": target.stat().st_size,
            "sha256": digest.hexdigest(),
            "icon_count": icon_count,
            "asset_count": asset_count,
            "colors": list(ICON_COLOR_NAMES.values()),
            "file_type": "png",
        }

    def _icon_row_from_zip_member(self, member: str) -> dict | None:
        parsed = self._parse_icon_member(member)
        if parsed is None:
            return None
        color_folder, filename, base_id = parsed
        tags = [value for value in re.split(r"[^a-z0-9]+", base_id.casefold()) if value]
        return {
            "id": filename.removesuffix(".png"),
            "name": re.sub(r"[-_]+", " ", base_id).title(),
            "category": "",
            "color": ICON_COLOR_NAMES[color_folder],
            "tags": tags,
            "download_url": f"zip://{member}",
            "thumbnail_url": "",
            "source_url": ICON_LIBRARY_URL,
            "file_type": "png",
        }

    def _icon_zip_rows(self) -> list[dict]:
        rows = []
        with zipfile.ZipFile(self._zip_cache_path()) as archive:
            for member in archive.namelist():
                row = self._icon_row_from_zip_member(member)
                if row is not None:
                    rows.append(row)
        return sorted(rows, key=lambda item: (item["name"].casefold(), item["color"].casefold()))

    def _icon_base_id(self, item: dict) -> str:
        member = str(item["download_url"]).removeprefix("zip://")
        parsed = self._parse_icon_member(member)
        return parsed[2] if parsed is not None else item["id"]

    def _get_icon_record(self, item_id: str, color: str | None = None) -> dict:
        rows = self.list_icons(limit=0)
        for item in rows:
            if item["id"] == item_id:
                if color is None:
                    return item
                target_color = canonical_icon_color(color)
                for candidate in rows:
                    if (
                        self._icon_base_id(candidate) == self._icon_base_id(item)
                        and candidate["color"] == target_color
                    ):
                        return candidate
                raise ClientError(f"Icon color variant not found: {item_id} ({target_color})")
        if color is not None:
            target_color = canonical_icon_color(color)
            for item in rows:
                if self._icon_base_id(item) == item_id and item["color"] == target_color:
                    return item
            raise ClientError(f"Icon color variant not found: {item_id} ({target_color})")
        for item in rows:
            if self._icon_base_id(item) == item_id:
                return item
        raise ClientError(f"Icon not found: {item_id}")

    def _download_target(self, output: Path, item: dict) -> Path:
        if output.exists() and output.is_dir():
            url = item["download_url"] or item["thumbnail_url"]
            filename = url.removeprefix("zip://").rsplit("/", 1)[-1]
            return output / filename
        return output

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

    def list_icons(self, limit: int = 0) -> list[dict]:
        rows = self._icon_zip_rows()
        return rows[:limit] if limit > 0 else rows

    def search_icons(self, query: str, limit: int = 0) -> list[dict]:
        needle = query.casefold()
        rows = [
            item
            for item in self.list_icons(limit=0)
            if needle
            in " ".join(
                [
                    item["id"],
                    item["name"],
                    item["category"],
                    item["color"],
                    " ".join(item["tags"]),
                ]
            ).casefold()
        ]
        return rows[:limit] if limit > 0 else rows

    def get_icon(self, item_id: str, color: str | None = None) -> dict:
        return self._get_icon_record(item_id, color)

    def download_icon(self, item_id: str, output: Path, color: str | None = None) -> dict:
        item = self._get_icon_record(item_id, color)
        url = item["download_url"]
        if not url.startswith("zip://"):
            raise ClientError(f"Icon cache URL is invalid: {url}")
        member = url.removeprefix("zip://")
        with zipfile.ZipFile(self._zip_cache_path()) as archive:
            content = archive.read(member)
        if not content:
            raise ClientError(f"Downloaded icon is empty: {item_id}")
        target = self._download_target(Path(output), item)
        if target.suffix.casefold() != ".png":
            raise ClientError("Author Kit asset is PNG; output must use a .png extension.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return {
            **item,
            "output": str(target),
            "bytes": len(content),
            "content_type": "image/png",
        }

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
