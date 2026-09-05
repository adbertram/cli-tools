"""Regression tests for the Notion Publish Date written after a WordPress publish.

Defect: publish_article wrote Notion Status and Published URL but never wrote
Publish Date, so the property stayed null forever while unpublish_article kept
clearing it. These tests pin the Publish Date write for every WordPress status
the publish path can produce (draft, publish, future).

Hermetic: every collaborator is stubbed, page IDs are randomised per run, and
the featured image lives in pytest's per-test tmp_path.
"""

from __future__ import annotations

import json
import secrets
import subprocess

import pytest

from ata_blog_cli.client import AtaBlogClient, ClientError
from ata_blog_cli.utils import images as images_module


# Live-schema property types for the properties this path writes. Mirrors
# `notion database schema 2a317112-d9c8-42ee-a4d4-a2b8a5a20818`.
_SCHEMA_PROPERTY_TYPES = {
    "Status": "status",
    "Published URL": "url",
    "Publish Date": "date",
}

_WORDPRESS_MEDIA_ID = 99001


def _random_page_id() -> str:
    """Return a per-run 32-hex Notion page ID so parallel runs cannot collide."""
    return secrets.token_hex(16)


def _completed(args, payload) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")


class _PublishHarness:
    """Stubbed publish_article collaborators plus recorded notion/wordpress calls."""

    def __init__(self, wordpress_post, read_back_post=None):
        self.wordpress_post = wordpress_post
        # publish_article never trusts the create response's `link`; it
        # re-reads the committed post to resolve its real permalink. Tests
        # that do not care about the permalink pass no read-back post and get
        # the create response echoed back.
        self.read_back_post = (
            wordpress_post if read_back_post is None else read_back_post
        )
        self.notion_calls: list[list[str]] = []
        self.wordpress_calls: list[list[str]] = []

    def build_client(self) -> AtaBlogClient:
        client = object.__new__(AtaBlogClient)
        client._property_types_cache = dict(_SCHEMA_PROPERTY_TYPES)
        # These tests pin the classic WordPress leg's Notion contract only.
        # publish_article dual-publishes whenever the P05/P13 handoff files
        # exist on the machine, so without this the harness would be routed
        # into the static transaction and would assert nothing about
        # WordPress. Mirrors test_static_publisher.py's dual-publish tests,
        # which stub the same gate. Dual-publish behavior is unchanged.
        client._static_cutover_active = lambda: False

        client.get_article = lambda page_id: {
            "Title": "Power Automate Document Intake Pipeline",
            "Keywords": "power automate document intake",
            "Category": "IT Ops",
            "Tags": "Power Automate",
            "Excerpt": "Build a document intake pipeline with Power Automate.",
            "Schema Type": "TechArticle",
        }
        client.get_article_markdown = lambda page_id: "# Body\n\nReal content.\n"
        client.check_duplicate_post = lambda slug: False
        client.resolve_category_by_name = lambda name: 5403
        client.resolve_tags_by_names = lambda names: [11, 12]
        client.find_next_schedule_slot = lambda: "2026-07-28T09:00:00"
        client.clear_schedule_reservation = lambda: None
        client._run_notion = self._fake_run_notion
        client._run_wordpress = self._fake_run_wordpress
        return client

    def _fake_run_notion(self, args, timeout=60):
        self.notion_calls.append(list(args))
        return _completed(args, {"ok": True})

    def _fake_run_wordpress(self, args, timeout=60):
        self.wordpress_calls.append(list(args))
        if args[:2] == ["posts", "create"]:
            return _completed(args, self.wordpress_post)
        if args[:2] == ["posts", "update"]:
            return _completed(
                args,
                {**self.wordpress_post, "featured_media": _WORDPRESS_MEDIA_ID},
            )
        if args[:2] == ["posts", "get"]:
            return _completed(args, self.read_back_post)
        raise AssertionError(f"Unexpected wordpress call: {args}")

    def notion_update_properties(self) -> dict:
        """Return the --properties JSON from the recorded page update call."""
        updates = [
            call
            for call in self.notion_calls
            if call[:3] == ["database", "page", "update"]
        ]
        assert len(updates) == 1, f"Expected one page update, got {updates}"
        args = updates[0]
        assert "--properties" in args, f"No --properties in notion call: {args}"
        return json.loads(args[args.index("--properties") + 1])

    def notion_update_status(self) -> str:
        args = next(
            call
            for call in self.notion_calls
            if call[:3] == ["database", "page", "update"]
        )
        return args[args.index("--status") + 1]


@pytest.fixture
def featured_image(tmp_path):
    path = tmp_path / "featured_image.png"
    path.write_bytes(b"png-bytes")
    return str(path)


@pytest.fixture(autouse=True)
def stub_image_utils(monkeypatch):
    """Neutralise the WordPress media upload and inline image processing."""
    monkeypatch.setattr(
        images_module,
        "upload_to_wordpress",
        lambda image_path: {
            "id": _WORDPRESS_MEDIA_ID,
            "source_url": "https://adamtheautomator.com/img.webp",
        },
    )
    monkeypatch.setattr(
        images_module,
        "process_images_for_wordpress",
        lambda markdown_content, article_slug, verbose=False: markdown_content,
    )


_SLUG = "power-automate-document-intake-pipeline"
# A live post's permalink comes back from the read-back, and Permalink Manager
# makes it differ from the wp/v2 slug (post 9234: slug
# `recall-email-in-outlook`, permalink `/recall-outlook-email/`).
_LIVE_PERMALINK = "https://adamtheautomator.com/power-automate-intake/"
_DERIVED_PERMALINK = f"https://adamtheautomator.com/{_SLUG}/"


@pytest.mark.parametrize(
    "status,auto_schedule,date,wordpress_status,wordpress_date,read_back_link,expected_url",
    [
        (
            "draft",
            False,
            None,
            "draft",
            "2026-07-28T14:31:02",
            "https://adamtheautomator.com/?p=27165",
            _DERIVED_PERMALINK,
        ),
        (
            "publish",
            False,
            None,
            "publish",
            "2026-07-28T14:31:02",
            _LIVE_PERMALINK,
            _LIVE_PERMALINK,
        ),
        (
            None,
            True,
            None,
            "future",
            "2026-07-28T09:00:00",
            "https://adamtheautomator.com/?p=27165",
            _DERIVED_PERMALINK,
        ),
        (
            None,
            False,
            "2026-08-04T09:00:00",
            "future",
            "2026-08-04T09:00:00",
            "https://adamtheautomator.com/?p=27165",
            _DERIVED_PERMALINK,
        ),
    ],
    ids=["draft", "publish", "auto-schedule", "explicit-date"],
)
def test_publish_writes_notion_publish_date_for_every_status(
    featured_image,
    status,
    auto_schedule,
    date,
    wordpress_status,
    wordpress_date,
    read_back_link,
    expected_url,
):
    """Every successful publish records the effective date and a real permalink.

    The create response always carries WordPress's slugless `?p=<id>`
    placeholder here, which is exactly what used to be stored verbatim in
    Notion. No status may store it now.
    """
    page_id = _random_page_id()
    harness = _PublishHarness(
        {
            "id": 27165,
            "status": wordpress_status,
            "date": wordpress_date,
            "link": "https://adamtheautomator.com/?p=27165",
        },
        read_back_post={
            "id": 27165,
            "status": wordpress_status,
            "slug": _SLUG,
            "link": read_back_link,
        },
    )
    client = harness.build_client()

    result = client.publish_article(
        page_id,
        status=status or "draft",
        slug=_SLUG,
        date=date,
        auto_schedule=auto_schedule,
        check_duplicates=False,
        featured_image=featured_image,
    )

    assert result["status"] == wordpress_status
    assert result["wordpress_url"] == expected_url
    assert "?p=" not in result["wordpress_url"]
    assert harness.notion_update_status() == "Status:Published"
    assert harness.notion_update_properties() == {
        "Published URL": {"url": expected_url},
        "Publish Date": {"date": {"start": wordpress_date}},
    }


def test_publish_refuses_placeholder_permalink_for_a_live_post(featured_image):
    """A live post that still reports ?p=<id> is unresolvable, not storable."""
    harness = _PublishHarness(
        {
            "id": 27165,
            "status": "publish",
            "date": "2026-07-28T14:31:02",
            "link": "https://adamtheautomator.com/?p=27165",
        },
        read_back_post={
            "id": 27165,
            "status": "publish",
            "slug": _SLUG,
            "link": "https://adamtheautomator.com/?p=27165",
        },
    )
    client = harness.build_client()

    with pytest.raises(ClientError, match="placeholder permalink"):
        client.publish_article(
            _random_page_id(),
            status="publish",
            slug=_SLUG,
            check_duplicates=False,
            featured_image=featured_image,
        )

    assert not [
        call
        for call in harness.notion_calls
        if call[:3] == ["database", "page", "update"]
    ]


def test_publish_refuses_a_slugless_unpublished_post(featured_image):
    """A pending post with neither permalink nor slug cannot be resolved."""
    harness = _PublishHarness(
        {
            "id": 27165,
            "status": "future",
            "date": "2026-08-04T09:00:00",
            "link": "https://adamtheautomator.com/?p=27165",
        },
        read_back_post={
            "id": 27165,
            "status": "future",
            "slug": "",
            "link": "https://adamtheautomator.com/?p=27165",
        },
    )
    client = harness.build_client()

    with pytest.raises(ClientError, match="neither a permalink nor a slug"):
        client.publish_article(
            _random_page_id(),
            status="publish",
            slug=_SLUG,
            date="2026-08-04T09:00:00",
            check_duplicates=False,
            featured_image=featured_image,
        )


def test_publish_fails_fast_when_wordpress_returns_no_date(featured_image):
    """A missing WordPress date must raise, never silently skip Publish Date."""
    harness = _PublishHarness(
        {
            "id": 27165,
            "status": "publish",
            "date": None,
            "link": "https://adamtheautomator.com/?p=27165",
        }
    )
    client = harness.build_client()

    with pytest.raises(ClientError, match="returned no date"):
        client.publish_article(
            _random_page_id(),
            status="publish",
            slug="power-automate-document-intake-pipeline",
            check_duplicates=False,
            featured_image=featured_image,
        )

    assert not [
        call
        for call in harness.notion_calls
        if call[:3] == ["database", "page", "update"]
    ]


def test_publish_fails_fast_when_wordpress_returns_no_link(featured_image):
    """A missing WordPress link must raise instead of clearing Published URL."""
    harness = _PublishHarness(
        {
            "id": 27165,
            "status": "publish",
            "date": "2026-07-28T14:31:02",
            "link": None,
        }
    )
    client = harness.build_client()

    with pytest.raises(ClientError, match="returned no link"):
        client.publish_article(
            _random_page_id(),
            status="publish",
            slug="power-automate-document-intake-pipeline",
            check_duplicates=False,
            featured_image=featured_image,
        )


def test_publish_date_is_cleared_by_the_unpublish_artifact_fields():
    """The set/clear pair must stay symmetric across publish and unpublish."""
    assert "Publish Date" in AtaBlogClient.UNPUBLISH_ARTIFACT_FIELDS
    assert "Published URL" in AtaBlogClient.UNPUBLISH_ARTIFACT_FIELDS


def test_notion_cli_has_no_date_flag_so_properties_json_is_required():
    """Document why the publish path routes through update_article.

    `notion database page update` exposes --status/--select/--text/--checkbox/
    --number/--url but no --date, so a date property can only be written via the
    raw --properties JSON that _build_notion_property builds from the live
    schema. This test pins the payload shape that contract produces.
    """
    client = object.__new__(AtaBlogClient)
    client._property_types_cache = dict(_SCHEMA_PROPERTY_TYPES)

    assert client._build_notion_property(
        "Publish Date", "2026-07-28T09:00:00"
    ) == {"date": {"start": "2026-07-28T09:00:00"}}
    assert client._build_notion_property("Publish Date", "") == {"date": None}
