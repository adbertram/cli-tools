"""Generic data-driven reorder flow engine.

The reorder flow is described in `data/reorder_flow.json`. This module is a
generic processor: it reads each step's `action` field and dispatches to the
matching handler. Adding a new step or rewiring a selector is a config edit,
not a code edit.

Design:
- One execution path per step, no fallbacks.
- Selectors are tried in order via `click_first` / `wait_for_selector_any`;
  the first match wins (this is intentional: DoorDash ships multiple data-testid
  generations side by side).
- `confirm_only` steps run only when the caller passes `confirm=True`.
- Every step crashes loudly with `ReorderFlowError` on failure; no silent skips.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class ReorderFlowError(Exception):
    """Raised when a reorder step fails."""


# ==================== Result types ====================


@dataclass
class StepResult:
    step_id: str
    description: str
    action: str
    status: str  # "ok" | "skipped" | "failed"
    detail: Optional[str] = None
    captured: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReorderResult:
    order_id: str
    order_uuid: Optional[str]
    confirm: bool
    submitted: bool
    cart_uuid: Optional[str] = None
    cart_url: Optional[str] = None
    steps: List[StepResult] = field(default_factory=list)
    cart_summary: Dict[str, Any] = field(default_factory=dict)
    final_url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id,
            "order_uuid": self.order_uuid,
            "confirm": self.confirm,
            "submitted": self.submitted,
            "cart_uuid": self.cart_uuid,
            "cart_url": self.cart_url,
            "final_url": self.final_url,
            "cart_summary": self.cart_summary,
            "steps": [
                {"id": s.step_id, "description": s.description, "action": s.action,
                 "status": s.status, "detail": s.detail, "captured": s.captured}
                for s in self.steps
            ],
        }


def load_flow_config() -> Dict[str, Any]:
    """Load the reorder flow JSON config bundled with the package."""
    config_path = Path(__file__).parent / "data" / "reorder_flow.json"
    if not config_path.exists():
        raise ReorderFlowError(f"Reorder flow config missing: {config_path}")
    with config_path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


# ==================== Page interaction primitives ====================


def _safe_visible(page, selector: str):
    """Query a selector and return the element only if it's visible. Swallows
    Playwright exceptions for selectors that fail to evaluate."""
    try:
        el = page.query_selector(selector)
        if el is not None and el.is_visible():
            return el
    except Exception:  # noqa: BLE001
        pass
    return None


def _wait_for_any_selector(page, selectors: List[str], timeout_ms: int) -> Optional[str]:
    deadline = time.time() + (timeout_ms / 1000.0)
    while time.time() < deadline:
        for sel in selectors:
            if _safe_visible(page, sel) is not None:
                return sel
        time.sleep(0.5)
    return None


def _wait_for_selectors_to_disappear(page, selectors: List[str], timeout_ms: int) -> List[str]:
    deadline = time.time() + (timeout_ms / 1000.0)
    while time.time() < deadline:
        present = [s for s in selectors if _safe_visible(page, s) is not None]
        if not present:
            return []
        time.sleep(1.0)
    return [s for s in selectors if _safe_visible(page, s) is not None]


def _wait_for_url_match(page, patterns: List[str], timeout_ms: int) -> Optional[str]:
    deadline = time.time() + (timeout_ms / 1000.0)
    compiled = [re.compile(p) for p in patterns]
    while time.time() < deadline:
        url = getattr(page, "url", "") or ""
        for pattern in compiled:
            if pattern.search(url):
                return url
        time.sleep(0.5)
    return None


def _click_first_match(page, selectors: List[str]) -> Optional[str]:
    for sel in selectors:
        el = _safe_visible(page, sel)
        if el is None:
            continue
        try:
            el.click()
            return sel
        except Exception:  # noqa: BLE001
            continue
    return None


def _capture_text(page, selectors: List[str]) -> Optional[str]:
    for sel in selectors:
        el = _safe_visible(page, sel)
        if el is None:
            continue
        try:
            text = el.text_content()
        except Exception:  # noqa: BLE001
            continue
        if text:
            return text.strip()
    return None


# ==================== Step dispatch ====================


def _ok(step: Dict[str, Any], detail: str, captured: Optional[Dict[str, Any]] = None) -> StepResult:
    return StepResult(
        step_id=step["id"],
        description=step.get("description", ""),
        action=step["action"],
        status="ok",
        detail=detail,
        captured=captured or {},
    )


def _step_goto(page, step: Dict[str, Any], context: Dict[str, str]) -> StepResult:
    target = None
    for t in step.get("url_templates") or []:
        try:
            target = t.format(**context)
            break
        except KeyError:
            continue
    if not target:
        raise ReorderFlowError(
            f"Step {step['id']}: no usable URL templates "
            f"(missing placeholders for {sorted(context.keys())})"
        )
    page.goto(target)
    selectors = step.get("wait_for_selector_any") or []
    timeout_ms = int(step.get("wait_timeout_ms", 20000))
    if not selectors:
        return _ok(step, f"loaded {target}")
    match = _wait_for_any_selector(page, selectors, timeout_ms)
    if not match:
        raise ReorderFlowError(
            f"Step {step['id']}: no expected element appeared at {target} "
            f"within {timeout_ms}ms (tried {selectors})"
        )
    return _ok(step, f"loaded {target}, matched selector: {match}")


def _step_click_first(page, step: Dict[str, Any], context: Dict[str, str]) -> StepResult:
    selectors = step.get("selectors") or []
    if not selectors:
        raise ReorderFlowError(f"Step {step['id']}: no selectors configured")
    matched = _click_first_match(page, selectors)
    if not matched:
        raise ReorderFlowError(
            f"Step {step['id']}: none of the configured selectors matched a "
            f"visible element ({selectors}). The DoorDash UI selectors in "
            f"data/reorder_flow.json may need updating."
        )
    return _ok(step, f"clicked: {matched}")


def _step_wait_for_url_or_selector(page, step: Dict[str, Any], context: Dict[str, str]) -> StepResult:
    timeout_ms = int(step.get("wait_timeout_ms", 30000))
    url_patterns = step.get("url_patterns") or []
    selectors = step.get("selectors") or []
    deadline = time.time() + (timeout_ms / 1000.0)
    while time.time() < deadline:
        if url_patterns:
            hit = _wait_for_url_match(page, url_patterns, 500)
            if hit:
                return _ok(step, f"url matched: {hit}")
        if selectors:
            hit = _wait_for_any_selector(page, selectors, 500)
            if hit:
                return _ok(step, f"selector matched: {hit}")
    raise ReorderFlowError(
        f"Step {step['id']}: neither URL pattern {url_patterns} nor selectors "
        f"{selectors} matched within {timeout_ms}ms"
    )


def _step_capture(page, step: Dict[str, Any], context: Dict[str, str]) -> StepResult:
    captured = {name: _capture_text(page, sels) for name, sels in (step.get("fields") or {}).items()}
    return _ok(step, f"captured fields: {list(captured.keys())}", captured=captured)


def _step_wait_for_selectors_to_disappear(page, step: Dict[str, Any], context: Dict[str, str]) -> StepResult:
    selectors = step.get("selectors") or []
    if not selectors:
        raise ReorderFlowError(f"Step {step['id']}: no selectors configured")
    timeout_ms = int(step.get("wait_timeout_ms", 30000))
    still_visible = _wait_for_selectors_to_disappear(page, selectors, timeout_ms)
    if still_visible:
        raise ReorderFlowError(
            f"Step {step['id']}: selectors still visible after {timeout_ms}ms: "
            f"{still_visible}. Cloudflare Turnstile may not have resolved, or "
            f"the page is stuck on a loading state."
        )
    return _ok(step, f"all selectors gone: {selectors}")


_DISPATCH: Dict[str, Callable[..., StepResult]] = {
    "goto": _step_goto,
    "click_first": _step_click_first,
    "wait_for_url_or_selector": _step_wait_for_url_or_selector,
    "wait_for_selectors_to_disappear": _step_wait_for_selectors_to_disappear,
    "capture": _step_capture,
}


def run_reorder_flow(
    page,
    order_id: str,
    order_uuid: Optional[str],
    confirm: bool,
    log: Optional[Callable[[str], None]] = None,
    extra_context: Optional[Dict[str, str]] = None,
) -> ReorderResult:
    """Run the reorder flow defined in data/reorder_flow.json."""
    steps = load_flow_config().get("steps") or []
    if not steps:
        raise ReorderFlowError("reorder_flow.json defines no steps")

    context = {"order_id": order_id}
    if order_uuid:
        context["order_uuid"] = order_uuid
    if extra_context:
        context.update(extra_context)

    result = ReorderResult(order_id=order_id, order_uuid=order_uuid, confirm=confirm, submitted=False)
    _log = log or (lambda _msg: None)

    for step in steps:
        action = step.get("action")
        step_id = step.get("id", "?")
        if step.get("confirm_only") and not confirm:
            _log(f"[skip] {step_id}: confirm_only step skipped (no --confirm)")
            result.steps.append(StepResult(
                step_id=step_id, description=step.get("description", ""), action=action,
                status="skipped", detail="confirm_only step; --confirm not passed",
            ))
            continue
        if action not in _DISPATCH:
            raise ReorderFlowError(
                f"Step {step_id}: unknown action '{action}'. Update reorder.py "
                f"or fix data/reorder_flow.json."
            )
        _log(f"[run]  {step_id}: {action}")
        step_result = _DISPATCH[action](page, step, context)
        result.steps.append(step_result)
        _log(f"[ok]   {step_id}: {step_result.detail or 'done'}")
        if step_id == "wait_for_confirmation" and step_result.status == "ok":
            result.submitted = True
    result.final_url = page.url
    return result
