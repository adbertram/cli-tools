"""Normalize Upwork profile data into the CLI's public record shape."""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

from cli_tools_shared.exceptions import ClientError


PROFILE_FIELDS = [
    {
        "name": "name",
        "label": "Name",
        "editable": False,
        "type": "string",
        "page": "profile",
        "aliases": ["full_name"],
    },
    {
        "name": "title",
        "label": "Title",
        "editable": True,
        "type": "string",
        "page": "profile",
        "aliases": ["headline", "professional_title"],
    },
    {
        "name": "overview",
        "label": "Overview",
        "editable": True,
        "type": "string",
        "page": "profile",
        "aliases": ["bio", "summary", "description"],
    },
    {
        "name": "hourly_rate",
        "label": "Hourly Rate",
        "editable": True,
        "type": "number",
        "page": "profile",
        "aliases": ["rate", "hourly", "hourlyRate"],
    },
    {
        "name": "skills",
        "label": "Skills",
        "editable": True,
        "type": "list",
        "page": "profile",
        "aliases": ["skill", "tags"],
    },
    {
        "name": "categories",
        "label": "Categories",
        "editable": True,
        "type": "list",
        "page": "profile",
        "aliases": ["category", "services"],
    },
    {
        "name": "availability",
        "label": "Availability",
        "editable": True,
        "type": "string",
        "page": "profile",
        "aliases": ["available", "hours"],
    },
    {
        "name": "languages",
        "label": "Languages",
        "editable": True,
        "type": "list",
        "page": "profile",
        "aliases": ["language"],
    },
    {
        "name": "location",
        "label": "Location",
        "editable": False,
        "type": "string",
        "page": "settings",
        "aliases": ["address", "city", "country"],
    },
    {
        "name": "profile_url",
        "label": "Profile URL",
        "editable": False,
        "type": "string",
        "page": "profile",
        "aliases": ["url"],
    },
]


def editable_profile_fields(include_read_only: bool = False) -> list[dict[str, Any]]:
    """Return the supported common Upwork profile fields."""
    fields = PROFILE_FIELDS if include_read_only else [field for field in PROFILE_FIELDS if field["editable"]]
    return [field.copy() for field in fields]


def normalize_field_name(name: str) -> str:
    """Return the canonical field name for a user-supplied profile field."""
    raw = (name or "").strip()
    if not raw:
        raise ClientError("Profile field name cannot be empty.")
    lowered = raw.lower().replace("-", "_").replace(" ", "_")
    for field in PROFILE_FIELDS:
        aliases = {field["name"], *(alias.lower().replace("-", "_") for alias in field.get("aliases", []))}
        if lowered in aliases:
            return field["name"]
    supported = ", ".join(field["name"] for field in PROFILE_FIELDS)
    raise ClientError(f"Unsupported profile field '{name}'. Supported fields: {supported}.")


def field_definition(name: str) -> dict[str, Any]:
    """Return metadata for a supported profile field."""
    canonical = normalize_field_name(name)
    for field in PROFILE_FIELDS:
        if field["name"] == canonical:
            return field.copy()
    raise ClientError(f"Unsupported profile field '{name}'.")


def normalize_profile_updates(updates: dict[str, Any]) -> dict[str, Any]:
    """Normalize update keys and values before browser mutation."""
    normalized: dict[str, Any] = {}
    for raw_name, value in updates.items():
        field = field_definition(raw_name)
        name = field["name"]
        if field["type"] == "number":
            normalized[name] = _normalize_number(value, name)
        elif field["type"] == "list":
            normalized[name] = _normalize_list(value)
        else:
            normalized[name] = _clean(value)
    return normalized


def normalize_profile(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize extracted DOM data into common profile attributes."""
    text = _clean(raw.get("text"))
    headings = [_clean(value) for value in raw.get("headings", []) if _clean(value)]
    links = raw.get("links", [])
    inputs = raw.get("inputs", [])
    json_ld = _parse_json_ld(raw.get("json_ld", []))

    profile = {
        "name": _first(
            _json_ld_value(json_ld, "name"),
            _heading_name(headings),
        ),
        "title": _first(
            _json_ld_value(json_ld, "jobTitle"),
            _profile_title(headings),
            _meta_content(raw, "og:title"),
        ),
        "overview": _first(
            _section(text, "Overview"),
            _section(text, "About"),
            _meta_content(raw, "description"),
        ),
        "hourly_rate": _first(
            _regex(text, r"\$([0-9]+(?:\.[0-9]{1,2})?)\s*/?\s*(?:hr|hour)"),
            _input_value(inputs, "hourly"),
        ),
        "skills": _first(
            _extract_skills(links),
            _section_list(text, "Skills"),
        ),
        "categories": _section_list(text, "Categories"),
        "availability": _first(
            _section(text, "Availability"),
            _regex(text, r"([0-9]+\s*(?:hrs|hours)\s*/\s*week)"),
        ),
        "languages": _section_list(text, "Languages"),
        "location": _first(
            _json_ld_value(json_ld, "address.addressLocality"),
            _json_ld_value(json_ld, "address.addressCountry"),
            _location(text),
        ),
        "profile_url": raw.get("url"),
    }
    return {name: _clean_value(value) for name, value in profile.items()}


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _clean_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_clean(item) for item in value if _clean(item)]
    return _clean(value) or None


def _normalize_number(value: Any, field_name: str) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = _clean(value).replace("$", "").replace("/hr", "").strip()
    try:
        return float(cleaned)
    except ValueError as exc:
        raise ClientError(f"Field '{field_name}' must be numeric.") from exc


def _normalize_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [_clean(part) for part in re.split(r"[,;\n]", value) if _clean(part)]
    if isinstance(value, Iterable):
        return [_clean(part) for part in value if _clean(part)]
    raise ClientError("List profile fields must be a list or comma-separated string.")


def _first(*values: Any) -> Any:
    for value in values:
        if isinstance(value, list):
            cleaned = [_clean(item) for item in value if _clean(item)]
            if cleaned:
                return cleaned
        elif _clean(value):
            return _clean(value)
    return None


def _parse_json_ld(values: list[str]) -> list[dict[str, Any]]:
    parsed = []
    for value in values:
        try:
            item = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(item, list):
            parsed.extend(entry for entry in item if isinstance(entry, dict))
        elif isinstance(item, dict):
            parsed.append(item)
    return parsed


def _json_ld_value(items: list[dict[str, Any]], dotted_key: str) -> str | None:
    parts = dotted_key.split(".")
    for item in items:
        current: Any = item
        for part in parts:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(part)
        if _clean(current):
            return _clean(current)
    return None


def _heading_name(headings: list[str]) -> str | None:
    return headings[0] if headings else None


def _profile_title(headings: list[str]) -> str | None:
    for heading in headings[1:4]:
        if heading and "$" not in heading and len(heading) <= 120:
            return heading
    return None


def _meta_content(raw: dict[str, Any], name: str) -> str | None:
    for meta in raw.get("meta", []):
        if meta.get("name") == name or meta.get("property") == name:
            return _clean(meta.get("content"))
    return None


def _regex(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    return _clean(match.group(1))


def _section(text: str, label: str) -> str | None:
    pattern = rf"{re.escape(label)}\s+(.*?)(?:\s+(?:Skills|Portfolio|Work History|Employment History|Education|Languages|Availability|Categories)\s+|$)"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    return _clean(match.group(1))


def _section_list(text: str, label: str) -> list[str]:
    section = _section(text, label)
    if not section:
        return []
    return _unique(part for part in re.split(r"[,;•|]", section) if _clean(part))


def _extract_skills(links: list[dict[str, Any]]) -> list[str]:
    return _unique(
        link.get("text")
        for link in links
        if "/freelancers/" not in _clean(link.get("href")) and _clean(link.get("text"))
    )


def _input_value(inputs: list[dict[str, Any]], needle: str) -> str | None:
    needle = needle.lower()
    for item in inputs:
        haystack = " ".join(
            _clean(item.get(key))
            for key in ("name", "id", "aria", "placeholder", "label")
        ).lower()
        if needle in haystack and _clean(item.get("value")):
            return _clean(item.get("value"))
    return None


def _location(text: str) -> str | None:
    match = re.search(r"([A-Z][A-Za-z .'-]+,\s*(?:United States|USA|[A-Z][A-Za-z .'-]+))", text)
    if not match:
        return None
    return _clean(match.group(1))


def _unique(values: Iterable[Any]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        cleaned = _clean(value)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result
