"""TikTok transcript downloader using yt-dlp, plus the tiktok.com web client
(favorites, own posted videos, delete) described above TikTokWebClient."""
import subprocess
from contextlib import contextmanager
import time
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

from cli_tools_shared.http_session import (
    DEFAULT_REQUESTS_BASE_DELAY,
    DEFAULT_REQUESTS_JITTER,
    DEFAULT_REQUESTS_MAX_DELAY,
    DEFAULT_REQUESTS_MAX_RETRIES,
    DEFAULT_REQUESTS_RETRYABLE_STATUS_CODES,
    RequestsRetryPolicy,
)

from .config import get_config


class ClientError(Exception):
    """Sanitized SDK failure; optional provider cooldown without message parsing."""
    def __init__(self, message, *, code=None, category="unknown", status=None, retry_after_seconds=None):
        super().__init__(message)
        self.code = code
        self.category = category
        self.status = status
        self.retry_after_seconds = retry_after_seconds
        self.retry_after = retry_after_seconds


class TiktokClient:
    """Client for downloading TikTok transcripts using yt-dlp."""

    def __init__(self):
        """Initialize TikTok client."""
        self.ytdlp_path = self._find_ytdlp()

    def _find_ytdlp(self) -> str:
        """Find yt-dlp executable path."""
        result = subprocess.run(
            ["which", "yt-dlp"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise ClientError(
                "yt-dlp not found. Install it with: brew install yt-dlp"
            )
        return result.stdout.strip()

    def get_video_metadata(self, url: str) -> Dict:
        """Get video metadata using yt-dlp."""
        cmd = [
            self.ytdlp_path,
            "--dump-json",
            "--skip-download",
            url,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise ClientError(f"Failed to get video metadata: {result.stderr}")

        return json.loads(result.stdout)

    def _get_available_sub_lang(self, url: str, preferred_lang: str) -> str:
        """Discover available subtitle language matching the preferred language.

        TikTok uses language codes like 'eng-US' instead of 'en'.
        This method finds the best match from available subtitles.
        """
        cmd = [
            self.ytdlp_path,
            "--list-subs",
            "--skip-download",
            url,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        output = result.stdout + result.stderr

        # Map short codes to yt-dlp language prefixes
        lang_map = {
            "en": "eng",
            "es": "spa",
            "fr": "fra",
            "de": "deu",
            "ja": "jpn",
            "ko": "kor",
            "zh": "zho",
            "pt": "por",
            "it": "ita",
            "ru": "rus",
        }

        prefix = lang_map.get(preferred_lang, preferred_lang)

        # Parse available languages from --list-subs output
        for line in output.split('\n'):
            line = line.strip()
            # Lines like "eng-US   vtt"
            if line and not line.startswith('[') and not line.startswith('WARNING') and not line.startswith('Language'):
                available_lang = line.split()[0]
                # Match by prefix (eng matches eng-US)
                if available_lang.startswith(prefix) or available_lang == preferred_lang:
                    return available_lang

        # No match found — return original and let yt-dlp handle it
        return preferred_lang

    def download_transcript(
        self,
        url: str,
        output_dir: str = ".",
        format: str = "srt",
        lang: str = "en",
        auto_sub: bool = True,
        manual_sub: bool = False,
    ) -> Dict:
        """Download transcript for a TikTok video."""
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Get metadata first
        metadata = self.get_video_metadata(url)

        # Discover the actual subtitle language code available
        actual_lang = self._get_available_sub_lang(url, lang)

        # Build yt-dlp command — TikTok subs use --write-sub (not --write-auto-sub)
        cmd = [
            self.ytdlp_path,
            "--skip-download",
            "--write-sub",
            "--sub-lang", actual_lang,
            "--convert-subs", format,
            "-o", f"{output_dir}/%(title)s.%(ext)s",
            url,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise ClientError(f"Failed to download transcript: {result.stderr}")

        # Check if subtitles were actually found
        if "There are no subtitles" in result.stderr or "There aren't any subtitles" in result.stderr:
            raise ClientError(f"No subtitles available for language '{lang}' (tried '{actual_lang}')")

        # Find the downloaded file — try both the actual lang code and the requested one
        output_files = list(Path(output_dir).glob(f"*.{actual_lang}.{format}"))
        if not output_files:
            output_files = list(Path(output_dir).glob(f"*.{lang}.{format}"))

        actual_file = None
        if output_files:
            output_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
            actual_file = output_files[0]
        else:
            title = metadata.get("title", "unknown")
            safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
            actual_file = Path(output_dir) / f"{safe_title}.{actual_lang}.{format}"

        return {
            "url": url,
            "title": metadata.get("title", "Unknown"),
            "duration": metadata.get("duration", 0),
            "file_path": str(actual_file),
            "file_size": actual_file.stat().st_size if actual_file.exists() else 0,
            "format": format,
            "language": actual_lang,
        }

    def download_transcripts(
        self,
        urls: List[str],
        output_dir: str = ".",
        format: str = "srt",
        lang: str = "en",
        auto_sub: bool = True,
        manual_sub: bool = False,
    ) -> List[Dict]:
        """Download transcripts for multiple TikTok videos."""
        results = []
        for url in urls:
            result = self.download_transcript(
                url=url,
                output_dir=output_dir,
                format=format,
                lang=lang,
                auto_sub=auto_sub,
                manual_sub=manual_sub,
            )
            results.append(result)
        return results


# Module-level client instance - singleton pattern
_client: Optional[TiktokClient] = None


def get_client() -> TiktokClient:
    """Get or create the global TikTok client instance."""
    global _client
    if _client is None:
        _client = TiktokClient()
    return _client


# ---------------------------------------------------------------------------
# Favorites (saved/bookmarked TikTok videos)
# ---------------------------------------------------------------------------
# Why an in-page fetch instead of a standalone HTTP client
# ----------------------------------------------------------
# TikTok has no public API for a user's saved videos. Its web app posts every
# "Favorites" (bookmark) query to ``GET /api/user/collect/item_list/`` on
# tiktok.com's own domain. That endpoint is always private — bookmarked videos
# are never exposed to other viewers, unlike a profile's public "Liked" tab
# (``/api/favorite/item_list/``) — so it only ever returns data for the
# caller's own logged-in session.
#
# Every request TikTok's web app makes to ``/api/*`` is auto-signed
# client-side by its own ``webmssdk`` script, which transparently intercepts
# the page's ``window.fetch`` and appends ``msToken``, ``X-Bogus``, and
# ``X-Gnarly``. This was confirmed live during CLI creation: a bare
# unauthenticated ``fetch('/api/user/collect/item_list/?aid=1988&count=5&cursor=0')``
# run via ``page.evaluate()`` on a real tiktok.com page came back fully signed
# (network capture showed ``msToken``/``X-Bogus``/``X-Gnarly`` appended
# automatically) with a clean ``HTTP 200`` and empty body — proving the route
# and signing both work without any client-side signature code of our own,
# and that the empty result is the server's private-endpoint gate, not a
# signing failure. ``TikTokWebClient`` therefore runs the exact same fetch
# INSIDE the live tiktok.com page through ``page.evaluate()`` (the same
# in-page-fetch pattern this repo already uses for OfferUp), carrying the
# real browser's cookies via ``credentials: 'include'``, so once
# ``tiktok auth login --credential-type browser_session`` has a real
# logged-in session, the same call returns Adam's own saved videos.
#
# Item field shape
# -----------------
# ``itemList`` entries are TikTok's standard "aweme" video object, the same
# shape yt-dlp's own ``TikTokBaseIE._parse_aweme_video_web`` parses for every
# other ``*/item_list/`` endpoint (creator, collection): ``id``, ``desc``
# (caption), ``createTime`` (post time), and ``author.uniqueId``. Those fields
# are used here with confidence. TikTok does not document a distinct
# "favorited/bookmarked-at" timestamp on this endpoint, and no authenticated
# sample response was available to confirm one; ``saved_at`` is populated only
# if the raw item happens to carry a ``collectTime`` key (TikTok's own naming
# convention, mirroring ``createTime``), and is otherwise ``None`` rather than
# guessed.
#
# Posted videos and delete
# ------------------------
# The Content Posting API cannot list or delete the caller's videos: Display
# API ``video.list`` returns only public posts, a SELF_ONLY Direct Post never
# gets a ``publicaly_available_post_id``, and no TikTok scope grants delete.
# TikTok's own web app does both through the same signed in-page ``/api/*``
# surface used for favorites, so ``TikTokWebClient`` reuses it:
#
# - Own posts: ``GET /api/post/item_list/?secUid=...`` — the call TikTok's
#   profile page makes (``userPostList`` in its webapp bundle). ``secUid``
#   comes from the profile page's ``webapp.user-detail`` rehydration data
#   (``userInfo.user.secUid``), confirmed live.
# - Delete: ``POST /api/aweme/delete/?aweme_id=...`` with ``tt_csrf_token``
#   in the query and the ``tt-csrf-token`` header, both set to
#   ``webapp.app-context.csrfToken`` — exactly how the webapp's
#   ``postVideoDelete`` issues it. The endpoint answers
#   ``{"status_code": 0}`` on success and, confirmed live,
#   ``{"status_code": 8, "status_msg": "Login expired"}`` without a session.

FAVORITES_PATH = "/api/user/collect/item_list/?aid=1988"
POSTS_PATH = "/api/post/item_list/?aid=1988"
DELETE_PATH = "/api/aweme/delete/?aid=1988"
ACCOUNT_INFO_PATH = "/passport/web/account/info/?aid=1988"
ACCOUNT_INFO_ORIGIN = "https://www.tiktok.com"

# Page size TikTok's own web app requests, and the paging ceiling this client
# walks before giving up on reaching --limit.
ITEM_PAGE_SIZE = 30
ITEM_MAX_PAGES = 50

_LOGIN_HINT = (
    "Run 'tiktok auth login --credential-type browser_session' "
    "(or '--force' to refresh a stale session) and retry."
)

_WEB_FETCH_JS = """async (opts) => {
    const init = { method: opts.method, credentials: 'include', headers: {} };
    let path = opts.path;
    if (opts.csrf) {
        const el = document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__');
        const scope = el ? (JSON.parse(el.textContent).__DEFAULT_SCOPE__ || {}) : {};
        const token = (scope['webapp.app-context'] || {}).csrfToken;
        if (!token) {
            return { status: 0, statusText: 'page has no webapp.app-context csrfToken', body: '' };
        }
        path += '&tt_csrf_token=' + encodeURIComponent(token);
        init.headers['tt-csrf-token'] = token;
    }
    const resp = await fetch(path, init);
    return {
        status: resp.status,
        statusText: resp.statusText,
        retryAfter: resp.headers.get('retry-after'),
        body: await resp.text(),
    };
}"""

_SEC_UID_JS = """() => {
    const el = document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__');
    if (!el) return null;
    const detail = (JSON.parse(el.textContent).__DEFAULT_SCOPE__ || {})['webapp.user-detail'] || {};
    const user = (detail.userInfo || {}).user;
    if (detail.statusCode === 10221 && !user) return { error: 'account_not_found' };
    return (user || {}).secUid || null;
}"""


def _aweme_record(raw: dict) -> Dict:
    video_id = str(raw.get("id") or "")
    author = raw.get("author") or raw.get("authorInfo") or {}
    author_id = author.get("uniqueId") or "_"
    return {
        "id": video_id,
        "url": f"https://www.tiktok.com/@{author_id}/video/{video_id}",
        "caption": raw.get("desc"),
        "author": author.get("uniqueId"),
    }


def normalize_favorite(raw: dict) -> Dict:
    """Normalize one TikTok aweme item into the favorites output contract."""
    return {**_aweme_record(raw), "saved_at": raw.get("collectTime")}


def normalize_posted_video(raw: dict) -> Dict:
    """Normalize one TikTok aweme item into the videos list output contract."""
    return {**_aweme_record(raw), "created_at": raw.get("createTime")}


def favorite_id_to_url(item: str) -> str:
    """Resolve a bare video id or a full TikTok URL to a webpage URL.

    Mirrors the yt-dlp ``TikTokBaseIE._create_url`` convention: the ``@_``
    placeholder author segment is a real, working TikTok URL that redirects
    to the correct canonical page regardless of the actual author handle
    (used by yt-dlp itself whenever the author is not already known).
    """
    value = (item or "").strip()
    if not value:
        raise ClientError("A video id or tiktok.com video URL is required.")
    if "://" in value:
        return value
    return f"https://www.tiktok.com/@_/video/{value}"


def favorite_from_video_metadata(metadata: dict) -> Dict:
    """Normalize yt-dlp ``--dump-json`` output into the favorites output
    contract, for looking up one saved video's details by id/URL.

    Field names (``id``, ``description``, ``uploader``, ``webpage_url``)
    were confirmed live against a real TikTok video during CLI creation.
    ``saved_at`` is always ``None`` here: a standalone id/URL lookup carries
    no bookmark-list context, unlike ``list_favorites()``.
    """
    return {
        "id": str(metadata.get("id") or ""),
        "url": metadata.get("webpage_url") or metadata.get("original_url"),
        "caption": metadata.get("description"),
        "author": metadata.get("uploader"),
        "saved_at": None,
    }


def normalize_account_identity(payload: dict) -> Dict:
    """Whitelist observed passport identity fields; reject inconsistent IDs."""
    malformed = "TikTok account identity response is malformed; identity was not verified."
    if not isinstance(payload, dict):
        raise ClientError(malformed)
    data = payload.get("data")
    if payload.get("message") == "error":
        raise ClientError("TikTok account session is not authenticated. " + _LOGIN_HINT,
                          code="account_not_authenticated", category="auth")
    if payload.get("message") != "success" or not isinstance(data, dict):
        raise ClientError(malformed)
    if "error_code" in data:
        if type(data["error_code"]) is not int:
            raise ClientError(malformed)
        if data["error_code"] != 0:
            raise ClientError("TikTok account session is not authenticated. " + _LOGIN_HINT,
                          code="account_not_authenticated", category="auth")
    account_id = data.get("user_id_str")
    numeric_id = data.get("user_id")
    username = data.get("username")
    if (
        not isinstance(account_id, str)
        or not re.fullmatch(r"[1-9][0-9]{0,63}", account_id)
        or type(numeric_id) is not int
        or str(numeric_id) != account_id
        or not isinstance(username, str)
        or not re.fullmatch(r"[A-Za-z0-9_.]{1,256}", username)
        or not any(char.isalnum() or char == "_" for char in username)
    ):
        raise ClientError(malformed)
    return {"account_id": account_id, "username": username}


class TikTokWebClient:
    """Drives a live tiktok.com page and calls its own signed web API."""

    def __init__(
        self,
        config=None,
        max_retries: int = DEFAULT_REQUESTS_MAX_RETRIES,
        base_delay: float = DEFAULT_REQUESTS_BASE_DELAY,
        max_delay: float = DEFAULT_REQUESTS_MAX_DELAY,
        jitter: float = DEFAULT_REQUESTS_JITTER,
        browser=None,
    ):
        self.config = config or get_config()
        self._retry_policy = RequestsRetryPolicy(
            max_retries=max_retries,
            base_delay=base_delay,
            max_delay=max_delay,
            jitter=jitter,
            retryable_status_codes=DEFAULT_REQUESTS_RETRYABLE_STATUS_CODES,
        )
        self._browser = browser

    def _get_browser(self):
        if self._browser is None:
            self._browser = self.config.get_browser()
        return self._browser

    def close(self):
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    def _page(self, path: str = "/"):
        return self._get_browser().get_page(f"{self.config.base_url.rstrip('/')}{path}")

    def _retry_after_seconds(self, raw: Optional[str]) -> Optional[float]:
        from .studio import retry_after_seconds
        return retry_after_seconds(raw)

    def _fetch_json(self, page, path: str, *, method: str = "GET", csrf: bool = False) -> dict:
        """Run one in-page request with retry and return its JSON payload."""
        policy = self._retry_policy
        last_exception: Optional[Exception] = None
        last_status = None

        for attempt in range(policy.max_retries + 1):
            try:
                result = page.evaluate(
                    _WEB_FETCH_JS, {"path": path, "method": method, "csrf": csrf}
                )
            except Exception as exc:  # browser-harness / network failure
                last_exception = exc
                if attempt < policy.max_retries:
                    time.sleep(policy.calculate_delay(attempt))
                    continue
                raise ClientError(
                    f"TikTok web request {path} failed after {attempt + 1} attempts: {exc}",
                    code="tiktok_transport_failed", category="transient", status=0
                ) from exc

            status = int(result.get("status") or 0)
            last_status = status
            body = str(result.get("body") or "")
            provider_delay = self._retry_after_seconds(result.get("retryAfter"))
            if (status in policy.retryable_status_codes and attempt < policy.max_retries
                    and (provider_delay is None or provider_delay <= policy.max_delay)):
                time.sleep(
                    policy.calculate_delay(
                        attempt, provider_delay
                    )
                )
                continue
            if status != 200:
                raise ClientError(
                    f"TikTok web request {path} HTTP {status} "
                    f"{result.get('statusText', '')}: {body[:300]}",
                    code=f"tiktok_http_{status}", category="rate_limit" if status == 429 else "auth" if status in (401,403) else "transient" if status >= 500 or status == 0 else "upstream",
                    status=status, retry_after_seconds=provider_delay
                )
            if not body:
                raise ClientError(
                    f"TikTok web request {path} returned an empty response. "
                    "This endpoint only returns data for the logged-in account. "
                    + _LOGIN_HINT
                )
            try:
                payload = json.loads(body)
            except (ValueError, TypeError) as exc:
                raise ClientError(
                    f"TikTok web request {path} returned a non-JSON body: {exc}"
                ) from exc
            status_code = payload.get("statusCode", payload.get("status_code"))
            if status_code not in (0, None):
                raise ClientError(
                    f"TikTok web request {path} returned status code {status_code}: "
                    f"{payload.get('statusMsg') or payload.get('status_msg')}"
                )
            return payload

        raise ClientError(
            f"TikTok web request {path} failed after retries "
            f"(last status={last_status}): {last_exception}"
        )

    @contextmanager
    def _studio_session(self, username, expected_account_id):
        from uuid import uuid4
        from .studio import (CAPTURE_JS, READY_JS, CLEANUP_JS, STUDIO_CONTENT_URL,
                             STUDIO_PAGE_SIZE, STUDIO_ITEMS_PATH, StudioReader, StudioContractError)
        identity = self.get_account(expected_username=username, expected_account_id=expected_account_id)
        page = self._get_browser().get_page(STUDIO_CONTENT_URL)
        key = "__tiktok_cli_read_" + uuid4().hex
        try:
            control = page.get_by_role("button", name="Views", exact=True)
            for _ in range(60):
                if control.count() == 1:
                    break
                page.wait_for_timeout(250)
            else:
                raise StudioContractError("TikTok Studio content control was unavailable; result is inconclusive.")
            from .studio_inventory import canonical
            actor = {field: identity[field] for field in ("account_id", "username", "profile")}
            if len(canonical(actor)) > 4096:
                raise StudioContractError("Studio inventory actor binding exceeds its 4 KiB limit.")
            page.evaluate(CAPTURE_JS, {"key": key, "path": STUDIO_ITEMS_PATH, "page_size": STUDIO_PAGE_SIZE})
            control.click()
            for _ in range(60):
                if page.evaluate(READY_JS, key):
                    break
                page.wait_for_timeout(250)
            else:
                raise StudioContractError("TikTok Studio native content read was unavailable; result is inconclusive.")
            yield StudioReader(page, key, identity)
            checked = self.get_account(expected_username=identity["username"], expected_account_id=identity["account_id"])
            if any(checked.get(field) != identity[field] for field in ("account_id", "username", "profile")):
                raise StudioContractError("TikTok Studio owner or profile changed during read; result is inconclusive.")
        except ClientError:
            raise
        except StudioContractError as error:
            raise ClientError(str(error), code=error.code, category=error.category, status=error.status,
                              retry_after_seconds=error.retry_after_seconds) from None
        except Exception:
            raise ClientError("TikTok Studio content read failed; result is inconclusive.",
                              code="studio_transport_failed", category="transient") from None
        finally:
            try:
                page.evaluate(CLEANUP_JS, key)
            except Exception:
                pass

    def _studio_read(self, username: str, *, limit: int = 100, video_id: Optional[str] = None, expected_account_id: Optional[str] = None) -> List[Dict]:
        """Read only observed Studio content for the verified session owner."""
        from .studio import MAX_STUDIO_ITEMS, MAX_STUDIO_PAGES, StudioContractError
        if type(limit) is not int or not 1 <= limit <= MAX_STUDIO_ITEMS:
            raise ClientError(f"Studio --limit must be between 1 and {MAX_STUDIO_ITEMS}.")
        if video_id is not None and not re.fullmatch(r"[1-9][0-9]{0,63}", video_id):
            raise ClientError("Studio video ID must be a positive numeric string.")
        missing = False
        with self._studio_session(username, expected_account_id) as reader:
            records, seen, cursor = [], set(), 0
            for _ in range(MAX_STUDIO_PAGES):
                items, more, next_cursor = reader.read_page(cursor)
                for record in items:
                    if record["id"] in seen:
                        raise StudioContractError("TikTok Studio repeated a video; pagination is inconclusive.")
                    seen.add(record["id"])
                    records.append(record)
                    if video_id == record["id"]:
                        return [record]
                    if video_id is None and len(records) >= limit:
                        return records[:limit]
                if not more:
                    if video_id is not None:
                        missing = True
                        break
                    return records
                cursor = next_cursor
                if len(records) >= limit:
                    break
            if not missing:
                raise ClientError("studio_lookup_inconclusive: bounded content scan did not establish absence.")
        raise ClientError("studio_video_not_found: the complete observed own-account feed did not contain that ID.")

    def get_studio_videos(self, username: str, video_ids: List[str], *, expected_account_id: str,
                          continuation: Optional[Dict] = None, max_pages: int = 20) -> Dict:
        """Batch exact IDs through one bounded own-account Studio scan.

        Caller retains prior records and the public continuation. Unresolved IDs
        remain unknown, including when the provider ends this observation pass.
        """
        from .studio_inventory import validate_request, batch_read
        from .studio import StudioContractError
        try:
            request = validate_request(video_ids, continuation, max_pages, expected_account_id)
            if request["continuation"] is not None and request["continuation"]["actor"]["username"] != username:
                raise StudioContractError("Studio inventory continuation username changed.")
        except StudioContractError as error:
            raise ClientError(str(error), code=error.code, category="invalid_request", status=error.status,
                              retry_after_seconds=error.retry_after_seconds) from None
        with self._studio_session(username, expected_account_id) as reader:
            return batch_read(reader, request)

    def list_studio_videos(self, username: str, limit: int = 100, expected_account_id: Optional[str] = None) -> List[Dict]:
        return self._studio_read(username, limit=limit, expected_account_id=expected_account_id)

    def get_studio_video(self, username: str, video_id: str, expected_account_id: Optional[str] = None) -> Dict:
        from .studio import MAX_STUDIO_ITEMS
        return self._studio_read(username, limit=MAX_STUDIO_ITEMS, video_id=video_id, expected_account_id=expected_account_id)[0]

    def _list_items(self, page, path: str, normalize, limit: int) -> List[Dict]:
        """Walk an ``itemList``/``hasMore``/``cursor`` feed up to ``limit`` items."""
        items: List[Dict] = []
        seen = set()
        cursor = 0
        pages = 0

        while len(items) < limit and pages < ITEM_MAX_PAGES:
            page_size = min(ITEM_PAGE_SIZE, max(limit - len(items), 1))
            payload = self._fetch_json(page, f"{path}&count={page_size}&cursor={cursor}")
            for item in payload.get("itemList") or []:
                video_id = item.get("id")
                if not video_id or video_id in seen:
                    continue
                seen.add(video_id)
                items.append(normalize(item))
            pages += 1
            if not payload.get("hasMore"):
                break
            next_cursor = payload.get("cursor")
            if next_cursor is None or str(next_cursor) == str(cursor):
                break
            cursor = next_cursor

        return items[:limit]

    def get_account(self, expected_username: Optional[str] = None, expected_account_id: Optional[str] = None) -> Dict:
        """Read verified current identity without exporting passport secrets.

        The shared in-page fetch returns response TEXT, parsed by Python, so
        64-bit user_id values never pass through a JavaScript Number.
        """
        if expected_username is not None:
            expected_username = expected_username.strip().removeprefix("@")
            if not re.fullmatch(r"[A-Za-z0-9_.]{1,256}", expected_username):
                raise ClientError("--expected-username must be a nonempty TikTok handle.")
        if expected_account_id is not None and not re.fullmatch(r"[1-9][0-9]{0,63}", expected_account_id):
            raise ClientError("--expected-account-id must be a positive numeric ID.")
        try:
            page = self._get_browser().get_page(ACCOUNT_INFO_ORIGIN + "/")
            payload = self._fetch_json(page, ACCOUNT_INFO_PATH)
        except ClientError as error:
            # Keep only structured provider metadata; never passport bodies.
            raise ClientError("TikTok account identity request failed; identity was not verified.",
                              code=error.code, category=error.category, status=error.status,
                              retry_after_seconds=error.retry_after_seconds) from None
        except Exception:
            raise ClientError("TikTok account identity request failed; identity was not verified.",
                              code="account_transport_failed", category="transient") from None
        identity = normalize_account_identity(payload)
        if expected_username is not None and identity["username"].casefold() != expected_username.casefold():
            raise ClientError("TikTok account identity mismatch: username does not match --expected-username.")
        if expected_account_id is not None and identity["account_id"] != expected_account_id:
            raise ClientError("TikTok account identity mismatch: account ID does not match --expected-account-id.")
        return {
            **identity,
            "profile": self.config.get_active_profile_name(),
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "provenance": ACCOUNT_INFO_ORIGIN + ACCOUNT_INFO_PATH,
        }

    def list_favorites(self, limit: int = 100) -> List[Dict]:
        """List the logged-in account's saved (favorited) TikTok videos."""
        return self._list_items(self._page(), FAVORITES_PATH, normalize_favorite, limit)

    def list_posted_videos(self, username: str, limit: int = 100) -> List[Dict]:
        """List a profile's posted videos; private posts appear only for the
        logged-in owner's own profile."""
        handle = (username or "").strip().lstrip("@")
        if not handle:
            raise ClientError("A TikTok username is required.")
        page = self._page(f"/@{quote(handle)}")
        sec_uid = page.evaluate(_SEC_UID_JS)
        if isinstance(sec_uid, dict) and sec_uid.get("error") == "account_not_found":
            raise ClientError(f"account_not_found: TikTok profile @{handle} was not found.")
        if not sec_uid:
            raise ClientError(
                f"TikTok profile page for @{handle} did not expose "
                "webapp.user-detail userInfo.user.secUid."
            )
        path = f"{POSTS_PATH}&secUid={quote(sec_uid, safe='')}"
        return self._list_items(page, path, normalize_posted_video, limit)

    def get_posted_video(self, username: str, video_id: str) -> Dict:
        """Find one of a profile's posted videos by id."""
        for video in self.list_posted_videos(username, limit=ITEM_PAGE_SIZE * ITEM_MAX_PAGES):
            if video["id"] == str(video_id):
                return video
        raise ClientError(f"Video {video_id} not found in @{username.lstrip('@')}'s posts.")

    def delete_video(self, video_id: str) -> Dict:
        """Delete one of the logged-in account's videos."""
        value = str(video_id or "").strip()
        if not value.isdigit():
            raise ClientError(f"TikTok video id must be numeric, got {video_id!r}.")
        self._fetch_json(
            self._page(),
            f"{DELETE_PATH}&aweme_id={value}",
            method="POST",
            csrf=True,
        )
        return {"video_id": value, "deleted": True}


# Module-level web client instance - singleton pattern
_web_client: Optional[TikTokWebClient] = None


def get_web_client() -> TikTokWebClient:
    """Get or create the global TikTok web client instance."""
    global _web_client
    if _web_client is None:
        _web_client = TikTokWebClient()
    return _web_client
