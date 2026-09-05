"""Regression tests for per-post R2 mirroring of WordPress media derivatives.

Defect: the static publisher's inline-media mirroring copied only the exact URL
a post body referenced. WordPress generates a family of resized derivatives per
attachment (thumbnail, medium, medium_large, large, 1536x1536, 2048x2048, plus
this theme's featured-small/featured-large) and the built static site emits them
in `srcset`, so none of them reached R2. The 2026-09-05 media parity audit
measured 112 missing derivative keys across 15 attachments created since
2026-08-26, 7 of which were missing even their base file.

These tests pin that every referenced attachment now mirrors its base file plus
every variant declared in `media_details.sizes`, at the identical
`wp-content/uploads/...` key, and that a key containing a literal `..` is
uploaded through the R2 S3-compatible transport because Cloudflare's REST edge
WAF answers those paths with a 403 before R2 sees them.

Hermetic: no network, no Cloudflare calls; every collaborator is stubbed.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from ata_blog_cli.client import AtaBlogClient, ClientError


_ORIGIN = "https://adamtheautomator.com"
_UPLOADS = f"{_ORIGIN}/wp-content/uploads"

_HUB_SPOKE_RECORD = {
    "id": 27232,
    "source_url": f"{_UPLOADS}/2026/08/hub-spoke-topology.png",
    "media_details": {
        "file": "2026/08/hub-spoke-topology.png",
        "sizes": {
            "thumbnail": {
                "source_url": f"{_UPLOADS}/2026/08/hub-spoke-topology-150x150.png"
            },
            "medium": {
                "source_url": f"{_UPLOADS}/2026/08/hub-spoke-topology-300x167.png"
            },
            "featured-large": {
                "source_url": f"{_UPLOADS}/2026/08/hub-spoke-topology-1200x675.png"
            },
        },
    },
}

_HUB_SPOKE_KEYS = [
    "wp-content/uploads/2026/08/hub-spoke-topology-1200x675.png",
    "wp-content/uploads/2026/08/hub-spoke-topology-150x150.png",
    "wp-content/uploads/2026/08/hub-spoke-topology-300x167.png",
    "wp-content/uploads/2026/08/hub-spoke-topology.png",
]

# An attachment WordPress registered with no derivatives at all serializes its
# empty size map as a PHP array, which reaches JSON as [].
_NO_SIZES_RECORD = {
    "id": 27237,
    "source_url": f"{_UPLOADS}/2026/09/featured_image.webp",
    "media_details": {"file": "2026/09/featured_image.webp", "sizes": []},
}

# Cloudflare's REST edge blocks any object path containing a literal '..'.
_DOTDOT_RECORD = {
    "id": 27299,
    "source_url": f"{_UPLOADS}/2026/09/az..cli-output.png",
    "media_details": {
        "file": "2026/09/az..cli-output.png",
        "sizes": {
            "thumbnail": {
                "source_url": f"{_UPLOADS}/2026/09/az..cli-output-150x150.png"
            }
        },
    },
}


class _MediaHarness:
    """Stubbed origin reads and R2 calls for the inline mirroring path."""

    def __init__(self, records, *, present_keys=()):
        self.records = list(records)
        self.present_keys = set(present_keys)
        self.searches: list[str] = []
        self.fetched_urls: list[str] = []
        self.r2_calls: list[list[str]] = []

    def build_client(self) -> AtaBlogClient:
        client = object.__new__(AtaBlogClient)
        client._fetch_static_origin_bytes = self._fake_fetch
        client._existing_static_inline_media_key = self._fake_existing
        client._run_checked_command = self._fake_r2
        return client

    def _fake_fetch(self, url, *, attempts=5):
        if "/wp-json/wp/v2/media" in url:
            search = url.split("search=", 1)[1].split("&", 1)[0]
            self.searches.append(search)
            matched = [
                record
                for record in self.records
                if search in json.dumps(record)
            ]
            return json.dumps(matched).encode("utf-8"), "application/json"
        self.fetched_urls.append(url)
        return b"image-bytes", "image/png; charset=binary"

    def _fake_existing(self, key):
        if key in self.present_keys:
            return {"key": key, "size": len(b"image-bytes")}
        return None

    def _fake_r2(self, command, *, cwd=None, timeout, label):
        self.r2_calls.append(list(command))
        key = command[5]
        # Uploading makes the key present, so the post-upload verify passes.
        self.present_keys.add(key)
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps({"key": key}), stderr=""
        )

    def uploaded_keys(self) -> list[str]:
        return [call[5] for call in self.r2_calls]

    def put_subcommands(self) -> list[str]:
        return [call[3] for call in self.r2_calls]


def test_reference_expands_to_every_declared_size_variant():
    """A base-file reference must enumerate the whole attachment key family."""
    harness = _MediaHarness([_HUB_SPOKE_RECORD])
    client = harness.build_client()

    keys = client._wordpress_media_keys_for_reference(
        "wp-content/uploads/2026/08/hub-spoke-topology.png"
    )

    assert keys == _HUB_SPOKE_KEYS
    assert harness.searches == ["hub-spoke-topology"]


def test_derivative_reference_resolves_through_its_parent_attachment():
    """A -WxH reference must drop that suffix to find its owning attachment."""
    harness = _MediaHarness([_HUB_SPOKE_RECORD])
    client = harness.build_client()

    keys = client._wordpress_media_keys_for_reference(
        "wp-content/uploads/2026/08/hub-spoke-topology-300x167.png"
    )

    assert keys == _HUB_SPOKE_KEYS
    assert harness.searches == ["hub-spoke-topology"]


def test_attachment_without_derivatives_yields_only_its_base_key():
    """An empty PHP sizes array must not be mistaken for shape drift."""
    harness = _MediaHarness([_NO_SIZES_RECORD])
    client = harness.build_client()

    assert client._wordpress_media_keys_for_reference(
        "wp-content/uploads/2026/09/featured_image.webp"
    ) == ["wp-content/uploads/2026/09/featured_image.webp"]


def test_unowned_reference_fails_loudly():
    """A referenced key no attachment publishes must raise, not mirror alone."""
    harness = _MediaHarness([_HUB_SPOKE_RECORD])
    client = harness.build_client()

    with pytest.raises(ClientError, match="No WordPress media attachment publishes"):
        client._wordpress_media_keys_for_reference(
            "wp-content/uploads/2026/08/hub-spoke-topology-missing.png"
        )


def test_ambiguous_reference_fails_loudly():
    """Two attachments claiming one key is unresolvable, never a silent pick."""
    duplicate = {**_HUB_SPOKE_RECORD, "id": 27233}
    harness = _MediaHarness([_HUB_SPOKE_RECORD, duplicate])
    client = harness.build_client()

    with pytest.raises(ClientError, match="published by 2 WordPress media attachments"):
        client._wordpress_media_keys_for_reference(
            "wp-content/uploads/2026/08/hub-spoke-topology.png"
        )


def test_unrelated_search_hits_never_break_the_lookup():
    """A malformed unrelated record in the search result must be ignored."""
    harness = _MediaHarness([{"id": 1, "slug": "hub-spoke-topology"}, _HUB_SPOKE_RECORD])
    client = harness.build_client()

    assert (
        client._wordpress_media_keys_for_reference(
            "wp-content/uploads/2026/08/hub-spoke-topology.png"
        )
        == _HUB_SPOKE_KEYS
    )


def test_inline_mirroring_uploads_every_variant_once():
    """Every variant is mirrored, and two references share one key family."""
    harness = _MediaHarness([_HUB_SPOKE_RECORD])
    client = harness.build_client()

    markdown = (
        f"![diagram]({_UPLOADS}/2026/08/hub-spoke-topology.png)\n\n"
        f"![thumb]({_UPLOADS}/2026/08/hub-spoke-topology-300x167.png)\n"
    )
    receipts = client._upload_static_inline_media(markdown)

    assert sorted(receipt["key"] for receipt in receipts) == _HUB_SPOKE_KEYS
    assert sorted(harness.uploaded_keys()) == _HUB_SPOKE_KEYS
    assert len(harness.uploaded_keys()) == len(set(harness.uploaded_keys()))
    assert all(receipt["recovered"] is False for receipt in receipts)
    assert sorted(harness.fetched_urls) == [f"{_ORIGIN}/{key}" for key in _HUB_SPOKE_KEYS]


def test_inline_mirroring_skips_variants_already_in_the_bucket():
    """Mirroring is idempotent per key, so a resumed run re-uploads nothing."""
    harness = _MediaHarness([_HUB_SPOKE_RECORD], present_keys=_HUB_SPOKE_KEYS)
    client = harness.build_client()

    receipts = client._upload_static_inline_media(
        f"![diagram]({_UPLOADS}/2026/08/hub-spoke-topology.png)\n"
    )

    assert sorted(receipt["key"] for receipt in receipts) == _HUB_SPOKE_KEYS
    assert all(receipt["recovered"] is True for receipt in receipts)
    assert harness.r2_calls == []
    assert harness.fetched_urls == []


def test_dotdot_keys_upload_through_the_s3_transport():
    """Cloudflare's REST edge 403s '..' paths, so those keys must use put-s3."""
    harness = _MediaHarness([_DOTDOT_RECORD])
    client = harness.build_client()

    receipts = client._upload_static_inline_media(
        f"![shot]({_UPLOADS}/2026/09/az..cli-output.png)\n"
    )

    assert sorted(receipt["key"] for receipt in receipts) == [
        "wp-content/uploads/2026/09/az..cli-output-150x150.png",
        "wp-content/uploads/2026/09/az..cli-output.png",
    ]
    assert harness.put_subcommands() == ["put-s3", "put-s3"]


def test_put_subcommand_selection_is_keyed_on_the_dotdot_substring():
    assert (
        AtaBlogClient._r2_put_subcommand("wp-content/uploads/2026/09/a..b.png")
        == "put-s3"
    )
    assert (
        AtaBlogClient._r2_put_subcommand("wp-content/uploads/2026/09/ab.png") == "put"
    )
