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
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class ReorderFlowError(Exception):
    """Raised when a reorder step fails."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ==================== Network logging (diagnostic-only) ====================
#
# Data-driven event recorder. Each Playwright event type is described by a
# spec dict mapping field-name -> extractor lambda. A single generic handler
# factory closes over the spec to produce the per-event listener.
# Adding a new event = adding a dict entry.

_BODY_RESOURCE_TYPES = {"xhr", "fetch", "document"}
_BODY_MAX_BYTES = 4096


def _resp_extras(response) -> Dict[str, Any]:
    if response.request.resource_type not in _BODY_RESOURCE_TYPES or response.status < 400:
        return {}
    body = response.body()
    return {"body_excerpt": {
        "bytes": len(body),
        "truncated": len(body) > _BODY_MAX_BYTES,
        "text": body[:_BODY_MAX_BYTES].decode("utf-8", errors="replace"),
    }}


_EVENT_SPECS: Dict[str, Dict[str, Callable[[Any], Any]]] = {
    "request": {
        "method": lambda r: r.method,
        "url": lambda r: r.url,
        "resource_type": lambda r: r.resource_type,
        "is_navigation": lambda r: getattr(r, "is_navigation_request", lambda: False)(),
    },
    "response": {
        "method": lambda r: r.request.method,
        "url": lambda r: r.url,
        "status": lambda r: r.status,
        "status_text": lambda r: r.status_text,
        "resource_type": lambda r: r.request.resource_type,
        # `_extras` returns a dict that's merged into the record (not stored
        # under the `_extras` key). The handler factory honors this convention.
        "_extras": _resp_extras,
    },
    "requestfailed": {
        "method": lambda r: r.method,
        "url": lambda r: r.url,
        "resource_type": lambda r: r.resource_type,
        "failure": lambda r: str(r.failure) if getattr(r, "failure", None) else None,
    },
}


class NetworkLogger:
    """Append-only JSON-lines network logger backed by a Playwright context.

    Reads `_EVENT_SPECS` to attach one generic handler per event type and
    writes one JSON line per event to ``<debug_dir>/network.jsonl``. The file
    is opened in append mode so reruns inside the same debug_dir accumulate,
    with each run delimited by a `_run_started` event.

    Diagnostic-only: this class does not affect the reorder flow's
    success/failure decisions.
    """

    def __init__(self, context, debug_dir: Path) -> None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        self._path = debug_dir / "network.jsonl"
        self._fp = self._path.open("a", encoding="utf-8")
        self._lock = threading.Lock()
        self._context = context
        self._closed = False
        self._handlers: Dict[str, Callable[[Any], None]] = {
            event: self._make_handler(event, spec) for event, spec in _EVENT_SPECS.items()
        }
        for event, handler in self._handlers.items():
            context.on(event, handler)
        self._write({"event": "_run_started", "timestamp": _now(), "log_path": str(self._path)})

    def _write(self, record: Dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            if self._closed:
                return
            self._fp.write(line + "\n")
            self._fp.flush()

    def _make_handler(self, event: str, spec: Dict[str, Callable[[Any], Any]]) -> Callable[[Any], None]:
        def handler(obj) -> None:
            record: Dict[str, Any] = {"event": event, "timestamp": _now()}
            for name, extractor in spec.items():
                value = extractor(obj)
                if name == "_extras" and isinstance(value, dict):
                    record.update(value)
                else:
                    record[name] = value
            self._write(record)
        return handler

    def mark(self, label: str, **fields: Any) -> None:
        """Write a marker event so the network log lines up with flow steps."""
        self._write({"event": "_marker", "timestamp": _now(), "label": label, **fields})

    def flush_close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for event, handler in self._handlers.items():
            self._context.remove_listener(event, handler)
        self._fp.flush()
        self._fp.close()


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


def _dump_debug_artifacts(page, debug_dir: Path, step_id: str) -> None:
    """Write URL, HTML, and screenshot of the current page on a step failure."""
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / f"{step_id}.url.txt").write_text(page.url + "\n", encoding="utf-8")
    (debug_dir / f"{step_id}.html").write_text(page.content(), encoding="utf-8")
    shot = page.page_screenshot()
    shutil.copyfile(shot["file"], debug_dir / f"{step_id}.png")


def run_reorder_flow(
    page,
    order_id: str,
    order_uuid: Optional[str],
    confirm: bool,
    log: Optional[Callable[[str], None]] = None,
    debug_dir: Optional[Path] = None,
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

    network_logger: Optional[NetworkLogger] = None
    if debug_dir is not None:
        if page._browser_context is None:
            raise ReorderFlowError("Cannot attach network logger: browser context is not open.")
        network_logger = NetworkLogger(page._browser_context, debug_dir)
        _log(f"[debug] network log: {debug_dir / 'network.jsonl'}")

    try:
        for step in steps:
            action = step.get("action")
            step_id = step.get("id", "?")
            if step.get("confirm_only") and not confirm:
                _log(f"[skip] {step_id}: confirm_only step skipped (no --confirm)")
                if network_logger:
                    network_logger.mark(f"step_skipped:{step_id}", action=action)
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
            if network_logger:
                network_logger.mark(f"step_started:{step_id}", action=action)
            try:
                step_result = _DISPATCH[action](page, step, context)
            except ReorderFlowError:
                if network_logger:
                    network_logger.mark(f"step_failed:{step_id}", action=action)
                if debug_dir is not None:
                    _dump_debug_artifacts(page, debug_dir, step_id)
                    _log(f"[debug] wrote artifacts to {debug_dir}")
                raise
            if network_logger:
                network_logger.mark(f"step_ok:{step_id}", action=action)
            result.steps.append(step_result)
            _log(f"[ok]   {step_id}: {step_result.detail or 'done'}")
            if step_id == "wait_for_confirmation" and step_result.status == "ok":
                result.submitted = True
        result.final_url = page.url
        return result
    finally:
        if network_logger is not None:
            network_logger.flush_close()
