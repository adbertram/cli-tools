"""Regression tests for the Published URL the publisher records in Notion.

Defect: the classic publish leg stored the WordPress create response's `link`
verbatim. WordPress renders that field before the post's permalink is settled
and returns its slugless `?p=<id>` placeholder, so four Notion pages in
Published status carried `https://adamtheautomator.com/?p=27234` (also 27230,
27238, 26816) instead of a permalink.

The resolver reads the permalink back from WordPress after the post is
committed, and it uses that `link` rather than rebuilding a URL from the wp/v2
`slug`, because this site runs Permalink Manager: post 9234's slug is
`recall-email-in-outlook` while its canonical path is `/recall-outlook-email/`
(the other known overrides are 21405, 22142, 22628, 26230, 26259, 26341, 26851,
27147). Permalink Manager filters `get_permalink()`, so `link` carries those
overrides and the slug does not.

Hermetic: the WordPress CLI is stubbed; no network.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from ata_blog_cli.client import AtaBlogClient, ClientError


def _client(read_back):
    client = object.__new__(AtaBlogClient)
    calls: list[list[str]] = []

    def fake_run_wordpress(args, timeout=60):
        calls.append(list(args))
        return subprocess.CompletedProcess(
            args, 0, stdout=json.dumps(read_back), stderr=""
        )

    client._run_wordpress = fake_run_wordpress
    return client, calls


def test_live_permalink_override_beats_the_wordpress_slug():
    """A Permalink Manager override must survive; the slug must not win."""
    client, calls = _client(
        {
            "id": 9234,
            "status": "publish",
            "slug": "recall-email-in-outlook",
            "link": "https://adamtheautomator.com/recall-outlook-email/",
        }
    )

    assert (
        client._resolve_wordpress_permalink(9234)
        == "https://adamtheautomator.com/recall-outlook-email/"
    )
    assert calls == [["posts", "get", "9234"]]


def test_pending_post_permalink_is_built_from_its_own_slug():
    """A post that is not live yet has no permalink for WordPress to give."""
    client, _ = _client(
        {
            "id": 27165,
            "status": "future",
            "slug": "azure-sql-performance-tuning",
            "link": "https://adamtheautomator.com/?p=27165",
        }
    )

    assert (
        client._resolve_wordpress_permalink(27165)
        == "https://adamtheautomator.com/azure-sql-performance-tuning/"
    )


def test_live_post_with_a_placeholder_permalink_raises():
    """The `?p=` form must never be recorded, not even for a live post."""
    client, _ = _client(
        {
            "id": 27234,
            "status": "publish",
            "slug": "build-azure-landing-zones",
            "link": "https://adamtheautomator.com/?p=27234",
        }
    )

    with pytest.raises(ClientError, match="placeholder permalink"):
        client._resolve_wordpress_permalink(27234)


def test_missing_link_raises_instead_of_writing_an_empty_url():
    client, _ = _client({"id": 27234, "status": "publish", "slug": "x", "link": ""})

    with pytest.raises(ClientError, match="returned no link"):
        client._resolve_wordpress_permalink(27234)


def test_non_object_read_back_raises():
    client, _ = _client([{"id": 27234}])

    with pytest.raises(ClientError, match="read back as list"):
        client._resolve_wordpress_permalink(27234)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://adamtheautomator.com/?p=27234", True),
        ("https://adamtheautomator.com/", True),
        ("https://adamtheautomator.com/recall-outlook-email/", False),
        ("https://adamtheautomator.com/2026/09/post/", False),
    ],
)
def test_placeholder_permalink_detection(url, expected):
    assert AtaBlogClient._is_placeholder_permalink(url) is expected
