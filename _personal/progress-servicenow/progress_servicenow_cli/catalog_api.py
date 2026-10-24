"""Authenticated ServiceNow Service Catalog API access.

The Employee Center search page renders its catalog results inside shadow DOM,
so DOM/locator scraping cannot see them.  The ``sn_sc`` Service Catalog REST API
is reachable from the authenticated browser page with the session's ``g_ck``
user token and returns catalog items, their variables, and each variable's
choice list directly.

Every helper here raises :class:`ClientError` when the live service does not
return what the caller asked for.  Nothing in this module substitutes a default,
an empty list, or a cached value for a live answer.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from cli_tools_shared.exceptions import ClientError

ITEM_ENDPOINT = "/api/sn_sc/servicecatalog/items"

# ServiceNow ``friendly_type`` -> the field type used by ticket_template.json
# and by the form-filling code in client.py.
FIELD_TYPE_MAP = {
    "select_box": "dropdown",
    "yes_no": "dropdown",
    "multiple_choice": "dropdown",
    "lookup_select_box": "dropdown",
    "reference": "reference",
    "check_box": "checkbox",
    "single_line_text": "text",
    "wide_single_line_text": "text",
    "masked": "text",
    "email": "text",
    "url": "text",
    "numeric_scale": "text",
    "date": "text",
    "date_time": "text",
    "multi_line_text": "textarea",
    "html": "textarea",
}

# Presentation-only variables that carry no input value.
NON_INPUT_TYPES = {
    "container_start",
    "container_split",
    "container_end",
    "label",
    "break",
    "macro",
    "macro_with_label",
    "ui_page",
    "rich_text_label",
}


def _evaluate_json(page: Any, path: str) -> Dict[str, Any]:
    """GET ``path`` from the authenticated ServiceNow session and return JSON."""
    result = page.evaluate(
        """async (path) => {
            const headers = {'Accept': 'application/json', 'X-UserToken': window.g_ck || ''};
            const res = await fetch(path, {headers});
            const text = await res.text();
            return {status: res.status, ok: res.ok, text: text, token: !!window.g_ck};
        }""",
        path,
    )
    if not result.get("token"):
        raise ClientError(
            "The ServiceNow page has no g_ck user token, so the Service Catalog API "
            f"cannot be called. Requested path: {path}"
        )
    if not result.get("ok"):
        raise ClientError(
            f"ServiceNow Service Catalog API request failed: GET {path} returned "
            f"HTTP {result.get('status')}: {str(result.get('text'))[:400]}"
        )
    try:
        return json.loads(result["text"])
    except json.JSONDecodeError as exc:
        raise ClientError(
            f"ServiceNow Service Catalog API returned non-JSON for GET {path}: {exc}"
        ) from exc


def search_items(page: Any, text: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Search catalog items by free text. Returns the raw API records."""
    path = f"{ITEM_ENDPOINT}?sysparm_text={_quote(text)}&sysparm_limit={int(limit)}"
    payload = _evaluate_json(page, path)
    items = payload.get("result")
    if not isinstance(items, list):
        raise ClientError(
            f"ServiceNow catalog search for {text!r} returned an unexpected payload shape: "
            f"expected result list, got {type(items).__name__}"
        )
    return items


def get_item(page: Any, sys_id: str) -> Dict[str, Any]:
    """Fetch one catalog item, including its full variable tree."""
    payload = _evaluate_json(page, f"{ITEM_ENDPOINT}/{sys_id}")
    item = payload.get("result")
    if not isinstance(item, dict):
        raise ClientError(
            f"ServiceNow catalog item {sys_id} returned an unexpected payload shape: "
            f"expected result object, got {type(item).__name__}"
        )
    return item


def resolve_item_sys_id(page: Any, name: str) -> str:
    """Resolve a catalog item display name to its sys_id.

    Raises:
        ClientError: When no live catalog item carries that exact name. The
            message names the searched value, the endpoint, and the candidates
            the service did return.
    """
    candidates = search_items(page, name)
    target = name.strip().lower()
    for item in candidates:
        if str(item.get("name", "")).strip().lower() == target:
            return str(item["sys_id"])
    found = ", ".join(sorted({str(item.get("name", "")) for item in candidates})) or "nothing"
    raise ClientError(
        f"No catalog item named {name!r} exists in the live ServiceNow catalog. "
        f"Searched {ITEM_ENDPOINT}?sysparm_text={name!r} and it returned: {found}. "
        "Run 'progress-servicenow ticket template refresh' to resync the template "
        "registry, or pass --url with the catalog item form URL."
    )


def flatten_variables(variables: Any) -> List[Dict[str, Any]]:
    """Flatten the catalog item variable tree into a list of input variables."""
    flat: List[Dict[str, Any]] = []
    if not isinstance(variables, list):
        raise ClientError(
            "ServiceNow catalog item has no variable list; expected list, got "
            f"{type(variables).__name__}"
        )
    for variable in variables:
        children = variable.get("children")
        if children:
            flat.extend(flatten_variables(children))
        if variable.get("friendly_type") in NON_INPUT_TYPES:
            continue
        flat.append(variable)
    return flat


def variable_options(variable: Dict[str, Any]) -> List[str]:
    """Return the choice labels for a variable, or an empty list when it has none."""
    choices = variable.get("choices")
    if not isinstance(choices, list):
        return []
    return [str(choice["label"]) for choice in choices if choice.get("label") is not None]


def field_key(variable: Dict[str, Any]) -> str:
    """Derive a stable snake_case template field key from a ServiceNow variable name.

    ``var_product`` -> ``product``; ``description__desc`` -> ``description``;
    ``ReqImpact`` -> ``req_impact``.
    """
    name = str(variable.get("name") or "")
    if not name:
        raise ClientError(
            f"ServiceNow variable {variable.get('label')!r} has no name, so no stable "
            "template field key can be derived."
        )
    if name.startswith("var_"):
        name = name[4:]
    if name.endswith("__desc"):
        name = name[: -len("__desc")]
    out: List[str] = []
    for index, char in enumerate(name):
        if char.isupper() and index and not name[index - 1].isupper():
            out.append("_")
        out.append(char.lower())
    return "".join(out).strip("_")


def field_type(variable: Dict[str, Any]) -> str:
    """Map a ServiceNow ``friendly_type`` to the template field type."""
    friendly = str(variable.get("friendly_type") or "")
    if friendly not in FIELD_TYPE_MAP:
        raise ClientError(
            f"ServiceNow variable {variable.get('name')!r} "
            f"({variable.get('label')!r}) has friendly_type {friendly!r}, which the "
            "progress-servicenow template refresh does not know how to represent. "
            "Add it to catalog_api.FIELD_TYPE_MAP or NON_INPUT_TYPES."
        )
    return FIELD_TYPE_MAP[friendly]


def build_template_entry(item: Dict[str, Any]) -> Dict[str, Any]:
    """Build a ticket_template.json catalog item entry from a live catalog item."""
    sys_id = item.get("sys_id")
    if not sys_id:
        raise ClientError("ServiceNow catalog item payload has no sys_id.")

    fields: Dict[str, Any] = {}
    required: List[str] = []
    for variable in flatten_variables(item.get("variables", [])):
        key = field_key(variable)
        definition: Dict[str, Any] = {
            "label": str(variable.get("label") or ""),
            "type": field_type(variable),
            "required": bool(variable.get("mandatory")),
            "variable": str(variable.get("name") or ""),
            "sn_type": str(variable.get("friendly_type") or ""),
        }
        options = variable_options(variable)
        if options:
            definition["options"] = options
        fields[key] = definition
        if definition["required"]:
            required.append(key)

    category = item.get("category")
    return {
        "name": str(item.get("name") or ""),
        "description": str(item.get("short_description") or ""),
        "category": str((category or {}).get("title") or ""),
        "sys_id": str(sys_id),
        "url": f"?id=sc_cat_item&sys_id={sys_id}",
        "required_fields": required,
        "fields": fields,
    }


def template_key_for(name: str) -> str:
    """Derive a template registry key from a catalog item display name."""
    slug = "".join(char.lower() if char.isalnum() else "_" for char in name)
    while "__" in slug:
        slug = slug.replace("__", "_")
    key = slug.strip("_")
    if not key:
        raise ClientError(f"Catalog item name {name!r} produces an empty template key.")
    return key


def _quote(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


def find_field(template_data: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
    """Return one field definition from a template entry, or None."""
    fields = template_data.get("fields")
    if not isinstance(fields, dict):
        return None
    definition = fields.get(key)
    return definition if isinstance(definition, dict) else None
