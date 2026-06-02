"""Medium browser-backed client."""

from __future__ import annotations

import html
import re
import time
from typing import Optional

from cli_tools_shared.exceptions import ClientError

from .config import get_config

NEW_STORY_URL = "https://medium.com/new-story"
_LOGIN_URL_RE = re.compile(r"/m/signin|/m/signup|/m/register|/m/sign-in")
_DRAFT_EDIT_URL_RE = re.compile(r"^https://medium\.com/p/[A-Za-z0-9]+/edit(?:[?#].*)?$")
_EDITOR_SELECTOR = '[contenteditable="true"]'
_TITLE_SELECTOR = '[data-testid="editorTitleParagraph"]'
_BODY_SELECTOR = '[data-testid="editorParagraphText"]'
_COMPOSER_TIMEOUT_MS = 60000

_SELECT_EDITOR_FIELD_JS = """
(selector) => {
  const root = document.querySelector('[contenteditable="true"]');
  if (!root) {
    return {success: false, error: 'Medium editor root was not found.'};
  }
  const field = document.querySelector(selector);
  if (!field) {
    return {success: false, error: `Medium editor field was not found: ${selector}`};
  }
  root.focus();
  const target = field.querySelector('.defaultValue') || field;
  const range = document.createRange();
  range.selectNodeContents(target);
  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
  return {success: true};
}
"""

_VERIFY_DRAFT_JS = """
(expected) => {
  const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim();
  const titleEl = document.querySelector('[data-testid="editorTitleParagraph"]');
  const bodyEl = document.querySelector('[data-testid="editorParagraphText"]');
  const titleText = normalize(titleEl ? titleEl.innerText : '');
  const bodyText = normalize(bodyEl ? bodyEl.innerText : '');
  return {
    url: window.location.href,
    titleText,
    bodyText,
    containsTitle: titleText === expected.title,
    containsBody: bodyText.includes(expected.bodyText),
  };
}
"""


def _render_medium_html(content: str) -> str:
    text = content.strip()
    if not text:
        raise ClientError("Post content cannot be empty.")
    if text.startswith("<"):
        return text

    paragraphs = []
    for chunk in re.split(r"\n\s*\n", text):
        lines = [html.escape(line) for line in chunk.splitlines()]
        paragraphs.append(f"<p>{'<br>'.join(lines)}</p>")
    return "".join(paragraphs)


def _visible_text_from_content(content: str) -> str:
    text = content.strip()
    if not text:
        raise ClientError("Post content cannot be empty.")
    if text.startswith("<"):
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()
    return re.sub(r"\s+", " ", text).strip()


def _input_text_from_content(content: str) -> str:
    text = content.strip()
    if not text:
        raise ClientError("Post content cannot be empty.")
    if text.startswith("<"):
        return _visible_text_from_content(text)
    return text


class MediumClient:
    """Create Medium drafts through the real Medium web composer."""

    def __init__(self, config=None):
        self.config = config if config is not None else get_config()
        self.browser = self.config.get_browser()

    def close(self) -> None:
        self.browser.close()

    def _get_page(self, url: str):
        page = self.browser.get_page(url)
        if _LOGIN_URL_RE.search(page.url):
            raise ClientError("Medium redirected to sign-in. Run 'medium auth login' first.")
        return page

    def _wait_for_draft_url(self, page, timeout_seconds: int = 20) -> str:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            current_url = page.url
            if _DRAFT_EDIT_URL_RE.match(current_url):
                return current_url
            page.wait_for_timeout(1000)
        raise ClientError(
            "Medium did not navigate to a draft edit URL after filling the composer."
        )

    def _select_editor_field(self, page, selector: str) -> None:
        result = page.evaluate(_SELECT_EDITOR_FIELD_JS, selector)
        if not isinstance(result, dict):
            raise ClientError("Medium editor selection returned an invalid response.")
        if not result.get("success"):
            raise ClientError(result.get("error") or "Medium editor selection failed.")

    def create_post(
        self,
        *,
        title: str,
        content: str,
    ) -> dict:
        """Create a Medium draft via the web composer."""
        normalized_title = title.strip()
        if not normalized_title:
            raise ClientError("Post title cannot be empty.")

        body_input = _input_text_from_content(content)
        body_text = _visible_text_from_content(content)

        page = self._get_page(NEW_STORY_URL)
        page.wait_for_selector(_EDITOR_SELECTOR, timeout=_COMPOSER_TIMEOUT_MS)
        page.wait_for_selector(_TITLE_SELECTOR, timeout=_COMPOSER_TIMEOUT_MS)
        page.wait_for_selector(_BODY_SELECTOR, timeout=_COMPOSER_TIMEOUT_MS)

        self._select_editor_field(page, _TITLE_SELECTOR)
        page.type_text(normalized_title)
        self._select_editor_field(page, _BODY_SELECTOR)
        page.type_text(body_input)

        page.wait_for_network_idle(timeout=10.0, idle_ms=1000)
        draft_url = self._wait_for_draft_url(page)
        verification = page.evaluate(
            _VERIFY_DRAFT_JS,
            {"title": normalized_title, "bodyText": body_text},
        )
        if not isinstance(verification, dict):
            raise ClientError("Medium draft verification returned an invalid response.")
        if not verification.get("containsTitle"):
            raise ClientError("Medium draft title did not match the requested title.")
        if not verification.get("containsBody"):
            raise ClientError("Medium draft body did not match the requested content.")

        return {
            "title": normalized_title,
            "draft_url": draft_url,
            "edit_url": draft_url,
        }


_client: Optional[MediumClient] = None


def get_client() -> MediumClient:
    """Get or create the global Medium client instance."""
    global _client
    if _client is None:
        _client = MediumClient()
    return _client
