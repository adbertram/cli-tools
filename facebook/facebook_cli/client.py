"""Facebook client using BrowserAutomation for browser automation."""
import html
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from cli_tools_shared.http_session import (
    BrowserAuthState,
    BrowserAuthenticatedHttpClient,
    RelayFormRequest,
    RelayGraphQLClient,
    extract_embedded_define,
)
from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import print_info
from cli_tools_shared._debug_logging import get_debug_logger

from .config import get_config
from .models import FACEBOOK_BASE_URL, MarketplaceListing, Group, GroupPost, Comment
from .parsers import extract_listings_from_snapshot

logger = get_debug_logger("cli_tools.facebook.client")


MARKETPLACE_BASE = f"{FACEBOOK_BASE_URL}/marketplace"
MESSENGER_BASE = f"{FACEBOOK_BASE_URL}/messages/t"
GROUPS_BASE = f"{FACEBOOK_BASE_URL}/groups"
DEFAULT_LOCATION = "evansville"
FACEBOOK_DESKTOP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "Upgrade-Insecure-Requests": "1",
}
GROUP_DISCUSSION_FRIENDLY_NAME = "CometGroupDiscussionRootSuccessQuery"
GROUP_DISCUSSION_DOC_ID = "26647538378198347"
GROUP_DISCUSSION_BOOTSTRAP_MARKERS = [
    '["CurrentUserInitialData",',
    '["DTSGInitialData",',
    '["LSD",',
    f'"queryID":"{GROUP_DISCUSSION_DOC_ID}"',
    f'"queryName":"{GROUP_DISCUSSION_FRIENDLY_NAME}"',
]
GROUP_POST_THREAD_STOP_MARKERS = [
    "CometFeedStorySeoLLMCommentSummarySection_story",
]


class FacebookClient:
    """Client that uses BrowserAutomation to automate Facebook."""

    def __init__(self):
        t0 = time.monotonic()
        self.config = get_config()
        self._browser_instance = None
        self._http_client: Optional[BrowserAuthenticatedHttpClient] = None
        logger.debug("__init__: config loaded in %.2fs", time.monotonic() - t0)

    @property
    def _browser(self):
        if self._browser_instance is None:
            t0 = time.monotonic()
            from .browser import FacebookBrowser
            self._browser_instance = FacebookBrowser(self.config)
            logger.debug("_browser: FacebookBrowser created in %.2fs", time.monotonic() - t0)
        return self._browser_instance

    def _get_page(self, url: str, settle_ms: int = 3000):
        """Get a page navigated to the given URL."""
        t0 = time.monotonic()
        logger.debug("_get_page: requesting page for %s", url)
        page = self._browser.get_page(url)
        logger.debug("_get_page: get_page() returned in %.2fs", time.monotonic() - t0)
        if settle_ms:
            page.wait_for_timeout(settle_ms)
            logger.debug("_get_page: %sms wait done, total %.2fs", settle_ms, time.monotonic() - t0)
        return page

    def _snapshot(self, page) -> str:
        """Take an accessibility tree snapshot and return the YAML content.

        Uses the shared browser driver's Playwright-backed
        ``aria_snapshot()`` helper so the client stays on the
        BrowserAutomation abstraction.
        """
        t0 = time.monotonic()
        try:
            result = page.aria_snapshot(timeout=5000)
            logger.debug("_snapshot: captured in %.2fs (%d chars)", time.monotonic() - t0, len(result))
            return result
        except Exception as e:
            raise ClientError(f"Failed to capture page snapshot: {e}")

    def _assert_authenticated_page(self, page, requested_url: str, surface: str) -> None:
        """Fail fast when Facebook serves a login or challenge page."""
        current_url = getattr(page, "url", "") or ""
        if any(token in current_url for token in ("/login", "two_step_verification", "/checkpoint")):
            raise ClientError(
                f"Facebook redirected {surface} to {current_url} "
                f"(requested: {requested_url}). Run 'facebook auth login --force' to authenticate."
            )
        blocked = page.evaluate(
            """() => ({
                loginForm: !!document.querySelector('input[name="email"], input[name="pass"]'),
                recaptcha: !!document.querySelector('iframe[src*="recaptcha"], iframe#captcha-recaptcha')
            })"""
        )
        if isinstance(blocked, dict) and blocked.get("recaptcha"):
            raise ClientError(
                f"Facebook presented a reCAPTCHA challenge for {surface}. "
                "Complete 'facebook auth login --force' in a headed browser."
            )
        if isinstance(blocked, dict) and blocked.get("loginForm"):
            raise ClientError(
                f"Facebook served a login form for {surface} at {current_url}. "
                f"(requested: {requested_url}). Run 'facebook auth login --force' to authenticate."
            )

    def _group_post_ref_parts(self, post_ref: str) -> Dict[str, str]:
        """Return canonical URL, group ID, and stable post ID for a group post ref."""
        if post_ref.startswith("http"):
            url = post_ref
        else:
            url = f"{GROUPS_BASE}/{post_ref}"

        post_match = re.search(r"/posts/(\d+)", url) or re.search(r"/permalink/(\d+)", url)
        group_match = re.search(r"/groups/([^/?]+)/", url)
        if not post_match:
            raise ClientError(f"Post URL does not contain a stable post ID: {url}")
        if not group_match:
            raise ClientError(f"Post URL does not contain a group ID: {url}")

        group_id = group_match.group(1)
        post_id = post_match.group(1)
        canonical_url = f"{GROUPS_BASE}/{group_id}/posts/{post_id}/"
        return {"url": canonical_url, "group_id": group_id, "post_id": post_id}

    def _wait_for_rendered_text(self, page, text: str, selector: str, timeout_ms: int) -> None:
        """Wait until text appears outside an editable textbox in a page region.

        Kept for backward compatibility (used by create_post). Prefer
        ``_wait_for_composer_cleared`` for comment/reply flows: Facebook strips
        Markdown (``**bold**``, link syntax) when rendering comments, so a literal
        substring search against the original input text is unreliable for any
        text containing formatting characters.
        """
        deadline = time.monotonic() + (timeout_ms / 1000)
        js = (
            '(args) => {'
            ' const root = document.querySelector(args.selector);'
            ' if (!root) return false;'
            ' const nodes = [...root.querySelectorAll("*")];'
            ' return nodes.some(el => {'
            '   if (el.closest(\'[role="textbox"][contenteditable="true"]\')) return false;'
            '   const value = (el.innerText || el.textContent || "").trim();'
            '   return value.includes(args.text);'
            ' });'
            ' }'
        )
        while time.monotonic() < deadline:
            if page.evaluate(js, {"selector": selector, "text": text}):
                return
            page.wait_for_timeout(500)
        raise ClientError(f"Timed out waiting for submitted text to render: {text[:80]}")

    def _wait_for_composer_cleared(self, page, timeout_ms: int) -> Dict:
        """Wait until the visible Lexical comment composer is empty.

        After Facebook accepts a comment/reply, it clears the composer's
        contenteditable region. This is a far more reliable success signal than
        searching for the submitted text in the rendered comments list, because:
          - Facebook strips Markdown formatting (``**bold**``, ``[text](url)``)
            when rendering comments, so the literal input substring may never
            appear in the DOM.
          - New comments may be appended via React portals or virtualized lists
            that paint outside the polled selector.
          - Whitespace and entity normalization further break naive substring
            matching for longer comments.

        Returns a status dict instead of raising; the caller decides whether a
        composer-not-cleared state is fatal or worth a secondary check (comment-
        count delta, markdown-stripped text match) before failing.

        Returns:
            {"cleared": True,  "reason": "composer-empty"|"composer-removed"} on success
            {"cleared": False, "remaining": [str, ...]}                       on timeout
        """
        deadline = time.monotonic() + (timeout_ms / 1000)
        js = (
            '() => {'
            ' const boxes = Array.from(document.querySelectorAll('
            '   \'[role="textbox"][contenteditable="true"][data-lexical-editor="true"]\''
            ' )).filter(el => {'
            '   const r = el.getBoundingClientRect();'
            '   return r.width > 0 && r.height > 0;'
            ' });'
            ' if (boxes.length === 0) {'
            # Composer disappeared entirely — that also counts as cleared
            # (e.g. reply composers collapse after submit).
            '   return {cleared: true, reason: "composer-removed"};'
            ' }'
            ' const nonEmpty = boxes.filter(b => (b.textContent || "").trim().length > 0);'
            ' if (nonEmpty.length === 0) {'
            '   return {cleared: true, reason: "composer-empty"};'
            ' }'
            ' return {'
            '   cleared: false,'
            '   remaining: nonEmpty.map(b => (b.textContent || "").trim().slice(0, 80))'
            ' };'
            ' }'
        )
        last_state: Dict = {"cleared": False, "remaining": []}
        while time.monotonic() < deadline:
            state = page.evaluate(js)
            if isinstance(state, dict):
                last_state = state
                if state.get("cleared"):
                    return state
            page.wait_for_timeout(500)
        return last_state

    @staticmethod
    def _normalize_for_match(text: str) -> str:
        """Normalize text for fuzzy DOM matching.

        Strips Markdown formatting characters Facebook drops during rendering,
        collapses whitespace, and lowercases. Used as a "did our text appear
        anywhere on the page" secondary check when the primary composer-cleared
        signal is inconclusive.
        """
        if not text:
            return ""
        # Strip ``**bold**`` and ``__bold__`` markers
        cleaned = re.sub(r"\*+|_+", "", text)
        # Strip Markdown link syntax ``[label](url)`` -> ``label url``
        cleaned = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 \2", cleaned)
        # Collapse all whitespace
        cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
        return cleaned

    def _count_post_comments(self, page) -> int:
        """Count visible comment articles within the active post.

        Returns 0 if no post article is found, or -1 if the JS evaluator failed.
        Used as a delta signal: if the count goes up after submit, our comment
        landed even when the composer-cleared check is inconclusive.
        """
        js = (
            '() => {'
            ' const main = document.querySelector(\'[role="main"]\');'
            ' if (!main) return -1;'
            # The post itself is a [role=article]; nested [role=article] under
            # it are the comments. Count any nested article whose ancestor is
            # the outermost article in [role=main].
            ' const articles = Array.from(main.querySelectorAll(\'[role="article"]\'));'
            ' if (articles.length === 0) return 0;'
            # The first article in document order is typically the post; treat
            # everything else as comments.
            ' return Math.max(0, articles.length - 1);'
            ' }'
        )
        try:
            value = page.evaluate(js)
            return int(value) if isinstance(value, (int, float)) else -1
        except Exception:
            return -1

    def _text_appears_on_page(self, page, normalized: str) -> bool:
        """Check whether ``normalized`` appears anywhere outside the composer.

        Compares against a normalized snapshot of the page text so that
        Markdown-stripped content still matches. Returns False on any error so
        callers can treat it as "inconclusive, fall through to next check."
        """
        if not normalized:
            return False
        # Search a slice that's distinctive enough to avoid false positives but
        # short enough to dodge whitespace/entity drift in the rest of the body.
        needle = normalized[:120]
        if len(needle) < 20:
            return False
        js = (
            '(args) => {'
            ' const main = document.querySelector(\'[role="main"]\') || document.body;'
            ' if (!main) return false;'
            ' const raw = (main.innerText || main.textContent || "");'
            ' const cleaned = raw'
            '   .replace(/\\*+|_+/g, "")'
            '   .replace(/\\s+/g, " ")'
            '   .toLowerCase();'
            ' return cleaned.indexOf(args.needle) !== -1;'
            ' }'
        )
        try:
            return bool(page.evaluate(js, {"needle": needle}))
        except Exception:
            return False

    def _verify_comment_landed(
        self,
        page,
        text: str,
        comment_count_before: int,
        composer_timeout_ms: int = 10000,
        secondary_timeout_ms: int = 10000,
    ) -> Dict:
        """Multi-stage verification that a submitted comment/reply actually posted.

        Stage 1: composer-cleared (most reliable signal).
        Stage 2: comment-count delta (count went from N -> N+).
        Stage 3: markdown-stripped text appears on page.

        Returns:
            {"verification": "confirmed",                     "signal": "composer-cleared"|"count-delta"|"text-appeared"}
            {"verification": "render-timeout-likely-success", "signal": "composer-cleared-but-no-other-evidence", "diagnostic": ...}
        Raises ClientError only when ALL three checks fail — that means the submit truly didn't land.
        """
        composer_state = self._wait_for_composer_cleared(page, timeout_ms=composer_timeout_ms)
        composer_cleared = bool(composer_state.get("cleared"))

        normalized = self._normalize_for_match(text)

        # Stage 2 + 3: poll for count-delta or text-appeared, regardless of
        # composer state. This corroborates the composer signal AND catches
        # the rare case where the composer didn't fully clear but the comment
        # did land (e.g. FB re-focuses the composer with stale text).
        deadline = time.monotonic() + (secondary_timeout_ms / 1000)
        last_count = comment_count_before
        while time.monotonic() < deadline:
            count_now = self._count_post_comments(page)
            if count_now >= 0:
                last_count = count_now
                if comment_count_before >= 0 and count_now >= comment_count_before + 1:
                    return {"verification": "confirmed", "signal": "count-delta",
                            "commentCountBefore": comment_count_before, "commentCountAfter": count_now}
            if self._text_appears_on_page(page, normalized):
                return {"verification": "confirmed", "signal": "text-appeared",
                        "commentCountBefore": comment_count_before, "commentCountAfter": last_count}
            if composer_cleared and (time.monotonic() - (deadline - secondary_timeout_ms / 1000)) > 3.0:
                # We have one strong signal (composer cleared) and have given
                # the page a few seconds to render. That's good enough — return
                # confirmed via composer-cleared without burning the full
                # secondary timeout.
                return {"verification": "confirmed", "signal": "composer-cleared",
                        "commentCountBefore": comment_count_before, "commentCountAfter": last_count}
            page.wait_for_timeout(500)

        # Secondary timeout exhausted.
        if composer_cleared:
            # The strongest single signal fired; the corroborators were
            # inconclusive (FB likely lazy-rendering the new comment off-DOM).
            # Treat this as likely-success rather than a hard failure;
            # callers record the weaker verification signal accordingly.
            return {
                "verification": "render-timeout-likely-success",
                "signal": "composer-cleared-but-no-other-evidence",
                "diagnostic": {
                    "commentCountBefore": comment_count_before,
                    "commentCountAfter": last_count,
                    "composerReason": composer_state.get("reason"),
                },
            }

        # No signal fired at all. The submit truly didn't land.
        raise ClientError(
            "Comment submit verification failed: composer never cleared, comment "
            f"count did not increment ({comment_count_before} -> {last_count}), and "
            f"the submitted text never appeared on the page. Composer remaining text: "
            f"{composer_state.get('remaining', [])}."
        )

    def _iter_comment_tree(self, comments: Optional[List[Comment]]):
        """Yield comments and nested replies from a GroupPost comment tree."""
        for comment in comments or []:
            yield comment
            yield from self._iter_comment_tree(comment.replies)

    def _wait_for_comment_on_exact_post(
        self,
        group_id: str,
        post_id: str,
        text: str,
        timeout_ms: int,
    ) -> Dict:
        """Verify the submitted text exists on the exact requested post ID."""
        normalized = self._normalize_for_match(text)
        if not normalized:
            raise ClientError("Cannot verify an empty comment.")

        deadline = time.monotonic() + (timeout_ms / 1000)
        last_comment_count = 0
        while time.monotonic() < deadline:
            post = self.get_group_post(f"{group_id}/posts/{post_id}")
            if post.post_id != post_id:
                raise ClientError(f"Fetched post ID {post.post_id} did not match requested post ID {post_id}.")

            comments = list(self._iter_comment_tree(post.comments))
            last_comment_count = len(comments)
            for comment in comments:
                if self._normalize_for_match(comment.text) == normalized:
                    return {
                        "verification": "confirmed",
                        "signal": "exact-post-comment-found",
                        "groupId": group_id,
                        "postId": post_id,
                        "commentId": comment.comment_id,
                        "commentCountAfter": last_comment_count,
                    }

            time.sleep(1)

        raise ClientError(
            "Submitted comment was not found on the exact target post after submit: "
            f"group_id={group_id}, post_id={post_id}, comments_checked={last_comment_count}."
        )

    def close(self):
        """Close the browser."""
        if self._browser_instance is not None:
            self._browser_instance.close()
            self._browser_instance = None
            logger.debug("close: closed browser")

    # --- Marketplace helper methods ---

    def _extract_list_page_image_urls(self, page) -> Dict[str, List[str]]:
        """Extract image URLs for each listing on a list/search results page.

        Returns:
            Dict mapping item_id -> list of image URLs.
        """
        js = (
            '() => { const r = {}; document.querySelectorAll(\'a[href*="/marketplace/item/"]\').forEach(a => {'
            ' const m = a.href.match(/\\/marketplace\\/item\\/(\\d+)\\//); if (m == null) return;'
            ' const id = m[1]; if (r[id]) return;'
            ' const imgs = [...a.querySelectorAll(\'img[src*="scontent"]\')];'
            ' const urls = imgs.map(i => i.src).filter(Boolean);'
            ' if (urls.length) r[id] = urls; }); return r; }'
        )
        result = page.evaluate(js)
        return result if isinstance(result, dict) else {}

    def _extract_detail_page_image_urls(self, page) -> List[str]:
        """Extract image URLs from a listing detail page.

        Returns:
            Deduplicated list of image URLs.
        """
        js = (
            '() => { const main = document.querySelector(\'[role="main"]\') || document;'
            ' const imgs = [...main.querySelectorAll(\'img[src*="scontent"]\')];'
            ' const urls = imgs.filter(i => i.naturalWidth > 100'
            ' && i.closest(\'a[href*="/marketplace/item/"]\') == null).map(i => i.src);'
            ' return [...new Set(urls)]; }'
        )
        result = page.evaluate(js)
        return result if isinstance(result, list) else []

    def _extract_detail_page_info(self, page) -> Dict:
        """Extract title, price, location, and description from a listing detail page.

        Returns:
            Dict with title, price, location, description keys.
        """
        js = (
            '() => { const main = document.querySelector(\'[role="main"]\');'
            ' if (main == null) return {title:"",price:"",location:"",description:""};'
            ' const h1 = main.querySelector("h1");'
            ' const title = h1 ? (h1.innerText || "").trim() : "";'
            ' const text = main.innerText || "";'
            ' const lines = text.split("\\n").map(l => l.trim()).filter(Boolean);'
            ' let price = "";'
            ' for (let i = 0; i < lines.length; i++) {'
            '   if (lines[i] === title && i + 1 < lines.length) {'
            '     const next = lines[i+1];'
            '     if (next.match(/^\\$[\\d,]+/) || next === "Free" || next === "FREE") { price = next; break; }'
            '   }'
            ' }'
            ' let location = "";'
            ' const locLine = lines.find(l => l.startsWith("Listed in "));'
            ' if (locLine) location = locLine.replace("Listed in ", "");'
            ' let description = "";'
            ' const di = text.indexOf("Details\\n"); const si = text.indexOf("Seller information");'
            ' if (di >= 0) {'
            '   const start = di + "Details\\n".length;'
            '   const end = si > start ? si : text.length;'
            '   let desc = text.substring(start, end).trim();'
            '   const cm = desc.match(/^Condition\\n[^\\n]+\\n/);'
            '   if (cm) desc = desc.substring(cm[0].length).trim();'
            '   const lm = desc.match(/\\n[A-Z][a-zA-Z ]+,\\s*[A-Z]{2}\\nLocation is approximate$/);'
            '   if (lm) desc = desc.substring(0, desc.length - lm[0].length).trim();'
            '   description = desc;'
            ' }'
            ' return {title: title, price: price, location: location, description: description}; }'
        )
        result = page.evaluate(js)
        if isinstance(result, dict):
            return result
        return {"title": "", "price": "", "location": "", "description": ""}

    def _scroll_collect(
        self,
        page,
        extract_fn: Callable,
        id_key: str,
        limit: int,
        label: str,
    ) -> List[Dict]:
        """Scroll a page and collect deduplicated items via infinite scroll.

        Args:
            page: The Playwright page to scroll.
            extract_fn: Callable that takes the page and returns a list of dicts.
            id_key: Dict key used for deduplication.
            limit: Maximum number of items to collect.
            label: Label for log/status messages.

        Returns:
            Deduplicated list of raw dicts (up to limit).
        """
        t_start = time.monotonic()
        all_items: List[Dict] = []
        seen_ids: set = set()
        scroll_count = 0

        while len(all_items) < limit:
            t_extract = time.monotonic()
            raw = extract_fn(page)
            logger.debug("_scroll_collect[%s]: scroll %d: %d raw in %.2fs (total unique: %d)",
                         label, scroll_count, len(raw), time.monotonic() - t_extract, len(all_items))

            new_count = 0
            for item in raw:
                item_id = item.get(id_key)
                if item_id and item_id not in seen_ids:
                    seen_ids.add(item_id)
                    all_items.append(item)
                    new_count += 1

            if len(all_items) >= limit:
                break

            if new_count == 0 and scroll_count > 0:
                break

            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)
            scroll_count += 1

        logger.debug("_scroll_collect[%s]: total %.2fs, %d items, %d scrolls",
                     label, time.monotonic() - t_start, len(all_items), scroll_count)
        print_info(f"Loaded {len(all_items)} {label}(s) after {scroll_count} scroll(s)")
        return all_items[:limit]

    def _dismiss_marketplace_login_dialog(self, page) -> None:
        """Close Facebook's login upsell dialog on public Marketplace pages."""
        try:
            close_button = page.get_by_role("button", name="Close")
            if close_button.count() == 0:
                return
            close_button.first.click()
            page.wait_for_timeout(1000)
        except Exception:
            logger.debug("_dismiss_marketplace_login_dialog: close button not actionable")

    def _paginated_fetch(self, url: str, status_msg: str, limit: int) -> List[MarketplaceListing]:
        """Navigate to a Marketplace URL and scroll to collect listings."""
        print_info(status_msg)
        page = self._get_page(url)
        self._dismiss_marketplace_login_dialog(page)

        def _extract(p):
            snapshot = self._snapshot(p)
            return extract_listings_from_snapshot(snapshot)

        items = self._scroll_collect(page, _extract, "item_id", limit, "listing")
        return [MarketplaceListing(**d) for d in items]

    # --- Marketplace methods ---

    def search(
        self,
        query: str,
        location: str = DEFAULT_LOCATION,
        min_price: Optional[int] = None,
        max_price: Optional[int] = None,
        limit: int = 50,
    ) -> List[MarketplaceListing]:
        """Search Facebook Marketplace for listings."""
        params = [f"query={query}"]
        if min_price is not None:
            params.append(f"minPrice={min_price}")
        if max_price is not None:
            params.append(f"maxPrice={max_price}")

        url = f"{MARKETPLACE_BASE}/{location}/search/?{'&'.join(params)}"
        return self._paginated_fetch(
            url=url,
            status_msg=f"Searching for '{query}' in {location}...",
            limit=limit,
        )

    def browse(
        self,
        location: str = DEFAULT_LOCATION,
        limit: int = 50,
    ) -> List[MarketplaceListing]:
        """Browse Facebook Marketplace 'Today's picks' for a location."""
        url = f"{MARKETPLACE_BASE}/{location}/"
        return self._paginated_fetch(
            url=url,
            status_msg=f"Browsing Marketplace in {location}...",
            limit=limit,
        )

    @cached
    def get_item(self, item_id: str, include_images: bool = False) -> MarketplaceListing:
        """Get details for a specific marketplace listing.

        Extracts title, price, location, and description directly from the
        detail page DOM rather than the snapshot parser (which picks up
        recommended listings instead of the main one).

        Args:
            item_id: The marketplace item ID.
            include_images: If True, extract image URLs from the page.

        Returns:
            MarketplaceListing with item details.
        """
        url = f"{MARKETPLACE_BASE}/item/{item_id}/"
        print_info(f"Getting listing {item_id}...")

        page = self._get_page(url)
        self._dismiss_marketplace_login_dialog(page)

        info = self._extract_detail_page_info(page)
        listing = MarketplaceListing(
            item_id=item_id,
            title=info.get("title") or "Unknown",
            price=info.get("price") or "Unknown",
            url=f"/marketplace/item/{item_id}/",
            location=info.get("location") or None,
            description=info.get("description") or None,
        )

        if include_images:
            listing.image_urls = self._extract_detail_page_image_urls(page)

        return listing

    # --- Messenger methods ---

    def list_conversations(self, limit: int = 20) -> List[Dict]:
        """List Messenger conversations.

        Args:
            limit: Maximum number of conversations to return.

        Returns:
            List of conversation dicts with id, name, snippet, timestamp.
        """
        from .messenger_parsers import extract_conversations_from_snapshot

        t_start = time.monotonic()
        print_info("Loading Messenger conversations...")
        requested_url = "https://www.facebook.com/messages/t/"
        page = self._get_page(requested_url)
        self._assert_authenticated_page(page, requested_url, "Messenger conversations")
        logger.debug("list_conversations: page loaded in %.2fs", time.monotonic() - t_start)
        page.wait_for_timeout(1000)  # extra wait for messenger

        snapshot = self._snapshot(page)
        conversations = extract_conversations_from_snapshot(snapshot)
        logger.debug("list_conversations: total %.2fs, %d conversations",
                     time.monotonic() - t_start, len(conversations))
        return conversations[:limit]

    def get_conversation(self, conversation_id: str, message_limit: int = 50) -> Dict:
        """Get a conversation with its messages.

        Args:
            conversation_id: The conversation/thread ID.
            message_limit: Maximum number of messages to return.

        Returns:
            Dict with conversation info and messages list.
        """
        from .messenger_parsers import extract_messages_from_snapshot

        print_info(f"Loading conversation {conversation_id}...")
        requested_url = f"{MESSENGER_BASE}/{conversation_id}/"
        page = self._get_page(requested_url)
        self._assert_authenticated_page(page, requested_url, f"Messenger conversation {conversation_id}")
        page.wait_for_timeout(1000)  # extra wait for messenger

        snapshot = self._snapshot(page)
        messages = extract_messages_from_snapshot(snapshot)

        return {
            "conversation_id": conversation_id,
            "messages": messages[-message_limit:],
        }

    def send_message(self, conversation_id: str, text: str) -> Dict:
        """Send a message in a conversation.

        Args:
            conversation_id: The conversation/thread ID.
            text: The message text to send.

        Returns:
            Dict with send status.
        """
        print_info(f"Sending message to conversation {conversation_id}...")
        requested_url = f"{MESSENGER_BASE}/{conversation_id}/"
        page = self._get_page(requested_url)
        self._assert_authenticated_page(page, requested_url, f"Messenger conversation {conversation_id}")

        # Type the message into the composer and send
        escaped_text = json.dumps(text)
        js_type = (
            '(escapedText) => {'
            ' const box = document.querySelector(\'[role="textbox"][contenteditable="true"]\');'
            ' if (!box) return {success: false, error: "Message box not found"};'
            ' box.focus();'
            ' box.textContent = "";'
            ' document.execCommand("insertText", false, escapedText);'
            ' return {success: true};'
            ' }'
        )
        typed = page.evaluate(js_type, text)
        if not isinstance(typed, dict):
            typed = {"success": False, "error": "Failed to type message"}

        if not typed.get("success"):
            raise ClientError(f"Failed to type message: {typed.get('error', 'unknown')}")

        page.wait_for_timeout(500)

        # Press Enter to send
        page.evaluate(
            '() => { document.querySelector(\'[role="textbox"]\').dispatchEvent('
            'new KeyboardEvent("keydown", {key: "Enter", code: "Enter", keyCode: 13, bubbles: true})); }'
        )
        page.wait_for_timeout(2000)

        return {"success": True, "conversation_id": conversation_id, "text": text}

    # --- Groups methods ---

    def _extract_joined_groups(self, page) -> List[Dict]:
        """Extract groups from the user's joined groups page.

        Returns:
            List of group dicts with group_id, name, url, member_count.
        """
        js = (
            '() => {'
            ' const groups = [];'
            ' const seen = new Set();'
            ' const links = document.querySelectorAll(\'a[href*="/groups/"]\');'
            ' links.forEach(a => {'
            '   const href = a.href || "";'
            '   const m = href.match(/\\/groups\\/([^/?]+)/);'
            '   if (!m) return;'
            '   const gid = m[1];'
            '   if (gid === "feed" || gid === "discover" || gid === "joins" || seen.has(gid)) return;'
            # Try to get a clean group name from an image alt text or aria-label first,
            # then fall back to the shortest meaningful text child.
            '   let name = "";'
            '   const img = a.querySelector("img[alt]");'
            '   if (img && img.alt && img.alt.length > 1 && img.alt.length < 100) {'
            '     name = img.alt.trim();'
            '   }'
            '   if (!name) {'
            '     const label = a.getAttribute("aria-label");'
            '     if (label && label.length > 1 && label.length < 100) name = label.trim();'
            '   }'
            '   if (!name) {'
            # Walk child spans/divs for the shortest non-trivial text (likely the group name)
            # Skip text containing notification indicators
            '     const candidates = [];'
            '     a.querySelectorAll("span, strong, h3").forEach(el => {'
            '       const t = (el.innerText || "").trim();'
            '       if (t.length >= 3 && t.length <= 80'
            '           && !t.includes("Unread") && !t.includes("Mark as read")'
            '           && !t.includes("posted in") && !t.includes("ago")'
            '           && !t.match(/^\\d+[hmd]$/)) {'
            '         candidates.push(t);'
            '       }'
            '     });'
            '     if (candidates.length > 0) {'
            '       candidates.sort((a, b) => a.length - b.length);'
            '       name = candidates[0];'
            '     }'
            '   }'
            '   if (!name || name.length < 2) return;'
            '   seen.add(gid);'
            '   let memberCount = "";'
            '   const fullText = (a.innerText || "");'
            '   const mMatch = fullText.match(/(\\d[\\d,.]*\\s*[KkMm]?\\s*members?)/i);'
            '   if (mMatch) memberCount = mMatch[1].trim();'
            '   groups.push({group_id: gid, name: name, url: href.split("?")[0], member_count: memberCount});'
            ' });'
            ' return groups;'
            ' }'
        )
        result = page.evaluate(js)
        return result if isinstance(result, list) else []

    def list_joined_groups(self, limit: int = 50) -> List[Group]:
        """List Facebook Groups the user has joined."""
        print_info("Loading joined groups...")
        page = self._get_page(f"{GROUPS_BASE}/joins/", settle_ms=0)
        page.wait_for_selector('a[href*="/groups/"]', timeout=15000)

        items = self._scroll_collect(page, self._extract_joined_groups, "group_id", limit, "group")
        return [Group(**g) for g in items]

    def get_group(self, group_id: str) -> Group:
        """Get a Facebook Group by ID or slug."""
        if group_id.startswith("http"):
            match = re.search(r"/groups/([^/?]+)", group_id)
            if not match:
                raise ClientError(f"Group URL does not contain a group ID: {group_id}")
            group_ref = match.group(1)
            url = group_id
        else:
            group_ref = group_id
            url = f"{GROUPS_BASE}/{group_ref}/"

        body = self._fetch_authenticated_facebook_html(url)
        name = self._extract_group_name(body)
        member_count = self._extract_group_member_count(body)

        return Group(
            group_id=group_ref,
            name=name,
            url=f"{GROUPS_BASE}/{group_ref}/",
            member_count=member_count,
        )

    def _facebook_http_client(self) -> BrowserAuthenticatedHttpClient:
        """Get the shared fast HTTP client for browser-authenticated reads."""
        if self._http_client is None:
            self._http_client = BrowserAuthenticatedHttpClient(
                auth_state=BrowserAuthState.from_config(self.config),
                allowed_domains=["facebook.com"],
                required_cookies=["c_user"],
                headers=FACEBOOK_DESKTOP_HEADERS,
                timeout=10,
            )
        return self._http_client

    def _fetch_authenticated_facebook_html(self, url: str) -> str:
        """Fetch enough authenticated Facebook HTML for group metadata."""
        return self._fetch_authenticated_facebook_page(
            url,
            stop_markers=[
                "</title>",
                '"group_member_profiles":{"formatted_count_text":"',
            ],
        )

    def _fetch_authenticated_facebook_full_html(self, url: str) -> str:
        """Fetch a complete authenticated Facebook page without launching Chromium."""
        return self._fetch_authenticated_facebook_page(url)

    def _fetch_authenticated_facebook_bootstrap_html(self, url: str) -> str:
        """Fetch only the Facebook Relay bootstrap slice needed for group posts."""
        return self._fetch_authenticated_facebook_page(
            url,
            stop_markers=GROUP_DISCUSSION_BOOTSTRAP_MARKERS,
        )

    def _fetch_authenticated_facebook_page(
        self,
        url: str,
        stop_markers: Optional[List[str]] = None,
    ) -> str:
        """Fetch an authenticated Facebook page without launching Chromium."""
        result = self._facebook_http_client().get_text_result(
            url,
            stop_after_markers=stop_markers or (),
        )
        logger.debug(
            "_fetch_authenticated_facebook_page: fetched in %.2fs (%d chars, %d bytes)",
            result.elapsed_seconds,
            len(result.text),
            result.bytes_read,
        )
        return result.text

    def _extract_group_name(self, body: str) -> str:
        """Extract the group name from fetched Facebook HTML."""
        title_match = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
        if not title_match:
            raise ClientError("Failed to extract group name from Facebook HTML title.")

        name = html.unescape(re.sub(r"\s+", " ", title_match.group(1))).strip()
        if not name or name == "Facebook" or name == "Error":
            raise ClientError("Facebook group page did not include a group title.")
        return name

    def _extract_group_member_count(self, body: str) -> str:
        """Extract the group member count from fetched Facebook HTML."""
        match = re.search(r'"group_member_profiles":\{"formatted_count_text":"([^"]+)"', body)
        if not match:
            raise ClientError("Failed to extract group member count from Facebook HTML.")
        return html.unescape(match.group(1))

    def _facebook_server_define(self, body: str, name: str) -> Dict:
        """Extract a ServerJS define payload from Facebook HTML."""
        return extract_embedded_define(body, name)

    def _facebook_jazoest(self, token: str) -> str:
        """Build Facebook's jazoest form value from the DTSG token."""
        return "2" + "".join(str(ord(char)) for char in token)

    def _iter_relay_prefetched_stream_results(self, body: str, allow_truncated_tail: bool = False):
        """Yield RelayPrefetchedStreamCache result objects from Facebook HTML."""
        marker = '["RelayPrefetchedStreamCache","next"'
        decoder = json.JSONDecoder()
        index = 0
        while True:
            start = body.find(marker, index)
            if start < 0:
                return
            try:
                value, index = decoder.raw_decode(body, start)
            except json.JSONDecodeError as exc:
                if allow_truncated_tail:
                    return
                raise ClientError(f"Failed to decode JSON at marker: {marker}") from exc
            if (
                not isinstance(value, list)
                or len(value) < 4
                or not isinstance(value[3], list)
                or len(value[3]) < 2
                or not isinstance(value[3][1], dict)
            ):
                raise ClientError("Facebook HTML contained invalid Relay stream data.")
            bbox = value[3][1].get("__bbox")
            if not isinstance(bbox, dict):
                raise ClientError("Facebook Relay stream payload is missing __bbox.")
            result = bbox.get("result")
            if isinstance(result, dict):
                yield result

    def _extract_text_path(self, data: Dict, path: List[str]) -> Optional[str]:
        """Extract a nested string from a dictionary."""
        value = data
        for part in path:
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ClientError(f"Expected string at {'.'.join(path)}, got {type(value).__name__}.")
        return value

    def _extract_group_post_text(self, node: Dict) -> Optional[str]:
        """Extract text from Facebook's typed group story message section."""
        message = node.get("comet_sections", {}).get("content", {}).get("story", {}).get("comet_sections", {}).get("message")
        if message is None:
            return None
        if not isinstance(message, dict):
            raise ClientError("Facebook story message section is not an object.")

        typename = message.get("__typename")
        if typename in (
            "CometFeedStoryDefaultMessageRenderingStrategy",
            "CometFeedStoryLargeMessageRenderingStrategy",
            "CometFeedStoryFormattedBackgroundMessageRenderingStrategy",
        ):
            return self._extract_text_path(message, ["story", "message", "text"])

        if typename == "CometFeedStoryRichMessageRenderingStrategy":
            container_text = self._extract_text_path(message, ["message_container", "story", "message", "text"])
            if container_text is not None:
                return container_text
            rich_message = message.get("rich_message")
            if not isinstance(rich_message, list):
                raise ClientError("Facebook rich message section is missing rich_message blocks.")
            parts = []
            for block in rich_message:
                if not isinstance(block, dict):
                    raise ClientError("Facebook rich message block is not an object.")
                block_text = block.get("text")
                if block_text is not None and not isinstance(block_text, str):
                    raise ClientError("Facebook rich message block text is not a string.")
                if block_text:
                    parts.append(block_text)
            return "\n".join(parts) if parts else None

        if not isinstance(typename, str):
            raise ClientError("Facebook story message section is missing __typename.")
        raise ClientError(f"Unsupported Facebook story message renderer: {typename}")

    @staticmethod
    def _title_from_group_post_body(body: Optional[str]) -> Optional[str]:
        """Derive a thread title from the first non-empty line of post text."""
        if body is None:
            return None
        for line in body.splitlines():
            title = line.strip()
            if title:
                return title[:160]
        return None

    def _group_post_from_story_node(self, group_id: str, node: Dict) -> Dict:
        """Convert a Facebook Story node into a GroupPost dictionary."""
        if not isinstance(node, dict):
            raise ClientError("Facebook group feed story node is not an object.")
        post_id = node.get("post_id")
        if not isinstance(post_id, str) or not post_id:
            raise ClientError("Facebook group feed story node is missing post_id.")

        created = node.get("comet_sections", {}).get("timestamp", {}).get("story", {}).get("creation_time")
        if created is not None and not isinstance(created, (int, float)):
            raise ClientError("Facebook group feed story creation_time is not numeric.")

        timestamp = None
        if created is not None:
            timestamp = datetime.fromtimestamp(created, timezone.utc).isoformat()

        body = self._extract_group_post_text(node)
        thread_url = (
            self._extract_text_path(node, ["comet_sections", "timestamp", "story", "url"])
            or f"{GROUPS_BASE}/{group_id}/posts/{post_id}/"
        )

        return {
            "post_id": post_id,
            "title": self._title_from_group_post_body(body),
            "author": self._extract_text_path(node, ["feedback", "owning_profile", "name"]),
            "text": body,
            "body": body,
            "timestamp": timestamp,
            "url": thread_url,
            "thread_url": thread_url,
            "image_urls": None,
        }

    def _extract_story_image_urls(self, node: Dict) -> List[str]:
        """Extract media URLs from a story's attachment subtree."""
        urls: List[str] = []
        seen = set()

        def visit(value) -> None:
            if isinstance(value, str):
                if not value.startswith("http"):
                    return
                if "scontent" not in value and "fbcdn" not in value:
                    return
                if any(size_token in value for size_token in ("s40x40", "s48x48", "s74x74")):
                    return
                if value in seen:
                    return
                seen.add(value)
                urls.append(value)
                return
            if isinstance(value, dict):
                for child in value.values():
                    visit(child)
                return
            if isinstance(value, list):
                for child in value:
                    visit(child)

        visit(node.get("attachments"))
        visit(node.get("attached_story", {}).get("attachments") if isinstance(node.get("attached_story"), dict) else None)
        return urls

    @staticmethod
    def _optional_text_path(data: Dict, path: List[str]) -> Optional[str]:
        value = data
        for part in path:
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ClientError(f"Expected string at {'.'.join(path)}, got {type(value).__name__}.")
        return value

    def _comment_from_relay_node(self, node: Dict) -> Optional[Dict]:
        if node.get("__typename") != "Comment":
            return None
        legacy_fbid = node.get("legacy_fbid")
        if not isinstance(legacy_fbid, str) or not legacy_fbid:
            return None
        author = self._optional_text_path(node, ["author", "name"])
        if not author:
            raise ClientError(f"Facebook comment {legacy_fbid} is missing author.name.")
        text = (
            self._optional_text_path(node, ["body", "text"])
            or self._optional_text_path(node, ["preferred_body", "text"])
        )
        if text is None:
            raise ClientError(f"Facebook comment {legacy_fbid} is missing body text.")
        created = node.get("created_time")
        if created is not None and not isinstance(created, (int, float)):
            raise ClientError(f"Facebook comment {legacy_fbid} created_time is not numeric.")
        created_time = datetime.fromtimestamp(created, timezone.utc).isoformat() if created is not None else None
        parent = node.get("comment_direct_parent")
        parent_id = None
        if isinstance(parent, dict):
            parent_value = parent.get("legacy_fbid")
            if parent_value is not None and not isinstance(parent_value, str):
                raise ClientError(f"Facebook comment {legacy_fbid} parent legacy_fbid is not a string.")
            parent_id = parent_value
        return {
            "_parent_id": parent_id,
            "comment_id": legacy_fbid,
            "author": author,
            "text": text,
            "created_time": created_time,
            "replies": [],
        }

    def _extract_comments_from_relay_payloads(self, payloads: tuple[Dict, ...]) -> List[Dict]:
        """Extract top-level comments and replies from post Relay payloads."""
        by_id: Dict[str, Dict] = {}
        ordered: List[Dict] = []

        def visit(value) -> None:
            if isinstance(value, dict):
                comment = self._comment_from_relay_node(value)
                if comment is not None:
                    comment_id = comment["comment_id"]
                    if comment_id not in by_id:
                        by_id[comment_id] = comment
                        ordered.append(comment)
                for child in value.values():
                    visit(child)
                return
            if isinstance(value, list):
                for child in value:
                    visit(child)

        for payload in payloads:
            visit(payload)

        return self._comment_tree_from_ordered(ordered, by_id)

    def _comment_tree_from_ordered(self, ordered: List[Dict], by_id: Dict[str, Dict]) -> List[Dict]:
        """Build a nested comment tree from ordered Relay comment nodes."""
        top: List[Dict] = []
        for comment in ordered:
            parent_id = comment["_parent_id"]
            if parent_id and parent_id in by_id:
                by_id[parent_id]["replies"].append(comment)
            else:
                top.append(comment)

        def clean(entries: List[Dict]) -> List[Dict]:
            cleaned = []
            for entry in entries:
                cleaned.append({
                    "comment_id": entry["comment_id"],
                    "author": entry["author"],
                    "text": entry["text"],
                    "created_time": entry["created_time"],
                    "replies": clean(entry["replies"]),
                })
            return cleaned

        return clean(top)

    def _extract_story_and_comments_from_payloads(
        self,
        payloads: tuple[Dict, ...],
        post_id: str,
    ) -> tuple[Optional[Dict], List[Dict]]:
        """Collect the target story node and Relay comments in one traversal."""
        story_candidates: List[Dict] = []
        by_id: Dict[str, Dict] = {}
        ordered: List[Dict] = []

        def visit(value) -> None:
            if isinstance(value, dict):
                if value.get("post_id") == post_id:
                    story_candidates.append(value)
                comment = self._comment_from_relay_node(value)
                if comment is not None:
                    comment_id = comment["comment_id"]
                    if comment_id not in by_id:
                        by_id[comment_id] = comment
                        ordered.append(comment)
                for child in value.values():
                    visit(child)
                return
            if isinstance(value, list):
                for child in value:
                    visit(child)

        for payload in payloads:
            visit(payload)

        story_node = None
        for candidate in story_candidates:
            author = self._extract_text_path(candidate, ["feedback", "owning_profile", "name"])
            if author is not None:
                story_node = candidate
                break
        if story_node is None and story_candidates:
            story_node = story_candidates[0]
        return story_node, self._comment_tree_from_ordered(ordered, by_id)

    def _full_group_post_from_html(
        self,
        group_id: str,
        post_id: str,
        url: str,
        body: str,
        *,
        allow_truncated_tail: bool = False,
    ) -> GroupPost:
        """Extract a complete group post from authenticated post HTML."""
        started = time.monotonic()
        payloads = tuple(self._iter_relay_prefetched_stream_results(
            body,
            allow_truncated_tail=allow_truncated_tail,
        ))
        payload_elapsed = time.monotonic() - started
        extract_started = time.monotonic()
        story_node, comments = self._extract_story_and_comments_from_payloads(payloads, post_id)
        extract_elapsed = time.monotonic() - extract_started
        if story_node is None:
            raise ClientError(f"Failed to extract post {post_id} from {url}")

        build_started = time.monotonic()
        data = self._group_post_from_story_node(group_id, story_node)
        data["comments"] = comments
        data["comment_count"] = self._count_comments(comments)
        data["image_urls"] = self._extract_story_image_urls(story_node)
        logger.debug(
            "_full_group_post_from_html[%s]: payload %.2fs, extract %.2fs, build %.2fs, comments=%d, images=%d",
            post_id,
            payload_elapsed,
            extract_elapsed,
            time.monotonic() - build_started,
            data["comment_count"],
            len(data["image_urls"]),
        )
        return GroupPost(**data)

    def _extract_rendered_thread_details(self, url: str, post_id: str) -> Dict[str, List[Dict] | List[str]]:
        """Render a post permalink once and extract comments plus post images."""
        page = self._get_page(url, settle_ms=4000)
        page.wait_for_selector('[role="main"]', timeout=20000)
        page.wait_for_timeout(2500)

        image_urls = page.evaluate(
            r"""
            () => {
              const scope = document.querySelector('[role="dialog"]') || document.querySelector('[role="main"]');
              if (!scope) return [];
              const postArticle = scope.querySelector('[role="article"]');
              if (!postArticle) return [];
              const urls = [];
              const seen = new Set();
              for (const img of postArticle.querySelectorAll('img[src*="scontent"]')) {
                const src = img.getAttribute("src") || "";
                if (!src) continue;
                if (img.naturalWidth <= 100 && img.naturalHeight <= 100) continue;
                if (seen.has(src)) continue;
                seen.add(src);
                urls.push(src);
              }
              return urls;
            }
            """
        )
        if not isinstance(image_urls, list):
            raise ClientError("Rendered Facebook post image extractor did not return a list.")
        for image_url in image_urls:
            if not isinstance(image_url, str) or not image_url:
                raise ClientError("Rendered Facebook post image extractor returned a non-string URL.")

        comments = self._extract_comments_from_rendered_page(page, post_id)
        return {"comments": comments, "image_urls": image_urls}

    def _extract_initial_group_feed(self, group_id: str, body: str) -> tuple[List[Dict], str]:
        """Extract initial group feed stories and pagination cursor from group HTML."""
        posts: List[Dict] = []
        cursor = None
        for result in self._iter_relay_prefetched_stream_results(body):
            label = result.get("label")
            if not isinstance(label, str):
                continue
            data = result.get("data")
            if not isinstance(data, dict):
                raise ClientError("Facebook group feed Relay result is missing data.")
            if label.startswith("GroupsCometFeedRegularStories_paginationGroup$stream"):
                node = data.get("node")
                posts.append(self._group_post_from_story_node(group_id, node))
            if label.startswith("GroupsCometFeedRegularStories_paginationGroup$defer"):
                page_info = data.get("page_info")
                if not isinstance(page_info, dict):
                    raise ClientError("Facebook group feed page_info is missing.")
                cursor = page_info.get("end_cursor")

        if not isinstance(cursor, str) or not cursor:
            raise ClientError("Facebook group feed HTML did not include a pagination cursor.")
        return posts, cursor

    def _extract_group_discussion_request(self, body: str, group_id: str) -> tuple[Dict, str]:
        """Extract the current group discussion Relay variables and document ID."""
        friendly_marker = f'"queryName":"{GROUP_DISCUSSION_FRIENDLY_NAME}"'
        decoder = json.JSONDecoder()
        decoded_variable_keys: List[List[str]] = []
        best_variables: Optional[Dict] = None
        best_document_id: Optional[str] = None
        best_score = -1

        def contains_group_id(value) -> bool:
            if isinstance(value, str):
                return value == group_id
            if isinstance(value, dict):
                return any(contains_group_id(child) for child in value.values())
            if isinstance(value, list):
                return any(contains_group_id(child) for child in value)
            return False

        start = body.find(friendly_marker)
        while start >= 0:
            window_start = max(0, start - 6000)
            window_end = min(len(body), start + 6000)
            window = body[window_start:window_end]

            doc_matches = list(re.finditer(r'"queryID":"(\d+)"', window))
            if doc_matches:
                document_id = doc_matches[-1].group(1)
                variable_markers = [m.start() for m in re.finditer(r'"variables":', window)]
                for marker_index in variable_markers:
                    try:
                        variables, _ = decoder.raw_decode(window, marker_index + len('"variables":'))
                    except json.JSONDecodeError:
                        continue
                    if isinstance(variables, dict):
                        keys = sorted(variables.keys())
                        decoded_variable_keys.append(keys)
                        if contains_group_id(variables):
                            score = 0
                            for key in (
                                "regular_stories_count",
                                "regular_stories_stream_initial_count",
                                "feedLocation",
                                "sortingSetting",
                                "feedbackSource",
                                "groupID",
                            ):
                                if key in variables:
                                    score += 1
                            if score > best_score:
                                best_variables = variables
                                best_document_id = document_id
                                best_score = score
                        continue
                    decoded_variable_keys.append([f"<{type(variables).__name__}>"])

            start = body.find(friendly_marker, start + len(friendly_marker))

        if best_variables is not None and best_document_id is not None:
            return best_variables, best_document_id

        candidates = sorted(set(re.findall(r'"queryName":"([^"]*Group[^"]*)"', body)))[:12]
        title_match = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
        title = html.unescape(re.sub(r"\s+", " ", title_match.group(1))).strip() if title_match else None
        raise ClientError(
            "Facebook group discussion Relay preloader variables were not found. "
            f"Page title: {title!r}. Candidate group queries: {candidates}. "
            f"Decoded variable keys near discussion query: {decoded_variable_keys[:8]}"
        )

    def _graphql_group_discussion_posts(
        self,
        group_id: str,
        body: str,
        count: int,
    ) -> tuple[List[Dict], bool]:
        """Fetch group feed stories through Facebook's discussion Relay query."""
        current_user = self._facebook_server_define(body, "CurrentUserInitialData")
        dtsg = self._facebook_server_define(body, "DTSGInitialData")
        lsd = self._facebook_server_define(body, "LSD")

        user_id = current_user.get("USER_ID")
        fb_dtsg = dtsg.get("token")
        lsd_token = lsd.get("token")
        if not isinstance(user_id, str) or not user_id:
            raise ClientError("Facebook CurrentUserInitialData is missing USER_ID.")
        if not isinstance(fb_dtsg, str) or not fb_dtsg:
            raise ClientError("Facebook DTSGInitialData is missing token.")
        if not isinstance(lsd_token, str) or not lsd_token:
            raise ClientError("Facebook LSD data is missing token.")

        variables, document_id = self._extract_group_discussion_request(body, group_id)
        variables["regular_stories_count"] = count
        variables["regular_stories_stream_initial_count"] = count
        headers = {
            "Origin": FACEBOOK_BASE_URL,
            "Referer": f"{GROUPS_BASE}/{group_id}/",
            "X-FB-Friendly-Name": GROUP_DISCUSSION_FRIENDLY_NAME,
            "X-FB-LSD": lsd_token,
            "Accept-Encoding": "gzip",
        }
        relay_request = RelayFormRequest(
            endpoint=f"{FACEBOOK_BASE_URL}/api/graphql/",
            operation_name=GROUP_DISCUSSION_FRIENDLY_NAME,
            document_id=document_id,
            variables=variables,
            base_fields={
                "av": user_id,
                "__user": user_id,
                "__a": "1",
                "fb_dtsg": fb_dtsg,
                "jazoest": self._facebook_jazoest(fb_dtsg),
                "lsd": lsd_token,
                "fb_api_caller_class": "RelayModern",
                "server_timestamps": "true",
            },
        )
        payloads = RelayGraphQLClient(self._facebook_http_client()).execute(relay_request, headers=headers)
        return self._extract_group_discussion_posts(
            group_id,
            payloads,
            document_id=document_id,
            variable_keys=sorted(variables.keys()),
        )

    def _extract_group_discussion_posts(
        self,
        group_id: str,
        payloads: tuple[Dict, ...],
        *,
        document_id: Optional[str] = None,
        variable_keys: Optional[List[str]] = None,
    ) -> tuple[List[Dict], bool]:
        """Extract Story edges and next-page status from discussion Relay payloads."""
        posts: List[Dict] = []
        has_next_page = False
        for payload in payloads:
            errors = payload.get("errors")
            if errors:
                raise ClientError(
                    "Facebook group feed GraphQL returned errors: "
                    f"{errors}. document_id={document_id!r} variable_keys={variable_keys!r}"
                )

            data = payload.get("data")
            if isinstance(data, dict):
                group = data.get("group")
                if isinstance(group, dict):
                    group_feed = group.get("group_feed")
                    if isinstance(group_feed, dict):
                        edges = group_feed.get("edges")
                        if not isinstance(edges, list):
                            raise ClientError("Facebook group feed GraphQL edges is not a list.")
                        for edge in edges:
                            if not isinstance(edge, dict):
                                raise ClientError("Facebook group feed GraphQL edge is not an object.")
                            node = edge.get("node")
                            if isinstance(node, dict) and node.get("__typename") == "Story":
                                post = self._group_post_from_story_node(group_id, node)
                                comments = self._extract_comments_from_relay_payloads((node,))
                                post["comments"] = comments
                                post["comment_count"] = self._count_comments(comments)
                                post["image_urls"] = self._extract_story_image_urls(node)
                                posts.append(post)
                        page_info = group_feed.get("page_info")
                        if isinstance(page_info, dict):
                            has_next_page_value = page_info.get("has_next_page")
                            if not isinstance(has_next_page_value, bool):
                                raise ClientError("Facebook group feed page_info has_next_page is not boolean.")
                            has_next_page = has_next_page or has_next_page_value

                page_info = data.get("page_info")
                if isinstance(page_info, dict):
                    has_next_page_value = page_info.get("has_next_page")
                    if not isinstance(has_next_page_value, bool):
                        raise ClientError("Facebook group feed page_info has_next_page is not boolean.")
                    has_next_page = has_next_page or has_next_page_value

            label = payload.get("label")
            if isinstance(label, str) and label.endswith("$page_info"):
                payload_data = payload.get("data")
                if not isinstance(payload_data, dict):
                    raise ClientError("Facebook streamed group feed page_info payload is missing data.")
                page_info = payload_data.get("page_info")
                if not isinstance(page_info, dict):
                    raise ClientError("Facebook streamed group feed payload is missing page_info.")
                next_cursor_value = page_info.get("end_cursor")
                has_next_page_value = page_info.get("has_next_page")
                if next_cursor_value is not None and not isinstance(next_cursor_value, str):
                    raise ClientError("Facebook streamed group feed end_cursor is not a string.")
                if not isinstance(has_next_page_value, bool):
                    raise ClientError("Facebook streamed group feed has_next_page is not boolean.")
                has_next_page = has_next_page or has_next_page_value

        return posts, has_next_page

    @staticmethod
    def _parse_aria_label(aria: str) -> Optional[Dict[str, Optional[str]]]:
        """Classify an aria-label as a comment or reply.

        Returns None if the label is not a comment/reply (e.g. the post itself
        or an unrelated article).
        """
        if not isinstance(aria, str) or not aria:
            return None
        # Reply first — "Reply by X to Y's comment ..."
        m = re.match(r"^Reply by (.+?) to (.+?)'s comment(?:\s.*)?$", aria)
        if m:
            return {"kind": "reply", "author": m.group(1).strip(), "parent_author": m.group(2).strip()}
        m = re.match(r"^Comment by (.+?)(?:\s\d.*|\s[a-z]+ ago.*|\sjust now.*|\sEdited.*|\sYesterday.*)?$", aria)
        if m:
            return {"kind": "comment", "author": m.group(1).strip(), "parent_author": None}
        # Fallback: "Comment by X" with no age suffix
        m = re.match(r"^Comment by (.+)$", aria)
        if m:
            return {"kind": "comment", "author": m.group(1).strip(), "parent_author": None}
        return None

    def _extract_comments_from_rendered_page(self, page, post_id: str) -> List[Dict]:
        """Scrape comments from an already-rendered post page.

        Facebook lazy-loads replies. The caller is responsible for loading the
        permalink first. This method expands every "View N replies" /
        "View more replies" button until no new ones appear, then parses every
        role="article" element inside the dialog.

        Each article is classified via aria-label:
          - "Comment by X"                      -> top-level comment
          - "Reply by X to Y's comment"         -> nested reply (parent=Y)

        Parent/child linkage comes from the comment permalink href, which for
        replies contains `comment_id=PARENT_LEGACY_ID&reply_comment_id=SELF_LEGACY_ID`
        and for top-level comments contains only `comment_id=SELF_LEGACY_ID`.

        Fails loudly (raises ClientError) if:
          - The dialog cannot be located,
          - An article is missing a recognizable aria-label,
          - A reply's parent comment_id cannot be resolved.
        """
        # Iteratively expand "View N replies" / "View more replies" buttons.
        expand_js = r"""
        () => {
          const dialog = document.querySelector('[role="dialog"]') || document.body;
          const els = Array.from(dialog.querySelectorAll('div[role="button"], span, a'));
          const clicks = [];
          for (const el of els) {
            const t = (el.innerText || "").trim();
            if (/^View\s+\d+\s+repl/i.test(t) || /^View\s+more\s+repl/i.test(t)) {
              const target = el.closest('div[role="button"]') || el;
              try { target.click(); clicks.push(t); } catch(e) {}
            }
          }
          return clicks;
        }
        """
        total_clicked: List[str] = []
        for _ in range(5):
            clicked = page.evaluate(expand_js)
            if not isinstance(clicked, list):
                raise ClientError("Reply-expansion evaluator did not return a list.")
            if not clicked:
                break
            total_clicked.extend(clicked)
            page.wait_for_timeout(2000)
        logger.debug("_extract_comments_from_rendered_page: expanded %d reply threads", len(total_clicked))

        # Harvest every [role="article"] inside the dialog (or main, if permalink
        # rendered inline rather than as a dialog).
        harvest_js = r"""
        () => {
          const dialog = document.querySelector('[role="dialog"]');
          const scope = dialog || document.querySelector('[role="main"]');
          if (!scope) return {error: "no dialog or main scope"};
          const arts = Array.from(scope.querySelectorAll('[role="article"]'));
          const out = [];
          for (let i = 0; i < arts.length; i++) {
            const a = arts[i];
            const aria = a.getAttribute("aria-label");
            let permalink = null;
            const anchors = a.querySelectorAll('a[href*="comment_id="]');
            for (const anc of anchors) {
              const h = anc.getAttribute("href") || "";
              if (h.indexOf("comment_id=") !== -1) { permalink = h; break; }
            }
            // Body text: longest [dir="auto"] inside the article is the comment body.
            const autos = Array.from(a.querySelectorAll('[dir="auto"]'))
              .map(n => (n.innerText || "").trim())
              .filter(t => t.length > 0);
            autos.sort((x, y) => y.length - x.length);
            const body = autos.length ? autos[0] : null;
            // Author name — first anchor inside an h3/h4/strong is the author link.
            let authorFromDom = null;
            const h3 = a.querySelector('h3 a, h4 a, strong a');
            if (h3) authorFromDom = (h3.innerText || "").trim();
            // Timestamp — no stable ISO timestamp exposed in the DOM; leave null.
            let timeText = null;
            const timeEl = a.querySelector('a[aria-label][role="link"] abbr, [data-visualcompletion="ignore-dynamic"] abbr');
            if (timeEl) timeText = (timeEl.getAttribute("aria-label") || timeEl.innerText || "").trim() || null;
            out.push({
              domIndex: i,
              aria: aria,
              permalink: permalink,
              body: body,
              authorFromDom: authorFromDom,
              timeText: timeText,
            });
          }
          return {articles: out};
        }
        """
        harvested = page.evaluate(harvest_js)
        if not isinstance(harvested, dict):
            raise ClientError("Comment harvester did not return an object.")
        if harvested.get("error"):
            raise ClientError(f"Comment harvester failed: {harvested['error']}")
        articles = harvested.get("articles")
        if not isinstance(articles, list):
            raise ClientError("Comment harvester returned no articles array.")

        # Parse each article. Extract:
        #   self_legacy_id  = reply_comment_id or comment_id from permalink
        #   parent_legacy_id = comment_id from permalink ONLY if reply_comment_id present
        flat: List[Dict] = []
        by_self_id: Dict[str, Dict] = {}
        for art in articles:
            aria = art.get("aria")
            parsed = self._parse_aria_label(aria) if aria else None
            if parsed is None:
                # Not all [role="article"] elements inside the dialog are comments
                # (the post itself, empty wrapper articles, etc.). Skip silently
                # — we only consume articles whose aria-label identifies them.
                continue
            permalink = art.get("permalink")
            if not isinstance(permalink, str) or "comment_id=" not in permalink:
                raise ClientError(
                    f"Comment article missing permalink href: aria-label={aria!r}"
                )
            # reply_comment_id takes precedence as the "self" id for replies.
            reply_match = re.search(r"reply_comment_id=(\d+)", permalink)
            cid_match = re.search(r"comment_id=(\d+)", permalink)
            if not cid_match:
                raise ClientError(f"Permalink missing comment_id: {permalink}")
            if parsed["kind"] == "reply":
                if not reply_match:
                    raise ClientError(
                        f"Reply article permalink missing reply_comment_id: aria={aria!r} href={permalink}"
                    )
                self_id = reply_match.group(1)
                parent_id = cid_match.group(1)
            else:
                # Top-level comment — reply_comment_id must NOT be present.
                self_id = cid_match.group(1)
                parent_id = None

            author = art.get("authorFromDom") or parsed.get("author")
            if not author:
                raise ClientError(f"Comment article has no author: aria={aria!r}")
            text = art.get("body")
            if text is None:
                raise ClientError(f"Comment article has no text body: aria={aria!r}")
            # Strip a leading duplicate of the author name that Facebook renders
            # at the top of every reply (e.g. "Author Name\nReply text ...").
            if isinstance(text, str) and text.startswith(author + "\n"):
                text = text[len(author) + 1 :]
            # Some replies begin with "<ParentAuthor> " as a mention prefix;
            # the agent surface should keep it since it is user-typed content.

            entry = {
                "_self_id": self_id,
                "_parent_id": parent_id,
                "_kind": parsed["kind"],
                "_parent_author_aria": parsed.get("parent_author"),
                "comment_id": self_id,
                "author": author,
                "text": text,
                "created_time": None,  # DOM does not expose a stable ISO timestamp
                "replies": [],
            }
            # Deduplicate by self_id — Facebook sometimes renders the same
            # comment twice (e.g. a parent summary and then within a thread).
            if self_id in by_self_id:
                continue
            by_self_id[self_id] = entry
            flat.append(entry)

        # Attach replies to their parent comments. Parent linkage is the
        # reply's comment_id (parent_id) -> another entry's self_id.
        top: List[Dict] = []
        for entry in flat:
            if entry["_kind"] == "reply":
                parent = by_self_id.get(entry["_parent_id"])
                if parent is None:
                    # Fallback: DOM order — the nearest preceding top-level
                    # comment whose author matches parent_author_aria.
                    parent = self._find_parent_by_dom_order(
                        flat, entry, parent_author=entry["_parent_author_aria"]
                    )
                if parent is None:
                    raise ClientError(
                        f"Could not resolve parent for reply {entry['_self_id']} "
                        f"(aria suggested parent author {entry['_parent_author_aria']!r}, "
                        f"parent comment_id {entry['_parent_id']!r}). "
                        "Parent comment is missing from the rendered DOM — "
                        "did 'View replies' expansion complete?"
                    )
                parent["replies"].append(entry)
            else:
                top.append(entry)

        # Strip internal fields before returning.
        def clean(entries: List[Dict]) -> List[Dict]:
            out = []
            for e in entries:
                out.append({
                    "comment_id": e["comment_id"],
                    "author": e["author"],
                    "text": e["text"],
                    "created_time": e["created_time"],
                    "replies": clean(e["replies"]),
                })
            return out

        return clean(top)

    @staticmethod
    def _find_parent_by_dom_order(
        flat: List[Dict], reply_entry: Dict, parent_author: Optional[str]
    ) -> Optional[Dict]:
        """Locate the most recent preceding comment entry that matches the
        aria-label's parent author. Used only when the reply's comment_id
        does not resolve to a parent's self_id in the harvested set.
        """
        reply_index = None
        for i, e in enumerate(flat):
            if e is reply_entry:
                reply_index = i
                break
        if reply_index is None:
            return None
        for i in range(reply_index - 1, -1, -1):
            candidate = flat[i]
            if candidate["_kind"] != "comment":
                continue
            if parent_author and candidate["author"] != parent_author:
                continue
            return candidate
        return None

    def _count_comments(self, comments: List[Dict]) -> int:
        """Total comment count including replies."""
        total = 0
        for c in comments:
            total += 1 + self._count_comments(c.get("replies", []))
        return total

    def _find_story_node_by_post_id(self, value, post_id: str) -> Optional[Dict]:
        """Find a full Story node with the requested post_id inside a Relay payload."""
        matches: List[Dict] = []

        def visit(current) -> None:
            if isinstance(current, dict):
                if current.get("post_id") == post_id:
                    matches.append(current)
                for child in current.values():
                    visit(child)
            elif isinstance(current, list):
                for child in current:
                    visit(child)

        visit(value)
        for match in matches:
            author = self._extract_text_path(match, ["feedback", "owning_profile", "name"])
            if author is not None:
                return match
        return matches[0] if matches else None

    def _extract_group_posts(self, page) -> List[Dict]:
        """Extract posts from a Facebook Group feed via h2 author elements.

        Facebook's authenticated group feed renders posts inside a [role="feed"]
        container. Each post has an h2 with the author name, followed by post
        text in [dir="auto"] elements, and reaction counts in "All reactions: N"
        text. Timestamps are obfuscated (individual scrambled characters) and
        cannot be reliably extracted.

        Returns:
            List of post dicts with post_id, author, text, url,
            reactions, comments.
        """
        js = (
            '() => {'
            ' const feed = document.querySelector(\'[role="feed"]\');'
            ' if (!feed) return [];'
            ' const h2s = [...feed.querySelectorAll("h2")];'
            ' const posts = [];'
            ' const seen = new Set();'
            ' for (const h2 of h2s) {'
            '   const authorText = (h2.innerText || "").trim();'
            '   if (!authorText || authorText.length > 80'
            '       || authorText === "New posts"'
            '       || authorText.toLowerCase().includes("sort")) continue;'
            # Walk up to find the post container (has Like/Comment buttons)
            '   let container = h2;'
            '   for (let i = 0; i < 15; i++) {'
            '     container = container.parentElement;'
            '     if (!container) break;'
            '     const t = (container.innerText || "");'
            '     if (t.includes("Like") && t.includes("Comment") && t.length > 50) break;'
            '   }'
            '   if (!container) continue;'
            # Post text: longest dir="auto" block, skip scrambled timestamps
            '   let text = "";'
            '   const dirAutos = container.querySelectorAll(\'[dir="auto"]\');'
            '   for (const el of dirAutos) {'
            '     const t = (el.innerText || "").trim();'
            # Skip: author name, UI labels, scrambled timestamps (single chars with spaces)
            '     if (t === authorText || t === "Like" || t === "Share"'
            '         || t.includes("Comment as") || t.length < 3) continue;'
            # Skip scrambled timestamp text: mostly single chars with no spaces/words
            '     const lines = t.split("\\n");'
            '     const singleCharLines = lines.filter(l => l.trim().length <= 2).length;'
            '     if (lines.length > 5 && singleCharLines / lines.length > 0.5) continue;'
            # Also skip text that looks like concatenated single chars (no spaces, no real words)
            '     const words = t.split(/\\s+/).filter(w => w.length > 0);'
            '     const avgWordLen = words.reduce((s, w) => s + w.length, 0) / (words.length || 1);'
            '     if (words.length <= 3 && avgWordLen > 15 && !t.includes(" ")) continue;'
            '     if (t.length > text.length) text = t;'
            '   }'
            # Fallback: h3 strong content
            '   if (!text) {'
            '     const h3 = container.querySelector("h3 strong, h3");'
            '     if (h3) { const t = (h3.innerText||"").trim(); if (t) text = t; }'
            '   }'
            # Reactions
            '   let reactions = 0;'
            '   const allText = container.innerText || "";'
            '   const rxm = allText.match(/All reactions:[\\s\\n]*(\\d+)/);'
            '   if (rxm) reactions = parseInt(rxm[1]);'
            # Comments
            '   let comments = 0;'
            '   const cm = allText.match(/(\\d+)\\s+comments?/i);'
            '   if (cm) comments = parseInt(cm[1]);'
            # Post ID: require a stable permalink.
            '   let postId = ""; let postUrl = "";'
            '   const links = [...container.querySelectorAll("a")];'
            '   for (const a of links) {'
            '     const href = a.href || "";'
            '     const m = href.match(/\\/posts\\/(\\d+)/) || href.match(/\\/permalink\\/(\\d+)/);'
            '     if (m) { postId = m[1]; postUrl = href.split("?")[0]; break; }'
            '   }'
            '   if (!postId) continue;'
            '   if (seen.has(postId)) continue;'
            '   seen.add(postId);'
            '   const summaryText = text.substring(0, 500);'
            '   posts.push({post_id: postId, title: null, author: authorText, text: summaryText, body: summaryText,'
            '     url: postUrl, thread_url: postUrl, reactions: reactions, comment_count: comments, image_urls: null});'
            ' }'
            ' return posts;'
            ' }'
        )
        result = page.evaluate(js)
        return result if isinstance(result, list) else []

    def _list_group_post_summaries(self, group_id: str, limit: int) -> List[GroupPost]:
        """List summary posts from a Facebook Group feed."""
        body = self._fetch_authenticated_facebook_bootstrap_html(f"{GROUPS_BASE}/{group_id}/")
        fetch_count = limit + 5
        fetched_posts, _has_next_page = self._graphql_group_discussion_posts(group_id, body, fetch_count)
        if not fetched_posts:
            raise ClientError("Facebook group discussion GraphQL did not return any posts.")

        items: List[Dict] = []
        seen_ids = set()
        for post in fetched_posts:
            post_id = post["post_id"]
            if post_id in seen_ids:
                continue
            seen_ids.add(post_id)
            items.append(post)
            if len(items) >= limit:
                break

        if len(items) < limit:
            raise ClientError(f"Facebook group discussion GraphQL returned {len(items)} unique posts; expected {limit}.")

        return [GroupPost(**p) for p in items]

    def list_group_posts(self, group_id: str, limit: int = 20, full_threads: bool = False) -> List[GroupPost]:
        """List posts from a Facebook Group."""
        posts = self._list_group_post_summaries(group_id, limit)
        if not full_threads:
            return posts

        self._facebook_http_client()

        def fetch(post: GroupPost) -> GroupPost:
            if not post.thread_url:
                raise ClientError(f"Facebook group post {post.post_id} is missing thread_url.")
            body = self._fetch_authenticated_facebook_page(
                post.thread_url,
                stop_markers=GROUP_POST_THREAD_STOP_MARKERS,
            )
            return self._full_group_post_from_html(
                group_id,
                post.post_id,
                post.thread_url,
                body,
                allow_truncated_tail=True,
            )

        results: Dict[str, GroupPost] = {}
        with ThreadPoolExecutor(max_workers=len(posts)) as executor:
            futures = {executor.submit(fetch, post): post.post_id for post in posts}
            for future in as_completed(futures):
                post_id = futures[future]
                results[post_id] = future.result()

        return [results[post.post_id] for post in posts]

    def get_group_post(self, post_ref: str) -> GroupPost:
        """Get a specific post from a Facebook Group.

        Args:
            post_ref: Full URL or path like 'group_id/posts/post_id'.

        Returns:
            GroupPost with post details.
        """
        ref = self._group_post_ref_parts(post_ref)
        url = ref["url"]
        group_id = ref["group_id"]
        post_id = ref["post_id"]

        body = self._fetch_authenticated_facebook_page(
            url,
            stop_markers=GROUP_POST_THREAD_STOP_MARKERS,
        )
        return self._full_group_post_from_html(
            group_id,
            post_id,
            url,
            body,
            allow_truncated_tail=True,
        )

    def create_group_post(self, group_id: str, text: str) -> Dict:
        """Create a new post in a Facebook Group.

        Args:
            group_id: The group ID.
            text: The post content text.

        Returns:
            Dict with success status.
        """
        print_info(f"Creating post in group {group_id}...")
        page = self._get_page(f"{GROUPS_BASE}/{group_id}/", settle_ms=0)

        # Wait for feed to load
        page.wait_for_selector('[role="feed"]', timeout=15000)

        # Click the post composer to activate it
        js_activate = (
            '() => {'
            ' const buttons = document.querySelectorAll(\'[role="button"]\');'
            ' for (const btn of buttons) {'
            '   const t = (btn.innerText || "").toLowerCase();'
            '   if (t.includes("write something") || t.includes("what\'s on your mind")) {'
            '     btn.click();'
            '     return {success: true};'
            '   }'
            ' }'
            ' return {success: false, error: "Post composer not found"};'
            ' }'
        )
        activated = page.evaluate(js_activate)
        if not isinstance(activated, dict) or not activated.get("success"):
            raise ClientError(f"Failed to open post composer: {(activated or {}).get('error', 'unknown')}")

        page.wait_for_selector('[role="textbox"][contenteditable="true"]', timeout=10000)

        # Type text into the composer textbox
        js_type = (
            '(text) => {'
            ' const boxes = document.querySelectorAll(\'[role="textbox"][contenteditable="true"]\');'
            ' if (!boxes.length) return {success: false, error: "Composer textbox not found"};'
            # Use the last textbox (the dialog composer, not inline)
            ' const box = boxes[boxes.length - 1];'
            ' box.focus();'
            ' document.execCommand("insertText", false, text);'
            ' return {success: true};'
            ' }'
        )
        typed = page.evaluate(js_type, text)
        if not isinstance(typed, dict) or not typed.get("success"):
            raise ClientError(f"Failed to type post: {(typed or {}).get('error', 'unknown')}")

        page.wait_for_timeout(1000)

        # Click the Post button
        js_submit = (
            '() => {'
            ' const buttons = document.querySelectorAll(\'[role="button"]\');'
            ' for (const btn of buttons) {'
            '   const label = (btn.getAttribute("aria-label") || "").toLowerCase();'
            '   const text = (btn.innerText || "").trim();'
            '   if (text === "Post" || label === "post") {'
            '     btn.click();'
            '     return {success: true};'
            '   }'
            ' }'
            ' return {success: false, error: "Post button not found"};'
            ' }'
        )
        submitted = page.evaluate(js_submit)
        if not isinstance(submitted, dict) or not submitted.get("success"):
            raise ClientError(f"Failed to submit post: {(submitted or {}).get('error', 'unknown')}")

        self._wait_for_rendered_text(page, text, selector='[role="feed"]', timeout_ms=20000)

        return {"success": True, "verified": True, "group_id": group_id, "text": text}

    def comment_on_post(self, post_url: str, text: str) -> Dict:
        """Comment on a Facebook Group post.

        Args:
            post_url: Full post URL or path like 'group_id/posts/post_id'.
            text: The comment text.

        Returns:
            Dict with success status.
        """
        ref = self._group_post_ref_parts(post_url)
        url = ref["url"]
        group_id = ref["group_id"]
        post_id = ref["post_id"]

        print_info("Commenting on post...")
        page = self._get_page(url, settle_ms=0)
        page.wait_for_selector('[role="main"]', timeout=15000)

        # Activate the post's comment control if the composer is not already
        # visible. On current Facebook post pages the Lexical textbox is often
        # created lazily only after clicking Comment.
        #
        # We navigated to the canonical single-post permalink URL, so the
        # [role="main"] region isolates exactly one target post (the post body,
        # its comment composer, and the existing comments). We therefore scope
        # the activator to [role="main"] and require a UNIQUE comment surface
        # there, rather than to a [role="article"] element.
        #
        # Why not scope to a [role="article"]: Facebook moved the post-permalink
        # anchor and the comment controls OUT of the [role="article"] wrapper
        # that sits in [role="main"]. The article wrappers are now empty of the
        # post's permalink anchor and comment controls (verified against the live
        # DOM), so the old "one article containing BOTH a matching permalink link
        # AND a comment control" requirement matched 0 articles and aborted with
        # "Expected one target article ... found 0". The permalink-page scoping
        # below is the resilient replacement: post identity is already pinned by
        # the canonical URL we navigated to, and the post-write verifier
        # (_wait_for_comment_on_exact_post) confirms the comment landed on the
        # exact post id afterward.
        js_activate = (
            '(args) => {'
            ' const isVisible = (el) => {'
            '   const r = el.getBoundingClientRect();'
            '   return r.width > 0 && r.height > 0;'
            ' };'
            ' const main = document.querySelector(\'[role="main"]\');'
            ' if (!main) return {success: false, error: "Main region not found"};'
            ' const composerSelector ='
            '   \'[role="textbox"][contenteditable="true"][data-lexical-editor="true"]\';'
            # The comment composer is rendered in a React portal OUTSIDE
            # [role="main"] (verified against the live DOM: the single visible
            # Lexical composer has inMain === false). So detect the
            # already-visible composer DOCUMENT-WIDE, not under [role="main"].
            # On this single-post permalink page there is exactly one target
            # post, so a single visible Lexical composer is unambiguous. This
            # mirrors how js_comment below locates the box to type into.
            ' const visibleComposers = Array.from(document.querySelectorAll(composerSelector))'
            '   .filter(isVisible);'
            ' if (visibleComposers.length === 1) {'
            '   return {success: true, alreadyVisible: true};'
            ' }'
            ' if (visibleComposers.length > 1) {'
            '   return {success: false, error: "Multiple visible comment composers on page (" + visibleComposers.length + ")"};'
            ' }'
            # No composer rendered yet — find and click the post\'s Comment
            # activator within [role="main"]. Prefer an exact "comment" text
            # control, then a comment-related aria-label. Require uniqueness so we
            # cannot click the wrong control.
            ' const clickables = Array.from(main.querySelectorAll('
            '   \'button, [role="button"], a\''
            ' )).filter(isVisible);'
            ' const exactText = clickables.filter(el => (el.innerText || "").trim().toLowerCase() === "comment");'
            ' if (exactText.length === 1) {'
            '   exactText[0].click();'
            '   return {success: true, alreadyVisible: false, activator: "exact-comment-text"};'
            ' }'
            ' if (exactText.length > 1) {'
            '   return {success: false, error: "Multiple exact Comment activators in main region (" + exactText.length + ")"};'
            ' }'
            ' const labelMatches = clickables.filter(el => {'
            '   const label = (el.getAttribute("aria-label") || "").trim().toLowerCase();'
            '   return label === "leave a comment"'
            '     || label === "write a comment"'
            '     || label.includes("comment as");'
            ' });'
            ' if (labelMatches.length === 1) {'
            '   labelMatches[0].click();'
            '   return {success: true, alreadyVisible: false, activator: "comment-label"};'
            ' }'
            ' if (labelMatches.length > 1) {'
            '   return {success: false, error: "Multiple labeled comment activators in main region (" + labelMatches.length + ")"};'
            ' }'
            ' return {success: false, error: "Comment activator not found in main region"};'
            ' }'
        )
        activated = page.evaluate(js_activate, {"groupId": group_id, "postId": post_id})
        if not isinstance(activated, dict) or not activated.get("success"):
            raise ClientError(f"Failed to activate comment composer: {(activated or {}).get('error', 'unknown')}")
        if not activated.get("alreadyVisible"):
            page.wait_for_selector(
                '[role="textbox"][contenteditable="true"][data-lexical-editor="true"]',
                timeout=10000,
            )

        # Find and focus the comment box.
        # Facebook personalizes the aria-placeholder/aria-label (e.g. "Answer as ...",
        # "Write a comment…", "Comment as …"), so we cannot rely on placeholder text
        # matching. The comment-dialog composer is also rendered in a React portal
        # outside [role="main"], so we scope to the full document and pick the unique
        # visible [role="textbox"][contenteditable="true"][data-lexical-editor="true"].
        # Fail loudly if that invariant ever breaks — no fallbacks.
        js_comment = (
            '(text) => {'
            ' const candidates = Array.from(document.querySelectorAll('
            '   \'[role="textbox"][contenteditable="true"][data-lexical-editor="true"]\''
            ' )).filter(el => {'
            '   const r = el.getBoundingClientRect();'
            '   return r.width > 0 && r.height > 0;'
            ' });'
            ' if (candidates.length === 0) {'
            '   return {success: false, error: "Comment composer not found (no visible Lexical textbox on page)"};'
            ' }'
            ' if (candidates.length > 1) {'
            '   const descs = candidates.map(el => ('
            '     (el.getAttribute("aria-placeholder") || el.getAttribute("aria-label") || "?")'
            '   )).join(" | ");'
            '   return {success: false, error: "Multiple Lexical composers found (ambiguous): " + descs};'
            ' }'
            ' const commentBox = candidates[0];'
            ' commentBox.focus();'
            ' document.execCommand("insertText", false, text);'
            ' return {'
            '   success: true,'
            '   placeholder: commentBox.getAttribute("aria-placeholder") || commentBox.getAttribute("aria-label") || ""'
            ' };'
            ' }'
        )
        typed = page.evaluate(js_comment, text)
        if not isinstance(typed, dict) or not typed.get("success"):
            raise ClientError(f"Failed to type comment: {(typed or {}).get('error', 'unknown')}")

        page.wait_for_timeout(500)

        # Snapshot the comment count BEFORE submit so the verifier has a
        # delta signal to corroborate the composer-cleared check.
        comment_count_before = self._count_post_comments(page)

        # Press Enter to submit the comment
        js_submit = (
            '() => {'
            ' const boxes = document.querySelectorAll(\'[role="textbox"][contenteditable="true"]\');'
            ' for (const box of boxes) {'
            '   if (box.textContent && box.textContent.trim().length > 0) {'
            '     box.dispatchEvent(new KeyboardEvent("keydown",'
            '       {key: "Enter", code: "Enter", keyCode: 13, bubbles: true}));'
            '     return {success: true};'
            '   }'
            ' }'
            ' return {success: false, error: "Could not find filled comment box"};'
            ' }'
        )
        submitted = page.evaluate(js_submit)
        if not isinstance(submitted, dict) or not submitted.get("success"):
            raise ClientError(f"Failed to submit comment: {(submitted or {}).get('error', 'unknown')}")

        composer_state = self._wait_for_composer_cleared(page, timeout_ms=10000)
        if not composer_state.get("cleared"):
            raise ClientError(
                "Comment submit did not clear the composer for the exact target post "
                f"{post_id}. Composer remaining text: {composer_state.get('remaining', [])}."
            )
        verification = self._wait_for_comment_on_exact_post(
            group_id,
            post_id,
            text,
            timeout_ms=20000,
        )
        verification["composer"] = composer_state
        verification["commentCountBefore"] = comment_count_before

        return {
            "success": True,
            "verified": verification["verification"] == "confirmed",
            "verification": verification["verification"],
            "verificationDetails": verification,
            "post_url": post_url,
            "group_id": group_id,
            "post_id": post_id,
            "text": text,
        }

    def reply_to_comment(self, post_url: str, comment_index: int, text: str) -> Dict:
        """Reply to a specific comment on a Facebook Group post.

        Args:
            post_url: Full post URL or path like 'group_id/posts/post_id'.
            comment_index: 1-based index of the comment to reply to.
            text: The reply text.

        Returns:
            Dict with success status.
        """
        if post_url.startswith("http"):
            url = post_url
        else:
            url = f"https://www.facebook.com/groups/{post_url}"

        print_info(f"Replying to comment #{comment_index}...")
        page = self._get_page(url, settle_ms=0)
        page.wait_for_selector('[role="main"]', timeout=15000)

        # Click the Reply link on the Nth comment
        js_reply = (
            '(commentIndex) => {'
            # Find all "Reply" links/buttons inside the post article.
            ' const replyLinks = [];'
            ' const allEls = document.querySelectorAll(\'[role="article"] [role="button"], [role="article"] a, [role="article"] span\');'
            ' for (const el of allEls) {'
            '   const text = (el.innerText || "").trim();'
            '   if (text === "Reply" || text === "reply") {'
            '     replyLinks.push(el);'
            '   }'
            ' }'
            ' if (commentIndex < 1 || commentIndex > replyLinks.length) {'
            '   return {success: false, error: "Comment index " + commentIndex + " out of range (found " + replyLinks.length + " comments)"};'
            ' }'
            ' replyLinks[commentIndex - 1].click();'
            ' return {success: true, total_comments: replyLinks.length};'
            ' }'
        )
        clicked = page.evaluate(js_reply, comment_index)
        if not isinstance(clicked, dict) or not clicked.get("success"):
            raise ClientError(f"Failed to click Reply: {(clicked or {}).get('error', 'unknown')}")

        page.wait_for_selector('[role="textbox"][contenteditable="true"]', timeout=10000)

        # Type into the reply textbox (should be the most recently focused/appearing textbox)
        js_type = (
            '(text) => {'
            ' const boxes = document.querySelectorAll(\'[role="textbox"][contenteditable="true"]\');'
            ' if (!boxes.length) return {success: false, error: "Reply textbox not found"};'
            # The reply textbox is typically the last one that appeared
            ' const box = boxes[boxes.length - 1];'
            ' box.focus();'
            ' document.execCommand("insertText", false, text);'
            ' return {success: true};'
            ' }'
        )
        typed = page.evaluate(js_type, text)
        if not isinstance(typed, dict) or not typed.get("success"):
            raise ClientError(f"Failed to type reply: {(typed or {}).get('error', 'unknown')}")

        page.wait_for_timeout(500)

        # Press Enter to submit
        js_submit = (
            '() => {'
            ' const boxes = document.querySelectorAll(\'[role="textbox"][contenteditable="true"]\');'
            ' for (const box of boxes) {'
            '   if (box.textContent && box.textContent.trim().length > 0) {'
            '     box.dispatchEvent(new KeyboardEvent("keydown",'
            '       {key: "Enter", code: "Enter", keyCode: 13, bubbles: true}));'
            '     return {success: true};'
            '   }'
            ' }'
            ' return {success: false, error: "Could not find filled reply box"};'
            ' }'
        )
        # Snapshot count before submitting the reply (replies are nested
        # articles too, so the count delta still applies).
        comment_count_before = self._count_post_comments(page)

        submitted = page.evaluate(js_submit)
        if not isinstance(submitted, dict) or not submitted.get("success"):
            raise ClientError(f"Failed to submit reply: {(submitted or {}).get('error', 'unknown')}")

        # Same multi-stage verification as comment_on_post.
        verification = self._verify_comment_landed(
            page, text, comment_count_before,
            composer_timeout_ms=10000, secondary_timeout_ms=10000,
        )

        return {
            "success": True,
            "verified": verification["verification"] == "confirmed",
            "verification": verification["verification"],
            "verificationDetails": verification,
            "post_url": post_url,
            "comment_index": comment_index,
            "text": text,
        }

    def list_requests(self, limit: int = 20) -> List[Dict]:
        """List Messenger message requests.

        Args:
            limit: Maximum number of requests to return.

        Returns:
            List of message request dicts.
        """
        from .messenger_parsers import extract_conversations_from_snapshot

        print_info("Loading message requests...")
        requested_url = "https://www.facebook.com/messages/filtered/"
        page = self._get_page(requested_url)
        self._assert_authenticated_page(page, requested_url, "Messenger message requests")
        page.wait_for_timeout(1000)  # extra wait

        snapshot = self._snapshot(page)
        requests = extract_conversations_from_snapshot(snapshot)
        return requests[:limit]


def get_client() -> FacebookClient:
    return FacebookClient()
