"""Loss-aware native route capture; background CDP traffic is never retained."""
import json
import math
import uuid
from urllib.parse import urlsplit


MAX_EVENTS = 500
MAX_REQUESTS = 100


def route_scope(session_id, method, origin, path, max_bytes):
    if (not isinstance(session_id, str) or not 1 <= len(session_id) <= 128
            or method not in ("POST", "PUT", "PATCH")
            or not isinstance(origin, str) or not 1 <= len(origin) <= 2048
            or not isinstance(path, str) or not 1 <= len(path) <= 4096
            or type(max_bytes) is not int or not 1 <= max_bytes <= 1_000_000):
        raise ValueError("network_capture_scope_invalid")
    try:
        url, relative = urlsplit(origin), urlsplit(path)
        valid = (url.scheme in ("http", "https") and url.hostname and url.netloc == url.netloc.lower()
            and url.username is None and url.password is None and not url.path and not url.query and not url.fragment
            and origin == url.scheme + "://" + url.netloc and origin.isascii()
            and (url.port is None or 1 <= url.port <= 65535)
            and path.startswith("/") and not relative.scheme and not relative.netloc
            and not relative.query and not relative.fragment and relative.path == path)
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("network_capture_scope_invalid")
    return {"session_id": session_id, "method": method, "origin": origin, "path": path, "max_bytes": max_bytes}


class NetworkCapture:
    def __init__(self, scope):
        self.scope = route_scope(**scope)
        self.id = uuid.uuid4().hex
        self.requests = set()
        self.events = []
        self.bytes = 0
        self.loss = None

    def _route(self, value):
        try:
            url = urlsplit(value)
            return url.scheme + "://" + url.netloc == self.scope["origin"] and url.path == self.scope["path"]
        except (ValueError, TypeError):
            return False

    def record(self, method, params, session_id):
        if self.loss is not None:
            return
        if not isinstance(params, dict):
            if session_id == self.scope["session_id"] and method.startswith("Network."):
                self.loss = "event_schema_invalid"
            return
        if method == "Target.detachedFromTarget" and params.get("sessionId") == self.scope["session_id"]:
            self.loss = "session_detached"
            return
        if session_id != self.scope["session_id"]:
            return
        if method == "Inspector.detached":
            self.loss = "session_detached"
            return
        request_id = params.get("requestId")
        known_request = isinstance(request_id, str) and request_id in self.requests
        selected = None
        if method == "Network.requestWillBeSent":
            request = params.get("request", {})
            matches = isinstance(request, dict) and request.get("method") == self.scope["method"] and self._route(request.get("url"))
            if "redirectResponse" in params and (matches or known_request):
                self.loss = "redirect_inconclusive"
                return
            if not matches:
                return
            if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
                self.loss = "request_identity_invalid"
                return
            body = request.get("postData")
            try:
                bounded_body = isinstance(body, str) and body and len(body.encode()) < self.scope["max_bytes"]
            except UnicodeError:
                bounded_body = False
            if not bounded_body or request.get("hasPostData") is False:
                self.loss = "request_body_unavailable_or_at_limit"
                return
            if request_id not in self.requests and len(self.requests) >= MAX_REQUESTS:
                self.loss = "request_limit_exceeded"
                return
            self.requests.add(request_id)
            selected = {"requestId": request_id, "request": {"method": self.scope["method"],
                "url": self.scope["origin"] + self.scope["path"], "postData": body}}
        elif method == "Network.responseReceived":
            response = params.get("response", {})
            if not known_request:
                if isinstance(response, dict) and self._route(response.get("url")):
                    self.loss = "response_without_request"
                return
            if not isinstance(response, dict) or not self._route(response.get("url")):
                self.loss = "response_route_changed"
                return
            if type(response.get("status")) is not int or not 100 <= response["status"] <= 599:
                self.loss = "event_schema_invalid"
                return
            selected = {"requestId": request_id, "response": {"url": self.scope["origin"] + self.scope["path"],
                "status": response.get("status")}}
        elif known_request and method in ("Network.loadingFinished", "Network.loadingFailed"):
            selected = {"requestId": request_id}
            if method == "Network.loadingFinished":
                size = params.get("encodedDataLength")
                if type(size) not in (int, float) or not 0 <= size <= self.scope["max_bytes"] or not math.isfinite(size):
                    self.loss = "response_size_inconclusive"
                    return
                selected["encodedDataLength"] = size
        if selected is None:
            return
        event = {"method": method, "params": selected, "session_id": session_id}
        size = len(json.dumps(event).encode())
        if len(self.events) >= MAX_EVENTS or self.bytes + size > 4 * self.scope["max_bytes"]:
            self.loss = "capture_limit_exceeded"
            return
        self.events.append(event)
        self.bytes += size

    def drain(self):
        result = {"capture_id": self.id, "scope": self.scope, "events": self.events, "loss": self.loss}
        self.events = []
        self.bytes = 0
        return result
