"""Hermetic contracts for removing a post from the static site.

Unpublish reuses the publisher's own build, preview deployment, and production
promotion machinery, so these tests run against the same fixture and the same
Cloudflare Pages command seam the publisher tests use.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import ata_blog_cli.client as client_module
from ata_blog_cli.client import AtaBlogClient, ClientError, _static_corpus_sha256
from test_static_publisher import (  # noqa: F401 - `publisher` is a fixture
    PAGE_ID,
    PRIOR_PRODUCTION_DEPLOYMENT_ID,
    PRODUCTION_DEPLOYMENT_ID,
    _arm_promotion,
    _publish,
    publisher,
)


def _published_post(client) -> Path:
    """Publish the fixture post to production and return its corpus file."""
    result = _publish(client, status="publish")
    assert result["promoted"] is True
    post = AtaBlogClient._find_static_post_by_notion_page_id(PAGE_ID)
    assert post is not None
    return post


def _unpublish(client, post, status="Draft"):
    return client._unpublish_static_transaction(
        page_id=PAGE_ID, static_post=post, status=status
    )


def test_unpublish_removes_post_and_promotes_the_rebuilt_site(publisher):
    client, article, _markdown, _image, _manifest, counters, _token = publisher
    calls, rollbacks = _arm_promotion(client)
    post = _published_post(client)
    original = post.read_bytes()

    result = _unpublish(client, post)

    assert not post.exists()
    # One build, one preview, and one production deployment beyond the publish.
    assert counters["build"] == 2
    assert counters["deploy"] == 2
    assert calls["promotion_create"] == 2
    assert rollbacks == []
    assert result["promotion_id"] == PRODUCTION_DEPLOYMENT_ID
    # The removed record is kept, byte for byte, outside the corpus.
    assert Path(result["backup_path"]).read_bytes() == original
    # Notion was reset through the data-driven artifact fields.
    assert article["Status"] == "Draft"
    assert article["Published URL"] == ""
    assert article["Promoted"] == "false"


def test_unpublish_builds_the_corpus_without_the_post(publisher):
    client, _article, _markdown, _image, _manifest, _counters, _token = publisher
    _arm_promotion(client)
    post = _published_post(client)
    built = []
    original_build = client._run_static_build

    def build(release_ref, corpus_sha256):
        built.append((release_ref, corpus_sha256, post.exists()))
        return original_build(release_ref, corpus_sha256)

    client._run_static_build = build

    _unpublish(client, post)

    assert built == [(None, _static_corpus_sha256(), False)]


def test_unpublish_retires_the_completed_publish_so_republish_is_real(publisher):
    client, _article, _markdown, _image, _manifest, counters, _token = publisher
    _arm_promotion(client)
    post = _published_post(client)

    result = _unpublish(client, post)

    transaction_root = client._publisher_runtime_root() / "transactions"
    assert list(transaction_root.glob("*.journal.json")) == []
    assert any(path.endswith(".journal.json") for path in result["retired_transactions"])
    assert all(Path(path).is_file() for path in result["retired_transactions"])

    republished = _publish(client, status="publish", force=True)

    assert republished["replayed"] is False
    assert counters["build"] == 3
    assert AtaBlogClient._find_static_post_by_notion_page_id(PAGE_ID) is not None


def test_build_failure_restores_the_exact_corpus_record(publisher):
    client, article, _markdown, _image, _manifest, _counters, _token = publisher
    calls, rollbacks = _arm_promotion(client)
    post = _published_post(client)
    original = post.read_bytes()
    corpus_before = _static_corpus_sha256()

    def failing_build(_release_ref, _corpus_sha256):
        raise ClientError("Static site build failed (exit 1): contract violation")

    client._run_static_build = failing_build

    with pytest.raises(ClientError, match="Static unpublish failed during build"):
        _unpublish(client, post)

    assert post.read_bytes() == original
    assert _static_corpus_sha256() == corpus_before
    assert calls["promotion_create"] == 1
    assert rollbacks == []
    assert article["Status"] == "Published"


def test_notion_failure_rolls_production_back_and_restores_the_post(publisher):
    client, _article, _markdown, _image, _manifest, _counters, _token = publisher
    _calls, rollbacks = _arm_promotion(client)
    post = _published_post(client)
    original = post.read_bytes()

    def failing_update(_page_id, *, status, properties):
        raise ClientError("notion command failed (exit 1): rate limited")

    client.update_article = failing_update

    with pytest.raises(ClientError, match="Static unpublish failed during Notion update"):
        _unpublish(client, post)

    # Production returns to the deployment that was live before the unpublish,
    # which is the one the publish promoted.
    assert rollbacks == [PRODUCTION_DEPLOYMENT_ID]
    assert PRIOR_PRODUCTION_DEPLOYMENT_ID not in rollbacks
    assert post.read_bytes() == original
    transaction_root = client._publisher_runtime_root() / "transactions"
    assert len(list(transaction_root.glob("*.journal.json"))) == 1


def test_unpublish_refuses_while_a_publish_transaction_is_active(publisher):
    client, _article, _markdown, _image, _manifest, _counters, _token = publisher
    _arm_promotion(client)
    post = _published_post(client)
    journal_path = next(
        (client._publisher_runtime_root() / "transactions").glob("*.journal.json")
    )
    journal = json.loads(journal_path.read_text())
    journal["state"] = "deployed"
    journal_path.write_text(json.dumps(journal))

    with pytest.raises(ClientError, match="publisher transaction is still active"):
        _unpublish(client, post)

    assert post.exists()


def test_unpublish_requires_the_build_token(publisher):
    client, _article, _markdown, _image, _manifest, _counters, build_token = publisher
    _arm_promotion(client)
    post = _published_post(client)
    build_token.unlink()

    with pytest.raises(ClientError, match="build-lock acquisition"):
        _unpublish(client, post)

    assert post.exists()
    assert client_module.STATIC_SITE_ROOT in post.parents
