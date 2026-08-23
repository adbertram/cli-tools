"""Regression tests for Mercari app-shell readiness."""

import pytest

from cli_tools_shared.exceptions import ClientError
from mercari_cli import client as client_module
from mercari_cli.client import MercariChallengeError, MercariClient


class _Page:
    def __init__(self, info):
        self.info = info
        self.calls = 0

    def evaluate(self, _script):
        self.calls += 1
        return self.info


class _Clock:
    def __init__(self):
        self.now = 0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_wait_ready_accepts_router_with_short_body():
    page = _Page(
        {
            "title": "your go-to marketplace | mercari",
            "bodyLen": 177,
            "routerReady": True,
            "challenged": False,
        }
    )

    MercariClient._wait_ready(page)

    assert page.calls == 1


def test_wait_ready_fails_closed_on_challenge():
    page = _Page(
        {
            "title": "just a moment",
            "bodyLen": 500,
            "routerReady": False,
            "challenged": True,
        }
    )

    with pytest.raises(MercariChallengeError, match="human verification challenge"):
        MercariClient._wait_ready(page)


def test_wait_ready_reports_router_timeout_without_inventing_challenge(monkeypatch):
    page = _Page(
        {
            "title": "your go-to marketplace | mercari",
            "bodyLen": 177,
            "routerReady": False,
            "challenged": False,
        }
    )
    clock = _Clock()
    monkeypatch.setattr(client_module, "time", clock)

    with pytest.raises(ClientError, match="router did not become ready") as exc:
        MercariClient._wait_ready(page, timeout=1)

    assert "challenge" not in str(exc.value).lower()
    assert "body_length=177" in str(exc.value)
