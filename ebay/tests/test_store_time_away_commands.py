"""Tests for eBay store Time Away commands."""
import json
from datetime import date
from unittest.mock import MagicMock

import pytest
from playwright.sync_api import sync_playwright
from typer.testing import CliRunner

from ebay_cli import time_away
from ebay_cli.commands import store
from ebay_cli.main import app


class _Browser:
    """Stand-in for the CLI-owned browser session; only close() is used here."""

    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _TimeAway:
    """Stand-in for the ebay_cli.time_away module, recording its calls."""

    def __init__(self):
        self.enabled_calls = []
        self.disabled = False
        self.state = {
            "url": "https://www.ebay.com/vac/timeaway",
            "title": "Time Away | eBay",
            "enabled": False,
            "mode": None,
            "has_schedule_action": True,
            "has_cancel_action": False,
            "text_excerpt": "Schedule time away",
        }

    def read_settings(self, browser):
        return self.state

    def enable(self, browser, **kwargs):
        self.enabled_calls.append(kwargs)
        return {
            **self.state,
            "enabled": True,
            "mode": kwargs["mode"],
            "has_cancel_action": True,
        }

    def disable(self, browser):
        self.disabled = True
        return {
            **self.state,
            "enabled": False,
            "has_schedule_action": True,
            "has_cancel_action": False,
        }


def _patch_browser(monkeypatch, browser):
    """Wire the fake browser and time_away module into the store commands."""
    config = MagicMock()
    config.get_browser.return_value = browser
    monkeypatch.setattr(store, "get_config", lambda profile=None: config)
    automation = _TimeAway()
    monkeypatch.setattr(store, "time_away", automation)
    return automation


def test_parse_time_away_date_accepts_supported_formats():
    assert store._parse_time_away_date("7/21/26") == date(2026, 7, 21)
    assert store._parse_time_away_date("07/21/2026") == date(2026, 7, 21)
    assert store._parse_time_away_date("2026-07-21") == date(2026, 7, 21)

    with pytest.raises(ValueError, match="date must be"):
        store._parse_time_away_date("07-21-2026")


def test_time_away_enable_refuses_without_yes_or_dry_run(monkeypatch):
    browser = _Browser()
    automation = _patch_browser(monkeypatch, browser)

    result = CliRunner().invoke(
        app,
        ["seller", "store", "time-away", "enable", "7/21/26"],
    )

    assert result.exit_code == 1
    assert "Refusing to update eBay Time Away without --yes or --dry-run" in result.stderr
    assert automation.enabled_calls == []
    assert browser.closed is False


def test_time_away_enable_dry_run_reads_without_saving(monkeypatch):
    browser = _Browser()
    automation = _patch_browser(monkeypatch, browser)

    result = CliRunner().invoke(
        app,
        ["seller", "store", "time-away", "enable", "7/21/26", "--start-date", "7/10/26", "--dry-run"],
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["action"] == "enable"
    assert data["dry_run"] is True
    assert data["submitted"] is False
    assert data["start_date"] == "2026-07-10"
    assert data["end_date"] == "2026-07-21"
    assert data["mode"] == "allow-sales"
    assert automation.enabled_calls == []
    assert browser.closed is True


def test_time_away_enable_saves_normalized_dates(monkeypatch):
    browser = _Browser()
    automation = _patch_browser(monkeypatch, browser)

    result = CliRunner().invoke(
        app,
        [
            "seller",
            "store",
            "time-away",
            "enable",
            "7/21/26",
            "--start-date",
            "7/10/26",
            "--mode",
            "pause-sales",
            "--yes",
        ],
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["submitted"] is True
    assert data["enabled"] is True
    assert data["mode"] == "pause-sales"
    assert automation.enabled_calls == [
        {
            "start_date_iso": "2026-07-10",
            "start_date_display": "7/10/2026",
            "end_date_iso": "2026-07-21",
            "end_date_display": "7/21/2026",
            "mode": "pause-sales",
        }
    ]
    assert browser.closed is True


def test_time_away_enable_rejects_invalid_mode(monkeypatch):
    browser = _Browser()
    automation = _patch_browser(monkeypatch, browser)

    result = CliRunner().invoke(
        app,
        ["seller", "store", "time-away", "enable", "7/21/26", "--mode", "hidden", "--yes"],
    )

    assert result.exit_code == 1
    assert "mode must be allow-sales or pause-sales" in result.stderr
    assert automation.enabled_calls == []


def test_time_away_disable_saves_with_yes(monkeypatch):
    browser = _Browser()
    automation = _patch_browser(monkeypatch, browser)

    result = CliRunner().invoke(
        app,
        ["seller", "store", "time-away", "disable", "--yes"],
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["action"] == "disable"
    assert data["submitted"] is True
    assert automation.disabled is True
    assert browser.closed is True


def test_time_away_form_selects_mode_when_text_wraps_radio():
    html = """
    <html>
      <body>
        <form>
          <label for="start">Start date</label>
          <input id="start" type="text" />
          <label for="end">End date</label>
          <input id="end" type="text" />
          <fieldset>
            <legend>What should happen to your listings?</legend>
            <div class="radio-option">
              <input id="allow" type="radio" name="mode" value="ALLOW" />
              <span>Allow item sales</span>
              <span>Buyers can purchase fixed price listings while Time Away is active.</span>
            </div>
            <div class="radio-option">
              <input id="pause" type="radio" name="mode" value="PAUSE" />
              <span>Pause item sales</span>
            </div>
          </fieldset>
        </form>
      </body>
    </html>
    """

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)

        time_away.set_form(
            page,
            start_date_iso="2026-07-09",
            start_date_display="7/9/2026",
            end_date_iso="2026-07-21",
            end_date_display="7/21/2026",
            mode="allow-sales",
        )
        result = page.evaluate(
            """() => ({
                allowChecked: document.querySelector("#allow").checked,
                pauseChecked: document.querySelector("#pause").checked,
                start: document.querySelector("#start").value,
                end: document.querySelector("#end").value,
            })"""
        )
        browser.close()

    assert result == {
        "allowChecked": True,
        "pauseChecked": False,
        "start": "7/9/2026",
        "end": "7/21/2026",
    }
