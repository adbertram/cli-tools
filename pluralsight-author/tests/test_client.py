import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest
from cli_tools_shared.auth import AuthResult
from cli_tools_shared.exceptions import ClientError

from pluralsight_author_cli.client import PluralsightAuthorClient
from pluralsight_author_cli.config import Config
from pluralsight_author_cli.parsers import extract_opportunities_from_snapshot


PAGE_ONE_SNAPSHOT = """
- generic [ref=e1]:
  - text: 4 results
  - text: First Opportunity
  - text: NEW!
  - img "play circle icon" [ref=e2]
  - text: Video Course
  - text: ●
  - text: Developer
  - text: ●
  - text: Posted
  - text: May 11, 2026
  - img "bookmark icon" [ref=e3]
  - text: Second Opportunity
  - img "play circle icon" [ref=e4]
  - text: Video Course
  - text: ●
  - text: Security
  - text: ●
  - text: Posted
  - text: May 10, 2026
  - img "bookmark icon" [ref=e5]
  - button "Page 1 is your current page" [ref=e6]
  - button "Page 2" [ref=e7]
  - button "Next page" [ref=e8]
  - text: Features
"""


PAGE_TWO_SNAPSHOT = """
- generic [ref=e1]:
  - text: 4 results
  - text: Third Opportunity
  - img "play circle icon" [ref=e2]
  - text: Video Course
  - text: ●
  - text: Artificial Intelligence
  - text: ●
  - text: Posted
  - text: May 09, 2026
  - img "bookmark icon" [ref=e3]
  - text: Fourth Opportunity
  - img "labs icon" [ref=e4]
  - text: Code Lab
  - text: ●
  - text: Artificial Intelligence
  - text: ●
  - text: Posted
  - text: May 08, 2026
  - img "bookmark icon" [ref=e5]
  - button "Previous page" [ref=e6]
  - button "Page 1" [ref=e7]
  - button "Page 2 is your current page" [ref=e8]
  - text: Features
"""


DETAIL_SNAPSHOT = """
- generic:
  - text: Product Strategy: Steering with Evidence
  - text: Learning Objective
  - text: (
  - text: 2
  - text: )
  - button "Apply"
  - button "1. Evaluate a strategic decision against a chain of evidenceExpanded"
  - button "2. Distinguish signal from noise in product dataExpanded"
"""

APPLY_OPEN_SNAPSHOT = {
    "texts": [
        "Product Strategy: Steering with Evidence",
        "Application for:",
        "Tell us about your availability and domain expertise.",
        "When could you start?",
        "How many weeks will it take you to finish this opportunity?",
        "What prior experience do you have using this skill?",
        "Paste links to any applicable projects or portfolios.",
    ],
    "buttons": ["Apply", "Cancel", "Send application", "Close dialog"],
}

APPLY_SUBMITTED_SNAPSHOT = {
    "texts": [
        "Product Strategy: Steering with Evidence",
        "Learning Objective",
    ],
    "buttons": ["Apply", "Copy link"],
}


class FakeBodyLocator:
    def __init__(self, page):
        self.page = page

    def aria_snapshot(self):
        return self.page.snapshots[self.page.current_page]


class FakeRawPage:
    def __init__(self, page):
        self.page = page

    def locator(self, selector):
        assert selector == "body"
        return FakeBodyLocator(self.page)


def _extract_texts_and_buttons(snapshot_text: str) -> dict:
    texts = []
    buttons = []
    for line in snapshot_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- text:"):
            value = stripped[len("- text:"):].strip()
            if value.startswith('"') and value.endswith('"'):
                value = json.loads(value)
            if value in {"●", "Posted"}:
                continue
            texts.append(value)
            continue
        if stripped.startswith('- button "'):
            match = re.match(r'- button "([^"]+)"', stripped)
            if match is not None:
                buttons.append(match.group(1))
    return {"texts": texts, "buttons": buttons}


class FakePageButton:
    def __init__(self, page, target_page):
        self.page = page
        self.target_page = target_page

    def click(self):
        self.page.current_page = self.target_page


class FakeLocator:
    def __init__(self, page, target_page):
        self.page = page
        self.target_page = target_page

    def count(self):
        return 1 if self.target_page in self.page.snapshots else 0

    @property
    def first(self):
        return FakePageButton(self.page, self.target_page)


class FakePage:
    def __init__(self, snapshots, detail_ids):
        self.snapshots = snapshots
        self.detail_ids = detail_ids
        self.current_page = 1

    def wait_for_timeout(self, ms):
        assert ms in {2000, 3000}

    def _get_page(self):
        return FakeRawPage(self)

    def evaluate(self, js, arg=None):
        del arg
        if "data-testid" in js:
            return self.detail_ids[self.current_page]
        return _extract_texts_and_buttons(self.snapshots[self.current_page])

    def get_by_role(self, role, *, name=None):
        assert role == "button"
        page_number = int(re.search(r"\^Page (\d+)", name.pattern).group(1))
        return FakeLocator(self, page_number)


class FakeSnapshotPage:
    def __init__(self, snapshot_data):
        self.snapshot_data = snapshot_data

    def wait_for_timeout(self, ms):
        assert ms in {2000, 3000}

    def evaluate(self, js, arg=None):
        del js
        del arg
        return self.snapshot_data


class FakeClickButton:
    def __init__(self, page):
        self.page = page

    def click(self):
        self.page.apply_clicked = True
        self.page.snapshot_data = APPLY_OPEN_SNAPSHOT


class FakeFieldInput:
    def __init__(self, page, label):
        self.page = page
        self.label = label

    def fill(self, value):
        self.page.filled_fields[self.label] = value


class FakeSendButton:
    def __init__(self, page):
        self.page = page

    def click(self):
        self.page.send_clicked = True
        self.page.snapshot_data = APPLY_SUBMITTED_SNAPSHOT


class FakeClickLocator:
    def __init__(self, page, count, button_factory):
        self.page = page
        self._count = count
        self._button_factory = button_factory

    def count(self):
        return self._count

    @property
    def first(self):
        return self._button_factory(self.page)


class FakeApplyPage(FakeSnapshotPage):
    def __init__(self, snapshot_data, apply_count=1):
        super().__init__(snapshot_data)
        self.apply_count = apply_count
        self.apply_clicked = False
        self.send_clicked = False
        self.filled_fields = {}
        self.button_requests = []

    def get_by_role(self, role, *, name=None):
        assert role == "button"
        self.button_requests.append(name)
        if getattr(name, "pattern", None) == "^Apply$":
            return FakeClickLocator(self, self.apply_count, FakeClickButton)
        if getattr(name, "pattern", None) == "^Send application$":
            return FakeClickLocator(self, 1, FakeSendButton)
        raise AssertionError(f"Unexpected button requested: {name}")

    def get_by_label(self, label, *, exact=False):
        assert exact is True
        return FakeFieldInput(self, label)

    def evaluate(self, js, arg=None):
        if arg is not None and isinstance(arg, dict) and {"label", "value"} <= set(arg):
            self.filled_fields[arg["label"]] = arg["value"]
            return True
        if arg is not None and isinstance(arg, dict) and {"selector", "value"} <= set(arg):
            self.filled_fields[arg["selector"]] = arg["value"]
            return True
        return super().evaluate(js, arg)


class FakeBrowser:
    def __init__(self, pages_by_url):
        self.pages_by_url = pages_by_url

    def is_authenticated(self):
        return AuthResult(authenticated=True, live_check=True)

    def get_page(self, url):
        return self.pages_by_url[url]

    def close(self):
        pass


def test_client_paginates_and_builds_models():
    client = PluralsightAuthorClient()
    fake_page = FakePage(
        {1: PAGE_ONE_SNAPSHOT, 2: PAGE_TWO_SNAPSHOT},
        {
            1: ["detail-id-1", "detail-id-2"],
            2: ["detail-id-3", "detail-id-4"],
        },
    )
    client._browser_instance = FakeBrowser(
        {"https://app.pluralsight.com/author-home/opportunities/all": fake_page}
    )
    client.config = SimpleNamespace(
        base_url="https://app.pluralsight.com/author-home/opportunities/all",
        storage_dir=Path("/tmp/pluralsight-author-test-cache"),
    )

    results = client.list_opportunities(limit=10)

    assert [item["title"] for item in results] == [
        "First Opportunity",
        "Second Opportunity",
        "Third Opportunity",
        "Fourth Opportunity",
    ]
    assert results[0]["id"] == "first-opportunity-may-11-2026"
    assert results[-1]["opportunity_type"] == "Code Lab"
    assert "opportunity_detail_id" not in results[0]


def test_get_item_fetches_learning_objectives_from_detail_page():
    client = PluralsightAuthorClient()
    list_page = FakePage(
        {1: PAGE_ONE_SNAPSHOT, 2: PAGE_TWO_SNAPSHOT},
        {
            1: ["detail-id-1", "detail-id-2"],
            2: ["detail-id-3", "detail-id-4"],
        },
    )
    detail_page = FakeSnapshotPage(_extract_texts_and_buttons(DETAIL_SNAPSHOT))
    client._browser_instance = FakeBrowser(
        {
            "https://app.pluralsight.com/author-home/opportunities/all": list_page,
            "https://app.pluralsight.com/author-home/opportunity/detail-id-1": detail_page,
        }
    )
    client.config = SimpleNamespace(
        base_url="https://app.pluralsight.com/author-home/opportunities/all",
        storage_dir=Path("/tmp/pluralsight-author-test-cache"),
    )

    result = client.get_item("first-opportunity-may-11-2026")

    assert result["title"] == "First Opportunity"
    assert result["learning_objectives"] == [
        "1. Evaluate a strategic decision against a chain of evidence",
        "2. Distinguish signal from noise in product data",
    ]


def test_apply_fills_required_form_fields_and_submits_application():
    client = PluralsightAuthorClient()
    list_page = FakePage(
        {1: PAGE_ONE_SNAPSHOT, 2: PAGE_TWO_SNAPSHOT},
        {
            1: ["detail-id-1", "detail-id-2"],
            2: ["detail-id-3", "detail-id-4"],
        },
    )
    detail_page = FakeApplyPage(
        {
            "texts": ["Product Strategy: Steering with Evidence", "Learning Objective"],
            "buttons": ["Apply", "Copy link"],
        }
    )
    client._browser_instance = FakeBrowser(
        {
            "https://app.pluralsight.com/author-home/opportunities/all": list_page,
            "https://app.pluralsight.com/author-home/opportunity/detail-id-1": detail_page,
        }
    )
    client.config = SimpleNamespace(
        base_url="https://app.pluralsight.com/author-home/opportunities/all",
        storage_dir=Path("/tmp/pluralsight-author-test-cache"),
    )

    result = client.apply(
        "first-opportunity-may-11-2026",
        {
            "start_date": "06/01/2026",
            "estimated_completion_weeks": "8",
            "experience": "Built and shipped security training for engineering teams.",
        },
    )

    assert detail_page.apply_clicked is True
    assert [request.pattern for request in detail_page.button_requests] == [
        "^Apply$",
        "^Send application$",
    ]
    assert detail_page.filled_fields == {
        "When could you start?": "06/01/2026",
        "How many weeks will it take you to finish this opportunity?": "8",
        "[data-testid='apply-description-textarea']": "Built and shipped security training for engineering teams.",
    }
    assert detail_page.send_clicked is True
    assert result == {
        "id": "first-opportunity-may-11-2026",
        "title": "First Opportunity",
        "detail_url": "https://app.pluralsight.com/author-home/opportunity/detail-id-1",
        "submitted_param_keys": ["estimated_completion_weeks", "experience", "start_date"],
        "form_markers": [
            "Application for:",
            "Tell us about your availability and domain expertise.",
            "Send application",
        ],
        "post_submit_state": "application_form_closed",
    }


def test_require_authenticated_session_uses_browser_saved_state_check():
    client = PluralsightAuthorClient()

    class FakeBrowser:
        def is_authenticated(self):
            return AuthResult(authenticated=False, live_check=True)

    client._browser_instance = FakeBrowser()

    with pytest.raises(ClientError, match="Saved browser session is not authenticated."):
        client._require_authenticated_session()


def test_config_test_connection_uses_browser_is_authenticated():
    config = Config.__new__(Config)

    class FakeBrowser:
        def is_authenticated(self):
            return AuthResult(authenticated=True, live_check=True)

    config.get_browser = lambda: FakeBrowser()

    assert Config.test_connection(config) == {"api_test": "passed"}


def test_config_test_connection_fails_when_browser_is_not_authenticated():
    config = Config.__new__(Config)

    class FakeBrowser:
        def is_authenticated(self):
            return AuthResult(authenticated=False, live_check=True)

    config.get_browser = lambda: FakeBrowser()

    with pytest.raises(RuntimeError, match="Saved browser session is not authenticated."):
        Config.test_connection(config)


def test_snapshot_preserves_features_boundary_before_footer_text():
    client = PluralsightAuthorClient()
    page = FakeSnapshotPage(
        {
            "texts": [
                "93 results",
                "Newest to oldest",
                "UX Accessibility: Designing for Mobile",
                "NEW!",
                "Video Course",
                "Product & UX",
                "May 11, 2026",
                "Features",
                "·",
                "Author",
                "·",
                "Mobile & offline apps",
                "Blog",
            ],
            "buttons": [
                "sort opportunitiesNewest to oldest",
                "Page 1 is your current page",
                "Next page",
            ],
        }
    )

    snapshot = client._snapshot(page)

    assert '"Newest to oldest"' not in snapshot
    assert snapshot.index('"Features"') < snapshot.index('"Author"')
    assert snapshot.index('"Features"') < snapshot.index('button "Page 1 is your current page"')
    assert extract_opportunities_from_snapshot(snapshot, page_number=1) == [
        {
                "title": "UX Accessibility: Designing for Mobile",
                "id": "ux-accessibility-designing-for-mobile-may-11-2026",
                "opportunity_type": "Video Course",
                "category": "Product & UX",
            "posted_date": "May 11, 2026",
            "is_new": True,
            "page_number": 1,
        }
    ]
