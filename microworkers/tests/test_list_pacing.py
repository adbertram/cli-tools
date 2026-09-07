"""Unit tests for the Microworkers listing-walk pacing and page bounding.

Issue #52: the old ``list_tasks`` walk fired /jobs.php pages back to back with
no pacing, which Microworkers' bot detection read as automation and punished
with a 1-day "Auto-refresh / Bot" ban. These tests verify the replacement
behavior with fakes only — no live browser, no network, no live pagination:

- ``_pages_needed`` bounds the walk by the caller's limit, not a fixed cap;
- ``list_tasks`` fetches only the pages the limit requires and never walks past
  need;
- ``list_tasks`` sleeps a jittered, config-driven delay between consecutive
  pages;
- the delay/jitter config properties parse env overrides and fall back safely.
"""

import microworkers_cli.client as client_module
from microworkers_cli.client import (
    LIST_JS,
    ROWS_PER_PAGE,
    MicroworkersClient,
    _pages_needed,
)
from microworkers_cli.config import Config


class _FakeConfig:
    base_url = "https://www.microworkers.com"
    list_page_delay_seconds = 4.0
    list_page_delay_jitter = 0.5


def _listing_row(index):
    return {
        "campaign_id": f"campaign{index:04d}",
        "title": f"Job {index}",
        "url": f"https://www.microworkers.com/jobs_details.php?Id={index:06d}",
        "payment": "$1.00",
        "success_rate": "90%",
        "ttr_days": "3 days",
        "ttf_minutes": "10 minutes",
        "done": "100/100",
    }


class _FakePage:
    def __init__(self, rows):
        self.rows = rows

    def wait_for_timeout(self, _ms):
        pass

    def evaluate(self, script):
        assert script == LIST_JS
        return self.rows


class _FakeBrowser:
    """Serves ``rows_per_page`` unique rows per page, recording every URL."""

    def __init__(self, rows_per_page=ROWS_PER_PAGE):
        self.rows_per_page = rows_per_page
        self.urls = []
        self._served = 0

    def get_page(self, url):
        self.urls.append(url)
        rows = [_listing_row(self._served + i) for i in range(self.rows_per_page)]
        self._served += self.rows_per_page
        return _FakePage(rows)

    def close(self):
        pass


def _make_client(browser, monkeypatch):
    # Disable the @cached on-disk layer so the walk runs inline against fakes.
    monkeypatch.setenv("CACHE_ENABLED", "false")
    client = object.__new__(MicroworkersClient)
    client.config = _FakeConfig()
    client._browser = browser
    client._refresh_checked = True  # skip the session-refresh gate
    return client


def test_pages_needed_rounds_up_to_page_boundary():
    assert _pages_needed(0) == 0
    assert _pages_needed(-5) == 0
    assert _pages_needed(1) == 1
    assert _pages_needed(100) == 1
    assert _pages_needed(101) == 2
    assert _pages_needed(250) == 3
    assert _pages_needed(2500) == 25


def test_list_tasks_fetches_only_pages_the_limit_requires(monkeypatch):
    browser = _FakeBrowser()
    client = _make_client(browser, monkeypatch)

    rows = client.list_tasks(limit=100)

    assert len(rows) == 100
    assert browser.urls == ["https://www.microworkers.com/jobs.php?page=1"]


def test_list_tasks_rounds_up_pages_for_partial_limit(monkeypatch):
    browser = _FakeBrowser()
    client = _make_client(browser, monkeypatch)

    rows = client.list_tasks(limit=250)

    assert len(rows) == 250
    assert browser.urls == [
        "https://www.microworkers.com/jobs.php?page=1",
        "https://www.microworkers.com/jobs.php?page=2",
        "https://www.microworkers.com/jobs.php?page=3",
    ]


def test_list_tasks_does_not_sleep_for_a_single_page(monkeypatch):
    browser = _FakeBrowser()
    client = _make_client(browser, monkeypatch)
    sleeps = []
    monkeypatch.setattr(client_module.time, "sleep", sleeps.append)

    rows = client.list_tasks(limit=100)

    assert len(rows) == 100
    assert sleeps == []


def test_list_tasks_sleeps_jittered_delay_between_pages(monkeypatch):
    browser = _FakeBrowser()
    client = _make_client(browser, monkeypatch)
    sleeps = []
    uniform_calls = []
    monkeypatch.setattr(client_module.time, "sleep", sleeps.append)
    monkeypatch.setattr(
        client_module.random,
        "uniform",
        lambda lo, hi: (uniform_calls.append((lo, hi)) or 1.0),
    )

    rows = client.list_tasks(limit=250)

    assert len(rows) == 250
    # Two page boundaries -> two pauses. With uniform() pinned to 1.0, the
    # delay equals base * 1.0 = 4.0. Jitter draws from [1 - 0.5, 1 + 0.5].
    assert sleeps == [4.0, 4.0]
    assert uniform_calls == [(0.5, 1.5), (0.5, 1.5)]


def test_list_tasks_stops_early_when_a_page_is_empty(monkeypatch):
    browser = _FakeBrowser(rows_per_page=0)
    client = _make_client(browser, monkeypatch)

    rows = client.list_tasks(limit=250)

    assert rows == []
    assert browser.urls == ["https://www.microworkers.com/jobs.php?page=1"]


def test_config_list_page_delay_defaults_and_env_override(monkeypatch):
    monkeypatch.delenv("LIST_PAGE_DELAY_SECONDS", raising=False)
    monkeypatch.delenv("LIST_PAGE_DELAY_JITTER", raising=False)
    cfg = object.__new__(Config)

    assert cfg.list_page_delay_seconds == 4.0
    assert cfg.list_page_delay_jitter == 0.5

    monkeypatch.setenv("LIST_PAGE_DELAY_SECONDS", "7.5")
    monkeypatch.setenv("LIST_PAGE_DELAY_JITTER", "0.25")
    cfg = object.__new__(Config)
    assert cfg.list_page_delay_seconds == 7.5
    assert cfg.list_page_delay_jitter == 0.25


def test_config_list_page_delay_invalid_value_falls_back(monkeypatch):
    monkeypatch.setenv("LIST_PAGE_DELAY_SECONDS", "not-a-number")
    monkeypatch.setenv("LIST_PAGE_DELAY_JITTER", "fast")
    cfg = object.__new__(Config)

    assert cfg.list_page_delay_seconds == 4.0
    assert cfg.list_page_delay_jitter == 0.5
