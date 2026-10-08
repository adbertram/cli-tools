"""Real Google Chrome launches wait while a demo holds the bare desktop (agent-issues#1277)."""

import json
import sys
import types

import pytest

import cli_tools_shared.browser.desktop_lease as desktop_lease
import cli_tools_shared.browser.driver as driver
import cli_tools_shared.browser.playwright_service as playwright_service
from cli_tools_shared.browser import BrowserHarnessError
from cli_tools_shared.browser.desktop_lease import wait_for_desktop_lease

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
HELD = {"protocolVersion": 1, "ok": True, "exitCode": 0, "leases": [
    {"lease": "lease-demo", "provider": "remote-bare", "type": "ui", "owner": "demo-slug", "state": "active"},
]}
FREE = {"protocolVersion": 1, "ok": True, "exitCode": 0, "leases": []}


@pytest.fixture
def warden(monkeypatch):
    """Install a fake Warden at the host path; it answers `status` from a queue of responses."""
    monkeypatch.setattr(desktop_lease.sys, "platform", "darwin")
    monkeypatch.delenv("TETHER_SESSION", raising=False)
    executable = desktop_lease.warden_executable()
    executable.parent.mkdir(parents=True)
    queue = executable.parent / "responses.json"
    calls = executable.parent / "calls.log"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, pathlib, sys\n"
        f"queue = pathlib.Path({str(queue)!r})\n"
        f"pathlib.Path({str(calls)!r}).open('a').write(' '.join(sys.argv[1:]) + '\\n')\n"
        "responses = json.loads(queue.read_text())\n"
        "print(responses[0] if isinstance(responses[0], str) else json.dumps(responses[0]))\n"
        "queue.write_text(json.dumps(responses[1:] or responses))\n"
    )
    executable.chmod(0o755)

    def respond(*responses):
        queue.write_text(json.dumps(list(responses)))
        return calls

    return respond


def test_waits_while_a_ui_lease_holds_the_desktop_then_launches(warden, monkeypatch, capsys):
    calls = warden(HELD, HELD, FREE)
    sleeps = []
    monkeypatch.setattr(desktop_lease.time, "sleep", sleeps.append)

    wait_for_desktop_lease(CHROME, timeout=60, poll=5)

    assert calls.read_text().splitlines() == ["status --provider remote-bare"] * 3
    assert sleeps == [5, 5]
    assert "lease lease-demo owner demo-slug (active)" in capsys.readouterr().err


def test_fails_clearly_when_the_lease_outlasts_the_wait(warden):
    warden(HELD)

    with pytest.raises(BrowserHarnessError, match=r"stayed leased for 0.2s \(lease lease-demo owner demo-slug"):
        wait_for_desktop_lease(CHROME, timeout=0.2, poll=0.05)


def test_does_not_wait_on_its_own_tether_session(warden, monkeypatch):
    warden(HELD)
    monkeypatch.setenv("TETHER_SESSION", "lease-demo")

    wait_for_desktop_lease(CHROME, timeout=0)


def test_cli_leases_do_not_hold_the_desktop(warden):
    warden({**FREE, "leases": [{**HELD["leases"][0], "type": "cli"}]})

    wait_for_desktop_lease(CHROME, timeout=0)


def test_unreadable_ledger_fails_the_launch(warden):
    warden("warden: nope")

    with pytest.raises(BrowserHarnessError, match="Cannot read the desktop lease ledger"):
        wait_for_desktop_lease(CHROME, timeout=60)


def test_other_browsers_and_hosts_without_warden_are_not_held(warden, monkeypatch):
    calls = warden(HELD)
    wait_for_desktop_lease("/Applications/Chromium.app/Contents/MacOS/Chromium", timeout=0)
    wait_for_desktop_lease(None, timeout=0)
    assert not calls.exists()

    desktop_lease.warden_executable().unlink()
    wait_for_desktop_lease(CHROME, timeout=0)


def test_holding_leases_answers_once_without_waiting(warden, monkeypatch):
    calls = warden(HELD)
    monkeypatch.setattr(desktop_lease.time, "sleep", lambda seconds: pytest.fail("waited"))

    assert [lease["lease"] for lease in desktop_lease.holding_leases(CHROME, timeout=3)] == ["lease-demo"]
    assert calls.read_text().splitlines() == ["status --provider remote-bare"]
    assert desktop_lease.holding_leases("/Applications/Chromium.app/Contents/MacOS/Chromium") == []
    warden(FREE)
    assert desktop_lease.holding_leases(CHROME) == []


def test_cdp_engine_checks_the_lease_before_spawning_chrome(tmp_path, monkeypatch):
    checked = []
    monkeypatch.setattr(driver, "_chrome_binary", lambda: CHROME)

    def held(executable):
        checked.append(executable)
        raise BrowserHarnessError("held")

    monkeypatch.setattr(driver, "wait_for_desktop_lease", held)
    monkeypatch.setattr(driver.subprocess, "Popen", lambda *a, **k: pytest.fail("Chrome spawned"))

    service = driver.BrowserHarnessService("lease-held-session")
    with pytest.raises(BrowserHarnessError, match="held"):
        service.browser_open(persistent_profile_dir=tmp_path / "chromium-profile")
    assert checked == [CHROME]


def test_playwright_engine_checks_the_lease_before_launching_chrome(tmp_path, monkeypatch):
    checked = []

    def held(executable):
        checked.append(executable)
        raise BrowserHarnessError("held")

    monkeypatch.setattr(playwright_service, "wait_for_desktop_lease", held)
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: pytest.fail("Chrome launched")
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)

    service = playwright_service.PlaywrightBrowserService("lease-held-session", executable_path=CHROME)
    with pytest.raises(BrowserHarnessError, match="held"):
        service.browser_open(persistent_profile_dir=tmp_path / "chromium-profile")
    assert checked == [CHROME]
