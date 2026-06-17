"""Tests for the post excerpt length guard.

A WordPress post excerpt doubles as the SEO meta description and the homepage
card text. An over-long excerpt (article body pasted in by mistake) must be
rejected loudly before it ever reaches WordPress. The guard runs inside both
`posts create` and `posts update`; this exercises the shared validator it calls.
"""
import pytest

from wordpress_cli.commands.posts import _validate_excerpt, EXCERPT_MAX_CHARS


def test_none_excerpt_is_allowed():
    _validate_excerpt(None)  # no excerpt provided -> nothing to validate


def test_excerpt_at_limit_is_allowed():
    _validate_excerpt("x" * EXCERPT_MAX_CHARS)  # exactly at the max is fine


def test_excerpt_over_limit_raises():
    with pytest.raises(ValueError) as exc:
        _validate_excerpt("x" * (EXCERPT_MAX_CHARS + 1))
    msg = str(exc.value)
    assert f"maximum is {EXCERPT_MAX_CHARS}" in msg
    assert "meta description" in msg


def test_only_trimmed_length_counts():
    # Leading/trailing whitespace must not push a valid excerpt over the limit.
    _validate_excerpt("  " + "x" * EXCERPT_MAX_CHARS + "  ")


def test_bloated_body_text_is_rejected():
    # Regression: the real failure -- ~1,060 chars of article intro in the excerpt.
    bloated = "The Death of Security Questions. " * 32
    assert len(bloated) > EXCERPT_MAX_CHARS
    with pytest.raises(ValueError):
        _validate_excerpt(bloated)
