"""Regression tests for Word comment extraction.

Guards the bug where ``docs comments list`` returned ``[]`` for documents that
also contain the sibling parts ``commentsIds`` / ``commentsExtended`` /
``commentsExtensible`` (whose relationship types all contain the substring
``comments``). The reader must select ``word/comments.xml`` by exact
relationship type and parse BOTH classic comments and modern threaded comments
(large integer id, ``w:date`` without a trailing ``Z``).
"""
from __future__ import annotations

from pathlib import Path

import docx
import pytest

from msword_cli.client import COMMENTS_REL_TYPE, MswordClient, _find_comments_part

FIXTURE = Path(__file__).parent / "fixtures" / "threaded-comments-sample.docx"

# Synthetic fixture identifiers (see fixtures/_build_threaded_comments_fixture.py).
CLASSIC_ID = "3"
MODERN_ID = "1402838193"  # large integer id, like a Word threaded reply


@pytest.fixture(scope="module")
def comments():
    return MswordClient().extract_comments(str(FIXTURE))


def test_fixture_reproduces_the_bug_shape():
    """The fixture must carry the sibling comment parts whose reltypes contain
    'comments', so the exact-match selection is actually exercised."""
    doc = docx.Document(str(FIXTURE))
    reltypes = {
        rel.reltype
        for rel in doc.part.rels.values()
        if not getattr(rel, "is_external", False)
    }
    substring_matches = {rt for rt in reltypes if "comments" in rt}
    # commentsIds + commentsExtended + commentsExtensible + comments == 4 parts
    # all contain the substring "comments"; a naive reader could pick the wrong one.
    assert len(substring_matches) >= 4, substring_matches
    assert COMMENTS_REL_TYPE in reltypes


def test_selects_comments_part_by_exact_reltype():
    """Exact-reltype selection returns word/comments.xml, never commentsIds."""
    doc = docx.Document(str(FIXTURE))
    part = _find_comments_part(doc)
    assert part is not None
    assert part.partname == "/word/comments.xml"


def test_returns_both_classic_and_modern_comments(comments):
    """Both a classic comment and a modern (large-id, no-Z-date) comment are returned."""
    assert len(comments) == 2
    by_id = {c.id: c for c in comments}
    assert set(by_id) == {CLASSIC_ID, MODERN_ID}


def test_classic_comment_fields(comments):
    classic = next(c for c in comments if c.id == CLASSIC_ID)
    assert classic.author == "Dana Lake"
    assert classic.date == "2026-01-05T09:30:00Z"  # classic dates keep the trailing Z
    assert classic.text == "Please assign a single owner here."
    assert classic.context == "The quarterly rollout plan needs a clearer owner."


def test_modern_threaded_comment_fields(comments):
    """The modern comment has a large integer id and a date WITHOUT a trailing Z."""
    modern = next(c for c in comments if c.id == MODERN_ID)
    assert modern.author == "Priya Anand"
    assert modern.date == "2026-02-11T14:07:42"
    assert not modern.date.endswith("Z")
    assert modern.text == "Agreed, a limited pilot first sounds right."
    # Anchored reference text resolves even for the modern comment.
    assert modern.context == "We should pilot the new workflow before the full launch."


def test_filter_by_author_returns_matching_comment(comments):
    """A document with both comments filters down to one author correctly."""
    from cli_tools_shared.filters import apply_filters

    dicts = [c.model_dump() for c in comments]
    filtered = apply_filters(dicts, ["author:eq:Priya Anand"])
    assert len(filtered) == 1
    assert filtered[0]["id"] == MODERN_ID


def test_get_single_comment_by_id():
    """get_comment resolves both classic and modern ids."""
    client = MswordClient()
    assert client.get_comment(str(FIXTURE), CLASSIC_ID).author == "Dana Lake"
    assert client.get_comment(str(FIXTURE), MODERN_ID).author == "Priya Anand"
