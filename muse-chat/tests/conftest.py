"""Keep legacy unit cases immediate; settling has explicit clock-driven tests."""
import pytest


@pytest.fixture(autouse=True)
def immediate_settling(monkeypatch):
    monkeypatch.setattr('muse_chat_cli.client.RESPONSE_SETTLE_SECONDS', 0)
