"""Close-only beforeunload handling is bounded and never accepts other dialogs."""
import asyncio

import pytest

from browser_harness import daemon, helpers


def test_close_helper_has_own_ipc_budget_and_only_blank_destination(monkeypatch):
    calls = []
    monkeypatch.setattr(helpers, "_send", lambda request, **kwargs: calls.append((request, kwargs)) or {"result": {"frameId": "FRAME"}})
    assert helpers.goto_url_for_close() == {"frameId": "FRAME"}
    assert calls == [({"meta": "close_navigation", "timeout": 5}, {"timeout": 6})]
    with pytest.raises(ValueError):helpers.goto_url_for_close("https://www.tiktok.com/")
    assert len(calls) == 1


def test_exact_beforeunload_unblocks_pending_navigation_without_changing_draft(monkeypatch):
    monkeypatch.setattr(daemon.ipc, "expected_token", lambda: None)
    async def scenario():
        instance = daemon.Daemon();instance.session = "PAGE"
        signal = asyncio.Event();calls = [];draft = {"key": "EXACT_PRIVATE_DRAFT", "caption": "preserved"}
        class CDP:
            async def send_raw(self, method, params, *, session_id):
                calls.append((method, params, session_id))
                if method == "Page.navigate":
                    instance.dialog = {"type": "beforeunload"}
                    await signal.wait()
                    return {"frameId": "FRAME"}
                assert method == "Page.handleJavaScriptDialog" and params == {"accept": True}
                instance.dialog = None;signal.set();return {}
        instance.cdp = CDP()
        result = await instance.handle({"meta": "close_navigation", "timeout": 1})
        assert result == {"result": {"frameId": "FRAME"}}
        assert calls == [("Page.navigate", {"url": "about:blank"}, "PAGE"),
                         ("Page.handleJavaScriptDialog", {"accept": True}, "PAGE")]
        assert draft == {"key": "EXACT_PRIVATE_DRAFT", "caption": "preserved"}
        assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["alert", "confirm", "prompt", "unknown"])
def test_unknown_dialog_never_accepted_and_pending_request_is_cancelled(monkeypatch, kind):
    monkeypatch.setattr(daemon.ipc, "expected_token", lambda: None)
    async def scenario():
        instance = daemon.Daemon();instance.session = "PAGE";calls = []
        class CDP:
            async def send_raw(self, method, params, *, session_id):
                calls.append(method);instance.dialog = {"type": kind}
                await asyncio.Event().wait()
        instance.cdp = CDP()
        with pytest.raises(RuntimeError, match="non-beforeunload"):
            await instance.handle({"meta": "close_navigation", "timeout": 1})
        assert calls == ["Page.navigate"] and instance.dialog == {"type": kind}
        assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
    asyncio.run(scenario())


def test_stalled_navigation_times_out_and_cancels_without_leaking_task(monkeypatch):
    monkeypatch.setattr(daemon.ipc, "expected_token", lambda: None)
    async def scenario():
        instance = daemon.Daemon();instance.session = "PAGE";cancelled = []
        class CDP:
            async def send_raw(self, method, params, *, session_id):
                try:await asyncio.Event().wait()
                finally:cancelled.append(method)
        instance.cdp = CDP()
        with pytest.raises(RuntimeError, match="timed out"):
            await instance.handle({"meta": "close_navigation", "timeout": 0.01})
        assert cancelled == ["Page.navigate"]
        assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
    asyncio.run(scenario())


@pytest.mark.parametrize("timeout", [True, 0, -1, 6, "5", None])
def test_close_budget_cannot_be_inflated_or_coerced(monkeypatch, timeout):
    monkeypatch.setattr(daemon.ipc, "expected_token", lambda: None)
    instance = daemon.Daemon()
    assert asyncio.run(instance.handle({"meta": "close_navigation", "timeout": timeout})) == {"error": "invalid close-navigation timeout"}
