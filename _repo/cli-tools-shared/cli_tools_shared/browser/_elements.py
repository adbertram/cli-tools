"""Locator + element wrappers for browser automation.

A locator is just a JS expression that returns an Array of DOM elements.
Every operation (.locator(child), .filter, .all()[i], .get_by_role) is a
JS-expression transformation, so we store the expression as data and use
one class for all locator shapes.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any, List, Optional

from . import BrowserHarnessError
from ._js_fragments import _CLICK_JS, _VISIBILITY_JS, _fill_js

if TYPE_CHECKING:
    from .driver import BrowserHarnessService


# ----------------------- JS expression builders -----------------------

_ROLE_CSS = {
    "button": "button, input[type='button'], input[type='submit'], [role='button']",
    "link": "a[href], [role='link']",
    "textbox": "input[type='text'], input:not([type]), textarea, [role='textbox']",
    "checkbox": "input[type='checkbox'], [role='checkbox']",
    "radio": "input[type='radio'], [role='radio']",
    "combobox": "select, [role='combobox']",
    "heading": "h1, h2, h3, h4, h5, h6, [role='heading']",
    "spinbutton": "input[type='number'], [role='spinbutton']",
    "listitem": "li, [role='listitem']",
}


def _css_js(selector: str) -> str:
    return f"Array.from(document.querySelectorAll({json.dumps(selector)}))"


def _scoped_css_js(parent_js: str, selector: str) -> str:
    scoped_selector = selector
    if selector.lstrip().startswith((">", "+", "~")):
        scoped_selector = f":scope {selector.lstrip()}"
    return (
        f"({parent_js}).flatMap("
        f"p => Array.from(p.querySelectorAll({json.dumps(scoped_selector)}))"
        f")"
    )


def _text_js(text_part: str) -> str:
    if text_part.startswith("/"):
        return (
            f"Array.from(document.querySelectorAll('*'))"
            f".filter(el => el.children.length === 0 && {text_part}.test(el.textContent))"
        )
    if text_part.startswith('"') or text_part.startswith("'"):
        exact = text_part.strip('"').strip("'")
        return (
            f"Array.from(document.querySelectorAll('*'))"
            f".filter(el => el.textContent.trim() === {json.dumps(exact)})"
        )
    return (
        f"Array.from(document.querySelectorAll('*'))"
        f".filter(el => el.textContent.toLowerCase().includes({json.dumps(text_part.lower())}))"
    )


def _has_text_js(selector: str) -> str:
    m = re.match(r'^(.*?):has-text\(\s*["\'](.+?)["\']\s*\)$', selector)
    if not m:
        return _css_js(selector)
    css_part = m.group(1) or "*"
    text_part = m.group(2)
    return (
        f"Array.from(document.querySelectorAll({json.dumps(css_part)}))"
        f".filter(el => el.textContent.includes({json.dumps(text_part)}))"
    )


def _name_filter_js(base_js: str, name) -> str:
    """Apply a name filter (string or compiled regex) on top of base_js."""
    if name is None:
        return base_js
    if hasattr(name, "pattern"):
        flags = "i" if name.flags & re.IGNORECASE else ""
        js_re = f"/{name.pattern}/{flags}"
        return (
            f"{base_js}.filter(el => {js_re}.test(el.textContent.trim())"
            f" || {js_re}.test(el.getAttribute('aria-label') || '')"
            f" || {js_re}.test(el.value || ''))"
        )
    needle = json.dumps(str(name))
    return (
        f"{base_js}.filter(el => el.textContent.trim().includes({needle})"
        f" || (el.getAttribute('aria-label') || '').includes({needle})"
        f" || (el.value || '').includes({needle}))"
    )


def _role_js(role: str, name=None, scope_js: Optional[str] = None) -> str:
    css = _ROLE_CSS.get(role, f"[role='{role}']")
    base = _scoped_css_js(scope_js, css) if scope_js else _css_js(css)
    return _name_filter_js(base, name)


def _has_text_filter_js(base_js: str, has_text) -> str:
    if hasattr(has_text, "pattern"):
        flags = "i" if has_text.flags & re.IGNORECASE else ""
        return f"{base_js}.filter(el => /{has_text.pattern}/{flags}.test(el.textContent))"
    return f"{base_js}.filter(el => el.textContent.includes({json.dumps(str(has_text))}))"


def _selector_js(selector: str) -> str:
    if selector.startswith("text="):
        return _text_js(selector[5:])
    if ":has-text(" in selector:
        return _has_text_js(selector)
    return _css_js(selector)


# ----------------------- Locator + Element classes -----------------------


class _ServiceLocator:
    """Lazy element locator. Holds a JS expression that returns an Array of elements."""

    def __init__(self, svc: BrowserHarnessService, selector_or_js: str, *, _is_js: bool = False):
        self._svc = svc
        # _is_js distinguishes "raw JS expression" from "selector string we should compile"
        self._find_js = selector_or_js if _is_js else _selector_js(selector_or_js)

    @classmethod
    def from_role(cls, svc: BrowserHarnessService, role: str, name=None) -> _ServiceLocator:
        return cls(svc, _role_js(role, name), _is_js=True)

    def _eval_on_first(self, body: str, *, require: bool = False) -> Any:
        guard = (
            'if (els.length === 0) throw new Error("No element found for locator");'
            if require else
            'if (els.length === 0) return null;'
        )
        return self._svc.evaluate(
            f"() => {{ const els = {self._find_js}; {guard} const el = els[0]; {body} }}"
        )

    # --- actions ---

    def click(self) -> None:
        self._eval_on_first(_CLICK_JS, require=True)

    def fill(self, text: str) -> None:
        self._eval_on_first(_fill_js(text), require=True)

    def select_option(self, value: str = None, *, label: str = None) -> None:
        _select_option(self._svc, f"({self._find_js})[0]", value=value, label=label)

    def press(self, key: str) -> None:
        self._eval_on_first("el.focus();")
        self._svc.keyboard_press(key)

    # --- queries ---

    def count(self) -> int:
        result = self._svc.evaluate(f"() => ({self._find_js}).length")
        if not result:
            return 0
        try:
            return int(result)
        except (ValueError, TypeError):
            raise BrowserHarnessError(f"count() expected integer, got: {str(result)[:200]}")

    @property
    def first(self) -> _ServiceElement:
        return _ServiceElement(self._svc, js_expr=f"({self._find_js})[0]")

    def is_visible(self, *, timeout: int = None) -> bool:
        return bool(self._eval_on_first(_VISIBILITY_JS))

    def is_enabled(self) -> bool:
        return bool(self._eval_on_first("return !el.disabled;"))

    def all_text_contents(self) -> List[str]:
        result = self._svc.evaluate(f"() => ({self._find_js}).map(el => el.textContent || '')")
        return result if isinstance(result, list) else []

    def text_content(self) -> Optional[str]:
        return self._eval_on_first("return el.textContent;")

    def inner_text(self) -> Optional[str]:
        return self._eval_on_first("return el.innerText || el.textContent || '';")

    def get_attribute(self, name: str) -> Optional[str]:
        return self._eval_on_first(f"return el.getAttribute({json.dumps(name)});")

    def input_value(self) -> str:
        value = self._eval_on_first("return 'value' in el ? el.value : '';")
        return value if isinstance(value, str) else ""

    # --- chaining ---

    def all(self) -> List[_ServiceLocator]:
        return [
            _ServiceLocator(self._svc, f"[({self._find_js})[{i}]].filter(Boolean)", _is_js=True)
            for i in range(self.count())
        ]

    def locator(self, child_selector: str) -> _ServiceLocator:
        return _ServiceLocator(
            self._svc, _scoped_css_js(self._find_js, child_selector), _is_js=True
        )

    def filter(self, *, has_text=None) -> _ServiceLocator:
        if has_text is None:
            return self
        return _ServiceLocator(
            self._svc, _has_text_filter_js(self._find_js, has_text), _is_js=True
        )

    def get_by_placeholder(self, text: str) -> _ServiceLocator:
        return self.locator(f'[placeholder="{text}"]')

    def get_by_role(self, role: str, *, name=None) -> _ServiceLocator:
        return _ServiceLocator(self._svc, _role_js(role, name, scope_js=self._find_js), _is_js=True)


class _ServiceElement:
    """A single resolved element. Held by ``_ServiceLocator.first``."""

    def __init__(self, svc: BrowserHarnessService, *, js_expr: str = None,
                 css: str = None, index: int = None):
        self._svc = svc
        if js_expr is not None:
            self._js = js_expr
        elif index is not None:
            self._js = f"document.querySelectorAll({json.dumps(css)})[{index}]"
        else:
            self._js = f"document.querySelector({json.dumps(css)})"

    def _eval_on_el(self, body: str) -> Any:
        return self._svc.evaluate(
            f"() => {{ const el = {self._js}; {body} }}"
        )

    def click(self) -> None:
        self._eval_on_el(f"if (el) {{ {_CLICK_JS} }}")

    def fill(self, text: str) -> None:
        self._eval_on_el(f"if (!el) throw new Error('Element not found'); {_fill_js(text)}")

    def select_option(self, value: str = None, *, label: str = None) -> None:
        _select_option(self._svc, self._js, value=value, label=label)

    def press(self, key: str) -> None:
        self._eval_on_el("if (el) el.focus();")
        self._svc.keyboard_press(key)

    def is_visible(self, *, timeout: int = None) -> bool:
        return bool(self._eval_on_el(f"if (!el) return false; {_VISIBILITY_JS}"))

    def count(self) -> int:
        return 1

    def text_content(self) -> Optional[str]:
        return self._eval_on_el("if (!el) return null; return el.textContent;")

    def inner_text(self) -> Optional[str]:
        return self._eval_on_el("if (!el) return null; return el.innerText || el.textContent || '';")

    def get_attribute(self, name: str) -> Optional[str]:
        return self._eval_on_el(
            f"if (!el) return null; return el.getAttribute({json.dumps(name)});"
        )

    def input_value(self) -> str:
        value = self._eval_on_el("if (!el) return ''; return 'value' in el ? el.value : '';")
        return value if isinstance(value, str) else ""

    def locator(self, child_selector: str) -> _ServiceLocator:
        return _ServiceLocator(
            self._svc,
            _scoped_css_js(f"[{self._js}].filter(Boolean)", child_selector),
            _is_js=True,
        )

    def filter(self, *, has_text=None) -> _ServiceLocator:
        if has_text is None:
            return _ServiceLocator(self._svc, f"[{self._js}].filter(Boolean)", _is_js=True)
        return _ServiceLocator(
            self._svc,
            _has_text_filter_js(f"[{self._js}].filter(Boolean)", has_text),
            _is_js=True,
        )

    def get_by_placeholder(self, text: str) -> _ServiceLocator:
        return self.locator(f'[placeholder="{text}"]')

    def get_by_role(self, role: str, *, name=None) -> _ServiceLocator:
        return _ServiceLocator(
            self._svc,
            _role_js(role, name, scope_js=f"[{self._js}].filter(Boolean)"),
            _is_js=True,
        )


def _select_option(svc: BrowserHarnessService, element_js: str, *,
                   value: str = None, label: str = None) -> None:
    if value is None and label is None:
        raise BrowserHarnessError("select_option requires value or label")
    if value is not None and label is not None:
        raise BrowserHarnessError("select_option accepts value or label, not both")

    criterion = "label" if label is not None else "value"
    wanted = label if label is not None else value
    svc.evaluate(
        f"""() => {{
            const el = {element_js};
            if (!el) throw new Error('Element not found');
            if (!(el instanceof HTMLSelectElement)) {{
                throw new Error('select_option target is not a select element');
            }}
            const criterion = {json.dumps(criterion)};
            const wanted = {json.dumps(str(wanted))};
            const option = Array.from(el.options).find(o =>
                criterion === 'label'
                    ? (o.textContent || '').trim() === wanted
                    : o.value === wanted
            );
            if (!option) throw new Error(`No select option matched ${{criterion}}: ${{wanted}}`);
            el.value = option.value;
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        }}"""
    )
