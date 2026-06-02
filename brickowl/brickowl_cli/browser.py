"""Browser automation service for Brick Owl.

Handles operations not available via API:
- Messages (list, view, reply, send, mark read/unread)
- Refunds (info, issue partial/full)
- Coupons (list, create user/code, delete)
- Quotes (list, view, submit)

Authentication and session management are fully delegated to
BrowserAutomation from cli_tools_shared.
"""
import re
import sys
from datetime import datetime
from typing import List, Optional

from cli_tools_shared.auth import BrowserAutomation, BrowserAutomationError
from cli_tools_shared.http_session import BrowserAuthState
from cli_tools_shared.data_cache import cached

from .config import get_config


class _BrickOwlAutomation(BrowserAutomation):
    SESSION_NAME = "brickowl"
    LOGIN_URL = "https://www.brickowl.com/user?destination=mystore/orders"
    AUTH_CHECK_URL = "https://www.brickowl.com/mystore/orders"
    AUTH_URL_PATTERN = r"/user(?:$|[/?].*)"
    AUTH_SUCCESS_SELECTOR = "#dLabel .hello"


class BrickOwlBrowser:
    """Brick Owl browser operations backed by shared BrowserAutomation."""

    def __init__(self, config=None):
        self._automation = _BrickOwlAutomation(config or get_config())
        self.config = self._automation.config
        self._user_id: Optional[str] = None

    def __getattr__(self, name):
        return getattr(self._automation, name)

    def _ensure_authenticated(self):
        """Verify browser session is authenticated and initialize page.

        Only checks on first call (when no page exists). Subsequent calls
        skip the check since the session was already verified.
        """
        if self._page is not None:
            return
        BrowserAuthState.from_config(self.config)
        if not self.is_authenticated():
            raise RuntimeError(
                "Not logged in. Run 'brickowl auth login -c browser_session' to authenticate."
            )
        self.get_page()

    # ==================== Site-Specific Methods ====================

    def get_user_id(self) -> Optional[str]:
        """Get the logged-in user's ID via the API (reliable) or browser fallback."""
        if self._user_id:
            return self._user_id

        # Primary: get uid from API (fast, doesn't require browser session)
        try:
            from .client import BrickowlClient
            client = BrickowlClient()
            details = client.get_user_details()
            if details.uid:
                self._user_id = details.uid
                return self._user_id
        except Exception:
            pass

        # Fallback: extract from browser redirect
        page = self.get_page("https://www.brickowl.com/user/me/messages")
        page.wait_for_timeout(1500)
        match = re.search(r"/user/(\d+)", page.url)
        if match:
            self._user_id = match.group(1)

        return self._user_id

    @staticmethod
    def normalize_subject(subject: str) -> str:
        """Normalize a message subject for conversation matching."""
        s = subject.strip()
        while s.lower().startswith("re: "):
            s = s[4:]
        s = re.sub(r'^Brick Owl:\s*Your order has been shipped\s*', 'Order ', s, flags=re.IGNORECASE)
        s = s.replace("#", "")
        s = re.sub(r'\s+', ' ', s).strip()
        return s.lower()

    # ==================== Messages ====================

    @cached
    def list_messages(self, folder: str = "received") -> list:
        """List messages from inbox, sent, or all folders.

        Args:
            folder: 'received', 'sent', or 'all'
        """
        self._ensure_authenticated()

        user_id = self.get_user_id()
        if not user_id:
            raise RuntimeError("Could not determine user ID.")

        folder_path = {
            "received": "messages",
            "sent": "messages/sent",
            "all": "messages/all",
        }.get(folder, "messages")

        self._page.goto(f"https://www.brickowl.com/user/{user_id}/{folder_path}")
        self._page.wait_for_timeout(2000)

        messages = self._page.evaluate("""() => {
            const results = [];
            const rows = document.querySelectorAll('table tbody tr');

            for (const row of rows) {
                const cells = row.querySelectorAll('td');
                if (cells.length < 5) continue;

                const subjectLink = row.querySelector('a[href*="/messages/all/"]');
                if (!subjectLink) continue;

                const href = subjectLink.href;
                const msgIdMatch = href.match(/\\/messages\\/all\\/(\\d+)/);
                if (!msgIdMatch) continue;

                const messageId = msgIdMatch[1];
                const date = cells[1]?.innerText?.trim() || '';
                const from = cells[2]?.textContent?.trim() || '';
                const to = cells[3]?.textContent?.trim() || '';
                const subject = subjectLink.textContent?.trim() || '';

                const orderMatch = subject.match(/Order #(\\d+)/);
                const orderId = orderMatch ? orderMatch[1] : null;

                const statusCell = cells[4];
                const statusIcons = statusCell?.querySelectorAll('[title]') || [];
                const statuses = Array.from(statusIcons).map(i => i.getAttribute('title'));
                const is_unread = statusIcons.length > 0 &&
                    Array.from(statusIcons).some(i => i.classList.contains('icon-envelope'));
                const response_required = Array.from(statusIcons).some(
                    i => i.classList.contains('icon-exclamation'));
                const status = statuses.join(', ');

                results.push({
                    message_id: messageId,
                    date,
                    from: from,
                    to,
                    subject,
                    order_id: orderId,
                    status,
                    is_unread,
                    response_required,
                    url: href
                });
            }

            return results;
        }""")

        return messages

    @cached
    def get_message(self, message_id: str) -> dict:
        """Get message details by message ID."""
        self._ensure_authenticated()

        user_id = self.get_user_id()
        if not user_id:
            raise RuntimeError("Could not determine user ID.")

        self._page.goto(
            f"https://www.brickowl.com/user/{user_id}/messages/all/{message_id}"
        )
        self._page.wait_for_timeout(1500)

        info = self._page.evaluate("""() => {
            const table = document.querySelector('table.form-list');
            const rows = table ? table.querySelectorAll('tr') : [];
            let from = null;
            let to = null;
            let sentDate = null;
            let subject = null;
            let orderId = null;
            let attachments = [];

            for (const row of rows) {
                const cells = row.querySelectorAll('td');
                if (cells.length < 2) continue;

                const label = cells[0]?.textContent?.trim();
                const value = cells[1]?.textContent?.trim();

                if (label === 'From') from = value;
                else if (label === 'To') to = value;
                else if (label === 'Sent') sentDate = value;
                else if (label === 'Subject') {
                    subject = value;
                    const orderMatch = subject.match(/Order #(\\d+)/);
                    if (orderMatch) orderId = orderMatch[1];
                } else if (label === 'Attachments') {
                    const links = cells[1].querySelectorAll('a');
                    for (const link of links) {
                        const filename = link.textContent?.trim();
                        const url = link.href;
                        const sizeMatch = cells[1].textContent.match(new RegExp(filename.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&') + '\\\\s*\\\\(([^)]+)\\\\)'));
                        const size = sizeMatch ? sizeMatch[1] : null;
                        if (filename && url) {
                            attachments.push({ filename, url, size });
                        }
                    }
                }
            }

            let body = null;
            const messageContents = document.querySelectorAll('div.message-content');
            for (const messageContent of messageContents) {
                const preElement = messageContent.querySelector('pre');
                if (preElement) {
                    const text = preElement.textContent?.trim();
                    if (text && !text.startsWith('View the response')) {
                        body = text;
                        break;
                    }
                }
            }
            if (!body && messageContents.length > 0) {
                body = messageContents[0].textContent?.trim();
            }

            return { from, to, sent_date: sentDate, subject, order_id: orderId, body, attachments: attachments.length > 0 ? attachments : null };
        }""")

        url = f"https://www.brickowl.com/user/{user_id}/messages/all/{message_id}"
        return {"message_id": message_id, **info, "url": url}

    def download_attachments(self, attachments: list, output_dir: str = None) -> list:
        """Download attachments to local files. Adds 'local_path' to each dict."""
        from pathlib import Path

        self._ensure_authenticated()

        target = Path(output_dir) if output_dir else Path.cwd()
        target.mkdir(parents=True, exist_ok=True)

        for att in attachments:
            url = att.get("url")
            if not url:
                continue
            filepath = target / att.get("filename", "attachment")
            resp = self._page.context.request.get(url)
            if not resp.ok:
                raise RuntimeError(f"Failed to download {url}: {resp.status} {resp.status_text}")
            filepath.write_bytes(resp.body())
            att["local_path"] = str(filepath)

        return attachments

    def _message_direction(self, sender: str) -> str:
        seller_name = (
            self.config._get("SELLER_NAME")
            or self.config._get("STORE_NAME")
            or self.config._get("USERNAME")
        )
        if seller_name and sender.strip().casefold() == seller_name.strip().casefold():
            return "sent"
        return "received"

    def get_conversation(self, order_id: str) -> dict:
        """Get full conversation thread for an order.

        Lists all messages, filters by order_id, fetches details,
        and returns a structured conversation.
        """
        all_messages = self.list_messages(folder="all")
        matching = [m for m in all_messages if m.get("order_id") == order_id]

        if not matching:
            return {
                "order_id": order_id,
                "platform": "brickowl",
                "message_count": 0,
                "messages": [],
                "last_message_from": None,
                "last_message_date": None,
                "days_since_last_message": None,
            }

        # Fetch full details for each matching message
        messages_with_details = []
        for msg in matching:
            try:
                details = self.get_message(msg["message_id"])
                sender = msg.get("from", "")
                direction = self._message_direction(sender)

                messages_with_details.append({
                    "message_id": msg["message_id"],
                    "direction": direction,
                    "sender": msg.get("from"),
                    "recipient": msg.get("to"),
                    "date": details.get("sent_date"),
                    "subject": details.get("subject"),
                    "body": details.get("body"),
                })
            except Exception:
                sender = msg.get("from", "")
                direction = self._message_direction(sender)
                messages_with_details.append({
                    "message_id": msg["message_id"],
                    "direction": direction,
                    "sender": msg.get("from"),
                    "recipient": msg.get("to"),
                    "date": None,
                    "subject": msg.get("subject"),
                    "body": None,
                })

        # Sort chronologically (oldest first), nulls last
        def sort_key(m):
            d = m.get("date")
            if not d:
                return datetime.max
            try:
                return datetime.strptime(d, "%b %d, %Y %I:%M %p")
            except (ValueError, TypeError):
                try:
                    return datetime.strptime(d, "%d %b %Y %H:%M")
                except (ValueError, TypeError):
                    return datetime.max

        messages_with_details.sort(key=sort_key)

        last_msg = messages_with_details[-1]

        # Calculate days since last message
        days_since = None
        if last_msg.get("date"):
            try:
                last_date = sort_key(last_msg)
                if last_date != datetime.max:
                    days_since = (datetime.now() - last_date).days
            except Exception:
                pass

        return {
            "order_id": order_id,
            "platform": "brickowl",
            "message_count": len(matching),
            "messages": messages_with_details,
            "last_message_from": last_msg.get("sender"),
            "last_message_date": last_msg.get("date"),
            "days_since_last_message": days_since,
        }

    def reply_to_message(self, message_id: str, body: str) -> dict:
        """Reply to a message by message ID.

        Navigates to the message detail page, extracts the contact/reply
        URL (or builds one from the other party's user ID), navigates to
        the contact form, fills the body, and sends the reply.
        """
        self._ensure_authenticated()

        user_id = self.get_user_id()
        if not user_id:
            raise RuntimeError("Could not determine user ID.")

        # Navigate to message detail page
        msg_url = f"https://www.brickowl.com/user/{user_id}/messages/all/{message_id}"
        self._page.goto(msg_url)
        self._page.wait_for_timeout(1500)

        # Extract reply info from the message page via JavaScript:
        # - Any link whose href contains "/contact" (reply link)
        # - The other party's user ID from profile links
        # - The message subject for pre-filling the reply
        reply_info = self._page.evaluate("""() => {
            // 1. Look for a contact/reply link (multiple selector strategies)
            //    Prefer links matching /user/<digits>/contact (Brick Owl user contact page)
            let contactHref = null;
            const allContactLinks = document.querySelectorAll('a[href*="/contact"]');
            for (const link of allContactLinks) {
                const href = link.getAttribute('href');
                if (!href) continue;
                // Match /user/<digits>/contact (with or without query params)
                if (/\\/user\\/\\d+\\/contact/.test(href)) {
                    contactHref = href;
                    break;
                }
            }

            // 2. Extract subject from the form-list table
            let subject = null;
            const table = document.querySelector('table.form-list');
            if (table) {
                const rows = table.querySelectorAll('tr');
                for (const row of rows) {
                    const cells = row.querySelectorAll('td');
                    if (cells.length >= 2) {
                        const label = cells[0]?.textContent?.trim();
                        if (label === 'Subject') {
                            subject = cells[1]?.textContent?.trim();
                        }
                    }
                }
            }

            // 3. Extract the other party's user ID from profile links
            //    Look for /user/<digits> links in the From/To rows
            let otherUserId = null;
            if (table) {
                const rows = table.querySelectorAll('tr');
                for (const row of rows) {
                    const cells = row.querySelectorAll('td');
                    if (cells.length >= 2) {
                        const label = cells[0]?.textContent?.trim();
                        if (label === 'From' || label === 'To') {
                            const link = cells[1].querySelector('a[href*="/user/"]');
                            if (link) {
                                const match = link.getAttribute('href').match(/\\/user\\/(\\d+)/);
                                if (match) {
                                    const uid = match[1];
                                    // Skip our own user ID
                                    if (uid !== '""" + user_id + """') {
                                        otherUserId = uid;
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // 4. Fallback: scan all links for a /user/<digits>/contact pattern
            if (!contactHref && !otherUserId) {
                const allLinks = document.querySelectorAll('a[href*="/user/"]');
                for (const link of allLinks) {
                    const href = link.getAttribute('href');
                    const match = href?.match(/\\/user\\/(\\d+)\\/contact/);
                    if (match) {
                        contactHref = href;
                        break;
                    }
                    // Also try to find any user ID that isn't ours
                    if (!otherUserId) {
                        const uidMatch = href?.match(/\\/user\\/(\\d+)/);
                        if (uidMatch && uidMatch[1] !== '""" + user_id + """') {
                            otherUserId = uidMatch[1];
                        }
                    }
                }
            }

            return { contactHref, subject, otherUserId };
        }""")

        contact_url = None

        # Strategy 1: Use the extracted contact link directly
        if reply_info.get("contactHref"):
            href = reply_info["contactHref"]
            contact_url = href if href.startswith("http") else f"https://www.brickowl.com{href}"

        # Strategy 2: Build contact URL from the other party's user ID
        if not contact_url and reply_info.get("otherUserId"):
            contact_url = f"https://www.brickowl.com/user/{reply_info['otherUserId']}/contact"

        if not contact_url:
            raise RuntimeError(
                f"Could not find reply link or recipient user ID on message page. "
                f"Page URL: {self._page.url}"
            )

        # Navigate to the contact/reply form
        self._page.goto(contact_url)
        self._page.wait_for_timeout(1500)

        # Verify we're on the contact form
        if "/contact" not in self._page.url:
            raise RuntimeError(
                f"Failed to navigate to reply form. "
                f"Expected URL containing '/contact', got: {self._page.url}"
            )

        # Pre-fill the subject as "Re: ..." if a subject input exists
        original_subject = reply_info.get("subject") or ""
        if original_subject and not original_subject.lower().startswith("re:"):
            reply_subject = f"Re: {original_subject}"
        else:
            reply_subject = original_subject

        if reply_subject:
            subject_input = self._page.query_selector(
                'input[name="main_subject"], input[name="subject"]'
            )
            if subject_input:
                subject_input.fill(reply_subject)

        # Fill in the message body (Brick Owl uses name="main_message")
        textarea = self._page.wait_for_selector(
            'textarea[name="main_message"], textarea[name="message"], textarea',
            state="visible",
            timeout=10000,
        )
        if not textarea:
            raise RuntimeError("Message textarea not found.")
        textarea.fill(body)

        # Click Send Message button (Brick Owl uses input[type="submit"])
        send_button = self._page.query_selector('input[type="submit"][value*="Send"]')
        if not send_button:
            send_button = self._page.get_by_role("button", name=re.compile(r"send message", re.IGNORECASE))
        send_button.click()
        self._page.wait_for_timeout(3000)

        # Check for success
        current_url = self._page.url
        page_content = self._page.content().lower()
        success = (
            "/messages" in current_url
            or "sent" in page_content
            or "message sent" in page_content
            or "/contact" not in current_url
        )

        return {
            "success": success,
            "message_id": message_id,
            "action": "reply",
            "message": "Reply sent successfully" if success else "Reply may have failed. Please verify on Brick Owl.",
        }

    def send_order_message(self, order_id: str, user_id: str, subject: str, body: str) -> dict:
        """Send a message to a buyer linked to an order.

        Uses the same contact form as ``send_message`` but includes the
        ``destination`` query parameter so Brick Owl links the message to the
        order.  This matches the URL produced by Actions → Contact Customer
        on the order page.

        Args:
            order_id: The Brick Owl order ID.
            user_id: The buyer's numeric user ID.
            subject: Message subject line.
            body: Message body text.
        """
        self._ensure_authenticated()

        from urllib.parse import quote
        contact_url = (
            f"https://www.brickowl.com/user/{user_id}/contact"
            f"?destination=mystore/orders/outstanding/{order_id}"
            f"&subject={quote(subject)}"
        )
        self._page.goto(contact_url)
        self._page.wait_for_timeout(1500)

        # Subject is pre-filled by the URL param, but fill explicitly to be safe
        subject_input = self._page.query_selector(
            'input[name="main_subject"], input[name="subject"]'
        )
        if subject_input:
            subject_input.fill(subject)

        textarea = self._page.wait_for_selector(
            'textarea[name="main_message"], textarea[name="message"], textarea',
            state="visible",
            timeout=10000,
        )
        if not textarea:
            raise RuntimeError("Message textarea not found.")
        textarea.fill(body)

        # Click Send Message button
        send_button = self._page.query_selector('input[type="submit"][value*="Send"]')
        if not send_button:
            send_button = self._page.get_by_role("button", name=re.compile(r"send message", re.IGNORECASE))
        send_button.click()
        self._page.wait_for_timeout(3000)

        # Check for success
        current_url = self._page.url
        page_content = self._page.content().lower()
        success = (
            "/contact" not in current_url
            or "sent" in page_content
            or "message sent" in page_content
        )

        return {
            "success": success,
            "order_id": order_id,
            "action": "send",
            "message": "Message sent successfully" if success else "Message may have failed. Please verify on Brick Owl.",
        }

    def send_message(self, username: str, subject: str, body: str) -> dict:
        """Send a new message to a user.

        Args:
            username: Recipient username or numeric user ID.
                      Numeric user IDs are preferred since Brick Owl profile
                      URLs by username are unreliable.
            subject: Message subject line.
            body: Message body text.
        """
        self._ensure_authenticated()

        # Navigate to user's contact page (numeric user ID is the reliable path)
        if username.isdigit():
            contact_url = f"https://www.brickowl.com/user/{username}/contact"
        else:
            # Navigate to user profile first to find contact link
            self._page.goto(f"https://www.brickowl.com/user/{username}")
            self._page.wait_for_timeout(1500)

            contact_link = self._page.query_selector('a[href*="/contact"]')
            if not contact_link:
                raise RuntimeError(f"Could not find contact link for user: {username}")
            href = contact_link.get_attribute("href")
            contact_url = href if href.startswith("http") else f"https://www.brickowl.com{href}"

        self._page.goto(contact_url)
        self._page.wait_for_timeout(1500)

        # Fill subject (Brick Owl uses name="main_subject")
        subject_input = self._page.query_selector(
            'input[name="main_subject"], input[name="subject"]'
        )
        if subject_input:
            subject_input.fill(subject)

        # Fill message body (Brick Owl uses name="main_message")
        textarea = self._page.wait_for_selector(
            'textarea[name="main_message"], textarea[name="message"], textarea',
            state="visible",
            timeout=10000,
        )
        if not textarea:
            raise RuntimeError("Message textarea not found.")
        textarea.fill(body)

        # Click Send Message button (Brick Owl uses input[type="submit"])
        send_button = self._page.query_selector('input[type="submit"][value*="Send"]')
        if not send_button:
            send_button = self._page.get_by_role("button", name=re.compile(r"send message", re.IGNORECASE))
        send_button.click()
        self._page.wait_for_timeout(3000)

        # Check for success
        current_url = self._page.url
        page_content = self._page.content().lower()
        success = (
            "/contact" not in current_url
            or "sent" in page_content
            or "message sent" in page_content
        )

        return {
            "success": success,
            "recipient": username,
            "action": "send",
            "message": "Message sent successfully" if success else "Message may have failed. Please verify on Brick Owl.",
        }

    def mark_as_read(self, message_id: str) -> dict:
        """Mark a message as read by navigating to it (viewing marks as read)."""
        self._ensure_authenticated()

        user_id = self.get_user_id()
        if not user_id:
            raise RuntimeError("Could not determine user ID.")

        self._page.goto(
            f"https://www.brickowl.com/user/{user_id}/messages/all/{message_id}"
        )
        self._page.wait_for_timeout(1500)

        page_content = self._page.content()
        success = "Subject" in page_content or "From" in page_content

        return {
            "success": success,
            "message_id": message_id,
            "action": "mark_as_read",
            "message": "Message marked as read" if success else "Could not mark message as read.",
        }

    def mark_as_unread(self, message_id: str) -> dict:
        """Mark a message as unread via the inbox checkbox + action."""
        self._ensure_authenticated()

        user_id = self.get_user_id()
        if not user_id:
            raise RuntimeError("Could not determine user ID.")

        # Navigate to received messages page
        self._page.goto(f"https://www.brickowl.com/user/{user_id}/messages")
        self._page.wait_for_timeout(1500)

        # Find and check the checkbox for this message
        checkbox = self._page.query_selector(f'input[type="checkbox"][value="{message_id}"]')
        if not checkbox:
            raise RuntimeError(
                f"Message {message_id} not found in inbox. "
                "It may be on a different page or already unread."
            )

        checkbox.check()
        self._page.wait_for_timeout(500)

        # Look for "Mark as Unread" button/link or action dropdown
        unread_button = self._page.query_selector(
            'button:has-text("Unread"), a:has-text("Unread"), input[value*="Unread"]'
        )
        if unread_button:
            unread_button.click()
        else:
            # Try action select dropdown
            action_select = self._page.query_selector('select[name="action"]')
            if action_select:
                action_select.select_option(label="Mark as Unread")
                submit_button = self._page.query_selector(
                    'button[type="submit"], input[type="submit"]'
                )
                if submit_button:
                    submit_button.click()
            else:
                unread_link = self._page.query_selector(
                    'a[href*="unread"], a[onclick*="unread"]'
                )
                if unread_link:
                    unread_link.click()
                else:
                    raise RuntimeError('Could not find "Mark as Unread" action on the page.')

        self._page.wait_for_timeout(2000)

        current_url = self._page.url
        page_content = self._page.content().lower()
        success = "/messages" in current_url and "error" not in page_content

        return {
            "success": success,
            "message_id": message_id,
            "action": "mark_as_unread",
            "message": "Message marked as unread" if success else "Could not mark message as unread.",
        }

    # ==================== Refunds ====================

    @cached
    def get_order_info(self, order_id: str) -> dict:
        """Get order page info by scraping the order history page.

        Returns dict with order_id, order_total, buyer_name, customer_user_id,
        status, payment_amount, transaction_id.
        """
        self._ensure_authenticated()

        self._page.goto(f"https://www.brickowl.com/mystore/orders/history/{order_id}")
        self._page.wait_for_timeout(2000)

        if self._is_login_page(self._page):
            raise RuntimeError("Session expired. Please login again.")

        info = self._page.evaluate("""() => {
            const getTableValue = (label) => {
                const rows = document.querySelectorAll('tr');
                for (const row of rows) {
                    const cells = row.querySelectorAll('td');
                    if (cells.length >= 2 && cells[0].textContent.trim().includes(label)) {
                        return cells[1].textContent.trim();
                    }
                }
                return null;
            };

            // Extract customer user ID from "Contact Customer" link
            let customerUserId = null;
            const contactLink = document.querySelector('a[href*="/contact"]');
            if (contactLink) {
                const match = contactLink.href.match(/\\/user\\/(\\d+)\\/contact/);
                if (match) customerUserId = match[1];
            }

            return {
                order_total: getTableValue('Order Total'),
                buyer_name: getTableValue('Customer'),
                customer_user_id: customerUserId,
                status: getTableValue('Order Status'),
                payment_amount: getTableValue('Payment Amount'),
                transaction_id: getTableValue('Transaction ID')
            };
        }""")

        return {"order_id": order_id, **info}

    def get_refund_info(self, order_id: str) -> dict:
        """Get refund info for an order.

        NOTE: Brick Owl does not expose prior refund history.
        Returns order info with a hint to check PayPal.
        """
        order_info = self.get_order_info(order_id)

        transaction_id = order_info.get("transaction_id")
        hint = (
            f'Use: paypal orders search "{transaction_id}" -s transaction'
            if transaction_id
            else "Look up the order in PayPal to find the transaction."
        )

        raise RuntimeError(
            f"Brick Owl does not expose prior refund history.\n"
            f"To check if a refund was issued, look up the PayPal transaction.\n"
            f"{hint}"
        )

    # Valid Brick Owl refund reason dropdown labels
    _VALID_REFUND_REASONS = [
        "Out of stock",
        "Missing items",
        "Customer request",
        "Order not received",
        "Other",
        "Damaged items",
        "Payment not received",
    ]

    # Keyword-to-dropdown-label mapping for freeform reason strings
    _REASON_KEYWORD_MAP = {
        "out of stock": "Out of stock",
        "stock": "Out of stock",
        "missing": "Missing items",
        "customer request": "Customer request",
        "not received": "Order not received",
        "damaged": "Damaged items",
        "payment": "Payment not received",
    }

    def _resolve_refund_reason(self, reason: str) -> tuple:
        """Map a freeform reason string to a valid dropdown label.

        Returns:
            (dropdown_label, note_text) where note_text is the original
            freeform reason if it didn't match a dropdown label exactly,
            or empty string if it matched exactly.
        """
        # Exact match (case-insensitive) against valid labels
        for valid in self._VALID_REFUND_REASONS:
            if reason.strip().lower() == valid.lower():
                return (valid, "")

        # Keyword match
        reason_lower = reason.strip().lower()
        for keyword, label in self._REASON_KEYWORD_MAP.items():
            if keyword in reason_lower:
                return (label, reason)

        # No match — use "Other" and put freeform text in the note
        return ("Other", reason)

    def _select_refund_reason(self, reason: str) -> None:
        """Select the refund reason dropdown and fill the note textbox.

        Raises RuntimeError if the dropdown is not found or selection fails.
        """
        dropdown_label, note_text = self._resolve_refund_reason(reason)

        reason_dropdown = self._page.query_selector("select")
        if not reason_dropdown:
            raise RuntimeError("Refund reason dropdown not found on page.")

        reason_dropdown.select_option(label=dropdown_label)
        self._page.wait_for_timeout(500)

        # Verify the selection took effect
        selected_value = self._page.evaluate(
            "() => { const s = document.querySelector('select'); return s.options[s.selectedIndex].text; }"
        )
        if selected_value == "Choose a refund reason":
            raise RuntimeError(
                f"Failed to select refund reason '{dropdown_label}'. "
                f"Dropdown still shows '{selected_value}'."
            )

        # Put freeform reason text in the note textbox if it didn't match exactly
        if note_text:
            note_input = self._page.query_selector(
                "select + input[type='text'], select ~ input[type='text'], "
                "select + textarea, select ~ textarea"
            )
            if note_input:
                note_input.fill(note_text)
                self._page.wait_for_timeout(300)

    def _clear_refund_draft_state(self) -> None:
        """Clear any persisted draft state from the refund form.

        Brick Owl persists refund form draft state server-side when "Update Totals"
        is clicked, even without submitting. This method reads the current values
        of Refund Shipping and Refund Adjustment, and if either is non-zero, resets
        them to 0.00 and clicks "Update Totals" to clear the server-side draft.
        """
        # Read current values of both fields
        draft_values = self._page.evaluate("""() => {
            const result = { shipping: null, adjustment: null };
            const rows = document.querySelectorAll('tr');
            for (const row of rows) {
                const cells = row.querySelectorAll('td');
                if (cells.length < 2) continue;
                const label = cells[0].textContent.trim();
                const input = cells[1].querySelector('input[type="text"], input[type="number"], input');
                if (!input) continue;
                if (label.includes('Refund Shipping')) {
                    result.shipping = input.value;
                } else if (label.includes('Refund Adjustment')) {
                    result.adjustment = input.value;
                }
            }
            return result;
        }""")

        shipping_val = float(draft_values.get("shipping") or "0")
        adjustment_val = float(draft_values.get("adjustment") or "0")

        if shipping_val == 0 and adjustment_val == 0:
            return

        sys.stderr.write(
            f"WARNING: Refund draft state detected — "
            f"Refund Shipping: {shipping_val:.2f}, "
            f"Refund Adjustment: {adjustment_val:.2f}. "
            f"Clearing to 0.00 before proceeding.\n"
        )

        # Clear both fields to 0.00
        self._page.evaluate("""() => {
            const rows = document.querySelectorAll('tr');
            for (const row of rows) {
                const cells = row.querySelectorAll('td');
                if (cells.length < 2) continue;
                const label = cells[0].textContent.trim();
                if (label.includes('Refund Shipping') || label.includes('Refund Adjustment')) {
                    const input = cells[1].querySelector('input[type="text"], input[type="number"], input');
                    if (input) {
                        input.value = '';
                        input.value = '0.00';
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                        input.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }
            }
        }""")
        self._page.wait_for_timeout(500)

        # Click "Update Totals" to reset the server-side draft state
        update_button = self._page.get_by_role("button", name=re.compile(r"update totals", re.IGNORECASE))
        update_button.click()
        self._page.wait_for_timeout(1500)

    def _fill_refund_adjustment(self, amount: float) -> None:
        """Fill the Refund Adjustment field and verify the value was set.

        Raises RuntimeError if the field is not found or value verification fails.
        """
        # Primary selector: the cell labeled "Refund Adjustment" contains the input
        adjustment_input = self._page.evaluate("""() => {
            const rows = document.querySelectorAll('tr');
            for (const row of rows) {
                const cells = row.querySelectorAll('td');
                if (cells.length >= 2 && cells[0].textContent.trim().includes('Refund Adjustment')) {
                    const input = cells[1].querySelector('input[type="text"], input[type="number"], input');
                    if (input) return true;
                }
            }
            return false;
        }""")

        if adjustment_input:
            # Use the evaluated selector to fill
            self._page.evaluate("""(amount) => {
                const rows = document.querySelectorAll('tr');
                for (const row of rows) {
                    const cells = row.querySelectorAll('td');
                    if (cells.length >= 2 && cells[0].textContent.trim().includes('Refund Adjustment')) {
                        const input = cells[1].querySelector('input[type="text"], input[type="number"], input');
                        if (input) {
                            input.value = '';
                            input.value = amount;
                            input.dispatchEvent(new Event('input', { bubbles: true }));
                            input.dispatchEvent(new Event('change', { bubbles: true }));
                            return;
                        }
                    }
                }
            }""", f"{amount:.2f}")
        else:
            raise RuntimeError(
                "Refund Adjustment input field not found on the refund page."
            )

        self._page.wait_for_timeout(500)

        # Verify the value was actually set
        actual_value = self._page.evaluate("""() => {
            const rows = document.querySelectorAll('tr');
            for (const row of rows) {
                const cells = row.querySelectorAll('td');
                if (cells.length >= 2 && cells[0].textContent.trim().includes('Refund Adjustment')) {
                    const input = cells[1].querySelector('input[type="text"], input[type="number"], input');
                    if (input) return input.value;
                }
            }
            return null;
        }""")

        if actual_value is None:
            raise RuntimeError("Could not verify Refund Adjustment value — input not found after fill.")
        if float(actual_value) != amount:
            raise RuntimeError(
                f"Refund Adjustment verification failed: expected {amount:.2f}, got {actual_value}."
            )

    def _fill_refund_shipping(self, amount: float) -> None:
        """Fill the Refund Shipping field and verify the value was set.

        Raises RuntimeError if the field is not found or value verification fails.
        """
        self._page.evaluate("""(amount) => {
            const rows = document.querySelectorAll('tr');
            for (const row of rows) {
                const cells = row.querySelectorAll('td');
                if (cells.length >= 2 && cells[0].textContent.trim().includes('Refund Shipping')) {
                    const input = cells[1].querySelector('input[type="text"], input[type="number"], input');
                    if (input) {
                        input.value = '';
                        input.value = amount;
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                        input.dispatchEvent(new Event('change', { bubbles: true }));
                        return;
                    }
                }
            }
            throw new Error('Refund Shipping input field not found');
        }""", f"{amount:.2f}")
        self._page.wait_for_timeout(500)

    def _submit_refund_and_verify(self, order_id: str) -> bool:
        """Click Update Totals, Submit Refund, and verify success.

        Returns True if refund was successfully applied.
        Raises RuntimeError if submission fails or cannot be verified.
        """
        # Click Update Totals
        update_button = self._page.get_by_role("button", name=re.compile(r"update totals", re.IGNORECASE))
        update_button.click()
        self._page.wait_for_timeout(1500)

        # Read the Total row to confirm a non-zero refund amount before submitting
        total_text = self._page.evaluate("""() => {
            const rows = document.querySelectorAll('tr');
            for (const row of rows) {
                const cells = row.querySelectorAll('td');
                if (cells.length >= 2) {
                    const label = cells[0].textContent.trim();
                    if (label === 'Total') {
                        return cells[1].textContent.trim();
                    }
                }
            }
            return null;
        }""")

        if total_text:
            total_amount = float(re.sub(r"[$,]", "", total_text))
            if total_amount <= 0:
                raise RuntimeError(
                    f"Refund total is ${total_text} after Update Totals. "
                    "The refund amount fields may not have been applied correctly."
                )

        # Capture current URL before submission
        url_before = self._page.url

        # Auto-accept confirmation dialog
        self._page.once("dialog", lambda dialog: dialog.accept())

        # Click Submit Refund
        submit_button = self._page.get_by_role("button", name=re.compile(r"submit refund", re.IGNORECASE))
        submit_button.click()
        self._page.wait_for_timeout(3000)

        # Check for an error message FIRST — never silently pass over it.
        error_el = self._page.query_selector(".alert-danger, .error, .alert-error")
        if error_el:
            error_text = error_el.text_content().strip()
            if error_text:
                raise RuntimeError(f"Refund submission returned an error: {error_text}")

        # Verify success by checking for URL redirect (away from refund page).
        # This is Brick Owl's actual success signal — the form posts and the
        # browser redirects to the order detail page.
        url_after = self._page.url
        if url_after != url_before and "/refund" not in url_after:
            return True

        # Or an explicit success string in the rendered page.
        page_content = self._page.content().lower()
        if "refund saved" in page_content or "refund has been" in page_content:
            return True

        # Otherwise: NOT verified. Do not infer success from the submit
        # button being gone — that can also mean the page changed for
        # reasons unrelated to a successful refund.
        return False

    def issue_refund(self, order_id: str, amount: float, reason: str = "Missing items") -> dict:
        """Issue a partial refund for an order.

        Args:
            order_id: The Brick Owl order ID.
            amount: Refund amount in USD.
            reason: Refund reason (mapped to valid dropdown label).
        """
        self._ensure_authenticated()

        self._page.goto(f"https://www.brickowl.com/mystore/orders/history/{order_id}/refund")
        self._page.wait_for_timeout(2000)

        if self._is_login_page(self._page):
            raise RuntimeError("Session expired. Please login again.")
        if "/refund" not in self._page.url:
            raise RuntimeError(f"Could not access refund page for order {order_id}.")

        # Clear any persisted draft state before filling new values
        self._clear_refund_draft_state()

        # Select refund reason (maps freeform text to valid dropdown label)
        self._select_refund_reason(reason)

        # Enter refund amount in the Adjustment field
        self._fill_refund_adjustment(amount)

        # Submit and verify
        success = self._submit_refund_and_verify(order_id)

        if not success:
            raise RuntimeError(
                f"Refund submission for order {order_id} could not be verified. "
                "Please check the order on Brick Owl."
            )

        return {
            "success": True,
            "order_id": order_id,
            "amount": f"{amount:.2f}",
            "reason": reason,
            "message": "Refund issued successfully",
        }

    def issue_full_refund(self, order_id: str, reason: str = "Customer request") -> dict:
        """Issue a full refund for an order.

        Gets order total from the refund page, sets all item quantities to refund,
        fills shipping refund, and submits.
        """
        self._ensure_authenticated()

        # Get order total first
        order_info = self.get_order_info(order_id)
        order_total_str = order_info.get("order_total")
        if not order_total_str:
            raise RuntimeError("Could not determine order total for full refund.")

        order_total = float(re.sub(r"[$,]", "", order_total_str))
        if order_total <= 0:
            raise RuntimeError(f"Invalid order total: {order_total_str}")

        # Navigate to refund page
        self._page.goto(f"https://www.brickowl.com/mystore/orders/history/{order_id}/refund")
        self._page.wait_for_timeout(2000)

        if self._is_login_page(self._page):
            raise RuntimeError("Session expired. Please login again.")
        if "/refund" not in self._page.url:
            raise RuntimeError(f"Could not access refund page for order {order_id}.")

        # Clear any persisted draft state before filling new values
        self._clear_refund_draft_state()

        # Select refund reason (maps freeform text to valid dropdown label)
        self._select_refund_reason(reason)

        # Set all item "Qty to Refund" fields to their ordered quantity
        self._page.evaluate("""() => {
            const rows = document.querySelectorAll('table tbody tr');
            for (const row of rows) {
                const cells = row.querySelectorAll('td');
                // Find rows that have a Qty to Refund input
                for (const cell of cells) {
                    const input = cell.querySelector('input[type="text"], input[type="number"]');
                    if (input) {
                        // Look for the Quantity cell in the same row
                        const qtyCell = row.querySelector('td:nth-child(5), td:nth-child(6)');
                        // Try to find the ordered quantity from the row text
                        const rowText = row.textContent;
                        const orderedMatch = rowText.match(/Ordered\\s+(\\d+)/);
                        if (orderedMatch) {
                            input.value = orderedMatch[1];
                            input.dispatchEvent(new Event('input', { bubbles: true }));
                            input.dispatchEvent(new Event('change', { bubbles: true }));
                        }
                    }
                }
            }
        }""")
        self._page.wait_for_timeout(500)

        # Read the Shipping amount from the Order Totals section on the refund page
        shipping_str = self._page.evaluate("""() => {
            const rows = document.querySelectorAll('tr');
            for (const row of rows) {
                const cells = row.querySelectorAll('td');
                if (cells.length >= 2 && cells[0].textContent.trim() === 'Shipping') {
                    return cells[1].textContent.trim();
                }
            }
            return null;
        }""")
        if shipping_str:
            shipping_amount = float(re.sub(r"[$,]", "", shipping_str))
            if shipping_amount > 0:
                self._fill_refund_shipping(shipping_amount)

        # Submit and verify
        success = self._submit_refund_and_verify(order_id)

        if not success:
            raise RuntimeError(
                f"Full refund submission for order {order_id} could not be verified. "
                "Please check the order on Brick Owl."
            )

        return {
            "success": True,
            "order_id": order_id,
            "amount": f"{order_total:.2f}",
            "reason": reason,
            "message": "Full refund issued successfully",
        }

    # ==================== Coupons ====================

    @cached
    def list_coupons(self) -> list:
        """List all store coupons by scraping the coupons page."""
        self._ensure_authenticated()

        self._page.goto("https://www.brickowl.com/mystore/coupons")
        self._page.wait_for_timeout(1000)

        coupons = self._page.evaluate("""() => {
            const rows = document.querySelectorAll('table tbody tr');
            const results = [];

            for (const row of rows) {
                const cells = row.querySelectorAll('td');
                if (cells.length < 8) continue;

                const editLink = row.querySelector('a[href*="/mystore/coupons/edit/"]');
                const couponId = editLink ? editLink.href.split('/edit/')[1] : null;

                const recipientLink = cells[1].querySelector('a');
                const recipientUsername = recipientLink ? recipientLink.textContent.trim() : null;

                results.push({
                    coupon_id: couponId,
                    code: cells[0].textContent.trim() || null,
                    recipient: recipientUsername,
                    note: cells[2].textContent.trim(),
                    redemptions: cells[3].textContent.trim(),
                    created: cells[4].innerText.trim(),
                    updated: cells[5].innerText.trim(),
                    status: cells[6].textContent.trim()
                });
            }

            return results;
        }""")

        return coupons

    def _fill_coupon_form(
        self,
        coupon_type_label: str,
        note: str,
        discount: float,
        free_shipping: bool = False,
        min_order: Optional[float] = None,
        max_discount: Optional[float] = None,
        limit: int = 1,
    ) -> None:
        """Fill common coupon creation form fields.

        Called after navigating to the create page and selecting the type.
        """
        # Fill note
        note_input = self._page.query_selector('input[name*="note"], textarea[name*="note"]')
        if note_input:
            note_input.fill(note)

        # Fill percent discount
        percent_input = self._page.query_selector('input[name*="percent"]')
        if percent_input:
            percent_input.fill(str(discount))

        # Free shipping checkbox
        if free_shipping:
            shipping_checkbox = self._page.query_selector('input[type="checkbox"][name*="shipping"]')
            if shipping_checkbox and not shipping_checkbox.is_checked():
                shipping_checkbox.check()

        # Min order
        if min_order is not None:
            min_input = self._page.query_selector('input[name*="min"]')
            if min_input:
                min_input.fill(str(min_order))

        # Max discount
        if max_discount is not None:
            max_input = self._page.query_selector('input[name*="max"]')
            if max_input:
                max_input.fill(str(max_discount))

        # Redemption limit
        limit_input = self._page.query_selector('input[name*="limit"], input[name*="redemption"]')
        if limit_input:
            limit_input.fill(str(limit))

    def create_user_coupon(
        self,
        username: str,
        discount: float,
        note: str = "",
        free_shipping: bool = False,
        min_order: Optional[float] = None,
        max_discount: Optional[float] = None,
    ) -> dict:
        """Create a coupon for a specific user.

        Args:
            username: Recipient username.
            discount: Discount percentage.
            note: Coupon note.
            free_shipping: Include free shipping.
            min_order: Minimum order amount.
            max_discount: Maximum discount amount.
        """
        self._ensure_authenticated()

        self._page.goto("https://www.brickowl.com/mystore/coupons/create")
        self._page.wait_for_timeout(1000)

        # Select coupon type: "User Specific Coupon"
        self._page.select_option('select[name*="type"]', label="User Specific Coupon")
        self._page.wait_for_timeout(500)

        # Fill recipient username
        self._page.fill('input[name*="recipient"], input[name*="username"]', username)

        # Fill common fields
        self._fill_coupon_form(
            coupon_type_label="User Specific Coupon",
            note=note,
            discount=discount,
            free_shipping=free_shipping,
            min_order=min_order,
            max_discount=max_discount,
        )

        # Click Create
        create_button = self._page.get_by_role("button", name=re.compile(r"create", re.IGNORECASE))
        create_button.click()
        self._page.wait_for_timeout(2000)

        current_url = self._page.url
        page_content = self._page.content().lower()
        success = (
            "/mystore/coupons" in current_url and "/create" not in current_url
        ) or "success" in page_content or "created" in page_content

        # Check for error messages
        error_el = self._page.query_selector(".error, .alert-error, .message-error")
        if not success and error_el:
            error_msg = error_el.text_content()
            raise RuntimeError(f"Failed to create coupon: {error_msg}")

        return {
            "success": success,
            "coupon_type": "user",
            "username": username,
            "message": "User coupon created successfully" if success else "Coupon creation may have failed.",
        }

    def create_coupon_code(
        self,
        code: str,
        discount: float,
        note: str = "",
        free_shipping: bool = False,
        min_order: Optional[float] = None,
        max_discount: Optional[float] = None,
        limit: int = 1,
    ) -> dict:
        """Create a coupon with a specific code.

        Args:
            code: Coupon code string.
            discount: Discount percentage.
            note: Coupon note.
            free_shipping: Include free shipping.
            min_order: Minimum order amount.
            max_discount: Maximum discount amount.
            limit: Maximum redemptions.
        """
        self._ensure_authenticated()

        self._page.goto("https://www.brickowl.com/mystore/coupons/create")
        self._page.wait_for_timeout(1000)

        # Select coupon type: "Coupon Code"
        self._page.select_option('select[name*="type"]', label="Coupon Code")
        self._page.wait_for_timeout(500)

        # Fill coupon code
        self._page.fill('input[name*="code"]', code)

        # Fill common fields
        self._fill_coupon_form(
            coupon_type_label="Coupon Code",
            note=note,
            discount=discount,
            free_shipping=free_shipping,
            min_order=min_order,
            max_discount=max_discount,
            limit=limit,
        )

        # Click Create
        create_button = self._page.get_by_role("button", name=re.compile(r"create", re.IGNORECASE))
        create_button.click()
        self._page.wait_for_timeout(2000)

        current_url = self._page.url
        page_content = self._page.content().lower()
        success = (
            "/mystore/coupons" in current_url and "/create" not in current_url
        ) or "success" in page_content or "created" in page_content

        error_el = self._page.query_selector(".error, .alert-error, .message-error")
        if not success and error_el:
            error_msg = error_el.text_content()
            raise RuntimeError(f"Failed to create coupon: {error_msg}")

        return {
            "success": success,
            "coupon_type": "code",
            "code": code,
            "message": "Coupon code created successfully" if success else "Coupon creation may have failed.",
        }

    def delete_coupon(self, coupon_id: str) -> dict:
        """Delete a coupon by ID."""
        self._ensure_authenticated()

        self._page.goto("https://www.brickowl.com/mystore/coupons")
        self._page.wait_for_timeout(1000)

        delete_link = self._page.query_selector(f'a[href*="/delete_coupon/{coupon_id}/"]')
        if not delete_link:
            raise RuntimeError(
                f"Could not find delete link for coupon {coupon_id}. "
                "It may not exist or may not be deletable."
            )

        delete_link.click()
        self._page.wait_for_timeout(2000)

        success = "/mystore/coupons" in self._page.url

        return {
            "success": success,
            "coupon_id": coupon_id,
            "message": "Coupon deleted successfully" if success else "Coupon deletion may have failed.",
        }

    # ==================== Quotes ====================

    @cached
    def list_quotes(self, filter: str = "outstanding") -> list:
        """List quotes from outstanding or history.

        Args:
            filter: 'outstanding' or 'all' (history).
        """
        self._ensure_authenticated()

        url_path = (
            "https://www.brickowl.com/mystore/quotes/history"
            if filter == "all"
            else "https://www.brickowl.com/mystore/quotes"
        )

        self._page.goto(url_path)
        self._page.wait_for_timeout(2000)

        # Check for "no quote requests" message
        no_quotes = self._page.evaluate("""() => {
            const main = document.querySelector('main');
            if (main && main.textContent.includes('does not currently have any quote requests')) {
                return true;
            }
            return false;
        }""")
        if no_quotes:
            return []

        quotes = self._page.evaluate("""() => {
            const results = [];
            const rows = document.querySelectorAll('table tbody tr');

            for (const row of rows) {
                const cells = row.querySelectorAll('td');
                if (cells.length < 6) continue;

                const idLink = row.querySelector('a[href*="/quotes/"]');
                if (!idLink) continue;

                const href = idLink.href;
                const quoteIdMatch = href.match(/\\/quotes\\/(?:outstanding|history)\\/(\\d+)/);
                if (!quoteIdMatch) continue;

                const quoteId = quoteIdMatch[1];
                const quoteDate = cells[1]?.innerText?.trim() || '';

                const buyerCell = cells[2];
                const countryImg = buyerCell?.querySelector('img');
                const country = countryImg?.alt || '';
                const buyerLink = buyerCell?.querySelector('a');
                const buyerUsername = buyerLink?.textContent?.trim() || '';
                const buyerName = buyerCell?.textContent
                    ?.replace(buyerUsername, '')
                    .replace('(', '').replace(')', '').trim() || '';
                const buyerUrl = buyerLink?.href || '';
                const buyerIdMatch = buyerUrl.match(/\\/user\\/(\\d+)/);
                const buyerId = buyerIdMatch ? buyerIdMatch[1] : null;

                const itemsLots = cells[3]?.textContent?.trim() || '';
                const parts = itemsLots.split('/');
                const items = parseInt(parts[0]?.trim()) || 0;
                const lots = parseInt(parts[1]?.trim()) || 0;

                const total = cells[4]?.textContent?.trim() || '';
                const status = cells[5]?.textContent?.trim() || '';

                results.push({
                    quote_id: quoteId,
                    date: quoteDate,
                    buyer: {
                        name: buyerName,
                        username: buyerUsername,
                        user_id: buyerId,
                        country: country
                    },
                    items,
                    lots,
                    total,
                    status,
                    url: href
                });
            }

            return results;
        }""")

        return quotes

    @cached
    def get_quote(self, quote_id: str) -> dict:
        """Get quote details by quote ID."""
        self._ensure_authenticated()

        self._page.goto(f"https://www.brickowl.com/mystore/quotes/outstanding/{quote_id}")
        self._page.wait_for_timeout(2000)

        page_title = self._page.title()
        if "Page not found" in page_title:
            raise RuntimeError(
                f"Quote #{quote_id} not found. "
                "It may have been converted to an order or doesn't exist."
            )

        details = self._page.evaluate("""() => {
            const tables = document.querySelectorAll('table');
            let quoteDate = null;
            let buyer = null;
            let items = null;
            let weight = null;
            let subtotal = null;
            let shipping = null;
            let tax = null;
            let total = null;
            let customerInfo = null;

            // Parse all table rows for key-value data
            for (const table of tables) {
                const rows = table.querySelectorAll('tr');
                for (const row of rows) {
                    const cells = row.querySelectorAll('td');
                    if (cells.length < 2) continue;

                    const label = cells[0]?.textContent?.trim();
                    const value = cells[1]?.textContent?.trim();

                    if (label === 'Quote Date') quoteDate = value;
                    if (label === 'Buyer') {
                        const link = cells[1]?.querySelector('a');
                        buyer = {
                            display_text: value,
                            username: link?.textContent?.trim().replace(/\\s*\\(\\d+\\)$/, ''),
                            url: link?.href
                        };
                    }
                    if (label === 'Items') items = value;
                    if (label === 'Weight') weight = value;
                    if (label === 'Subtotal') subtotal = value;
                    if (label === 'Shipping Quote') shipping = value;
                    if (label?.includes('Tax')) tax = value;
                    if (label === 'Total') total = value;

                    if (label === 'Feedback' || label === 'Account Age' ||
                        label === 'Non Payments' || label === 'Order Not Arrived') {
                        if (!customerInfo) customerInfo = {};
                        if (label === 'Feedback') customerInfo.feedback = value;
                        if (label === 'Account Age') customerInfo.account_age = value;
                        if (label === 'Non Payments') customerInfo.non_payments = value;
                        if (label === 'Order Not Arrived') customerInfo.order_not_arrived = value;
                    }
                }
            }

            // Shipping address
            let shippingAddress = null;
            const separators = document.querySelectorAll('hr, [role="separator"]');
            for (const sep of separators) {
                const parent = sep.parentElement;
                if (parent) {
                    const text = parent.textContent || '';
                    if (text.includes('Phone:') && !text.includes('Store Address')) {
                        const divs = parent.querySelectorAll('div');
                        const addressLines = [];
                        let phone = null;
                        for (const div of divs) {
                            const content = div.textContent?.trim() || '';
                            if (content.startsWith('Phone:')) {
                                phone = content.replace('Phone:', '').trim();
                            } else if (content && !content.includes('Address') && content.length > 2) {
                                addressLines.push(content);
                            }
                        }
                        if (addressLines.length > 0) {
                            shippingAddress = {
                                name: addressLines[0] || null,
                                street: addressLines[1] || null,
                                city_state_zip: addressLines[2] || null,
                                country: addressLines[3] || null,
                                phone
                            };
                            break;
                        }
                    }
                }
            }

            // Line items table
            const lineItems = [];
            let itemTable = null;
            for (const table of tables) {
                const headers = table.querySelectorAll('th');
                const headerText = Array.from(headers).map(h => h.textContent?.trim()).join(' ');
                if (headerText.includes('Quantity') || headerText.includes('Item Price')) {
                    itemTable = table;
                    break;
                }
            }
            if (itemTable) {
                const rows = itemTable.querySelectorAll('tbody tr');
                for (const row of rows) {
                    const cells = row.querySelectorAll('td');
                    if (cells.length < 7) continue;

                    const conditionCell = cells[1];
                    const condition = conditionCell?.textContent?.trim() || '';
                    const nameCell = cells[2];
                    const itemLink = nameCell?.querySelector('a');
                    const itemName = itemLink?.textContent?.trim() || '';
                    const colorStrong = nameCell?.querySelector('strong');
                    const color = colorStrong?.textContent?.trim() || '';
                    const noteCell = cells[3];
                    const note = noteCell?.textContent?.trim() || '';
                    const itemPrice = cells[5]?.textContent?.trim() || '';
                    const rowTotal = cells[6]?.textContent?.trim() || '';

                    lineItems.push({
                        condition,
                        name: itemName,
                        color,
                        note,
                        item_price: itemPrice,
                        row_total: rowTotal
                    });
                }
            }

            return {
                date: quoteDate,
                buyer,
                items,
                weight,
                subtotal,
                shipping,
                tax,
                total,
                customer_info: customerInfo,
                shipping_address: shippingAddress,
                line_items: lineItems
            };
        }""")

        return {"quote_id": quote_id, **details, "url": self._page.url}

    def submit_quote(self, quote_id: str, amount: float, note: Optional[str] = None) -> dict:
        """Submit a shipping quote for a quote request.

        Args:
            quote_id: The Brick Owl quote ID.
            amount: Shipping amount to quote.
            note: Optional note to include.
        """
        self._ensure_authenticated()

        self._page.goto(f"https://www.brickowl.com/mystore/quotes/outstanding/{quote_id}")
        self._page.wait_for_timeout(2000)

        # Click "Enter Quote" button
        enter_quote_btn = self._page.query_selector("a.quote-edit")
        if not enter_quote_btn:
            raise RuntimeError("Enter Quote button not found. Quote may already have been submitted.")

        enter_quote_btn.click()
        self._page.wait_for_timeout(1500)

        # Fill quote amount
        quote_input = self._page.query_selector('input[name="main_quote"]')
        if not quote_input:
            raise RuntimeError("Quote input field not found.")

        amount_str = f"{amount:.2f}"
        quote_input.fill(amount_str)

        # Fill note if provided
        if note:
            note_input = self._page.query_selector('textarea[name="main_note"]')
            if note_input:
                note_input.fill(note)

        # Click Submit
        submit_btn = self._page.query_selector('input[name="bottom_op"][type="submit"]')
        if not submit_btn:
            raise RuntimeError("Submit button not found.")

        submit_btn.click()
        self._page.wait_for_timeout(2000)

        # Success if the quote form elements are gone
        enter_quote_after = self._page.query_selector("a.quote-edit")
        quote_input_after = self._page.query_selector('input[name="main_quote"]')
        success = not enter_quote_after and not quote_input_after

        return {
            "success": success,
            "quote_id": quote_id,
            "amount": amount_str,
            "message": f"Quote of ${amount_str} submitted successfully" if success else "Quote submission may have failed.",
        }

    # ==================== Catalog ====================

    @cached
    def catalog_search(self, query: str, page: int = 1) -> dict:
        """Search the Brick Owl catalog by scraping the search page.

        Args:
            query: Search query string.
            page: Page number (1-based).

        Returns:
            Dict with 'rows' (list of item dicts) and 'total' (int).
        """
        from urllib.parse import quote_plus

        self._ensure_authenticated()

        url = f"https://www.brickowl.com/search/catalog?query={quote_plus(query)}&page={page}"
        self._page.goto(url)
        self._page.wait_for_timeout(2000)

        results = self._page.evaluate("""() => {
            // Parse total from "1 to 60 of 1956" text
            const amountEl = document.querySelector('p.amount');
            let total = 0;
            if (amountEl) {
                const match = amountEl.textContent.match(/of\\s+([\\d,]+)/);
                if (match) total = parseInt(match[1].replace(/,/g, ''), 10);
            }

            // Parse pagination to find total pages
            let totalPages = 1;
            const paginationLinks = document.querySelectorAll('.pagination li a');
            for (const link of paginationLinks) {
                const href = link.getAttribute('href') || '';
                const pageMatch = href.match(/[?&]page=(\\d+)/);
                if (pageMatch) {
                    const p = parseInt(pageMatch[1], 10);
                    if (p > totalPages) totalPages = p;
                }
            }
            // Also check the active page
            const activePage = document.querySelector('.pagination li.active span');
            if (activePage) {
                const p = parseInt(activePage.textContent.trim(), 10);
                if (p > totalPages) totalPages = p;
            }

            // Parse search result items
            const items = document.querySelectorAll('.category-item');
            const rows = [];

            for (const item of items) {
                const boid = item.getAttribute('data-boid') || null;

                const nameLink = item.querySelector('.category-item-name a');
                const name = nameLink ? nameLink.textContent.trim() : null;
                const href = nameLink ? nameLink.getAttribute('href') : null;
                const itemUrl = href ? (href.startsWith('http') ? href : 'https://www.brickowl.com' + href) : null;

                const img = item.querySelector('.category-item-image img');
                const image = img ? img.getAttribute('src') : null;

                const priceEl = item.querySelector('.price');
                const price = priceEl ? priceEl.textContent.trim() : null;

                rows.push({
                    boid: boid,
                    name: name,
                    url: itemUrl,
                    image: image,
                    price: price
                });
            }

            return { rows, total, total_pages: totalPages };
        }""")

        return results

    # ==================== Issue Reports ====================

    def list_issue_reports(self) -> list:
        """List issue reports from the store's issue reports page.

        Navigates to https://www.brickowl.com/mystore/orders/issue_reports
        and parses the table of issue reports.

        Returns:
            List of dicts with keys: order_id, details, issue_type, status, date, url
        """
        self._ensure_authenticated()

        self._page.goto("https://www.brickowl.com/mystore/orders/issue_reports")
        self._page.wait_for_timeout(2000)

        # Check for empty state (no issue reports)
        no_reports = self._page.evaluate("""() => {
            const main = document.querySelector('main, .content, body');
            if (!main) return true;
            const text = main.textContent.toLowerCase();
            if (text.includes('no issue reports') || text.includes('no reports found') ||
                text.includes('does not have any issue reports')) {
                return true;
            }
            // If there's no table at all, consider it empty
            const table = document.querySelector('table');
            return !table;
        }""")
        if no_reports:
            return []

        reports = self._page.evaluate("""() => {
            const results = [];
            const rows = document.querySelectorAll('table tbody tr');
            const visibleText = (cell) => {
                if (!cell) return null;
                const clone = cell.cloneNode(true);
                clone.querySelectorAll('[hidden]').forEach(node => node.remove());
                return clone.textContent.replace(/\\s+/g, ' ').trim() || null;
            };

            for (const row of rows) {
                const cells = row.querySelectorAll('td');
                if (cells.length < 5) continue;

                // Extract resolve URL if present
                let resolveUrl = null;
                for (const link of row.querySelectorAll('a')) {
                    const href = link.getAttribute('href') || '';
                    const text = link.textContent.trim().toLowerCase();
                    if (text.includes('resolve') || text.includes('close') ||
                        href.includes('resolve') || href.includes('close_issue')) {
                        resolveUrl = href.startsWith('http') ? href : 'https://www.brickowl.com' + href;
                        break;
                    }
                }

                const date = visibleText(cells[0]);
                const issueType = visibleText(cells[1]);
                const details = visibleText(cells[2]);
                const orderCellText = visibleText(cells[3]);
                const orderLink = cells[3].querySelector('a[href]');
                const orderId = orderLink?.textContent.trim() || orderCellText;
                const orderUrl = orderLink
                    ? (orderLink.href.startsWith('http')
                        ? orderLink.href
                        : 'https://www.brickowl.com' + orderLink.getAttribute('href'))
                    : null;
                const status = visibleText(cells[4]);

                results.push({
                    order_id: orderId,
                    details: details,
                    issue_type: issueType,
                    status: status,
                    date: date,
                    url: orderUrl,
                    resolve_url: resolveUrl,
                });
            }

            return results;
        }""")

        return reports

    def resolve_issue_report(self, order_id: str) -> dict:
        """Resolve an issue report for a given order ID.

        Navigates to the issue reports page, finds the report matching
        the order ID, and clicks the resolve action.

        Args:
            order_id: The Brick Owl order ID.

        Returns:
            Dict with success status and message.
        """
        self._ensure_authenticated()

        self._page.goto("https://www.brickowl.com/mystore/orders/issue_reports")
        self._page.wait_for_timeout(2000)

        # Find the resolve link for the given order ID
        resolve_info = self._page.evaluate("""(orderId) => {
            const rows = document.querySelectorAll('table tbody tr');

            for (const row of rows) {
                const links = row.querySelectorAll('a');
                let isMatch = false;

                // Check if this row contains the target order ID
                for (const link of links) {
                    const href = link.getAttribute('href') || '';
                    const text = link.textContent.trim();
                    if (href.includes(orderId) || text.includes(orderId)) {
                        isMatch = true;
                        break;
                    }
                }

                // Also check cell text for order ID
                if (!isMatch) {
                    const cells = row.querySelectorAll('td');
                    for (const cell of cells) {
                        if (cell.textContent.includes(orderId)) {
                            isMatch = true;
                            break;
                        }
                    }
                }

                if (isMatch) {
                    // Find the resolve/close link
                    for (const link of links) {
                        const href = link.getAttribute('href') || '';
                        const text = link.textContent.trim().toLowerCase();
                        if (text.includes('resolve') || text.includes('close') ||
                            href.includes('resolve') || href.includes('close_issue')) {
                            return {
                                found: true,
                                resolve_url: href.startsWith('http') ? href : 'https://www.brickowl.com' + href,
                                link_text: link.textContent.trim()
                            };
                        }
                    }

                    // Check for buttons/inputs
                    const buttons = row.querySelectorAll('button, input[type="submit"]');
                    for (const btn of buttons) {
                        const text = (btn.textContent || btn.value || '').trim().toLowerCase();
                        if (text.includes('resolve') || text.includes('close')) {
                            return {
                                found: true,
                                resolve_url: null,
                                is_button: true,
                                button_text: btn.textContent || btn.value
                            };
                        }
                    }

                    return { found: true, resolve_url: null, no_resolve_action: true };
                }
            }

            return { found: false };
        }""", order_id)

        if not resolve_info.get("found"):
            raise RuntimeError(f"No issue report found for order {order_id}")

        if resolve_info.get("no_resolve_action"):
            raise RuntimeError(
                f"Issue report found for order {order_id} but no resolve action available. "
                f"It may already be resolved or require manual resolution."
            )

        if resolve_info.get("is_button"):
            # Click the button directly in the matching row
            self._page.evaluate("""(orderId) => {
                const rows = document.querySelectorAll('table tbody tr');
                for (const row of rows) {
                    let isMatch = false;
                    const cells = row.querySelectorAll('td');
                    for (const cell of cells) {
                        if (cell.textContent.includes(orderId)) {
                            isMatch = true;
                            break;
                        }
                    }
                    if (isMatch) {
                        const buttons = row.querySelectorAll('button, input[type="submit"]');
                        for (const btn of buttons) {
                            const text = (btn.textContent || btn.value || '').trim().toLowerCase();
                            if (text.includes('resolve') || text.includes('close')) {
                                btn.click();
                                return;
                            }
                        }
                    }
                }
            }""", order_id)
        else:
            # Navigate to the resolve URL
            self._page.goto(resolve_info["resolve_url"])

        self._page.wait_for_timeout(3000)

        # Check for confirmation dialog/form and submit if present
        confirm_result = self._page.evaluate("""() => {
            // Look for confirmation buttons/forms
            const confirmBtn = document.querySelector(
                'button[type="submit"], input[type="submit"], ' +
                'a.btn-primary, button.btn-primary, ' +
                '.confirm-button, [data-confirm]'
            );
            if (confirmBtn) {
                const text = (confirmBtn.textContent || confirmBtn.value || '').trim().toLowerCase();
                if (text.includes('confirm') || text.includes('resolve') ||
                    text.includes('close') || text.includes('yes') || text.includes('ok')) {
                    confirmBtn.click();
                    return { clicked_confirm: true, button_text: text };
                }
            }
            return { clicked_confirm: false };
        }""")

        if confirm_result.get("clicked_confirm"):
            self._page.wait_for_timeout(3000)

        # Verify resolution
        current_url = self._page.url
        page_text = self._page.evaluate("() => document.body.textContent.toLowerCase()")
        success = (
            "resolved" in page_text
            or "closed" in page_text
            or "success" in page_text
            or "issue_reports" in current_url
        )

        return {
            "success": success,
            "order_id": order_id,
            "action": "resolve",
            "message": (
                f"Issue report for order {order_id} resolved successfully"
                if success
                else f"Resolution may not have completed. Please verify on Brick Owl. Current URL: {current_url}"
            ),
        }


# Module-level singleton
_browser: Optional[BrickOwlBrowser] = None


def get_browser() -> BrickOwlBrowser:
    """Get or create the global browser service instance."""
    global _browser
    if _browser is None:
        _browser = BrickOwlBrowser()
    return _browser
