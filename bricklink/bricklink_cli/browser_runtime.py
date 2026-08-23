"""Browser automation service for Bricklink.

Handles operations not available via API:
- Messages (list, view, send, reply, mark read/unread)
- Refunds (info, issue, full)
- Order search by item
- Wanted list notifications

Uses BrowserAutomation base class with playwright CLI for session management.
"""
import re
import time
from typing import Optional

from cli_tools_shared.activity_log import get_activity_logger
from cli_tools_shared.data_cache import cached

from .browser import BricklinkBrowser
from .config import get_config
from .confirmation import (
    ConfirmationRequiredError,
    ConfirmationState,
    is_confirmation_code_page_url,
)
from .models import RefundReason
from .managed_auth import get_bricklink_confirmation_code

activity = get_activity_logger("bricklink")


class BricklinkRuntimeBrowser(BricklinkBrowser):
    """Bricklink browser automation using shared BrowserAutomation base."""

    NAVIGATION_READY_STATE = "domcontentloaded"

    def __init__(self, config=None):
        config = config or get_config()
        super().__init__(config)
        self.confirmation = ConfirmationState(self._get_browser_data_dir())
        activity.info("BricklinkBrowser initialized")

    def _is_auth_failure_page(self, url_or_page) -> bool:
        url = getattr(url_or_page, "url", url_or_page) or ""
        return bool(re.search(self.AUTH_FAILURE_URL_PATTERN, url))

    def _is_confirmation_code_page(self, url_or_page) -> bool:
        """Return True when the current page is BrickLink's email-code gate."""
        url = getattr(url_or_page, "url", url_or_page) or ""
        return is_confirmation_code_page_url(url)

    def _check_auth(self, page) -> bool:
        if self._is_auth_failure_page(page):
            return False
        return super()._check_auth(page)

    def _goto_page(self, page, url: str) -> None:
        # BrickLink can keep background requests open; selectors prove readiness.
        try:
            page.goto(url, wait_until=self.NAVIGATION_READY_STATE)
        except Exception as exc:
            if "net::ERR_ABORTED" not in str(exc):
                raise
            activity.warning(
                "Bricklink navigation aborted for %s; checking whether page rendered",
                url,
            )
        page.wait_for_selector("body", state="visible", timeout=15000)

    def _read_confirmation_code(self) -> str:
        return get_bricklink_confirmation_code(requested_after=int(time.time()) - 120)

    def _submit_confirmation_code(self, page, requested_url: str) -> None:
        code_input = page.query_selector("#confirmation-code")
        if not code_input:
            raise RuntimeError(
                "BrickLink confirmation code input #confirmation-code was not found. "
                f"URL: {page.url}"
            )
        code_input.fill(self._read_confirmation_code())
        submitted = page.evaluate(
            """() => {
                const buttons = Array.from(document.querySelectorAll('button'));
                const button = buttons.find((b) => (b.innerText || '').trim() === 'Submit');
                if (!button) return false;
                button.click();
                return true;
            }"""
        )
        if not submitted:
            raise RuntimeError(
                "BrickLink confirmation code Submit button was not found. "
                f"URL: {page.url}"
            )
        page.wait_for_timeout(2000)
        self._goto_page(page, requested_url)
        if self._is_confirmation_code_page(page):
            raise ConfirmationRequiredError("this operation")

    def _handle_confirmation_code_page(self, page, requested_url: str) -> None:
        if not self._is_confirmation_code_page(page):
            return
        activity.warning("Email confirmation required at %s", page.url)
        self._submit_confirmation_code(page, requested_url)

    def _check_session_expired(self, page):
        """Check if page was redirected to login / confirmation and raise if so.

        On a session-expired URL match, auto-clear the persistent browser
        profile via ``self.clear_session()`` and raise an actionable error
        naming the exact recovery command. The ``try/finally`` guarantees
        the actionable message reaches the user even when
        ``clear_session()`` itself fails (e.g. disk error) — silent
        clear-failure would leave the user staring at a misleading
        exception and a still-corrupt profile.
        """
        if self._is_confirmation_code_page(page):
            activity.warning("Email confirmation required at %s", page.url)
            raise ConfirmationRequiredError("this operation")
        if self._is_login_page(page):
            activity.error("Session expired — redirected to %s", page.url)
            try:
                self.clear_session()
            finally:
                raise RuntimeError(
                    "Bricklink session expired. "
                    "Run 'bricklink auth login --credential-type browser_session' "
                    "to re-authenticate."
                )

    # Bricklink server-error landing pages.
    #
    # When a requested URL is dead (404), broken (500), or otherwise rejected
    # by Bricklink's app server, the response is a redirect to
    # ``/oops.asp?err=<code>`` rendering a generic "HTTP Error <code>" page.
    # The redirect target still lives under ``bricklink.com`` and returns
    # HTTP 200, so an unsuspecting parser sees a valid page with zero
    # business-data elements and reports "0 matches" — silently masking
    # a dead endpoint as an empty result. ``_check_server_error`` raises
    # loudly with BOTH URLs in the message so the caller can distinguish
    # "endpoint changed" from "genuinely empty result".
    # NOTE: Bricklink ships multiple server-error landing page families:
    #   /oops.asp?err=<code>            (legacy)
    #   /v2/error_<code>.page           (e.g. /v2/error_404.page)
    #   /v3/error/<code>_<name>.page    (e.g. /v3/error/404_not_found.page,
    #                                    /v3/error/500_internal_server_error.page)
    # All three rewrite a dead/broken URL to a healthy-looking HTTP 200 with
    # zero business-data elements — the exact class of bug this guard exists
    # to kill. The pattern below must match all current forms.
    _SERVER_ERROR_URL_PATTERN = re.compile(
        r"/oops\.asp(?:[/?]|$)"
        r"|[?&]err=[45]\d\d\b"
        r"|/v2/error_\d{3}\.page\b"
        r"|/v3/error/\d{3}(?:_[^/?#]+)?\.page\b",
        re.IGNORECASE,
    )

    @classmethod
    def _matches_server_error_url(cls, url: str) -> bool:
        """Return True when ``url`` indicates a Bricklink server-error page."""
        if not url:
            return False
        return bool(cls._SERVER_ERROR_URL_PATTERN.search(url))

    def _check_server_error(self, page, requested_url: str) -> None:
        """Raise loudly when Bricklink redirected to a server-error page.

        Called after navigation completes but BEFORE any parser runs.
        The message names BOTH the originally-requested URL and the
        redirect target so the caller can immediately tell whether the
        endpoint has changed, the request was malformed, or the server
        is genuinely failing. NEVER returns silently with an unverified
        page — that is the entire bug class this method exists to kill.
        """
        current_url = getattr(page, "url", "") or ""
        if not self._matches_server_error_url(current_url):
            return
        activity.error(
            "Bricklink server error at %s (requested %s)",
            current_url,
            requested_url,
        )
        raise RuntimeError(
            f"Bricklink server error at {current_url} "
            f"(original target: {requested_url}). "
            "The endpoint may have changed or the request is malformed."
        )

    # AWS WAF / Amazon CAPTCHA challenge markers. BrickLink fronts pages with
    # AWS WAF; on bot-like access (especially headless Chrome) it serves a
    # CAPTCHA interstitial instead of the requested page. The challenge usually
    # clears on a follow-up navigation because the first response sets a WAF
    # token cookie. If it does not clear after several reloads, the operation
    # must abort with an actionable error — silently waiting for `textarea`
    # produces a misleading "selector timeout" failure.
    _WAF_TITLE_MARKERS = ("Human Verification",)
    _WAF_SELECTORS = (
        "#amzn-captcha-verify-button",
        "[class*='captcha']",
        "[id*='captcha']",
    )

    def _detect_waf_challenge(self, page) -> bool:
        """Return True if the current page is an AWS WAF CAPTCHA interstitial."""
        try:
            title = page.evaluate("document.title") or ""
        except Exception:
            title = ""
        if any(marker in title for marker in self._WAF_TITLE_MARKERS):
            return True
        for sel in self._WAF_SELECTORS:
            try:
                if page.query_selector(sel):
                    return True
            except Exception:
                continue
        return False

    def _get_page_for(self, url: str, max_waf_retries: int = 4):
        """Get page navigated to url, verify auth, and wait for JS rendering.

        Transparently retries on AWS WAF CAPTCHA challenges (Amazon "Human
        Verification" page). The challenge typically clears on the second
        request because the first response sets a WAF token cookie. If the
        challenge persists past ``max_waf_retries`` reloads, raises a
        descriptive RuntimeError instead of letting downstream waits time
        out on a missing form element.
        """
        activity.info("Navigating to %s", url)
        page = self.get_page()
        self._goto_page(page, url)
        self._handle_confirmation_code_page(page, url)
        self._check_session_expired(page)

        # AWS WAF CAPTCHA retry loop. Each reload gives the WAF token cookie
        # another chance to be accepted; a small backoff between attempts
        # avoids hammering the challenge endpoint.
        waf_attempts = 0
        while self._detect_waf_challenge(page):
            waf_attempts += 1
            if waf_attempts > max_waf_retries:
                raise RuntimeError(
                    "Bricklink is serving an AWS WAF CAPTCHA challenge for "
                    f"{url!r} that did not clear after {max_waf_retries} reloads. "
                    "Try again in a minute, or run an interactive command first "
                    "to refresh the session (e.g. `bricklink auth login`)."
                )
            activity.warning(
                "AWS WAF CAPTCHA detected (attempt %d/%d) — reloading %s",
                waf_attempts, max_waf_retries, url,
            )
            page.wait_for_timeout(2000 * waf_attempts)
            self._goto_page(page, url)
            self._handle_confirmation_code_page(page, url)
            self._check_session_expired(page)

        # Final gate before any parser runs: if Bricklink served a
        # server-error landing page (404, 500, oops.asp), raise loudly
        # with both the requested and final URLs. NEVER let a parser run
        # against an unverified page and return silently empty.
        self._check_server_error(page, url)

        page.wait_for_timeout(500)
        return page

    # ==================== Messages ====================

    @cached
    def list_messages(self, page_num: int = 1, folder: str = "i") -> list:
        """List messages from inbox or outbox."""
        url = f"{self.MESSAGES_URL}?pg={page_num}&a={folder}"
        page = self._get_page_for(url)

        # Wait for message links to appear in the DOM (up to 10s)
        try:
            page.wait_for_selector('a[href*="myMsg.asp?msgID="]', timeout=10000)
        except Exception:
            # No messages found after waiting — return empty list
            return []

        messages = page.evaluate("""() => {
            const results = [];
            const links = document.querySelectorAll('a[href*="myMsg.asp?msgID="]');
            const seenIds = new Set();

            for (const link of links) {
                const href = link.href;
                const msgIdMatch = href.match(/msgID=(\\d+)/);
                if (!msgIdMatch) continue;

                const messageId = msgIdMatch[1];
                if (seenIds.has(messageId)) continue;
                seenIds.add(messageId);

                const row = link.closest('tr');
                if (!row) continue;

                const cells = row.querySelectorAll('td');
                let date = '';
                for (const cell of cells) {
                    const text = cell.textContent?.trim() || '';
                    if (text.match(/^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\\s+\\d+,\\s+\\d{4}$/)) {
                        date = text;
                        break;
                    }
                }

                let username = '';
                const userLink = row.querySelector('a[href*="contact.asp?u="]');
                if (userLink) {
                    username = userLink.textContent?.trim().split('(')[0].trim() || '';
                }

                const isUnread = row.querySelector('b, strong') !== null ||
                                row.classList.contains('unread');

                const subject = (link.textContent || '').trim().replace(/\\s*[(]view order[)]\\s*$/i, '');
                results.push({ message_id: messageId, subject, username, date, is_unread: isUnread, url: href });
            }
            return results;
        }""")

        return messages

    @cached
    def get_message(self, message_id: str, folder: str = "i") -> dict:
        """Get message details by ID."""
        url = f"{self.MESSAGES_URL}?msgID={message_id}&a={folder}"
        page = self._get_page_for(url)

        info = page.evaluate("""() => {
            const cells = document.querySelectorAll('td');
            let subject = null, from_username = null, to_username = null, sentDate = null, body = null, orderId = null;

            for (const cell of cells) {
                const text = cell.textContent.trim();
                if (text === 'Subject:') {
                    const next = cell.nextElementSibling;
                    if (next) {
                        subject = next.textContent.trim();
                        const orderMatch = subject.match(/Order #(\\d+)/);
                        if (orderMatch) orderId = orderMatch[1];
                    }
                }
                if (text === 'From:') {
                    const next = cell.nextElementSibling;
                    if (next) {
                        const div = next.querySelector('div') || next;
                        from_username = div.textContent.trim().split('(')[0].trim();
                    }
                }
                if (text === 'To:') {
                    const next = cell.nextElementSibling;
                    if (next) {
                        const div = next.querySelector('div') || next;
                        to_username = div.textContent.trim().split('(')[0].trim();
                    }
                }
                if (text === 'Sent:') {
                    const next = cell.nextElementSibling;
                    if (next) sentDate = next.textContent.trim();
                }
            }

            // Clone page and remove quoted reply tables (dashed left border) before extracting body
            const pageClone = document.body.cloneNode(true);
            pageClone.querySelectorAll('table[style*="border-left"]').forEach(t => t.remove());
            const allText = pageClone.innerText;
            const dashIndex = allText.indexOf('------------------------------------------------------------');
            if (dashIndex !== -1) {
                body = allText.substring(dashIndex + 60).trim();
                const footerIndex = body.indexOf('BrickLink');
                if (footerIndex !== -1) body = body.substring(0, footerIndex).trim();
            }

            const replyLink = document.querySelector('a[href*="/contact.asp?myMsgID="]');
            let replyUrl = replyLink ? replyLink.href : null;

            return { subject, from_username, to_username, sent_date: sentDate, body, order_id: orderId, reply_url: replyUrl };
        }""")

        return {"message_id": message_id, **info, "url": page.url}

    def send_message(self, order_id: str, body: str, subject: str = None,
                     high_priority: bool = False, send_copy: bool = False) -> dict:
        """Send a message linked to an order."""
        url = f"{self.CONTACT_URL}?orderID={order_id}"
        page = self._get_page_for(url)

        if "contact.asp" not in page.url:
            raise RuntimeError("Failed to navigate to contact form.")

        return self._fill_and_send_message(page, body, subject, high_priority, send_copy, order_id=order_id)

    def contact_member(self, username: str, body: str, subject: str = None,
                       high_priority: bool = False, send_copy: bool = False) -> dict:
        """Send a message to a member via the contact form (no order required)."""
        url = f"{self.CONTACT_URL}?u={username}"
        page = self._get_page_for(url)

        if "contact.asp" not in page.url:
            raise RuntimeError("Failed to navigate to contact form.")

        return self._fill_and_send_message(page, body, subject, high_priority, send_copy, member=username)

    def reply_to_message(self, message_id: str, body: str, subject: str = None,
                         high_priority: bool = False, send_copy: bool = False) -> dict:
        """Reply to a specific message."""
        url = f"{self.MESSAGES_URL}?msgID={message_id}&a=i"
        page = self._get_page_for(url)

        # Extract reply URL and navigate directly via _get_page_for
        # (clicking the link bypasses confirmation code handling)
        reply_href = page.evaluate("""() => {
            const link = document.querySelector('a[href*="/contact.asp?myMsgID="]');
            return link ? link.href : null;
        }""")
        if not reply_href:
            raise RuntimeError("Reply link not found on message page.")

        page = self._get_page_for(reply_href)

        if "contact.asp" not in page.url:
            raise RuntimeError("Failed to navigate to reply form.")

        return self._fill_and_send_message(page, body, subject, high_priority, send_copy, message_id=message_id)

    @staticmethod
    def _sanitize_message_body(body: str) -> str:
        """Remove shell escaping artifacts and unwanted line breaks from message text.

        Fixes two issues that occur when message bodies pass through shell layers:
        1. Escaped exclamation marks (\\!) from bash history expansion escaping
        2. Mid-sentence line breaks from shell/terminal word-wrapping

        Preserves intentional paragraph breaks (blank lines / double newlines).
        """
        import re as _re
        # Remove backslash before exclamation marks (shell history escaping artifact)
        body = body.replace('\\!', '!')

        # Collapse single newlines into spaces (word-wrap artifacts) while
        # preserving intentional paragraph breaks (double newlines).
        # Strategy: protect double-newlines, collapse singles, restore doubles.
        _PARA_PLACEHOLDER = '\x00PARA\x00'
        body = body.replace('\r\n', '\n')
        body = body.replace('\n\n', _PARA_PLACEHOLDER)
        body = body.replace('\n', ' ')
        body = body.replace(_PARA_PLACEHOLDER, '\n\n')

        # Clean up any extra whitespace from collapsed newlines
        body = _re.sub(r' {2,}', ' ', body)

        return body.strip()

    def _fill_and_send_message(self, page, body: str, subject: str = None,
                                high_priority: bool = False, send_copy: bool = False,
                                **extra) -> dict:
        """Fill and submit the message form."""
        body = self._sanitize_message_body(body)

        if subject:
            try:
                subject_input = page.wait_for_selector(
                    'input[name="p_subject"]', state="visible", timeout=10000
                )
                if subject_input:
                    subject_input.click()
                    subject_input.fill("")
                    subject_input.fill(subject)
            except Exception:
                pass

        try:
            textarea = page.wait_for_selector("textarea", state="visible", timeout=20000)
        except Exception as e:
            # Surface a more actionable error than a raw selector timeout.
            # _get_page_for already retries past AWS WAF challenges, so if we
            # still cannot find a textarea here it is either a page-layout
            # change or an unrecognized interstitial.
            if self._detect_waf_challenge(page):
                raise RuntimeError(
                    "Bricklink is showing an AWS WAF CAPTCHA challenge on the "
                    "message compose form. Try again in a minute, or run "
                    "`bricklink auth login` to refresh the session."
                ) from e
            raise RuntimeError(
                f"Message textarea not found on {page.url!r} after 20s — "
                "the compose form did not render. The page may have changed "
                "or an interstitial is blocking it."
            ) from e
        if not textarea:
            raise RuntimeError("Message textarea not found.")
        textarea.fill(body)

        if high_priority or send_copy:
            checkboxes = page.query_selector_all('input[type="checkbox"]')
            if high_priority and len(checkboxes) > 0:
                checkboxes[0].check()
            if send_copy and len(checkboxes) > 1:
                checkboxes[1].check()

        send_button = page.get_by_role("button", name="Send Message")
        send_button.click()
        page.wait_for_timeout(3000)

        current_url = page.url
        content = page.evaluate("document.documentElement.outerHTML") or ""
        success = (
            "myMsg.asp" in current_url
            or "sent" in content.lower()
            or "contact.asp" not in current_url
        )

        return {"success": success, "body": body, "subject": subject or "(auto)", **extra,
                "message": "Message sent successfully" if success else "Message may have failed. Verify on Bricklink."}

    def mark_as_read(self, message_id: str) -> dict:
        """Mark a message as read by viewing it."""
        url = f"{self.MESSAGES_URL}?msgID={message_id}&a=i"
        page = self._get_page_for(url)

        content = page.evaluate("document.documentElement.outerHTML") or ""
        success = "Subject:" in content or "From:" in content

        return {"success": success, "message_id": message_id, "action": "mark_as_read",
                "message": "Message marked as read" if success else "Could not mark message as read."}

    def mark_as_unread(self, message_id: str) -> dict:
        """Mark a message as unread using checkbox + action dropdown."""
        url = f"{self.MESSAGES_URL}?a=i"
        page = self._get_page_for(url)

        checkbox = page.query_selector(
            f'input[type="checkbox"][name="chkMsgID"][value="{message_id}"]'
        )
        if not checkbox:
            raise RuntimeError(f"Message {message_id} not found in inbox.")

        checkbox.check()
        page.wait_for_timeout(500)

        # Try various approaches for the unread action
        unread_button = page.query_selector(
            'input[value*="Unread"], button:has-text("Unread"), a:has-text("Mark as Unread")'
        )
        if unread_button:
            unread_button.click()
        else:
            action_select = page.query_selector('select[name="action"]')
            if action_select:
                action_select.select_option("unread")
                go_button = page.query_selector('input[value="Go"], button:has-text("Go")')
                if go_button:
                    go_button.click()
            else:
                raise RuntimeError("Could not find 'Mark as Unread' action on the page.")

        page.wait_for_timeout(2000)

        return {"success": True, "message_id": message_id, "action": "mark_as_unread",
                "message": "Message marked as unread"}

    # ==================== Store Settings ====================

    STORE_ANNOUNCEMENT_FIELD = "strAnnouncement"
    STORE_BANNER_FIELD = "strBanner"

    def get_store_display_settings(self) -> dict:
        """Read the store announcement and banner text from Store Settings."""
        page = self._get_page_for(self.STORE_SETTINGS_URL)
        settings = page.evaluate(
            """(fieldNames) => {
            const announcement = document.querySelector(`input[name="${fieldNames.announcement}"]`);
            const banner = document.querySelector(`input[name="${fieldNames.banner}"]`);
            return {
                announcement_found: !!announcement,
                banner_found: !!banner,
                announcement: announcement ? announcement.value : null,
                banner: banner ? banner.value : null,
            };
        }""",
            {
                "announcement": self.STORE_ANNOUNCEMENT_FIELD,
                "banner": self.STORE_BANNER_FIELD,
            },
        )
        if (
            not settings
            or not settings.get("announcement_found")
            or not settings.get("banner_found")
        ):
            raise RuntimeError(
                "BrickLink store settings page did not contain both "
                f"input[name='{self.STORE_ANNOUNCEMENT_FIELD}'] and "
                f"input[name='{self.STORE_BANNER_FIELD}']."
            )
        return {
            "announcement": settings.get("announcement") or "",
            "banner": settings.get("banner") or "",
            "store_settings_url": page.url,
        }

    def save_store_display_settings(self, announcement: str, banner: str) -> dict:
        """Save the store announcement and banner through BrickLink's settings AJAX endpoint."""
        page = self._get_page_for(self.STORE_SETTINGS_URL)
        result = page.evaluate(
            """async (payload) => {
                const body = new URLSearchParams();
                body.set(payload.fields.announcement, payload.announcement);
                body.set(payload.fields.banner, payload.banner);

                const response = await fetch('/ajax/renovate/mystore/display.ajax?action=update', {
                    method: 'POST',
                    credentials: 'include',
                    headers: {
                        'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                        'x-requested-with': 'XMLHttpRequest',
                    },
                    body: body.toString(),
                });

                const text = await response.text();
                let data = null;
                try {
                    data = JSON.parse(text);
                } catch (error) {
                    data = { parse_error: String(error), raw_length: text.length };
                }

                return {
                    ok: response.ok,
                    status: response.status,
                    data,
                };
            }""",
            {
                "announcement": announcement,
                "banner": banner,
                "fields": {
                    "announcement": self.STORE_ANNOUNCEMENT_FIELD,
                    "banner": self.STORE_BANNER_FIELD,
                },
            },
        )
        data = (result or {}).get("data") or {}
        if not result or not result.get("ok") or data.get("returnCode") != 0:
            raise RuntimeError(
                "BrickLink store settings update failed: "
                f"status={result.get('status') if result else None}, "
                f"returnCode={data.get('returnCode')}, "
                f"returnMessage={data.get('returnMessage')!r}"
            )
        return {
            "success": True,
            "status": result.get("status"),
            "returnCode": data.get("returnCode"),
            "returnMessage": data.get("returnMessage"),
        }

    def get_enabled_shipping_methods(self) -> list[dict]:
        """Read enabled shipping methods and their buyer-facing descriptions."""
        page = self._get_page_for(self.SHIPPING_SETTINGS_URL)
        page.wait_for_timeout(2500)
        return page.evaluate(
            r"""() => Array.from(document.querySelectorAll('.shipping-method__row')).map((row) => {
                const link = row.querySelector('.shipping-method__method--title a');
                const desc = row.querySelector('.shipping-method__method--description');
                const checkbox = row.querySelector('.shipping-method__enabled input[type="checkbox"]');
                const href = link ? link.getAttribute('href') : '';
                const match = href.match(/id=(\d+)/);
                return {
                    id: match ? match[1] : null,
                    name: link ? link.innerText.trim() : '',
                    description: desc ? desc.innerText.trim() : '',
                    enabled: checkbox ? checkbox.checked : false,
                    href,
                };
            }).filter((item) => item.id && item.enabled)"""
        )

    def save_shipping_method_note(self, method_id: str, note: str) -> dict:
        """Save a shipping method's buyer note through the BrickLink edit page."""
        page = self._get_page_for(f"{self.SHIPPING_METHOD_EDIT_URL}?id={method_id}")
        page.wait_for_selector("textarea.bl-form-text", timeout=15000)
        save_enabled = page.evaluate(
            """(note) => {
                const textarea = document.querySelector('textarea.bl-form-text');
                if (!textarea) {
                    throw new Error('Note textarea not found');
                }
                const setter = Object.getOwnPropertyDescriptor(
                    HTMLTextAreaElement.prototype,
                    'value'
                ).set;
                setter.call(textarea, note);
                textarea.dispatchEvent(new InputEvent('input', {
                    bubbles: true,
                    inputType: 'insertText',
                    data: note,
                }));
                textarea.dispatchEvent(new Event('change', {bubbles: true}));
                return Array.from(document.querySelectorAll('button.js-button-save')).some(
                    (button) => !button.disabled
                        && !!(button.offsetWidth || button.offsetHeight || button.getClientRects().length)
                );
            }""",
            note,
        )
        if not save_enabled:
            raise RuntimeError(
                f"BrickLink shipping method {method_id} Save changes button did not enable."
            )
        clicked = page.evaluate(
            """() => {
                const buttons = Array.from(document.querySelectorAll('button.js-button-save'));
                const button = buttons.find((candidate) => !candidate.disabled
                    && !!(candidate.offsetWidth || candidate.offsetHeight || candidate.getClientRects().length));
                if (!button) {
                    return false;
                }
                button.click();
                return true;
            }"""
        )
        if not clicked:
            raise RuntimeError(
                f"BrickLink shipping method {method_id} enabled Save changes button was not found."
            )
        page.wait_for_timeout(4000)
        return {
            "success": True,
            "shipping_method_id": method_id,
        }

    # ==================== Refunds ====================

    # Poll budget for the refund page's async React render (transaction ID,
    # prior refunds, etc. are populated after an XHR completes post-mount).
    # `_get_page_for`'s flat 500ms wait only guarantees `domcontentloaded` +
    # a fixed pause — it does NOT guarantee the refund data has rendered.
    # Verified live 2026-08-11: `refund info` and `refund issue`'s pre-submit
    # gate both call this same method, yet `refund issue` intermittently read
    # no 'Prior refund(s)' value moments after `refund info` succeeded on the
    # identical order/URL — proving a render race, not a selector divergence.
    REFUND_RENDER_POLL_ATTEMPTS = 50
    REFUND_RENDER_POLL_INTERVAL_MS = 200

    # `_wait_for_refund_page_rendered` only proves the "Prior refund(s)" /
    # "Original payment" region has painted — a different DOM region than the
    # reason control, which can still be entirely absent at that point. See
    # `_reveal_refund_reason_dropdown` for why.
    REASON_CONTROL_POLL_ATTEMPTS = 25
    REASON_CONTROL_POLL_INTERVAL_MS = 200

    def _reveal_refund_reason_dropdown(self, page, order_id: str) -> None:
        """Ensure the refund-reason ``<select>``/combobox is present before
        callers query for it.

        BrickLink's refund page renders the reason control in one of two
        states, and `_submit_refund` previously assumed only the first:

        - No reason details saved yet for this order: the editable
          ``<select>`` is present directly, once the SPA finishes rendering.
        - Reason details already saved (e.g. this order already has an
          earlier partial refund): BrickLink instead shows a read-only
          "Reason for refund" summary with an "Edit reason details" button.
          The ``<select>`` does not enter the DOM at all until that button is
          clicked.

        Verified live on order 32187623 (2026-08-11, read-only): the summary
        panel and "Edit reason details" button render immediately and
        `_wait_for_refund_page_rendered` returns, yet
        `document.querySelectorAll('select')` stays at 0 indefinitely.
        Clicking "Edit reason details" makes the `<select>` appear with the
        full BrickLink reason option list. A same-session comparison against
        two orders with no prior refund (32283570, 32296775) showed the
        `<select>` present with no edit button at all — confirming this is a
        page-state branch, not a selector regression.

        This only reveals the dropdown; it never selects a value or clicks
        Review/Confirm.
        """
        def _dropdown_present() -> bool:
            return page.evaluate(
                "() => document.querySelectorAll('select, [role=\"combobox\"]').length > 0"
            )

        for _ in range(self.REASON_CONTROL_POLL_ATTEMPTS):
            if _dropdown_present():
                return
            page.wait_for_timeout(self.REASON_CONTROL_POLL_INTERVAL_MS)

        edit_btn = page.get_by_role("button", name="Edit reason details")
        if edit_btn.count() == 0:
            # Nothing more we can do here; the caller raises its own
            # descriptive error when the dropdown still can't be found.
            return

        activity.info(
            "Refund page for order %s shows saved reason details with no "
            "live dropdown — clicking 'Edit reason details' to reveal it.",
            order_id,
        )
        edit_btn.first.click()

        for _ in range(self.REASON_CONTROL_POLL_ATTEMPTS):
            if _dropdown_present():
                return
            page.wait_for_timeout(self.REASON_CONTROL_POLL_INTERVAL_MS)

        activity.warning(
            "Refund reason dropdown for order %s still not present after "
            "clicking 'Edit reason details'.",
            order_id,
        )

    def _wait_for_refund_page_rendered(self, page, order_id: str) -> None:
        """Block until the refund page shows either its data or an empty state.

        Does not raise on timeout — callers already treat an unreadable page
        as a hard-stop (see ``_read_prior_refunds_total`` / ``_submit_refund``).
        This only removes the race where extraction runs before the SPA has
        finished populating the DOM.
        """
        is_ready_js = """() => {
            if (document.querySelector('.empty-state__title')) return true;
            const divs = Array.from(document.querySelectorAll('div'));
            const hasPrior = divs.some(el => {
                const t = el.textContent.trim();
                return t === 'Prior refund(s)' || t === 'Prior refunds';
            });
            const hasOriginalPayment = divs.some(
                el => el.textContent.trim() === 'Original payment'
            );
            return hasPrior || hasOriginalPayment;
        }"""
        for _ in range(self.REFUND_RENDER_POLL_ATTEMPTS):
            if page.evaluate(is_ready_js):
                return
            page.wait_for_timeout(self.REFUND_RENDER_POLL_INTERVAL_MS)
        activity.warning(
            "Refund page for order %s did not render prior-refund or "
            "original-payment data within %.0fs",
            order_id,
            self.REFUND_RENDER_POLL_ATTEMPTS * self.REFUND_RENDER_POLL_INTERVAL_MS / 1000,
        )

    def get_refund_info(self, order_id: str) -> dict:
        """Get refund page info for an order."""
        url = f"{self.REFUND_URL}?id={order_id}"
        page = self._get_page_for(url)
        self._wait_for_refund_page_rendered(page, order_id)

        # Check for explicit empty state / error message on the page
        error_msg = page.evaluate(
            """() => {
                const emptyTitleEl = document.querySelector('.empty-state__title');
                if (emptyTitleEl) {
                    const descEl = emptyTitleEl.nextElementSibling;
                    const titleText = emptyTitleEl.innerText.trim();
                    const descText = descEl ? descEl.innerText.trim() : '';
                    return `${titleText}${descText ? ': ' + descText : ''}`;
                }
                return null;
            }"""
        )
        if error_msg:
            raise RuntimeError(
                f"Refund page for order {order_id} displays: {error_msg!r}"
            )

        info = page.evaluate("""() => {
            const getFieldValue = (labelText) => {
                const divs = Array.from(document.querySelectorAll('div'));
                for (const div of divs) {
                    if (div.textContent.trim() === labelText) {
                        const sibling = div.nextElementSibling;
                        if (sibling) return sibling.textContent.trim();
                    }
                }
                return null;
            };

            const paypalLink = document.querySelector('a[href*="paypal.com/activity/payment"]');
            const stripeLink = document.querySelector('a[href*="dashboard.stripe.com/payments"]');
            let transaction_id = null, payment_processor = null;
            if (paypalLink) { transaction_id = paypalLink.textContent.trim(); payment_processor = 'PayPal'; }
            else if (stripeLink) { transaction_id = stripeLink.textContent.trim(); payment_processor = 'Stripe'; }

            let refund_status = null;
            const statusEl = Array.from(document.querySelectorAll('div')).find(el => el.textContent.trim() === 'Refund status');
            if (statusEl) {
                const sib = statusEl.nextElementSibling;
                if (sib) { const p = sib.querySelector('p'); refund_status = p ? p.textContent.trim() : sib.textContent.trim(); }
            }

            let buyer_name = null, buyer_email = null;
            const refundToEl = Array.from(document.querySelectorAll('div')).find(el => el.textContent.trim() === 'Refund payment to');
            if (refundToEl) {
                const sib = refundToEl.nextElementSibling;
                if (sib) {
                    const ps = sib.querySelectorAll('p');
                    if (ps.length >= 1) buyer_name = ps[0].textContent.trim();
                    if (ps.length >= 2) buyer_email = ps[1].textContent.trim();
                }
            }

            const original_payment = getFieldValue('Original payment');

            let prior_refunds = null;
            const priorEl = Array.from(document.querySelectorAll('div')).find(
                el => { const t = el.textContent.trim(); return t === 'Prior refund(s)' || t === 'Prior refunds'; }
            );
            if (priorEl) {
                const sib = priorEl.nextElementSibling;
                if (sib && sib.childNodes.length > 0) {
                    const first = sib.childNodes[0];
                    prior_refunds = first.nodeType === 3 ? first.textContent.trim() : sib.textContent.trim().split('\\n')[0].trim();
                }
            }

            const order_date = getFieldValue('Order date');

            let refund_reason = null, refund_notes = null;
            const reasonEl = Array.from(document.querySelectorAll('div')).find(
                el => el.textContent.trim() === 'Reason details (visible to buyer)'
            );
            if (reasonEl) {
                const sib = reasonEl.nextElementSibling;
                if (sib) {
                    const strongs = sib.querySelectorAll('strong');
                    const ps = sib.querySelectorAll('p');
                    for (let i = 0; i < strongs.length; i++) {
                        const label = strongs[i].textContent.trim();
                        if (label === 'Reason for refund' && ps[i]) refund_reason = ps[i].textContent.trim();
                        if (label === 'Notes' && ps[i]) refund_notes = ps[i].textContent.trim();
                    }
                }
            }

            let refund_activity = [];
            const activityEl = Array.from(document.querySelectorAll('div')).find(el => el.textContent.trim() === 'Refund activity');
            if (activityEl) {
                const container = activityEl.nextElementSibling;
                if (container) {
                    const allDivs = container.querySelectorAll('div');
                    let dataValues = [];
                    let collecting = false;
                    for (const div of allDivs) {
                        const text = div.textContent.trim();
                        if (['Status', 'Date', 'to Buyer', 'from Seller', 'Refunded Sales tax from BrickLink'].includes(text)) continue;
                        if (['Completed', 'Pending', 'Failed'].includes(text)) {
                            if (dataValues.length > 0) {
                                refund_activity.push({status: dataValues[0], date: dataValues[1] || null, to_buyer: dataValues[2] || null, from_seller: dataValues[3] || null});
                            }
                            dataValues = [text];
                            collecting = true;
                        } else if (collecting && dataValues.length < 5) {
                            dataValues.push(text);
                        }
                    }
                    if (dataValues.length > 0) {
                        refund_activity.push({status: dataValues[0], date: dataValues[1] || null, to_buyer: dataValues[2] || null, from_seller: dataValues[3] || null});
                    }
                }
            }

            return { transaction_id, payment_processor, refund_status, buyer_name, buyer_email, original_payment, prior_refunds, order_date, refund_reason, refund_notes, refund_activity: refund_activity.length > 0 ? refund_activity : null };
        }""")

        return {"order_id": order_id, **info, "refund_page_url": page.url}

    def _parse_prior_refunds_amount(self, value) -> float | None:
        """Parse a prior_refunds string like 'US $3.50' into a float.

        Returns ``None`` when the value is missing or unparseable. ``None``
        means "the page did not tell us", which is NOT the same as $0.00.
        BrickLink renders a literal ``"US $0.00"`` for an order that has never
        been refunded (verified live against order 30891363 on 2026-07-30), so
        a missing value can only mean the page failed to render or the parser
        lost its anchor. Substituting 0.0 there previously let an unreadable
        page masquerade as a proven-zero page, which is how a posted refund got
        reported as "did NOT post".
        """
        if not value:
            return None
        import re as _re
        m = _re.search(r"([0-9]+(?:\.[0-9]+)?)", str(value))
        if not m:
            return None
        return float(m.group(1))

    @staticmethod
    def _resolve_refund_reason(reason: str, option_labels: list) -> str | None:
        """Map a user-supplied reason to an actual BL dropdown label.

        Accepts:
          - Exact labels: "Item was missing or unsatisfactory"
          - Slugs: "missing-unsatisfactory", "cancel-order", "overcharged-shipping",
                   "incorrect-amount", "cancel-items", "cannot-complete"
          - Free-text keywords: "missing", "cancel", "shipping", "incorrect"
        Returns the matched label verbatim, or None if no match.
        """
        if not reason or not option_labels:
            return None
        # 1. Exact label match (case-insensitive)
        for lbl in option_labels:
            if lbl.strip().lower() == reason.strip().lower():
                return lbl
        # 2. Slug / keyword map — keyed by distinguishing substrings that must
        #    appear in the BL label.
        slug_to_keywords = {
            "missing-unsatisfactory": ["missing", "unsatisfactory"],
            "missing": ["missing", "unsatisfactory"],
            "unsatisfactory": ["missing", "unsatisfactory"],
            "cancel-order": ["agreed to cancel order"],
            "cancel_order": ["agreed to cancel order"],
            "cancel-items": ["agreed to cancel items"],
            "cancel_items": ["agreed to cancel items"],
            "cannot-complete": ["cannot complete"],
            "cannot_complete": ["cannot complete"],
            "overcharged-shipping": ["overcharged shipping"],
            "overcharged_shipping": ["overcharged shipping"],
            "shipping": ["overcharged shipping"],
            "incorrect-amount": ["incorrect amount"],
            "incorrect_amount": ["incorrect amount"],
            "incorrect": ["incorrect amount"],
        }
        key = reason.strip().lower()
        keywords = slug_to_keywords.get(key)
        if keywords:
            for lbl in option_labels:
                ll = lbl.lower()
                if all(k in ll for k in keywords):
                    return lbl
        # 3. Last-resort substring match: any label containing the full reason text.
        for lbl in option_labels:
            if reason.strip().lower() in lbl.lower():
                return lbl
        return None

    def _read_prior_refunds_total(self, order_id: str) -> float | None:
        """Fetch the refund page fresh and return prior refunds as a float ($).

        Returns ``None`` when the page did not yield a readable value. The raw
        string is logged on every read so a future incident can distinguish
        "page said $0.00" from "page said nothing" — the activity log used to
        record only the collapsed float, which made those two cases
        indistinguishable after the fact.
        """
        info = self.get_refund_info(order_id)
        raw = info.get("prior_refunds")
        amount = self._parse_prior_refunds_amount(raw)
        activity.info(
            "refund page read for order %s: prior_refunds_raw=%r parsed=%s refund_status=%r",
            order_id, raw,
            "unreadable" if amount is None else f"${amount:.2f}",
            info.get("refund_status"),
        )
        return amount

    # BrickLink's refund page is EVENTUALLY CONSISTENT. The submitted refund
    # does not land in "Prior refund(s)" the moment the confirm button is
    # clicked. Measured on order 32175236 (2026-07-30, activity log): the page
    # still read $0.00 eleven seconds after submit and read $1.00 five minutes
    # later. The previous 3-attempt / ~6-second budget expired while the refund
    # was still in flight, then asserted "The refund did NOT post" — which
    # invites the operator to re-issue and double-refund a real buyer.
    # Cumulative budget below: 120 seconds.
    REFUND_VERIFY_BACKOFF_SECONDS = (2, 3, 5, 8, 12, 15, 20, 25, 30)

    def _verify_refund_posted(self, page, order_id: str, prior_before: float,
                              expected_delta: float | None) -> tuple[float, float]:
        """Poll the refund page until the submitted refund becomes visible.

        Returns ``(prior_after, actual_delta)`` once the increase is confirmed.

        Raises ``RuntimeError`` describing the outcome as UNCONFIRMED when the
        budget is exhausted. It must NEVER claim the refund did not post: by the
        time this runs the confirm button has already been clicked and the money
        may have moved. A positive reading proves the refund posted; the absence
        of a reading proves nothing at all.
        """
        target = prior_before + expected_delta if expected_delta is not None else None
        observations: list[str] = []
        last_amount: float | None = None
        elapsed = 0.0

        for wait_seconds in self.REFUND_VERIFY_BACKOFF_SECONDS:
            page.wait_for_timeout(int(wait_seconds * 1000))
            elapsed += wait_seconds
            try:
                amount = self._read_prior_refunds_total(order_id)
            except Exception as exc:
                observations.append(
                    f"+{elapsed:.0f}s read error: {type(exc).__name__}: {exc}"
                )
                continue
            if amount is None:
                observations.append(
                    f"+{elapsed:.0f}s page returned no readable prior-refund amount"
                )
                continue

            last_amount = amount
            observations.append(f"+{elapsed:.0f}s prior_refunds=${amount:.2f}")
            confirmed = (
                amount > prior_before + 0.005 if target is None
                else amount + 0.005 >= target
            )
            if confirmed:
                actual_delta = round(amount - prior_before, 2)
                activity.info(
                    "refund CONFIRMED for order %s after %.0fs: prior_refunds "
                    "$%.2f -> $%.2f (delta $%.2f)",
                    order_id, elapsed, prior_before, amount, actual_delta,
                )
                return amount, actual_delta

        trail = "; ".join(observations) or "no reads completed"
        expected_str = (
            f"reach ${target:.2f} (an increase of ${expected_delta:.2f})"
            if target is not None
            else f"rise above ${prior_before:.2f} (full refund)"
        )
        last_str = (
            "never read successfully" if last_amount is None else f"${last_amount:.2f}"
        )
        activity.error(
            "refund UNCONFIRMED for order %s after %.0fs; observations: %s",
            order_id, elapsed, trail,
        )
        raise RuntimeError(
            f"Refund state UNCONFIRMED for order {order_id}. The refund WAS submitted "
            f"to Bricklink — the confirm button was clicked — but the refund page did "
            f"not show the expected change within {elapsed:.0f}s. Expected prior_refunds "
            f"to {expected_str}. Before=${prior_before:.2f}, last observed={last_str}. "
            f"DO NOT re-issue this refund: Bricklink's refund page is eventually "
            f"consistent and the refund may already have posted. Check "
            f"`bricklink refund info {order_id}` or {self.REFUND_URL}?id={order_id} "
            f"and only re-issue if prior refunds are genuinely unchanged. "
            f"Read trail: {trail}"
        )

    def _submit_refund(self, order_id: str, reason: str, details: str = None,
                       amount: float = None, full: bool = False, dry_run: bool = False) -> dict:
        """Common refund submission logic for partial and full refunds.

        Verifies success by re-reading the refund page after submission and
        confirming that prior_refunds increased by at least the submitted
        amount. Never silently reports success.

        Failure semantics differ either side of the confirm click:
        - BEFORE the click, an unreadable page raises and states plainly that
          no refund was submitted.
        - AFTER the click, a missing confirmation raises as UNCONFIRMED. The
          money may already have moved, so the error tells the operator to
          check the refund page rather than re-issue. See
          ``_verify_refund_posted``.
        """
        try:
            # --- SNAPSHOT: capture prior refunds BEFORE submission ---
            # An unreadable snapshot is a hard stop, not a zero. Nothing has
            # been submitted yet, so failing here is safe and costs the buyer
            # nothing; guessing $0.00 here would poison the delta check later.
            prior_before = self._read_prior_refunds_total(order_id)
            if prior_before is None:
                raise RuntimeError(
                    f"Could not read prior refunds from the Bricklink refund page for "
                    f"order {order_id} before submitting. NO refund was submitted. "
                    "The page did not render a 'Prior refund(s)' amount — check that "
                    f"{self.REFUND_URL}?id={order_id} loads and shows the refund form."
                )
            activity.info(f"refund pre-submit prior_refunds=${prior_before:.2f} for order {order_id}")

            url = f"{self.REFUND_URL}?id={order_id}"
            page = self._get_page_for(url)
            self._reveal_refund_reason_dropdown(page, order_id)

            # Select reason
            dropdown = page.query_selector('select, [role="combobox"]')
            if not dropdown:
                raise RuntimeError(
                    f"Refund reason dropdown not found on refund page for order {order_id}. "
                    "Page structure may have changed, or the order is not eligible for refund."
                )
            # Resolve the user-supplied reason to an actual dropdown label.
            # Callers pass either a full BL label ("Item was missing or unsatisfactory"),
            # a slug ("missing-unsatisfactory"), or a free-text phrase ("Missing parts").
            # Enumerate the live <option> labels and pick the best match — anything
            # else leaves the default option selected and BL keeps the Review button
            # disabled, with no visible error.
            option_pairs = page.evaluate(
                """(sel) => {
                    const s = document.querySelector('select');
                    if (!s) return [];
                    return Array.from(s.options).map(o => [o.value, (o.textContent || '').trim()]);
                }"""
            )
            option_labels = [lbl for _, lbl in option_pairs]
            resolved_label = self._resolve_refund_reason(reason, option_labels)
            if not resolved_label:
                raise RuntimeError(
                    f"Could not match refund reason {reason!r} to any Bricklink refund "
                    f"dropdown option. Available options: {option_labels}"
                )
            dropdown.select_option(label=resolved_label)
            # Dispatch change event so React picks up the new value (some BL pages
            # wire validation to change, not just the native select_option call).
            page.evaluate(
                """() => {
                    const s = document.querySelector('select');
                    if (s) s.dispatchEvent(new Event('change', { bubbles: true }));
                }"""
            )
            page.wait_for_timeout(300)

            # Enter details
            if details:
                details_input = page.query_selector('input[placeholder*="refund details"], textarea')
                if details_input:
                    details_input.fill(details[:200])

            if full:
                full_btn = page.get_by_role("button", name="Refund full amount")
                if full_btn.count() == 0:
                    raise RuntimeError("Refund full amount button not found")
                full_btn.click()
                page.wait_for_timeout(1000)
            elif amount is not None:
                amount_input = page.query_selector('input.order-refund__money-input-input, input[type="number"]')
                if not amount_input:
                    raise RuntimeError(
                        f"Refund amount input not found on refund page for order {order_id}."
                    )
                # Format with 2 decimals — BL's React number input rejects "1.0"
                # but accepts "1.00". Use the native setter + explicit input event
                # so React's internal state updates (fill()/raw value assignment
                # bypass React's setState otherwise).
                formatted = f"{float(amount):.2f}"
                amount_input.click()
                amount_input.fill("")
                page.wait_for_timeout(100)
                page.evaluate(
                    """(val) => {
                        const el = document.querySelector('input.order-refund__money-input-input') ||
                                   document.querySelector('input[type="number"]');
                        if (!el) return;
                        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                        setter.call(el, val);
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        el.dispatchEvent(new Event('blur', { bubbles: true }));
                    }""",
                    formatted,
                )
                page.wait_for_timeout(1000)

            # Click Review refund
            review_btn = page.get_by_role("button", name="Review refund")
            if review_btn.count() == 0:
                raise RuntimeError("Review refund button not found on page")
            # BL disables Review until the form is valid (reason + amount).
            # Wait briefly for it to enable — if it doesn't, the form is invalid
            # and clicking would silently no-op and leave no Confirm button.
            def _review_disabled():
                return page.evaluate(
                    """() => {
                        const btns = Array.from(document.querySelectorAll('button'));
                        const b = btns.find(x => (x.innerText||'').trim() === 'Review refund');
                        if (!b) return null;
                        return !!b.disabled;
                    }"""
                )
            for _ in range(25):
                d = _review_disabled()
                if d is False:
                    break
                page.wait_for_timeout(200)
            if _review_disabled() is not False:
                # Dump form for diagnosis
                try:
                    import json as _json
                    form = page.evaluate(
                        """() => {
                            const inputs = Array.from(document.querySelectorAll('input, textarea, select')).map(el => ({
                                tag: el.tagName, type: el.type || null, name: el.name || null,
                                id: el.id || null, placeholder: el.placeholder || null,
                                required: el.required || el.ariaRequired || false,
                                value: el.value, disabled: el.disabled,
                                className: el.className,
                            }));
                            const labels = Array.from(document.querySelectorAll('label')).map(l => (l.innerText||'').trim()).filter(Boolean);
                            const errors = Array.from(document.querySelectorAll('.error, [role="alert"], .alert, .warning, .help, .hint')).map(e => (e.innerText||'').trim()).filter(Boolean);
                            return { inputs, labels, errors };
                        }"""
                    )
                    with open("/tmp/bl-refund-debug-form.json", "w") as _f:
                        _json.dump(form, _f, indent=2)
                    with open("/tmp/bl-refund-debug.html", "w") as _f:
                        _f.write(page.content())
                except Exception:
                    pass
                # Capture diagnostics before raising
                try:
                    sel_state = page.evaluate(
                        """() => {
                            const s = document.querySelector('select');
                            const a = document.querySelector('input[type="number"]');
                            return {
                                reason_value: s ? s.value : null,
                                reason_label: s ? (s.options[s.selectedIndex]||{}).text : null,
                                amount_value: a ? a.value : null,
                            };
                        }"""
                    )
                except Exception:
                    sel_state = {}
                raise RuntimeError(
                    f"Review refund button is disabled for order {order_id} — refund form "
                    f"is not valid. Reason resolved to {resolved_label!r}; form state: {sel_state}. "
                    "Bricklink will not allow Review to proceed, so no Confirm button will appear."
                )
            if dry_run:
                import os as _os
                if not _os.environ.get("BL_REFUND_DRYRUN_STOP_AT_CONFIRM"):
                    return {
                        "success": True,
                        "dry_run": True,
                        "order_id": order_id,
                        "reason_resolved": resolved_label,
                        "amount": amount,
                        "message": "Dry run: form filled and Review button enabled. Submission skipped.",
                    }
                # else: fall through, click Review, then stop at Confirm visibility.
            review_btn.click()
            page.wait_for_timeout(2000)

            # After Review click BL reveals a confirmation panel inline on the same
            # page containing a button literally labelled "Submit refund to <buyer>"
            # (class btn--cta-alt). Poll for its presence via raw JS — the
            # cli-tools-shared _ServiceLocator wrapper mis-handles compound
            # ":has-text" selectors and has no .wait_for(), so we roll our own.
            def _find_confirm_btn_js():
                return page.evaluate(
                    """() => {
                        const btns = Array.from(document.querySelectorAll('button'));
                        const b = btns.find(x => {
                            const t = (x.innerText || '').trim();
                            return t.startsWith('Submit refund to') && !x.disabled;
                        });
                        if (!b) return null;
                        const rect = b.getBoundingClientRect();
                        const visible = !!(b.offsetWidth || b.offsetHeight || b.getClientRects().length);
                        return { text: (b.innerText||'').trim(), visible, className: b.className };
                    }"""
                )
            confirm_info = None
            for _ in range(50):  # up to 10s
                confirm_info = _find_confirm_btn_js()
                if confirm_info and confirm_info.get("visible"):
                    break
                page.wait_for_timeout(200)

            if not (confirm_info and confirm_info.get("visible")):
                # Capture diagnostics for post-mortem
                import os as _os, json as _json, traceback as _tb
                out_dir = "/tmp/bl-refund-debug-stage2-artifacts"
                try:
                    _os.makedirs(out_dir, exist_ok=True)
                    with open(f"{out_dir}/url-fail.txt", "w") as _f:
                        _f.write(f"url={page.url}\nconfirm_info={confirm_info!r}\n")
                    with open(f"{out_dir}/post-review-fail.html", "w") as _f:
                        _f.write(page.content())
                    btns = page.evaluate(
                        """() => Array.from(document.querySelectorAll('button')).map(b => ({
                            text: (b.innerText||'').trim().slice(0,200),
                            cls: b.className, disabled: !!b.disabled,
                            visible: !!(b.offsetWidth||b.offsetHeight||b.getClientRects().length),
                        }))"""
                    )
                    with open(f"{out_dir}/buttons-fail.json", "w") as _f:
                        _json.dump(btns, _f, indent=2)
                except Exception:
                    pass
                err_text = None
                try:
                    err_el = page.query_selector('[role="alert"], .error, .alert-danger, .alert-error')
                    if err_el:
                        err_text = err_el.text_content().strip()
                except Exception:
                    pass
                raise RuntimeError(
                    f"Confirm (Submit refund to ...) button did not appear after clicking "
                    f"Review refund for order {order_id}. Refund was NOT submitted. "
                    f"Page error (if any): {err_text or 'none detected'}. URL: {page.url}. "
                    f"Debug artifacts in /tmp/bl-refund-debug-stage2-artifacts."
                )
            activity.info(f"confirm button found: {confirm_info.get('text')!r}")

            if dry_run:
                # Allow a deeper dry-run: stop AT confirm button, don't click.
                import os as _os
                if _os.environ.get("BL_REFUND_DRYRUN_STOP_AT_CONFIRM"):
                    return {
                        "success": True,
                        "dry_run": True,
                        "stage": "confirm_visible",
                        "order_id": order_id,
                        "reason_resolved": resolved_label,
                        "amount": amount,
                        "message": "Dry run: Review clicked, Submit refund button is visible. Not clicked.",
                    }

            # Click the confirm button via JS (same button we matched above).
            clicked = page.evaluate(
                """() => {
                    const btns = Array.from(document.querySelectorAll('button'));
                    const b = btns.find(x => {
                        const t = (x.innerText || '').trim();
                        return t.startsWith('Submit refund to') && !x.disabled;
                    });
                    if (!b) return false;
                    b.click();
                    return true;
                }"""
            )
            if not clicked:
                raise RuntimeError(
                    f"Submit refund button vanished before click for order {order_id}."
                )
            page.wait_for_timeout(3000)

            # --- VERIFY: re-read refund page and confirm prior_refunds delta ---
            # Small tolerance for float/rounding (BL displays to 2 decimals).
            expected_delta = float(amount) if (amount is not None and not full) else None
            prior_after, actual_delta = self._verify_refund_posted(
                page, order_id, prior_before, expected_delta
            )

            result = {
                "success": True,
                "order_id": order_id,
                "reason": reason,
                "details": details,
                "prior_refunds_before": round(prior_before, 2),
                "prior_refunds_after": round(prior_after, 2),
                "verified_delta": actual_delta,
            }
            if full:
                result["full_refund"] = True
                result["message"] = "Full refund issued successfully (verified via prior_refunds delta)"
            else:
                result["amount"] = amount
                result["message"] = f"Refund of ${amount} issued successfully (verified: prior_refunds ${prior_before:.2f} -> ${prior_after:.2f})"
            return result
        except ConfirmationRequiredError:
            raise

    def issue_refund(self, order_id: str, amount: float, reason: str = None,
                     details: str = None, dry_run: bool = False) -> dict:
        """Issue a partial refund for an order."""
        reason = reason or RefundReason.MISSING_UNSATISFACTORY.value
        return self._submit_refund(order_id, reason, details, amount=amount, dry_run=dry_run)

    def issue_full_refund(self, order_id: str, reason: str = None,
                          details: str = None, dry_run: bool = False) -> dict:
        """Issue a full refund for an order."""
        reason = reason or RefundReason.CANCEL_ORDER.value
        return self._submit_refund(order_id, reason, details, full=True, dry_run=dry_run)

    # ==================== Invoices ====================
    #
    # The `get_latest_invoice` and `pay_invoice` helpers were removed
    # on 2026-05-16 along with the `invoice` command group in
    # `commands/invoice.py`. Bricklink retired the legacy v3 billing
    # scrape target (`/v3/billing/invoice.page` and its v2/v3 siblings
    # all 302 to a 404 page family — verified by direct curl probe and
    # by `_check_server_error` raising on the redirect). Billing was
    # rolled into the LEGO Identity portal at `identity.lego.com`,
    # which has no public programmatic surface our session can reach.
    # The Bricklink OAuth REST API has never exposed an invoice/billing
    # endpoint — see `client.py` for the full method list.
    #
    # Restoring invoice support requires either:
    #   (a) Bricklink reintroducing a scrape-friendly billing page on
    #       bricklink.com that survives the LEGO ID redirect; or
    #   (b) Bricklink publishing an invoice/billing REST endpoint that
    #       can be added to `client.py` and exposed via a new
    #       `commands/invoice.py` group.
    # Until then, the `bricklink invoice ...` command group is gone.

    # ==================== Order Search ====================

    _ORDER_ITEM_TYPE_CODES = {
        "S": "S",
        "SET": "S",
        "SETS": "S",
        "P": "P",
        "PART": "P",
        "PARTS": "P",
        "M": "M",
        "MINIFIG": "M",
        "MINIFIGURE": "M",
        "MINIFIGURES": "M",
        "B": "B",
        "BOOK": "B",
        "BOOKS": "B",
        "G": "G",
        "GEAR": "G",
        "C": "C",
        "CATALOG": "C",
        "CATALOGS": "C",
        "I": "I",
        "INSTRUCTION": "I",
        "INSTRUCTIONS": "I",
        "O": "O",
        "ORIGINAL_BOX": "O",
        "ORIGINAL_BOXES": "O",
        "U": "U",
        "UNSORTED_LOT": "U",
        "UNSORTED_LOTS": "U",
    }

    @classmethod
    def _order_item_type_code(cls, item_type: Optional[str]) -> str:
        if not item_type:
            return ""
        key = item_type.strip().upper().replace(" ", "_")
        if key not in cls._ORDER_ITEM_TYPE_CODES:
            raise ValueError(f"Unsupported Bricklink order item type: {item_type}")
        return cls._ORDER_ITEM_TYPE_CODES[key]

    @staticmethod
    def _split_order_item_number(item_no: str) -> tuple[str, str]:
        match = re.match(r"^(.+)-([1-9]|1[0-9]|2[0-5])$", item_no)
        if not match:
            return item_no, "1"
        return match.group(1), match.group(2)

    @staticmethod
    def _order_search_date_parts(value: Optional[str], label: str) -> Optional[dict]:
        if not value:
            return None
        match = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", value.strip())
        if not match:
            raise ValueError(f"{label} date must be MM/DD/YYYY")
        month, day, year = match.groups()
        return {"month": str(int(month)), "day": str(int(day)), "year": year}

    @staticmethod
    def _order_search_url(direction: Optional[str]) -> str:
        if direction is None:
            return "https://www.bricklink.com/orderSearch.asp?a=p"
        key = direction.strip().lower()
        if key == "out":
            return "https://www.bricklink.com/orderSearch.asp?a=p"
        if key == "in":
            return "https://www.bricklink.com/orderSearch.asp?a=r"
        raise ValueError("Order search direction must be 'in' or 'out'")

    def search_orders_by_item(self, item_no: str, item_type: str = None,
                              color_id: int = None, condition: str = None,
                              status: str = None, from_date: str = None,
                              to_date: str = None,
                              direction: str = None) -> list:
        """Search orders containing a specific item (browser-based)."""
        item_base, item_seq = self._split_order_item_number(item_no)
        from_parts = self._order_search_date_parts(from_date, "--from")
        to_parts = self._order_search_date_parts(to_date, "--to")
        order_search_url = self._order_search_url(direction)
        page = self._get_page_for(order_search_url)

        # Sentinel: the orderSearch.asp results page must contain the
        # search form (an ``input[name="itemNo"]`` element). If that is
        # missing, the URL is no longer serving orderSearch — likely the
        # endpoint has changed and we are looking at a generic page that
        # would silently parse to []. Raise loudly instead of returning
        # an empty list that misrepresents "endpoint dead" as "0 matches".
        results_form = page.query_selector('input[name="itemNo"]')
        if not results_form:
            raise RuntimeError(
                f"orderSearch.asp at {page.url} did not return the expected "
                "results UI (missing input[name='itemNo']). The page may "
                "have changed or the search may have failed."
            )

        page.evaluate(
            """(data) => {
                const setValue = (selector, value) => {
                    const el = document.querySelector(selector);
                    if (!el) throw new Error(`Missing form control: ${selector}`);
                    el.value = value;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                };
                const setChecked = (selector, checked) => {
                    const el = document.querySelector(selector);
                    if (!el) throw new Error(`Missing form control: ${selector}`);
                    el.checked = checked;
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                };
                const setSelect = (selector, value) => {
                    const el = document.querySelector(selector);
                    if (!el) throw new Error(`Missing form control: ${selector}`);
                    if (value === '') {
                        el.value = '';
                    } else {
                        const normalized = String(value).trim().toLowerCase();
                        const option = Array.from(el.options).find((opt) =>
                            opt.value.toLowerCase() === normalized ||
                            opt.textContent.trim().toLowerCase() === normalized
                        );
                        if (!option) throw new Error(`Unsupported value ${value} for ${selector}`);
                        el.value = option.value;
                    }
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                };

                setValue('input[name="itemNo"]', data.itemNo);
                setSelect('select[name="itemSeq"]', data.itemSeq);
                setSelect('select[name="itemType"]', data.itemType);
                setSelect('select[name="colorID"]', data.colorID);
                setSelect('select[name="orderNew"]', data.condition);
                setSelect('select[name="st"]', data.status);
                setSelect('select[name="orderFiled"]', 'A');

                if (data.fromDate || data.toDate) {
                    setChecked('input[name="searchDate"]', true);
                    if (!data.fromDate || !data.toDate) {
                        throw new Error('Both --from and --to are required for date-filtered order search');
                    }
                    setSelect('select[name="fMM"]', data.fromDate.month);
                    setSelect('select[name="fDD"]', data.fromDate.day);
                    setSelect('select[name="fYY"]', data.fromDate.year);
                    setSelect('select[name="tMM"]', data.toDate.month);
                    setSelect('select[name="tDD"]', data.toDate.day);
                    setSelect('select[name="tYY"]', data.toDate.year);
                } else {
                    setChecked('input[name="searchDate"]', false);
                }

                const submit = document.querySelector('input[type="SUBMIT"][value="Search Now!"]');
                if (!submit) throw new Error('Missing Search Now button');
                submit.click();
            }""",
            {
                "itemNo": item_base,
                "itemSeq": item_seq,
                "itemType": self._order_item_type_code(item_type),
                "colorID": str(color_id or ""),
                "condition": condition or "",
                "status": status or "",
                "fromDate": from_parts,
                "toDate": to_parts,
            },
        )
        page.wait_for_timeout(3000)
        page.wait_for_selector("body", state="visible", timeout=15000)
        page.wait_for_network_idle(timeout=10)
        self._check_session_expired(page)
        self._check_server_error(page, order_search_url)

        orders = page.evaluate("""() => {
            const results = [];
            const links = document.querySelectorAll('a[href*="orderDetail.asp?ID="]');
            const seenIds = new Set();

            for (const link of links) {
                const href = link.href;
                const idMatch = href.match(/ID=(\\d+)/);
                if (!idMatch) continue;

                const orderId = idMatch[1];
                if (seenIds.has(orderId)) continue;
                seenIds.add(orderId);

                const row = link.closest('tr');
                let date = '', buyer = '', status = '';
                if (row) {
                    const cells = row.querySelectorAll('td');
                    if (cells.length >= 3) {
                        date = cells[1]?.textContent.trim() || '';
                        buyer = cells[2]?.textContent.trim() || '';
                    }
                }

                results.push({ order_id: orderId, date, buyer, url: href });
            }
            return results;
        }""")

        return orders

    # ==================== Wanted List Notification ====================

    def send_wanted_list_notification(self) -> dict:
        """Send wanted list notification to all matching stores."""
        url = self.WANTED_NOTIFY_URL
        page = self._get_page_for(url)

        # Click the send notification button
        send_btn = page.query_selector(
            'input[type="submit"][value*="Send"], button:has-text("Send")'
        )
        if not send_btn:
            return {"success": False, "message": "Send notification button not found."}

        send_btn.click()
        page.wait_for_timeout(3000)

        content = page.content()
        success = "sent" in content.lower() or "notification" in content.lower()

        return {"success": success,
                "message": "Wanted list notification sent" if success else "Notification may have failed. Verify on Bricklink."}

    # ==================== NSS Alerts ====================

    def list_nss_alerts(self) -> list:
        """List active Non-Shipping Seller (NSS) alerts against the seller."""
        url = "https://www.bricklink.com/orderReceived.asp?st=s"
        page = self._get_page_for(url)

        # Check if there's any orders on the page
        try:
            page.wait_for_selector('a[href*="orderDetail.asp?ID="], a[href*="orderDetail.asp?id="]', timeout=5000)
        except Exception:
            return []

        orders = page.evaluate("""() => {
            const results = [];
            const links = Array.from(document.querySelectorAll('a[href*="orderDetail.asp?ID="], a[href*="orderDetail.asp?id="]'));
            const seen = new Set();
            for (const link of links) {
                const href = link.getAttribute('href');
                const match = href.match(/ID=(\\d+)/i);
                if (!match) continue;
                const orderId = match[1];
                if (seen.has(orderId)) continue;
                seen.add(orderId);
                
                const tr = link.closest('tr');
                if (!tr) continue;
                const cells = Array.from(tr.querySelectorAll('td')).map(td => (td.textContent || '').trim());
                if (cells.length < 13) continue;
                
                let buyer = cells[6] || '';
                buyer = buyer.replace(/\\u00a0/g, ' ').split('(')[0].trim();
                
                results.push({
                    order_id: orderId,
                    date: cells[2] || '',
                    buyer: buyer,
                    items_cost: cells[9] || '',
                    grand_total: cells[10] || '',
                    final_total: cells[11] || '',
                    status: cells[12] || 'NSS',
                    url: 'https://www.bricklink.com/' + href
                });
            }
            return results;
        }""")
        return orders

    def get_nss_alert(self, order_id: str) -> dict:
        """Get details for a specific Non-Shipping Seller (NSS) alert by order ID."""
        url = f"https://www.bricklink.com/retractOrder.asp?ID={order_id}"
        page = self._get_page_for(url)

        info = page.evaluate("""() => {
            const bodyText = document.body.innerText;
            
            // Status and Cancel
            let status = '';
            const statusMatch = bodyText.match(/Current Problem Status:\\s*([\\s\\S]*?)(?=\\n\\n|\\nMy Next|\\nComments|\\nProblem Comments)/i);
            if (statusMatch) status = statusMatch[1].trim();
            
            let cancellation_info = '';
            const cancelMatch = bodyText.match(/This order can be cancelled after\\s*([^\\n]*)/i);
            if (cancelMatch) cancellation_info = cancelMatch[0].trim();
            
            let reason = '';
            const reasonMatch = bodyText.match(/Reason:\\s*([^\\n]*)/i);
            if (reasonMatch) reason = reasonMatch[1].trim();
            
            let details = '';
            const detailsMatch = bodyText.match(/Details:\\s*([\\s\\S]*?)(?=\\n\\n|\\nFrom:|\\nBrickLink)/i);
            if (detailsMatch) details = detailsMatch[1].trim();
            
            // Let's extract comments/history
            const comments = [];
            const commentsIndex = bodyText.indexOf('Problem Comments:');
            if (commentsIndex !== -1) {
                const commentsSection = bodyText.substring(commentsIndex).trim();
                const parts = commentsSection.split(/\\nFrom:\\s*/);
                for (let i = 1; i < parts.length; i++) {
                    const part = parts[i].trim();
                    const lines = part.split('\\n');
                    const header = lines[0] || '';
                    const headerMatch = header.match(/^([^\\t(]+)(?:\\(([^)]+)\\))?\\s*\\t*Posted on:\\s*([^\\t\\n]+)/);
                    
                    let user = '';
                    let date = '';
                    if (headerMatch) {
                        user = headerMatch[1].trim();
                        date = headerMatch[3].trim();
                    } else {
                        const postedOnIndex = header.indexOf('Posted on:');
                        if (postedOnIndex !== -1) {
                            user = header.substring(0, postedOnIndex).trim();
                            date = header.substring(postedOnIndex + 10).trim();
                        } else {
                            user = header;
                        }
                    }
                    user = user.replace(/\\u00a0/g, ' ').trim();
                    date = date.replace(/\\u00a0/g, ' ').trim();
                    
                    let commentBody = lines.slice(1).join('\\n').trim();
                    const footerIdx = commentBody.indexOf('\\nBrickLink');
                    if (footerIdx !== -1) {
                        commentBody = commentBody.substring(0, footerIdx).trim();
                    } else if (commentBody.includes('BrickLink\\nAbout Us')) {
                        const footerIdx2 = commentBody.indexOf('BrickLink\\nAbout Us');
                        commentBody = commentBody.substring(0, footerIdx2).trim();
                    }
                    
                    comments.push({
                        user,
                        date,
                        message: commentBody
                    });
                }
            }
            
            return {
                status: status.replace(/\\u00a0/g, ' '),
                cancellation_info: cancellation_info.replace(/\\u00a0/g, ' '),
                reason: reason.replace(/\\u00a0/g, ' '),
                details: details.replace(/\\u00a0/g, ' '),
                comments
            };
        }""")
        return {"order_id": order_id, **info, "url": page.url}
