"""Unit tests for the Microworkers IMDb task-work adapter (work.py).

The deterministic decisions live in pure functions and a thin page-driving
flow, so these tests exercise them with a fake browser page — no live browser,
no credentials, no network.
"""

import pytest

import microworkers_cli.work as work
from microworkers_cli.work import (
    ANCHORS_JS,
    IMDB_CREDITS_JS,
    TaskWorkError,
    google_search_url,
    is_bitly_preview,
    is_continue_link,
    is_imdb_name_url,
    normalize_name,
    parse_acting_credits,
    recognize_bitly_continue,
    run_imdb_credits_task,
    select_exact_imdb_name_result,
    validate_google_search_destination,
)

NAME = "Kurt Finney"
GOOGLE_URL = "https://www.google.com/search?q=Kurt+Finney&sourceid=chrome&ie=UTF-8&source=chrome.ctxt"
IMDB_NAME_URL = "https://www.imdb.com/name/nm0123456/"


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def test_normalize_name_collapses_whitespace():
    assert normalize_name("  Kurt   Finney  ") == "Kurt Finney"


def test_google_search_url_builds_exact_query():
    assert google_search_url("Kurt Finney") == "https://www.google.com/search?q=Kurt+Finney"


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Bitly | bit.ly/3UE6fyu", True),
        ("🐴 Bitly | bit.ly/3UE6fyu", True),
        ("Google Search", False),
        ("", False),
    ],
)
def test_is_bitly_preview(title, expected):
    assert is_bitly_preview(title) is expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Continue", True),
        ("  continue  ", True),
        ("Continue to site", True),
        ("Continue to the link", True),
        ("Back", False),
        ("", False),
        (None, False),
    ],
)
def test_is_continue_link(text, expected):
    assert is_continue_link(text) is expected


@pytest.mark.parametrize(
    "href,expected",
    [
        (GOOGLE_URL, True),
        ("https://www.google.com/search?q=Kurt+Finney", True),
        ("http://www.google.com/search?q=Kurt%20Finney", True),
        ("https://google.com/search?q=Kurt+Finney", True),
        # Wrong host / path / query
        ("https://www.bing.com/search?q=Kurt+Finney", False),
        ("https://www.google.com/webhp?q=Kurt+Finney", False),
        ("https://www.google.com/search?q=Someone+Else", False),
        ("https://www.google.com/search", False),
        ("", False),
    ],
)
def test_validate_google_search_destination(href, expected):
    assert validate_google_search_destination(href, NAME) is expected


@pytest.mark.parametrize(
    "url,expected",
    [
        (IMDB_NAME_URL, True),
        ("https://imdb.com/name/nm0123456/", True),
        ("https://m.imdb.com/name/nm0123456/", True),
        # Title pages and other IMDb paths are not name results
        ("https://www.imdb.com/title/tt0123456/", False),
        ("https://www.imdb.com/", False),
        ("https://example.com/name/nm0123456/", False),
        ("", False),
        (None, False),
    ],
)
def test_is_imdb_name_url(url, expected):
    assert is_imdb_name_url(url) is expected


# --------------------------------------------------------------------------- #
# select_exact_imdb_name_result
# --------------------------------------------------------------------------- #
def test_select_imdb_name_result_returns_single_match():
    results = [
        {"text": "Kurt Finney - IMDb", "href": IMDB_NAME_URL, "visible": True},
        {"text": "Some unrelated page", "href": "https://example.com/", "visible": True},
    ]
    assert select_exact_imdb_name_result(results, NAME) is results[0]


def test_select_imdb_name_result_ignores_hidden_and_title_pages():
    results = [
        {"text": "Kurt Finney - IMDb", "href": IMDB_NAME_URL, "visible": False},  # hidden
        {"text": "Kurt Finney - IMDb", "href": "https://www.imdb.com/title/tt1/", "visible": True},
        {"text": "Kurt Finney - IMDb", "href": IMDB_NAME_URL, "visible": True},
    ]
    assert select_exact_imdb_name_result(results, NAME) is results[2]


def test_select_imdb_name_result_matches_exact_issue_failure_message():
    with pytest.raises(TaskWorkError, match="found 0"):
        select_exact_imdb_name_result(
            [{"text": "Bitly", "href": GOOGLE_URL, "visible": True}], NAME
        )


def test_select_imdb_name_result_raises_on_two_matches():
    results = [
        {"text": "Kurt Finney - IMDb", "href": IMDB_NAME_URL, "visible": True},
        {"text": "Kurt Finney - IMDb", "href": "https://www.imdb.com/name/nm9999999/", "visible": True},
    ]
    with pytest.raises(TaskWorkError, match="found 2"):
        select_exact_imdb_name_result(results, NAME)


# --------------------------------------------------------------------------- #
# parse_acting_credits
# --------------------------------------------------------------------------- #
def test_parse_acting_credits_normalizes_fields():
    entries = [
        {"title": "  The Movie  ", "year": "2015", "role": "  John Doe  "},
        {"title": "TV Series", "year": None, "role": "Recurring"},
    ]
    assert parse_acting_credits(entries) == [
        {"title": "The Movie", "year": 2015, "role": "John Doe"},
        {"title": "TV Series", "year": None, "role": "Recurring"},
    ]


def test_parse_acting_credits_parses_first_four_digit_year():
    assert parse_acting_credits([{"title": "X", "year": "2015–2017", "role": ""}]) == [
        {"title": "X", "year": 2015, "role": ""}
    ]
    assert parse_acting_credits([{"title": "X", "year": "TV Movie", "role": ""}]) == [
        {"title": "X", "year": None, "role": ""}
    ]


def test_parse_acting_credits_drops_entries_without_title():
    assert parse_acting_credits([{"title": "", "year": "2015", "role": "x"}]) == []


# --------------------------------------------------------------------------- #
# Page-driving flow (fake page)
# --------------------------------------------------------------------------- #
class FakePage:
    """Stateful page double: each state has a title, anchors, and credits."""

    def __init__(self, states):
        self.states = states
        self.index = 0
        self.waits = []

    @property
    def current(self):
        return self.states[self.index]

    def evaluate(self, js):
        if "document.title" in js:
            return self.current["title"]
        if js == ANCHORS_JS:
            return self.current.get("anchors", [])
        if js == IMDB_CREDITS_JS:
            return self.current.get("credits", [])
        if "target[0].click()" in js:
            if self.index + 1 < len(self.states):
                self.index += 1
            return {"clicked": True, "count": 1}
        raise AssertionError(f"Unexpected evaluate call: {js!r}")

    def wait_for_timeout(self, ms):
        self.waits.append(ms)


def _states():
    return [
        {
            "title": "🐴 Bitly | bit.ly/3UE6fyu",
            "anchors": [
                {"text": "Continue", "href": GOOGLE_URL, "visible": True},
                {"text": "bit.ly", "href": "https://bit.ly/3UE6fyu", "visible": True},
            ],
        },
        {
            "title": "Kurt Finney - Google Search",
            "anchors": [
                {"text": "Kurt Finney - IMDb", "href": IMDB_NAME_URL, "visible": True},
                {"text": "Kurt Finney - Wikipedia", "href": "https://en.wikipedia.org/wiki/Kurt_Finney", "visible": True},
            ],
        },
        {
            "title": "Kurt Finney - IMDb",
            "credits": [
                {"title": "The Movie", "year": "2015", "role": "Detective"},
                {"title": "TV Series", "year": "2010", "role": "Recurring"},
            ],
        },
    ]


def test_recognize_bitly_continue_returns_validated_link():
    page = FakePage(_states())
    link = recognize_bitly_continue(page, NAME)
    assert link["href"] == GOOGLE_URL
    assert link["text"] == "Continue"


def test_recognize_bitly_continue_rejects_non_bitly_page():
    states = _states()
    states[0]["title"] = "Google Search"
    with pytest.raises(TaskWorkError, match="Bitly preview"):
        recognize_bitly_continue(FakePage(states), NAME)


def test_recognize_bitly_continue_rejects_zero_or_multiple_continue_links():
    states = _states()
    states[0]["anchors"] = [
        {"text": "Back", "href": "https://bit.ly/3UE6fyu", "visible": True},
    ]
    with pytest.raises(TaskWorkError, match="Continue link"):
        recognize_bitly_continue(FakePage(states), NAME)

    states = _states()
    states[0]["anchors"] = [
        {"text": "Continue", "href": GOOGLE_URL, "visible": True},
        {"text": "Continue", "href": "https://www.google.com/search?q=X", "visible": True},
    ]
    with pytest.raises(TaskWorkError, match="Continue link"):
        recognize_bitly_continue(FakePage(states), NAME)


def test_recognize_bitly_continue_rejects_wrong_destination():
    states = _states()
    states[0]["anchors"] = [
        {"text": "Continue", "href": "https://www.google.com/search?q=Someone+Else", "visible": True},
    ]
    with pytest.raises(TaskWorkError, match="exact Google query"):
        recognize_bitly_continue(FakePage(states), NAME)


def test_run_imdb_credits_task_returns_parsed_credits():
    page = FakePage(_states())
    credits = run_imdb_credits_task(page, NAME)
    assert credits == [
        {"title": "The Movie", "year": 2015, "role": "Detective"},
        {"title": "TV Series", "year": 2010, "role": "Recurring"},
    ]
    assert page.index == 2, "the flow clicked through Bitly -> Google -> IMDb"
    assert page.waits == [1500, 1500]


def test_run_imdb_credits_task_fails_when_no_imdb_name_result():
    states = _states()
    states[1]["anchors"] = [
        {"text": "Kurt Finney - Wikipedia", "href": "https://en.wikipedia.org/wiki/Kurt_Finney", "visible": True},
    ]
    with pytest.raises(TaskWorkError, match="IMDb name link"):
        run_imdb_credits_task(FakePage(states), NAME)
