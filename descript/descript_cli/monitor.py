"""CDP network monitor for Descript app.

Connects to Descript's Chrome DevTools Protocol endpoint and logs
all API network requests for endpoint discovery and debugging.
"""
import json
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import http.client
import websocket

CDP_PORT = 9222
MONITOR_DIR = Path.home() / ".descript"
PID_FILE = MONITOR_DIR / "monitor.pid"
LOG_FILE = MONITOR_DIR / "monitor.log"

# Noise domains to filter out
NOISE_DOMAINS = {
    "facebook.com", "google", "stripe", "sentry", "segment",
    "analytics", "intercom", "launchdarkly", "statsig",
    "amplitude", "sprig.com", "clarity.ms", "zendesk",
    "braze.com",
}

# Static asset extensions to filter
NOISE_EXTENSIONS = {
    ".js", ".css", ".png", ".svg", ".woff", ".woff2", ".ico",
    ".jpg", ".jpeg", ".gif", ".map",
}


def _is_noise(url: str) -> bool:
    """Check if URL is noise (analytics, static assets, etc.)."""
    lower = url.lower()

    for domain in NOISE_DOMAINS:
        if domain in lower:
            return True

    for ext in NOISE_EXTENSIONS:
        if ext in lower:
            return True

    if lower.startswith("data:") or "chrome-extension" in lower:
        return True

    return False


def _find_descript_page() -> Optional[str]:
    """Find Descript main page CDP target and return its WebSocket URL."""
    try:
        conn = http.client.HTTPConnection("127.0.0.1", CDP_PORT, timeout=5)
        conn.request("GET", "/json")
        response = conn.getresponse()

        if response.status != 200:
            return None

        targets = json.loads(response.read().decode())
        conn.close()

        for target in targets:
            if (target.get("type") == "page" and
                "Descript" in target.get("title", "") and
                "stripe" not in target.get("title", "")):
                return target.get("webSocketDebuggerUrl")

        return None
    except Exception:
        return None


def run_monitor(log_file: Path):
    """Run the network monitor, logging to the given file.

    Args:
        log_file: Path to write log output
    """
    ws_url = _find_descript_page()
    if not ws_url:
        print("Error: Cannot connect to Descript CDP. Is the app running?", file=sys.stderr)
        sys.exit(1)

    ws = websocket.create_connection(ws_url, timeout=30)

    # Enable network monitoring
    ws.send(json.dumps({"id": 1, "method": "Network.enable"}))

    # Track pending requests for matching responses
    pending = {}
    msg_id = 100  # Start high to avoid colliding with enable response

    def write_log(line: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {line}"
        with open(log_file, "a") as f:
            f.write(entry + "\n")

    write_log("--- Monitor started ---")

    # Handle graceful shutdown
    def shutdown(signum, frame):
        write_log("--- Monitor stopped ---")
        ws.close()
        if PID_FILE.exists():
            PID_FILE.unlink()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    ws.settimeout(1.0)

    while True:
        try:
            raw = ws.recv()
        except websocket.WebSocketTimeoutException:
            continue
        except (websocket.WebSocketConnectionClosedException, ConnectionError):
            write_log("--- Connection lost ---")
            break

        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue

        method = msg.get("method", "")

        if method == "Network.requestWillBeSent":
            params = msg.get("params", {})
            request_id = params.get("requestId")
            request = params.get("request", {})
            url = request.get("url", "")

            if _is_noise(url):
                continue

            pending[request_id] = {
                "method": request.get("method"),
                "url": url,
                "postData": request.get("postData"),
            }

            write_log(f">> {request.get('method')} {url}")

            post_data = request.get("postData")
            if post_data:
                try:
                    body = json.loads(post_data)
                    write_log(f"   Body: {json.dumps(body, indent=2)}")
                except (json.JSONDecodeError, TypeError):
                    write_log(f"   Body: {post_data[:300]}")

        elif method == "Network.responseReceived":
            params = msg.get("params", {})
            request_id = params.get("requestId")
            response = params.get("response", {})

            req = pending.get(request_id)
            if not req:
                continue

            status = response.get("status", 0)
            content_type = (response.get("headers", {}).get("content-type") or
                          response.get("headers", {}).get("Content-Type") or "unknown")

            write_log(f"<< {status} {req['url']}")
            write_log(f"   Content-Type: {content_type}")

            # Request body for JSON responses
            if "json" in content_type:
                msg_id += 1
                ws.send(json.dumps({
                    "id": msg_id,
                    "method": "Network.getResponseBody",
                    "params": {"requestId": request_id},
                }))

        elif msg.get("id") and msg.get("result", {}).get("body"):
            body = msg["result"]["body"]
            try:
                parsed = json.loads(body)
                pretty = json.dumps(parsed, indent=2)
                if len(pretty) > 3000:
                    write_log(f"   Response ({len(pretty)} chars, truncated):\n{pretty[:3000]}...")
                else:
                    write_log(f"   Response:\n{pretty}")
            except (json.JSONDecodeError, TypeError):
                if len(body) < 500:
                    write_log(f"   Response: {body}")
