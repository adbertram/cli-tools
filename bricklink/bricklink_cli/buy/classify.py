"""Classify BrickLink marketplace ajax HTTP responses."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional


class ResponseClass(str, Enum):
    OK_JSON = "OK_JSON"
    BL_ERROR = "BL_ERROR"
    THROTTLE = "THROTTLE"
    TRANSIENT = "TRANSIENT"
    OTHER = "OTHER"


@dataclass(frozen=True)
class ClassifiedResponse:
    classification: ResponseClass
    status_code: int
    payload: Any = None
    return_code: Any = None
    return_message: str = ""
    detail: str = ""


def _parse_json(body: bytes | str) -> Optional[Any]:
    if body is None:
        return None
    if isinstance(body, bytes):
        if not body:
            return None
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            return None
    else:
        text = body
        if not text:
            return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def classify_response(
    *,
    status_code: int,
    content: bytes = b"",
    headers: Mapping[str, str] | None = None,
) -> ClassifiedResponse:
    headers = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    body = content or b""

    if status_code == 403 and len(body) == 0:
        return ClassifiedResponse(
            ResponseClass.THROTTLE, status_code, detail="empty HTTP 403 (BrickLink throttle)"
        )
    if status_code == 429:
        return ClassifiedResponse(ResponseClass.THROTTLE, status_code, detail="HTTP 429")
    if status_code == 503:
        return ClassifiedResponse(ResponseClass.THROTTLE, status_code, detail="HTTP 503")
    if status_code == 202 or headers.get("x-amzn-waf-action") == "challenge":
        return ClassifiedResponse(
            ResponseClass.THROTTLE, status_code, detail="WAF challenge"
        )
    if 500 <= status_code <= 599:
        return ClassifiedResponse(
            ResponseClass.TRANSIENT, status_code, detail=f"HTTP {status_code}"
        )

    if status_code == 200:
        payload = _parse_json(body)
        if isinstance(payload, dict) and "returnCode" in payload:
            raw_rc = payload.get("returnCode")
            try:
                rc = int(raw_rc)
            except (TypeError, ValueError):
                rc = raw_rc
            msg = str(payload.get("returnMessage") or "")
            if rc == 0:
                return ClassifiedResponse(
                    ResponseClass.OK_JSON, status_code, payload=payload,
                    return_code=rc, return_message=msg,
                )
            # Soft IP/session throttle: catalogifs returns -1 Invalid request under burst.
            if rc == -1 and "invalid request" in msg.lower():
                return ClassifiedResponse(
                    ResponseClass.THROTTLE, status_code, payload=payload,
                    return_code=rc, return_message=msg,
                    detail=f"returnCode={rc}: {msg}",
                )
            return ClassifiedResponse(
                ResponseClass.BL_ERROR, status_code, payload=payload,
                return_code=rc, return_message=msg,
                detail=f"returnCode={rc}: {msg}",
            )
        if payload is not None:
            return ClassifiedResponse(
                ResponseClass.OK_JSON, status_code, payload=payload, return_code=0
            )

    return ClassifiedResponse(
        ResponseClass.OTHER, status_code,
        detail=f"unclassified status={status_code} bytes={len(body)}",
    )


class BrickLinkAjaxError(Exception):
    def __init__(self, classified: ClassifiedResponse):
        self.classified = classified
        super().__init__(classified.detail or classified.return_message or "BrickLink ajax error")


class BrickLinkThrottleError(Exception):
    def __init__(self, classified: ClassifiedResponse):
        self.classified = classified
        super().__init__(classified.detail or "throttled")
