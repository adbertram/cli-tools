"""Regression tests for the 2026-08-28 reply-composer locator fix.

Incident: ``facebook groups posts reply`` failed twice with identical errors
("composer never cleared, comment count did not increment") while
``facebook groups posts comment`` worked reliably 5/5 times the same day with
similar text. Root cause (confirmed by reading ``FacebookClient.reply_to_comment``
and ``FacebookClient.comment_on_post`` side by side): the reply path typed into
whichever ``[role="textbox"][contenteditable="true"]`` happened to be LAST in
raw DOM query order, with no visibility filter, no Search-box exclusion, and no
uniqueness requirement. The comment path instead used
``_wait_for_visible_comment_composer`` + ``_insert_text_into_visible_comment_composer``,
which require exactly one visible, non-search candidate before typing. The fix
makes ``reply_to_comment`` reuse those same two helpers instead of its own
looser inline JS.

These tests use a scripted fake Playwright ``page`` (no real browser) to prove:

1. ``reply_to_comment`` now routes text entry through the SAME guarded,
   uniqueness-checked locator ``comment_on_post`` uses (not the old
   last-element-in-DOM-order heuristic).
2. When that locator cannot find exactly one visible composer (the exact
   ambiguous-DOM condition the old code silently mis-handled), the reply now
   fails loudly via ``ClientError`` instead of typing into a Facebook-app
   textbox that Enter never actually submits.
"""

from cli_tools_shared.exceptions import ClientError

from facebook_cli import client as client_mod


def _make_client():
    client_mod.get_config = lambda: object()
    return client_mod.FacebookClient()


class _FakePage:
    """Minimal scripted stand-in for a Playwright Page.

    ``evaluate`` is dispatched by matching a distinguishing substring in the
    JS source against ``responses`` (a list of (marker, value_or_callable)
    pairs, checked in order). Every call is recorded in ``calls`` for
    assertions.
    """

    def __init__(self, responses):
        self.url = "https://www.facebook.com/groups/2318028917/posts/10163770021943918/"
        self._responses = responses
        self.calls = []

    def wait_for_selector(self, *args, **kwargs):
        return None

    def wait_for_timeout(self, *args, **kwargs):
        return None

    def evaluate(self, js, arg=None):
        self.calls.append(js)
        for marker, value in self._responses:
            if marker in js:
                return value(arg) if callable(value) else value
        raise AssertionError(f"No scripted response for JS containing: {js[:120]!r}")


def _not_authenticated_probe(_arg=None):
    return {"loginForm": False, "recaptcha": False}


def _make_click_reply_response(total_comments=8):
    def _respond(comment_index):
        return {"success": True, "total_comments": total_comments}
    return _respond


def _use_fast_fake_clock(monkeypatch):
    """Replace time.monotonic() with a fake clock that advances 1.0s per
    call. Every wait-loop in client.py compares real deadlines
    (``time.monotonic() + timeout_ms/1000``) against this clock, so a loop
    whose scripted response never satisfies its exit condition still
    terminates deterministically (after a handful of calls) instead of
    hanging, while a loop whose condition IS satisfied on the first probe
    still returns immediately. ``page.wait_for_timeout`` is a no-op in
    ``_FakePage``, so none of this burns real wall-clock time either way.
    """
    state = {"t": 0.0}

    def fake_monotonic():
        state["t"] += 1.0
        return state["t"]

    monkeypatch.setattr(client_mod.time, "monotonic", fake_monotonic)


def test_reply_to_comment_uses_guarded_composer_locator_and_succeeds(monkeypatch):
    client = _make_client()
    _use_fast_fake_clock(monkeypatch)

    # First _count_post_comments call is the pre-submit snapshot (3);
    # every call after that simulates the post-submit count (4), so the
    # count-delta verification confirms on its very first probe.
    count_calls = {"n": 0}

    def _count_response(_a):
        count_calls["n"] += 1
        return 3 if count_calls["n"] == 1 else 4

    page = _FakePage(responses=[
        ("loginForm", _not_authenticated_probe),
        ("replyLinks", _make_click_reply_response()),
        # The guarded, uniqueness-checked probe shared with comment_on_post.
        ("totalVisibleTextboxes", lambda _a: {
            "count": 1, "totalVisibleTextboxes": 1, "usedFilter": "commentish",
            "candidates": [{"isCommentish": True, "isSearch": False}],
        }),
        # The guarded, uniqueness-checked insert shared with comment_on_post.
        ("Expected exactly one visible comment textbox", lambda _a: {
            "success": True, "usedFilter": "commentish", "hasLexical": False,
        }),
        ("Math.max(0, articles.length - 1)", _count_response),
        ("Could not find filled comment box", lambda _a: {"success": True}),
        ("composer-removed", lambda _a: {"cleared": True, "reason": "composer-removed"}),
        ("cleaned.indexOf", lambda _a: False),
    ])
    monkeypatch.setattr(client, "_get_page", lambda url, settle_ms=0: page)

    result = client.reply_to_comment(
        "2318028917/posts/10163770021943918", 6, "Ha, good catch, Glenn.",
    )

    assert result["success"] is True
    assert result["verified"] is True
    # The reply path must have gone through the SAME guarded locator/typer
    # comment_on_post uses -- not a bespoke "last textbox in DOM order" probe.
    assert any("totalVisibleTextboxes" in c for c in page.calls), (
        "reply_to_comment did not call the shared _wait_for_visible_comment_composer probe"
    )
    assert any("Expected exactly one visible comment textbox" in c for c in page.calls), (
        "reply_to_comment did not call the shared _insert_text_into_visible_comment_composer typer"
    )
    # The old bespoke "boxes[boxes.length - 1]" reply-only typer must be gone.
    assert not any("boxes.length - 1" in c for c in page.calls), (
        "reply_to_comment still contains the removed unguarded last-textbox heuristic"
    )


def test_reply_to_comment_raises_instead_of_guessing_when_composer_is_ambiguous(monkeypatch):
    """Exactly the DOM condition the old code mishandled: more than one
    visible contenteditable textbox present when the reply composer opens
    (e.g. a still-open composer from a moment ago). The old reply-only JS
    would have silently grabbed `boxes[boxes.length - 1]` and typed into
    whichever one that happened to be. The fixed path must refuse to guess.
    """
    client = _make_client()
    _use_fast_fake_clock(monkeypatch)

    page = _FakePage(responses=[
        ("loginForm", _not_authenticated_probe),
        ("replyLinks", _make_click_reply_response()),
        # Two visible, non-search candidates -- genuinely ambiguous.
        ("totalVisibleTextboxes", lambda _a: {
            "count": 2, "totalVisibleTextboxes": 2, "usedFilter": "commentish",
            "candidates": [
                {"isCommentish": True, "isSearch": False},
                {"isCommentish": True, "isSearch": False},
            ],
        }),
    ])
    monkeypatch.setattr(client, "_get_page", lambda url, settle_ms=0: page)

    try:
        client.reply_to_comment(
            "2318028917/posts/10163770021943918", 6, "Ha, good catch, Glenn.",
        )
        raise AssertionError("expected ClientError for an ambiguous composer state")
    except ClientError as exc:
        assert "exactly one visible" in str(exc)

    # Must never have reached the typer with an unresolved ambiguity.
    assert not any("Expected exactly one visible comment textbox" in c for c in page.calls)
