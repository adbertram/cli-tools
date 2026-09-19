"""Garrul HTTP client.

One execution path: Garrul's own HTTP surface, authenticated with the session
cookie held by the CLI-owned browser profile. JSON endpoints are used wherever
Garrul has them; the admin pages that only render HTML are parsed by parsers.py.

Garrul enforces two different Origin gates, and this client satisfies both:

* /admin/*  POST, PATCH and DELETE must send Origin equal to the instance origin.
* /api/*    every request must send an Origin listed in ALLOWED_ORIGINS.
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import quote, urlparse

import requests
from bs4 import BeautifulSoup
from cli_tools_shared.exceptions import ClientError, CredentialError
from cli_tools_shared.http_session import BrowserAuthState, RequestsRetryPolicy, request_with_retry

from . import parsers
from .config import get_config

# Production names the cookie __Host-garrul_sess; an ENV=dev instance uses the bare name.
SESSION_COOKIE_NAMES = ("__Host-garrul_sess", "garrul_sess")
BULK_LIMIT = 100
DETAIL_WORKERS = 8
TIMEOUT_SECONDS = 30
NO_RETRY = RequestsRetryPolicy(max_retries=0)
IMPORT_SOURCES = ("disqus", "remark42", "comentario", "isso", "cusdis")
# Garrul serves 50 rows per page (see _pages). This bounds a --filter scan that Garrul
# cannot apply itself to 20,000 rows so an unmatched filter fails loudly instead of
# paging forever.
MAX_SCAN_PAGES = 400
AMBIGUOUS_MUTATION_NOTE = "The change may or may not have been applied; check before retrying."


CURSOR = re.compile(r"\d+\|[^|\s]+")


def segment(value: str) -> str:
    """Percent-encode one URL path segment so an id can never add path or query parts."""
    if not value:
        raise ClientError("An id or slug argument is empty.")
    if value in (".", ".."):
        raise ClientError(f"{value!r} is not a valid id or slug.")
    try:
        return quote(value, safe="")
    except UnicodeEncodeError as exc:
        raise ClientError("An id or slug argument is not valid UTF-8 text.") from exc


def check_cursor(before: Optional[str]) -> None:
    """Garrul silently serves page one for a cursor it cannot parse, so reject it here."""
    if before is not None and CURSOR.fullmatch(before) is None:
        raise ClientError(f"Invalid --before {before!r}. Expected '<milliseconds>|<id>' as printed by the previous page.")


def check_day(option: str, value: Optional[str]) -> None:
    """Garrul silently drops a date it cannot parse, which would return unfiltered rows."""
    if value is None:
        return
    try:
        valid = re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is not None and date.fromisoformat(value) is not None
    except ValueError:
        valid = False
    if not valid:
        raise ClientError(f"Invalid {option} {value!r}. Expected a real date as YYYY-MM-DD.")


class GarrulClient:
    """Client for one Garrul instance."""

    def __init__(self, config=None):
        self.config = config or get_config()
        self.base_url = self.config.instance_origin
        self.retry_policy = RequestsRetryPolicy()
        self._cookie: Optional[str] = None

    # ------------------------------------------------------------ transport

    def _session_cookie(self) -> str:
        """Read the session cookie that `garrul auth login` left in the CLI browser profile.

        BrowserAuthState.from_config reads live cookies through config.get_browser(),
        the BrowserAutomation subclass in browser.py. No page is driven.
        """
        if self._cookie is None:
            state = BrowserAuthState.from_config(self.config)
            host = urlparse(self.base_url).hostname
            found = [c for c in state.cookies_for_host(host, [host]) if c.name in SESSION_COOKIE_NAMES]
            if not found:
                raise CredentialError(
                    f"No Garrul session cookie for {host} in the CLI browser profile. Run 'garrul auth login'."
                )
            self._cookie = "; ".join(f"{cookie.name}={cookie.value}" for cookie in found)
        return self._cookie

    def _send(
        self,
        method: str,
        path: str,
        *,
        accept: str,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
        data: Optional[bytes] = None,
        headers: Optional[dict] = None,
    ) -> requests.Response:
        request_headers = {"Accept": accept, **(headers or {})}
        if path.startswith("/admin"):
            request_headers["Cookie"] = self._session_cookie()
            if method != "GET":
                request_headers["Origin"] = self.base_url
        elif path.startswith("/api/"):
            request_headers["Origin"] = self.config.embed_origin
        url = f"{self.base_url}{path}"

        def send() -> requests.Response:
            return requests.request(
                method,
                url,
                params=params,
                json=json_body,
                data=data,
                headers=request_headers,
                timeout=TIMEOUT_SECONDS,
                allow_redirects=False,
            )

        # Only reads are retried. A mutation that may already have been applied is never re-sent.
        policy = self.retry_policy if method == "GET" else NO_RETRY
        try:
            response = request_with_retry(send, policy)
        except requests.exceptions.RequestException as exc:
            message = f"{method} {url} failed: {exc}"
            if method != "GET":
                message += f" {AMBIGUOUS_MUTATION_NOTE}"
            raise ClientError(message) from exc
        if response.status_code == 401:
            raise CredentialError(f"Not signed in to {self.base_url}. Run 'garrul auth login'.")
        if response.status_code == 403 and self._error_detail(response) == "not_authorized":
            raise CredentialError(f"The signed-in Garrul account is not allowed to call {method} {path}.")
        if not response.ok or (300 <= response.status_code < 400 and not path.startswith("/c/")):
            message = f"{method} {path} returned HTTP {response.status_code}: {self._error_detail(response)}"
            if method != "GET":
                message += f" {AMBIGUOUS_MUTATION_NOTE}"
            raise ClientError(message)
        return response

    @staticmethod
    def _error_detail(response: requests.Response) -> str:
        content_type = response.headers.get("content-type", "")
        if "json" in content_type:
            try:
                body = response.json()
            except ValueError:
                return f"unreadable JSON body: {response.text[:200]!r}"
            if isinstance(body, dict) and "error" in body:
                extra = {key: value for key, value in body.items() if key != "error"}
                return f"{body['error']} {json.dumps(extra)}" if extra else str(body["error"])
            return json.dumps(body)
        if 300 <= response.status_code < 400:
            return f"unexpected redirect to {response.headers.get('location')!r}"
        if "html" in content_type:
            message = BeautifulSoup(response.text, "html.parser").select_one("body > p")
            if message is not None:
                return message.get_text(" ", strip=True)
        return response.text[:300]

    def _json(self, method: str, path: str, **kwargs) -> dict:
        response = self._send(method, path, accept="application/json", **kwargs)
        try:
            body = response.json()
        except ValueError as exc:
            raise ClientError(
                f"{method} {path} returned HTTP {response.status_code} with a body that is not JSON "
                f"(content-type {response.headers.get('content-type')!r}). "
                + (AMBIGUOUS_MUTATION_NOTE if method != "GET" else "")
            ) from exc
        if not isinstance(body, dict):
            raise ClientError(f"{method} {path} returned {type(body).__name__}, expected a JSON object.")
        return body

    def _html(self, path: str, params: Optional[dict] = None) -> str:
        return self._send("GET", path, accept="text/html", params=params).text

    def _pages(
        self,
        path: str,
        params: dict,
        parse: Callable[[str], dict],
        limit: int,
        before: Optional[str],
        *,
        post_filter: Optional[Callable[[list[dict]], list[dict]]] = None,
    ) -> dict:
        """Follow Garrul's `before` cursor until `limit` (matching) rows are collected.

        Garrul serves a fixed 50 rows per page and only hands out a cursor at a
        page boundary, so `next_before` is reported only when the returned rows
        end exactly on one.

        `post_filter`, when given, is the same client-side --filter the caller
        will still apply to the result (see `helpers.scan_filter`). Passing it
        makes `limit` bound the FILTERED row count instead of the raw fetch
        window: pagination keeps going until `limit` matches are collected or
        Garrul's own pages run out, instead of stopping once `limit` raw rows
        have been fetched and silently handing back fewer matches than exist.
        `post_filter` is None whenever there is nothing to filter, or every
        filter clause was already pushed to Garrul as a query parameter, so
        the page Garrul returned is already exact and the cheap raw-row-count
        stop below still applies.
        """
        if limit < 1:
            raise ClientError("--limit must be at least 1.")
        check_cursor(before)
        rows: list[dict] = []
        cursor = before
        pages_fetched = 0
        while True:
            page = parse(self._html(path, {**params, **({"before": cursor} if cursor else {})}))
            rows.extend(page["rows"])
            cursor = page["next_before"]
            pages_fetched += 1
            matched = post_filter(rows) if post_filter is not None else rows
            if cursor is None or len(matched) >= limit:
                break
            if post_filter is not None and pages_fetched >= MAX_SCAN_PAGES:
                raise ClientError(
                    f"--filter scanned {pages_fetched} pages ({len(rows)} rows) without collecting "
                    f"{limit} matching rows, and Garrul still has more. Narrow --filter or lower --limit."
                )
        if post_filter is not None:
            rows = post_filter(rows)
        truncated = len(rows) > limit
        return {"rows": rows[:limit], "next_before": None if truncated else cursor, "more": truncated or cursor is not None}

    # ------------------------------------------------------------- comments

    def list_comments(
        self,
        filters: dict,
        limit: int,
        before: Optional[str],
        post_filter: Optional[Callable[[list[dict]], list[dict]]] = None,
    ) -> dict:
        """List queue rows. Garrul applies every filter; rows lack parent_id and body_md."""
        check_day("--from", filters.get("from"))
        check_day("--to", filters.get("to"))
        return self._pages("/admin/queue", filters, parsers.parse_queue, limit, before, post_filter=post_filter)

    def add_comment_details(self, rows: list[dict]) -> list[dict]:
        """Add parent_id and body_md, which only the comment's own page carries. One request per row."""
        with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as pool:
            details = list(pool.map(lambda row: self.get_comment(row["id"]), rows))
        return [
            {**row, "parent_id": detail["parent_id"], "body_md": detail["body_md"]}
            for row, detail in zip(rows, details, strict=True)
        ]

    def get_comment(self, comment_id: str) -> dict:
        return parsers.parse_comment_detail(self._html(f"/admin/comments/{segment(comment_id)}"))

    def moderate_comment(self, comment_id: str, action: str, reason: Optional[str]) -> dict:
        body = {"action": action, **({"reason": reason} if reason is not None else {})}
        return self._json("POST", f"/admin/api/comments/{segment(comment_id)}", json_body=body)

    def bulk_moderate(self, ids: list[str], action: str) -> dict:
        return self._json("POST", "/admin/api/comments/bulk", json_body={"ids": ids, "action": action})

    def reply_to_comment(self, comment_id: str, body_md: str, notify: bool, saved_reply_id: Optional[str]) -> dict:
        body = {"body_md": body_md, "notify": notify}
        if saved_reply_id is not None:
            body["saved_reply_id"] = saved_reply_id
        return self._json("POST", f"/admin/api/comments/{segment(comment_id)}/reply", json_body=body)

    def preview_markdown(self, body_md: str) -> dict:
        return self._json("POST", "/admin/api/preview", json_body={"body_md": body_md})

    def resolve_reports(self, comment_id: str) -> dict:
        return self._json("POST", f"/admin/api/comments/{segment(comment_id)}/reports/resolve", json_body={})

    def get_thread(self, slug: str, sort: Optional[str], before: Optional[str]) -> dict:
        params = {"slug": slug}
        if sort is not None:
            params["sort"] = sort
        if before is not None:
            params["before"] = before
        return self._json("GET", "/api/v1/comments", params=params)

    def get_counts(self, slugs: list[str], include: list[str]) -> dict:
        params = {"slugs": ",".join(slugs)}
        if include:
            params["include"] = ",".join(include)
        return self._json("GET", "/api/v1/counts", params=params)

    def get_feed(self, slug: str) -> str:
        response = self._send("GET", f"/feed/{segment(slug)}", accept="application/atom+xml")
        content_type = response.headers.get("content-type", "")
        if "atom+xml" not in content_type:
            raise ClientError(f"GET /feed/{slug} returned {content_type!r}, not an Atom feed.")
        return response.text

    def resolve_permalink(self, comment_id: str) -> dict:
        response = self._send("GET", f"/c/{segment(comment_id)}", accept="text/html")
        if response.status_code != 302:
            raise ClientError(f"GET /c/{comment_id} returned HTTP {response.status_code}, expected a 302 redirect.")
        return {"id": comment_id, "url": response.headers["location"]}

    # ---------------------------------------------------------------- posts

    def set_post_closed(self, slug: str, closed: bool) -> dict:
        return self._json("POST", "/admin/api/posts/close", json_body={"slug": slug, "closed": closed})

    # ---------------------------------------------------------------- users

    def list_users(
        self,
        query: Optional[str],
        limit: int,
        before: Optional[str],
        post_filter: Optional[Callable[[list[dict]], list[dict]]] = None,
    ) -> dict:
        return self._pages(
            "/admin/users", {"q": query} if query else {}, parsers.parse_users, limit, before, post_filter=post_filter
        )

    def get_user(self, user_id: str, before: Optional[str]) -> dict:
        check_cursor(before)
        params = {"before": before} if before else None
        return parsers.parse_user_detail(self._html(f"/admin/users/{segment(user_id)}", params))

    def set_user_banned(self, user_id: str, banned: bool, reason: Optional[str], from_comment: Optional[str]) -> dict:
        body: dict = {"banned": banned}
        if reason is not None:
            body["reason"] = reason
        if from_comment is not None:
            body["from_comment"] = from_comment
        return self._json("POST", f"/admin/api/users/{segment(user_id)}", json_body=body)

    def revoke_user_sessions(self, user_id: str) -> dict:
        return self._json("POST", f"/admin/api/users/{segment(user_id)}/revoke-sessions", json_body={})

    def export_user(self, user_id: str) -> dict:
        return self._json("GET", f"/admin/api/users/{segment(user_id)}/export")

    def erase_user(self, user_id: str, redact_bodies: bool, reason: Optional[str]) -> dict:
        body: dict = {"confirm": "ERASE", "redact_bodies": redact_bodies}
        if reason is not None:
            body["reason"] = reason
        return self._json("POST", f"/admin/api/users/{segment(user_id)}/erase", json_body=body)

    def set_user_role(self, user_id: str, role: str, reason: Optional[str]) -> dict:
        body = {"role": role, **({"reason": reason} if reason is not None else {})}
        return self._json("POST", f"/admin/api/users/{segment(user_id)}/role", json_body=body)

    # -------------------------------------------------------- saved replies

    def list_saved_replies(self) -> list[dict]:
        body = self._json("GET", "/admin/api/saved-replies")
        if not isinstance(body.get("replies"), list):
            raise ClientError("GET /admin/api/saved-replies returned no 'replies' list.")
        return body["replies"]

    def get_saved_reply(self, reply_id: str) -> dict:
        for reply in self.list_saved_replies():
            if reply["id"] == reply_id:
                return reply
        raise ClientError(f"Saved reply {reply_id} does not exist or is not visible to this account.")

    def create_saved_reply(self, fields: dict) -> dict:
        return self._json("POST", "/admin/api/saved-replies", json_body=fields)

    def update_saved_reply(self, reply_id: str, fields: dict) -> dict:
        return self._json("PATCH", f"/admin/api/saved-replies/{segment(reply_id)}", json_body=fields)

    def delete_saved_reply(self, reply_id: str) -> dict:
        return self._json("DELETE", f"/admin/api/saved-replies/{segment(reply_id)}")

    # ---------------------------------------------------------------- notes

    def create_note(self, target_kind: str, target_id: str, body: str) -> dict:
        payload = {"target_kind": target_kind, "target_id": target_id, "body": body}
        return self._json("POST", "/admin/api/notes", json_body=payload)

    def delete_note(self, note_id: str) -> dict:
        return self._json("DELETE", f"/admin/api/notes/{segment(note_id)}")

    # ------------------------------------------------------------- webhooks

    def list_webhooks(self) -> list[dict]:
        return parsers.parse_webhooks(self._html("/admin/webhooks"))

    def get_webhook(self, webhook_id: str) -> dict:
        return parsers.parse_webhook_detail(self._html(f"/admin/webhooks/{segment(webhook_id)}"), webhook_id)

    def create_webhook(self, fields: dict) -> dict:
        return self._json("POST", "/admin/api/webhooks", json_body=fields)

    def update_webhook(self, webhook_id: str, fields: dict) -> dict:
        return self._json("PATCH", f"/admin/api/webhooks/{segment(webhook_id)}", json_body=fields)

    def delete_webhook(self, webhook_id: str) -> dict:
        return self._json("DELETE", f"/admin/api/webhooks/{segment(webhook_id)}")

    # -------------------------------------------------------- subscriptions

    def list_subscriptions(
        self,
        filters: dict,
        limit: int,
        before: Optional[str],
        post_filter: Optional[Callable[[list[dict]], list[dict]]] = None,
    ) -> dict:
        return self._pages(
            "/admin/subscriptions", filters, parsers.parse_subscriptions, limit, before, post_filter=post_filter
        )

    def act_on_subscription(self, subscription_id: str, action: str, reason: Optional[str]) -> dict:
        body = {"action": action, **({"reason": reason} if reason is not None else {})}
        return self._json("POST", f"/admin/api/subscriptions/{segment(subscription_id)}", json_body=body)

    # ---------------------------------------------------------------- audit

    def list_audit(
        self,
        filters: dict,
        limit: int,
        before: Optional[str],
        post_filter: Optional[Callable[[list[dict]], list[dict]]] = None,
    ) -> dict:
        check_day("--from", filters.get("from"))
        check_day("--to", filters.get("to"))

        def parse(html: str) -> dict:
            page = parsers.parse_audit(html)
            # Garrul drops an action or target kind it does not know and returns every row.
            for name, applied in page["applied"].items():
                if filters.get(name, "") != applied:
                    raise ClientError(f"Garrul ignored {name}={filters[name]!r}: it is not a value this instance knows.")
            return page

        return self._pages("/admin/audit", filters, parse, limit, before, post_filter=post_filter)

    def get_operator_status(self) -> dict:
        return parsers.parse_operator(self._html("/admin/operator"))

    # ------------------------------------------------------------- settings

    def list_settings(self) -> list[dict]:
        return parsers.parse_settings(self._html("/admin/settings"))

    def update_settings(self, payload: dict) -> dict:
        """Change settings, refusing anything Garrul would silently drop or alter.

        Garrul ignores a key it does not know (or one sent under the wrong group)
        and clamps an out-of-range number, answering ok either way.
        """
        groups = {row["key"]: row["group"] for row in self.list_settings()}
        for group, values in payload.items():
            for key in values:
                if key not in groups:
                    raise ClientError(f"Garrul has no setting named {key!r}. Nothing was changed.")
                if groups[key] != group:
                    raise ClientError(f"{key} is a {groups[key]} setting, not {group}. Nothing was changed.")
        stored = self._json("POST", "/admin/settings", json_body=payload)
        for group, values in payload.items():
            if group not in stored:
                raise ClientError(f"Garrul's response named no {group!r} group. {AMBIGUOUS_MUTATION_NOTE}")
            for key, value in values.items():
                if key not in stored[group]:
                    raise ClientError(f"Garrul's response had no {key!r} in the {group!r} group. {AMBIGUOUS_MUTATION_NOTE}")
                wanted = value.strip() if group == "texts" else value
                if stored[group][key] != wanted:
                    raise ClientError(f"Garrul stored {stored[group][key]!r} for {key}, not {value!r}: the value is outside its allowed range.")
        return stored

    def reset_settings(self) -> dict:
        return self._json("POST", "/admin/settings", json_body={"reset": True})

    # ------------------------------------------------------------- telegram

    def get_telegram(self) -> dict:
        return parsers.parse_telegram(self._html("/admin/telegram"))

    def create_telegram_link_code(self) -> dict:
        return self._json("POST", "/admin/api/telegram/link", json_body={})

    def delete_telegram_link(self) -> dict:
        return self._json("DELETE", "/admin/api/telegram/link")

    def set_telegram_digest(self, digest: bool) -> dict:
        return self._json("POST", "/admin/api/telegram/digest", json_body={"digest": digest})

    # ------------------------------------------------------------------ ops

    def rerender(self, batch: int, cursor: Optional[dict]) -> dict:
        return self._json("POST", "/admin/api/ops/rerender", json_body={"batch": batch, "cursor": cursor})

    def sweep_ip_retention(self) -> dict:
        return self._json("POST", "/admin/api/ops/ip-retention", json_body={})

    def sweep_audit_retention(self) -> dict:
        return self._json("POST", "/admin/api/ops/audit-retention", json_body={})

    def import_comments(self, source: str, file: Path, headers: dict) -> dict:
        return self._json("POST", f"/admin/api/ops/import-{source}", data=file.read_bytes(), headers=headers)

    def seed_demo(self) -> dict:
        return self._json("POST", "/admin/api/ops/seed-demo", json_body={})

    # --------------------------------------------------- instance read-outs

    def get_health(self) -> dict:
        return self._json("GET", "/api/v1/health")

    def get_public_config(self) -> dict:
        return self._json("GET", "/api/v1/config")

    def get_me(self) -> dict:
        return self._json("GET", "/api/v1/auth/me", headers={"Cookie": self._session_cookie()})

    def get_statistics(self) -> dict:
        return parsers.parse_dashboard(self._html("/admin"))

    def get_status(self) -> dict:
        return {"base_url": self.base_url, **self.get_health(), **parsers.parse_about(self._html("/admin/about"))}


_client: Optional[GarrulClient] = None


def get_client() -> GarrulClient:
    """Get or create the global Garrul client instance."""
    global _client
    if _client is None:
        _client = GarrulClient()
    return _client
