"""Browser-backed Muse chat operations."""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse
from uuid import UUID

from cli_tools_shared.activity_log import get_activity_logger
from cli_tools_shared.exceptions import ClientError, CredentialError

from .browser import (
    AUTH_STATE_JS,
    COMPOSER_SELECTOR,
    LOGIN_PANE_STATE,
    MuseChatSessionBrowser,
)
from .config import get_config
from .parsers import normalize_chat, normalize_messages, normalize_threads


MAIN_URL = "https://muse.ai/"
NEW_SIDE_URL = "https://muse.ai/thread/new"
SWITCHER_TRIGGER_SELECTOR = '[data-testid="hatch-chat-switcher-trigger"]'
CHAT_ID_RE = re.compile(r"^/thread/([0-9a-fA-F-]{36})/?$")
DEFAULT_TIMEOUT_SECONDS = 120
SEND_ACK_TIMEOUT_SECONDS = 20
SIDE_ID_TIMEOUT_SECONDS = 30
RESPONSE_SETTLE_SECONDS = 1.0
HISTORY_SETTLE_TIMEOUT_SECONDS = 5.0
SWITCHER_OPEN_TIMEOUT_SECONDS = 10.0
SWITCHER_SETTLE_SECONDS = 0.5

activity = get_activity_logger("muse-chat")


CHAT_SNAPSHOT_JS = r"""
() => {
  const log = document.querySelector('[role="log"][aria-label="Chat messages"]');
  if (!log) return {messages: [], typing: false, working: false, approvals: []};
  const clean = value => String(value || '').replace(/\s+/g, ' ').trim();
  const preserve = value => String(value || '').replace(/\r\n?/g, '\n').trim();
  const contentSelector = 'p, pre, blockquote, li, h1, h2, h3, h4, h5, h6';
  const nodes = Array.from(log.children);
  const messages = [];
  const approvals = [];
  const approvalPattern = /\b(approve|allow|authorize|confirm purchase|review and approve)\b/i;

  nodes.forEach((node, domIndex) => {
    const statusNodes = [];
    if (node.getAttribute && node.getAttribute('role') === 'status') statusNodes.push(node);
    statusNodes.push(...Array.from(node.querySelectorAll('[role="status"]')));
    const statusText = clean(statusNodes.map(el => el.textContent).join(' '));

    const descendants = Array.from(node.querySelectorAll('*'));
    const labeled = [node, ...descendants]
      .map(el => preserve(el.getAttribute && el.getAttribute('aria-label')))
      .filter(Boolean);
    const userLabel = labeled.find(label => /^user message:\s*/i.test(label));
    const assistantLabel = labeled.find(label => /^assistant message:\s*/i.test(label));
    const isUser = descendants.some(el => clean(el.textContent) === 'You:');
    const allBlocks = Array.from(node.querySelectorAll(contentSelector));
    const blocks = allBlocks.filter(
      el => !allBlocks.some(other => other !== el && other.contains(el))
    );
    const blockText = blocks.map(el => preserve(el.innerText || el.textContent)).filter(Boolean);
    const declaredRole = node.getAttribute && node.getAttribute('data-message-role');
    const messageId = preserve(node.getAttribute && node.getAttribute('data-message-id'));
    const turnId = preserve(node.getAttribute && node.getAttribute('data-message-turn-id'));

    if (declaredRole === 'user' || userLabel || isUser) {
      let text = userLabel ? userLabel.replace(/^user message:\s*/i, '') : blockText.join('\n\n');
      if (!text) {
        text = preserve(node.innerText || node.textContent)
          .replace(/^You:\s*/i, '')
          .replace(/^User message:\s*/i, '');
      }
      if (text) messages.push({
        role: 'user', text, dom_index: domIndex, message_id: messageId, turn_id: turnId
      });
    } else if ((declaredRole === 'assistant' || assistantLabel || blockText.length) && !statusText) {
      const text = assistantLabel
        ? assistantLabel.replace(/^assistant message:\s*/i, '')
        : blockText.join('\n\n');
      if (text) messages.push({
        role: 'assistant', text, dom_index: domIndex, message_id: messageId, turn_id: turnId
      });
    }

    const controls = Array.from(
      node.querySelectorAll('button, input[type="button"], input[type="submit"], [role="button"]')
    );
    controls.forEach(control => {
      const name = clean(
        control.getAttribute('aria-label') || control.innerText || control.value || control.textContent
      );
      if (approvalPattern.test(name)) approvals.push({name, dom_index: domIndex});
    });
  });

  const typing = Array.from(log.querySelectorAll('[role="status"]'))
    .some(el => /assistant is typing/i.test(clean(el.getAttribute('aria-label') || el.textContent)));
  const working = Array.from(document.querySelectorAll('button, [role="button"]'))
    .some(el => clean(el.getAttribute('aria-label') || el.innerText || el.textContent) === 'Stop');
  return {messages, typing, working, approvals};
}
"""


# null until the open switcher renders its thread rows (Main chat is always
# one); then the Side chats rows, or [] when the account has none.
SIDE_THREAD_ROWS_JS = r"""
() => {
  if (!document.querySelector('[data-testid="hatch-thread-row"]')) return null;
  const clean = value => String(value || '').replace(/\s+/g, ' ').trim();
  const heading = Array.from(document.querySelectorAll('h3 > button'))
    .find(el => clean(el.innerText || el.textContent) === 'Side chats');
  const controlledId = heading && heading.getAttribute('aria-controls');
  const container = controlledId && document.getElementById(controlledId);
  if (!container) return [];
  return Array.from(container.querySelectorAll('[data-testid="hatch-thread-row"]')).map((el, index) => ({
    index,
    title: clean(el.querySelector('[title]')?.getAttribute('title') || el.innerText || el.textContent),
  }));
}
"""

SIDE_THREAD_CLICK_JS = r"""
(index) => {
  const clean = value => String(value || '').replace(/\s+/g, ' ').trim();
  const heading = Array.from(document.querySelectorAll('h3 > button'))
    .find(el => clean(el.innerText || el.textContent) === 'Side chats');
  const controlledId = heading && heading.getAttribute('aria-controls');
  const container = controlledId && document.getElementById(controlledId);
  const row = container && container.querySelectorAll('[data-testid="hatch-thread-row"]')[index];
  if (!row) return false;
  row.click();
  return true;
}
"""


def _message_key(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class MuseChatClient:
    """Drive Muse through the shared persistent browser engine."""

    def __init__(self, profile: Optional[str] = None):
        self.config = get_config(profile=profile)
        self._browser: Optional[MuseChatSessionBrowser] = None

    def _get_browser(self) -> MuseChatSessionBrowser:
        if self._browser is None:
            self._browser = MuseChatSessionBrowser(self.config)
        return self._browser

    def _open_page(self, url: str):
        """Open ``url``, resuming an expired Muse session headlessly first."""
        browser = self._get_browser()
        page = browser.get_page(url)
        if page.evaluate(AUTH_STATE_JS) != LOGIN_PANE_STATE:
            return page
        activity.info("session expired; resuming saved account headlessly")
        outcome = browser.ensure_fresh_session()
        if not outcome.authenticated:
            raise CredentialError(
                f"Muse session expired and could not be resumed headlessly ({outcome.reason}). "
                "Run 'muse-chat auth login', then retry."
            )
        return browser.get_page(url)

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    @staticmethod
    def _chat_id_from_url(url: str) -> Optional[str]:
        match = CHAT_ID_RE.fullmatch(urlparse(url).path)
        if not match:
            return None
        try:
            return str(UUID(match.group(1)))
        except ValueError:
            return None

    @staticmethod
    def _validate_chat_id(chat_id: str) -> str:
        if chat_id == "main":
            return chat_id
        try:
            return str(UUID(chat_id))
        except ValueError as exc:
            raise ClientError("CHAT_ID must be 'main' or a valid UUID.") from exc

    @classmethod
    def _url_for_chat(cls, chat_id: str) -> str:
        validated = cls._validate_chat_id(chat_id)
        return MAIN_URL if validated == "main" else f"https://muse.ai/thread/{validated}"

    @staticmethod
    def _current_chat_id(page) -> str:
        parsed = urlparse(page.url)
        if parsed.scheme != "https" or parsed.netloc != "muse.ai":
            raise ClientError(f"Muse opened an unexpected origin: {parsed.scheme}://{parsed.netloc}")
        if parsed.path.rstrip("/") == "":
            return "main"
        chat_id = MuseChatClient._chat_id_from_url(page.url)
        if chat_id:
            return chat_id
        raise ClientError(f"Muse opened an unexpected chat path: {parsed.path}")

    @staticmethod
    def _require_target(page, expected_chat_id: str) -> None:
        actual_id = MuseChatClient._current_chat_id(page)
        if actual_id != expected_chat_id:
            raise ClientError(
                f"Muse opened chat {actual_id!r} instead of requested chat {expected_chat_id!r}."
            )

    @staticmethod
    def _require_composer(page) -> None:
        try:
            page.wait_for_selector(COMPOSER_SELECTOR, timeout=15000)
        except Exception as exc:
            raise ClientError(
                "Muse message composer was not available. Run 'muse-chat auth login', then retry."
            ) from exc

    @staticmethod
    def _snapshot(page) -> dict:
        raw = page.evaluate(CHAT_SNAPSHOT_JS)
        if not isinstance(raw, dict):
            raise ClientError("Muse chat DOM returned an invalid snapshot.")
        return {
            "messages": normalize_messages(raw.get("messages")),
            "typing": bool(raw.get("typing")),
            "working": bool(raw.get("working")),
            "approvals": raw.get("approvals") if isinstance(raw.get("approvals"), list) else [],
        }

    def _open_chat(self, chat_id: str):
        validated = self._validate_chat_id(chat_id)
        page = self._open_page(self._url_for_chat(validated))
        self._require_target(page, validated)
        self._require_composer(page)
        try:
            page.wait_for_selector(
                '[role="log"][aria-label="Chat messages"]'
                '[data-initial-history-motion="complete"]',
                timeout=15000,
            )
        except Exception as exc:
            raise ClientError("Muse chat history did not finish loading.") from exc
        return page

    @staticmethod
    def _wait_for_user_echo(page, baseline_ids: set[str], baseline_dom_index: int, message: str) -> dict:
        message_key = _message_key(message)
        deadline = time.monotonic() + SEND_ACK_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            snapshot = MuseChatClient._snapshot(page)
            matches = [
                row for row in snapshot["messages"]
                if row["role"] == "user"
                and row["dom_index"] > baseline_dom_index
                and row["message_id"] not in baseline_ids
                and _message_key(row["text"]) == message_key
            ]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise ClientError(
                    "Muse exposed multiple new user turns matching the submitted message. "
                    "The send outcome is ambiguous, so muse-chat refused to choose one."
                )
            page.wait_for_timeout(250)
        raise ClientError(
            "Muse did not confirm the submitted message in chat history. "
            "The send outcome is ambiguous, so muse-chat did not retry it."
        )

    @staticmethod
    def _wait_for_side_id(page) -> str:
        deadline = time.monotonic() + SIDE_ID_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            chat_id = MuseChatClient._chat_id_from_url(page.url)
            if chat_id:
                return chat_id
            page.wait_for_timeout(250)
        raise ClientError(
            "Muse accepted the side-chat message but did not expose a durable chat ID. "
            "The send outcome is ambiguous, so muse-chat did not retry it."
        )

    @staticmethod
    def _monitor_turn(
        page,
        chat_id: str,
        turn_dom_index: int,
        timeout: int,
        turn_message_id: str,
        new_side_message: Optional[str] = None,
    ) -> dict:
        """Wait for the response to one user turn.

        ``new_side_message`` is set only for a side chat this process just
        created. Muse gives the draft's user echo a temporary message ID and
        replaces it with the server ID once the thread is saved, so the
        submitted turn is re-anchored to the chat's only user turn when its
        text matches. Any other history still refuses to match.
        """
        deadline = time.monotonic() + timeout
        stable_signature = None
        stable_since = None
        while True:
            snapshot = MuseChatClient._snapshot(page)
            current_turn = next(
                (row for row in snapshot["messages"] if row["message_id"] == turn_message_id),
                None,
            )
            if current_turn is None and new_side_message is not None:
                user_turns = [row for row in snapshot["messages"] if row["role"] == "user"]
                if (
                    len(user_turns) == 1
                    and _message_key(user_turns[0]["text"]) == _message_key(new_side_message)
                ):
                    current_turn = user_turns[0]
                    activity.info(
                        "side chat turn re-anchored chat_id=%s from=%s to=%s",
                        chat_id, turn_message_id, current_turn["message_id"],
                    )
                    turn_message_id = current_turn["message_id"]
            if current_turn is None and new_side_message is not None and not user_turns:
                stable_signature, stable_since = None, None
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    page.wait_for_timeout(min(250, max(1, int(remaining * 1000))))
                    continue
            if current_turn is None:
                raise ClientError(
                    f"Muse chat {chat_id!r} no longer exposed submitted turn "
                    f"{turn_message_id!r}; "
                    "muse-chat refused to match another response."
                )
            current_turn_index = current_turn["dom_index"]
            next_user_index = min(
                (
                    row["dom_index"]
                    for row in snapshot["messages"]
                    if row["role"] == "user" and row["dom_index"] > current_turn_index
                ),
                default=None,
            )
            responses = [
                row for row in snapshot["messages"]
                if row["role"] == "assistant" and row["dom_index"] > current_turn_index
                and (next_user_index is None or row["dom_index"] < next_user_index)
            ]
            response_ambiguous = False
            latest_response = ""
            if len(responses) == 1:
                latest_response = responses[0]["text"]
            elif responses:
                response_turn_ids = {row.get("turn_id") for row in responses}
                if None not in response_turn_ids and len(response_turn_ids) == 1:
                    # Distinct durable message IDs are ordered components of
                    # one answer, including prose and task cards. Never dedup
                    # genuine components by their text.
                    components = {row["message_id"]: row["text"] for row in responses}
                    latest_response = "\n\n".join(components.values())
                else:
                    response_ambiguous = True

            approvals = [
                approval for approval in snapshot["approvals"]
                if isinstance(approval, dict)
                and isinstance(approval.get("dom_index"), int)
                and approval["dom_index"] > current_turn_index
                and (next_user_index is None or approval["dom_index"] < next_user_index)
            ]
            if approvals:
                return {
                    "status": "approval_required",
                    "chat_id": chat_id,
                    "turn_message_id": turn_message_id,
                    "url": page.url,
                    "response": latest_response or None,
                    "approval": approvals[-1].get("name"),
                }

            if not snapshot["typing"] and not snapshot["working"] and response_ambiguous:
                raise ClientError(
                    f"Muse chat {chat_id!r} exposed multiple assistant messages after "
                    "the submitted turn "
                    "without one shared durable turn ID. muse-chat refused to choose an "
                    "unrelated response."
                )

            now = time.monotonic()
            signature = tuple((row["message_id"], row.get("turn_id"), row["text"]) for row in responses)
            if latest_response and not snapshot["typing"] and not snapshot["working"]:
                if signature != stable_signature:
                    stable_signature, stable_since = signature, now
            else:
                stable_signature, stable_since = None, None
            if stable_since is not None and now <= deadline and now - stable_since >= RESPONSE_SETTLE_SECONDS:
                return {
                    "status": "completed",
                    "chat_id": chat_id,
                    "turn_message_id": turn_message_id,
                    "url": page.url,
                    "response": latest_response,
                }

            remaining = deadline - now
            if remaining <= 0:
                return {
                    "status": "timeout",
                    "chat_id": chat_id,
                    "turn_message_id": turn_message_id,
                    "url": page.url,
                    "response": latest_response or None,
                    "timeout_seconds": timeout,
                    "remote_task_cancelled": False,
                }
            page.wait_for_timeout(min(500, max(1, int(remaining * 1000))))

    def _send_on_page(
        self,
        page,
        message: str,
        *,
        monitor: bool,
        timeout: int,
        side_draft: bool = False,
    ) -> dict:
        if not message.strip():
            raise ClientError("MESSAGE must not be empty.")
        baseline = self._snapshot(page)["messages"]
        baseline_dom_index = max((row["dom_index"] for row in baseline), default=-1)
        baseline_ids = {row["message_id"] for row in baseline}
        composer = page.locator(COMPOSER_SELECTOR)
        composer.fill(message)
        try:
            composer.press("Enter")
        except Exception as exc:
            raise ClientError(
                "Muse browser control failed while submitting the message. "
                "The send outcome is ambiguous, so muse-chat did not retry it."
            ) from exc
        turn = self._wait_for_user_echo(page, baseline_ids, baseline_dom_index, message)
        turn_dom_index = turn["dom_index"]
        turn_message_id = turn["message_id"]
        if side_draft:
            parsed = urlparse(page.url)
            chat_id = self._chat_id_from_url(page.url)
            if chat_id is None:
                if (
                    parsed.scheme != "https"
                    or parsed.netloc != "muse.ai"
                    or parsed.path.rstrip("/") != "/thread/new"
                ):
                    raise ClientError(f"Muse opened an unexpected side-chat path: {page.url}")
                chat_id = "pending"
        else:
            chat_id = self._current_chat_id(page)
        activity.info("message submitted chat_id=%s monitor=%s chars=%d", chat_id, monitor, len(message))
        result = {
            "status": "sent",
            "chat_id": chat_id,
            "url": page.url,
            "message": message,
            "turn_dom_index": turn_dom_index,
            "turn_message_id": turn_message_id,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "monitored": monitor,
        }
        if not monitor:
            return result
        monitored = self._monitor_turn(
            page, chat_id, turn_dom_index, timeout, turn_message_id
        )
        monitored.update({
            "message": message,
            "turn_dom_index": turn_dom_index,
            "monitored": True,
        })
        return monitored

    def send(
        self,
        message: str,
        *,
        chat_id: str = "main",
        monitor: bool = False,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> dict:
        page = self._open_chat(chat_id)
        return self._send_on_page(page, message, monitor=monitor, timeout=timeout)

    def create_side(
        self,
        message: str,
        *,
        monitor: bool = False,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> dict:
        page = self._open_page(NEW_SIDE_URL)
        parsed = urlparse(page.url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "muse.ai"
            or parsed.path.rstrip("/") != "/thread/new"
        ):
            raise ClientError(f"Muse did not open a new side-chat draft: {page.url}")
        self._require_composer(page)
        result = self._send_on_page(
            page, message, monitor=False, timeout=timeout, side_draft=True
        )
        chat_id = self._wait_for_side_id(page)
        result.update({"chat_id": chat_id, "url": page.url})
        activity.info("side chat created chat_id=%s monitor=%s", chat_id, monitor)
        if not monitor:
            return result
        monitored = self._monitor_turn(
            page,
            chat_id,
            result["turn_dom_index"],
            timeout,
            result["turn_message_id"],
            new_side_message=message,
        )
        monitored.update({
            "message": message,
            "turn_dom_index": result["turn_dom_index"],
            "monitored": True,
        })
        return monitored

    def monitor(self, chat_id: str, *, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> dict:
        validated = self._validate_chat_id(chat_id)
        page = self._open_chat(validated)
        snapshot = self._snapshot(page)
        user_messages = [row for row in snapshot["messages"] if row["role"] == "user"]
        if not user_messages:
            raise ClientError(f"Chat {validated!r} has no user turn to monitor.")
        turn = user_messages[-1]
        activity.info("monitor started chat_id=%s turn_dom_index=%d", validated, turn["dom_index"])
        return self._monitor_turn(
            page,
            validated,
            turn["dom_index"],
            timeout,
            turn["message_id"],
        )

    @staticmethod
    def _open_switcher(page) -> list:
        """Open the chat switcher and return its settled Side chats rows."""
        try:
            page.wait_for_selector(SWITCHER_TRIGGER_SELECTOR, timeout=15000)
        except Exception as exc:
            raise ClientError("Muse side-chat switcher did not finish loading.") from exc
        page.locator(SWITCHER_TRIGGER_SELECTOR).click()
        deadline = time.monotonic() + SWITCHER_OPEN_TIMEOUT_SECONDS
        rows, stable_since = None, None
        while True:
            current = page.evaluate(SIDE_THREAD_ROWS_JS)
            now = time.monotonic()
            if current is not None and not isinstance(current, list):
                raise ClientError("Muse side-chat switcher returned invalid rows.")
            if current is not None and current == rows:
                if now - stable_since >= SWITCHER_SETTLE_SECONDS:
                    return rows
            else:
                rows, stable_since = current, now
            if now >= deadline:
                if rows is None:
                    raise ClientError("Muse side-chat switcher did not open.")
                raise ClientError("Muse side-chat switcher rows did not settle.")
            page.wait_for_timeout(100)

    def list_chats(self, limit: int = 100) -> list[dict]:
        page = self._open_chat("main")
        initial = self._open_switcher(page)
        discovered = []
        side_limit = max(0, limit - 1)
        for index, row in enumerate(initial[:side_limit]):
            if index:
                page.goto(MAIN_URL)
                self._require_target(page, "main")
                self._require_composer(page)
                self._open_switcher(page)
            clicked = page.evaluate(SIDE_THREAD_CLICK_JS, index)
            if not clicked:
                raise ClientError(f"Muse side-chat row {index} disappeared while listing chats.")
            deadline = time.monotonic() + 10
            thread_id = None
            while time.monotonic() < deadline:
                thread_id = self._chat_id_from_url(page.url)
                if thread_id:
                    break
                page.wait_for_timeout(100)
            if thread_id is None:
                raise ClientError(f"Muse side-chat row {index} did not open a durable thread URL.")
            discovered.append(
                {
                    "thread_id": thread_id,
                    "href": page.url,
                    "title": row.get("title", "") if isinstance(row, dict) else "",
                }
            )
        rows = normalize_threads(discovered)
        if discovered:
            page.goto(MAIN_URL)
        main = {"id": "main", "title": "Main chat", "url": MAIN_URL, "kind": "main"}
        return [main, *rows][:limit]

    def get_chat(self, chat_id: str) -> dict:
        validated = self._validate_chat_id(chat_id)
        page = self._open_chat(validated)
        deadline = time.monotonic() + HISTORY_SETTLE_TIMEOUT_SECONDS
        snapshot = self._snapshot(page)
        previous = snapshot
        stable_since = time.monotonic()
        while not snapshot["typing"] and not snapshot["working"]:
            now = time.monotonic()
            if now - stable_since >= RESPONSE_SETTLE_SECONDS or now >= deadline:
                break
            page.wait_for_timeout(min(250, max(1, int((deadline - now) * 1000))))
            snapshot = self._snapshot(page)
            if snapshot != previous:
                previous, stable_since = snapshot, time.monotonic()
        return normalize_chat(
            {
                "id": validated,
                "url": page.url,
                "messages": snapshot["messages"],
                "typing": snapshot["typing"],
            }
        )


def get_client(profile: Optional[str] = None) -> MuseChatClient:
    """Return a fresh client for one command invocation."""
    return MuseChatClient(profile=profile)
