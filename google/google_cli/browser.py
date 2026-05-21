"""Browser automation for Chrome Web Store Developer Dashboard listing edits."""
import json
from pathlib import Path
import re

from cli_tools_shared.auth import BrowserAutomation

from .client import ClientError
from .models.webstore import WebStoreListingData, WebStoreListingUpdateResult


STORE_LISTING_FIELD_LABELS = {
    "description": ("Detailed description", "Description"),
    "homepage_url": ("Homepage URL", "Official URL"),
    "support_url": ("Support URL", "Support"),
}

STORE_LISTING_URL_TEMPLATE = "https://chrome.google.com/webstore/devconsole/{publisher_id}/{item_id}/edit"
REVIEW_LOCKED_STATUS_PATTERN = re.compile(
    r"\b(pending review|in review|under review|submitted for review|review in progress)\b",
    re.IGNORECASE,
)


class ChromeWebStoreBrowser(BrowserAutomation):
    """Browser session for Chrome Web Store Developer Dashboard."""

    LOGIN_URL = "https://chrome.google.com/webstore/devconsole/"
    AUTH_CHECK_URL = "https://chrome.google.com/webstore/devconsole/"
    AUTH_URL_PATTERN = r"accounts\.google\.com|ServiceLogin"
    SESSION_NAME = "google-webstore"
    AUTH_CHECK_TTL = 0

def update_webstore_listing(
    browser: ChromeWebStoreBrowser,
    publisher_id: str,
    item_id: str,
    listing: WebStoreListingData,
) -> WebStoreListingUpdateResult:
    """Update the Store Listing tab for an existing Chrome Web Store item."""
    dashboard_url = STORE_LISTING_URL_TEMPLATE.format(
        publisher_id=publisher_id,
        item_id=item_id,
    )
    service = browser.get_page(dashboard_url)
    service.wait_for_load_state("networkidle", timeout=60000)
    service.wait_for_timeout(2000)
    _assert_listing_is_editable(service)

    updated_fields = _update_text_fields(service, listing)
    updated_fields.append(_update_category(service, listing.category))
    uploaded_assets = _upload_assets(service, listing)
    _save_listing(service)

    return WebStoreListingUpdateResult(
        item_id=item_id,
        dashboard_url=dashboard_url,
        updated_fields=updated_fields,
        uploaded_assets=uploaded_assets,
        save_status="saved",
    )


def _assert_listing_is_editable(service) -> None:
    status_text = _extract_dashboard_status_text(
        service.evaluate("() => document.body.innerText")
    )
    if status_text is not None and REVIEW_LOCKED_STATUS_PATTERN.search(status_text):
        raise ClientError(
            f"Chrome Web Store item is in {status_text}. "
            "Store Listing fields are not editable while review is in progress."
        )


def _update_text_fields(service, listing: WebStoreListingData) -> list[str]:
    fields = [
        {
            "name": field_name,
            "labels": labels,
            "value": getattr(listing, field_name),
        }
        for field_name, labels in STORE_LISTING_FIELD_LABELS.items()
    ]
    script = _update_text_fields_script(fields)
    result = service.evaluate(script)
    if not isinstance(result, list):
        raise ClientError("Dashboard text-field update did not return updated field names.")
    expected = [field["name"] for field in fields]
    if result != expected:
        raise ClientError(
            "Dashboard text-field update returned unexpected fields: "
            + ", ".join(str(item) for item in result)
        )
    return result


def _update_category(service, category: str) -> str:
    result = service.evaluate(_update_category_script(category))
    if result != "category":
        raise ClientError(f"Dashboard category update returned unexpected result: {result}")
    return result


def _upload_assets(service, listing: WebStoreListingData):
    page = service._get_page()
    uploaded = []
    screenshot_paths = [asset.path for asset in listing.screenshots]
    _set_file_input(page, "screenshots", screenshot_paths)
    uploaded.extend(listing.screenshots)

    if listing.small_promo_tile is not None:
        _set_file_input(page, "small promo", [listing.small_promo_tile.path])
        uploaded.append(listing.small_promo_tile)

    if listing.marquee_promo_image is not None:
        _set_file_input(page, "marquee", [listing.marquee_promo_image.path])
        uploaded.append(listing.marquee_promo_image)

    return uploaded


def _set_file_input(page, section_name: str, paths: list[str]) -> None:
    for path in paths:
        if not Path(path).is_file():
            raise ClientError(f"Listing asset does not exist: {path}")

    marker = f"cws-upload-{section_name.replace(' ', '-')}"
    for path in paths:
        script = _mark_file_input_script(section_name, marker)
        marked = page.evaluate(script)
        if marked is not True:
            raise ClientError(f"Could not find Chrome Web Store upload control for {section_name}.")
        locator = page.locator(f'input[type="file"][data-cws-upload-marker="{marker}"]')
        locator.set_input_files(path)
        page.wait_for_timeout(1000)


def _save_listing(service) -> None:
    clicked = service.evaluate(_click_save_button_script())
    if clicked is not True:
        raise ClientError("Could not find enabled Chrome Web Store save button.")
    service.wait_for_load_state("networkidle", timeout=60000)
    service.wait_for_timeout(2000)


def _update_text_fields_script(fields: list[dict]) -> str:
    payload = json.dumps(fields)
    return f"""
() => {{
  const fields = {payload};
  const updated = [];

  function textOf(node) {{
    return (node?.innerText || node?.textContent || "").replace(/\\s+/g, " ").trim();
  }}

  function controlText(control) {{
    const parts = [
      control.getAttribute("aria-label"),
      control.getAttribute("placeholder"),
      control.getAttribute("name"),
      control.id
    ];
    if (control.id) {{
      const label = document.querySelector(`label[for="${{CSS.escape(control.id)}}"]`);
      parts.push(textOf(label));
    }}
    parts.push(textOf(control.closest("label")));
    parts.push(textOf(control.closest("mat-form-field")));
    parts.push(textOf(control.parentElement));
    return parts.filter(Boolean).join(" | ").toLowerCase();
  }}

  function findControl(labels) {{
    const needles = labels.map((label) => label.toLowerCase());
    const controls = Array.from(document.querySelectorAll("input, textarea"));
    const matches = controls.filter((control) => {{
      if (control.type === "file") return false;
      const haystack = controlText(control);
      return needles.some((needle) => haystack.includes(needle));
    }});
    if (matches.length !== 1) {{
      throw new Error(`Expected one editable field for ${{labels.join("/")}}, found ${{matches.length}}`);
    }}
    if (matches[0].disabled || matches[0].readOnly || matches[0].getAttribute("aria-disabled") === "true") {{
      throw new Error(`Dashboard field is not editable for ${{labels.join("/")}}`);
    }}
    return matches[0];
  }}

  function setValue(control, value) {{
    const prototype = control.tagName === "TEXTAREA"
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
    const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
    descriptor.set.call(control, value);
    control.dispatchEvent(new Event("input", {{ bubbles: true }}));
    control.dispatchEvent(new Event("change", {{ bubbles: true }}));
    control.blur();
  }}

  for (const field of fields) {{
    const control = findControl(field.labels);
    setValue(control, field.value);
    updated.push(field.name);
  }}
  return updated;
}}
""".strip()


def _mark_file_input_script(section_name: str, marker: str) -> str:
    payload = json.dumps({"sectionName": section_name, "marker": marker})
    return f"""
() => {{
  const request = {payload};
  const needle = request.sectionName.toLowerCase();

  function textOf(node) {{
    return (node?.innerText || node?.textContent || "").replace(/\\s+/g, " ").trim();
  }}

  function isUsableInput(input) {{
    if (input.disabled) return false;
    if (input.closest("[hidden], [aria-hidden='true']")) return false;
    return true;
  }}

  function fileInputsIn(node) {{
    if (!node.querySelectorAll) return [];
    return Array.from(node.querySelectorAll('input[type="file"]'))
      .filter((input) => isUsableInput(input));
  }}

  function matchingSection(input) {{
    let node = input;
    for (let i = 0; i < 8 && node; i += 1) {{
      const text = textOf(node).toLowerCase();
      const inputCount = fileInputsIn(node).length;
      if (text.includes(needle) && inputCount === 1) return node;
      node = node.parentElement;
    }}
    return null;
  }}

  const inputs = Array.from(document.querySelectorAll('input[type="file"]'));
  inputs.forEach((input) => input.removeAttribute("data-cws-upload-marker"));
  const matches = inputs.filter((input) => isUsableInput(input) && matchingSection(input) !== null);
  if (matches.length !== 1) {{
    const candidates = inputs.map((input, index) => {{
      const section = matchingSection(input);
      return `${{index}}:${{textOf(section).slice(0, 120)}}`;
    }}).join(" | ");
    throw new Error(`Expected one file input for ${{request.sectionName}}, found ${{matches.length}}. Candidates: ${{candidates}}`);
  }}
  matches[0].setAttribute("data-cws-upload-marker", request.marker);
  return true;
}}
""".strip()


def _update_category_script(category: str) -> str:
    payload = json.dumps({"category": category})
    return f"""
async () => {{
  const request = {payload};

  function textOf(node) {{
    return (node?.innerText || node?.textContent || "").replace(/\\s+/g, " ").trim();
  }}

  function controlText(control) {{
    const parts = [
      control.getAttribute("aria-label"),
      control.getAttribute("placeholder"),
      control.id,
      textOf(control.closest("mat-form-field")),
      textOf(control.parentElement)
    ];
    return parts.filter(Boolean).join(" | ").toLowerCase();
  }}

  const nativeSelects = Array.from(document.querySelectorAll("select"))
    .filter((control) => controlText(control).includes("category"));
  if (nativeSelects.length === 1) {{
    const select = nativeSelects[0];
    const options = Array.from(select.options);
    const option = options.find((item) => item.text.trim() === request.category);
    if (!option) throw new Error(`Category option not found: ${{request.category}}`);
    select.value = option.value;
    select.dispatchEvent(new Event("input", {{ bubbles: true }}));
    select.dispatchEvent(new Event("change", {{ bubbles: true }}));
    return "category";
  }}

  const comboboxes = Array.from(document.querySelectorAll('[role="combobox"], mat-select'))
    .filter((control) => controlText(control).includes("category"));
  if (comboboxes.length !== 1) {{
    throw new Error(`Expected one category selector, found ${{comboboxes.length}}`);
  }}
  comboboxes[0].click();
  await new Promise((resolve) => setTimeout(resolve, 500));
  const options = Array.from(document.querySelectorAll('[role="option"], mat-option'));
  const option = options.find((item) => textOf(item) === request.category);
  if (!option) throw new Error(`Category option not found: ${{request.category}}`);
  option.click();
  await new Promise((resolve) => setTimeout(resolve, 500));
  return "category";
}}
""".strip()


def _click_save_button_script() -> str:
    return """
() => {
  const buttons = Array.from(document.querySelectorAll("button"));
  const candidates = buttons.filter((button) => {
    const text = (button.innerText || button.textContent || "").replace(/\\s+/g, " ").trim();
    return /^Save( draft)?$/i.test(text) && !button.disabled && button.getAttribute("aria-disabled") !== "true";
  });
  if (candidates.length !== 1) {
    throw new Error(`Expected one enabled save button, found ${candidates.length}`);
  }
  candidates[0].click();
  return true;
}
""".strip()


def _extract_dashboard_status_text(body_text: str) -> str | None:
    if not isinstance(body_text, str):
        raise ClientError("Dashboard status check expected page text.")
    match = re.search(r"Status:\s*(.+?)\s+ID:", body_text, re.DOTALL)
    if match is None:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip()
