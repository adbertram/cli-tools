"""Hermetic contracts for the journaled static-site publisher."""

from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import threading
import time
import zlib
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import ata_blog_cli.client as client_module
from ata_blog_cli.client import (
    AtaBlogClient,
    ClientError,
    _artifact_sha256,
    _atomic_write_json,
    _corpus_wall_clock,
    _image_pixel_size,
)
from ata_blog_cli.commands import notion_page


# The publisher measures the featured image it stages, so the fixture image has
# to be a real image file rather than a placeholder byte string. These are the
# fixture's dimensions and they are what the staged frontmatter must carry.
FIXTURE_IMAGE_WIDTH = 640
FIXTURE_IMAGE_HEIGHT = 360


def _png_bytes(width: int, height: int) -> bytes:
    """Return a real, decodable 8-bit RGB PNG of the given pixel size."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x00" * (width * 3) for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 1))
        + chunk(b"IEND", b"")
    )


PAGE_ID = "31b5d9c85b2b814298a0ea98cb7d78f4"
PRIOR_DEPLOYMENT_ID = "11111111-1111-4111-8111-111111111111"
PREVIEW_DEPLOYMENT_ID = "22222222-2222-4222-8222-222222222222"
PREVIEW_DEPLOYMENT_URL = "https://22222222.example.pages.dev"
# The real build's corpus-hashing contract, used only by
# test_staged_corpus_hash_matches_release_manifest_hash_corpus to cross-check
# Python's _static_corpus_sha256() against the actual JS hashCorpus()
# implementation. release_manifest.mjs imports the site's shared route/feed
# modules, so both have to be staged for the import to resolve.
REAL_RELEASE_MANIFEST_CONTRACT = Path(
    "/Users/adam/Dropbox/GitRepos/Agents/ATABlogger/static-site/scripts/"
    "release_manifest.mjs"
)
REAL_RELEASE_MANIFEST_CONTRACT_LIB = Path(
    "/Users/adam/Dropbox/GitRepos/Agents/ATABlogger/static-site/src/lib"
)


def _preview_deployment_payload(
    *,
    idempotency_key: str,
    source_revision: str,
    deployment_id: str = PREVIEW_DEPLOYMENT_ID,
    include_files: bool = True,
    release_id: str = "ata-static-testrelease0000",
):
    payload = {
        "id": deployment_id,
        "short_id": deployment_id[:8],
        "url": f"https://{deployment_id[:8]}.example.pages.dev",
        "environment": "preview",
        "latest_stage": {"name": "deploy", "status": "success"},
        "deployment_trigger": {
            "metadata": {
                "branch": f"publisher-{idempotency_key[:16]}-{release_id[-8:]}",
                "commit_hash": source_revision[:40],
                "commit_message": f"ata-blog publisher {idempotency_key}",
            },
        },
    }
    if include_files:
        payload["files"] = {
            "/index.html": hashlib.md5(b"accepted build").hexdigest(),
            "/release-manifest.json": "a" * 32,
        }
    return payload


class _Config:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    def get_profile_data_dir(self) -> Path:
        return self.data_dir



@pytest.fixture
def publisher(tmp_path, monkeypatch):
    repository = tmp_path / "ATABlogger"
    site = repository / "static-site"
    dist = site / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("accepted build")
    (site / "src" / "data" / "posts").mkdir(parents=True)
    for relative_path, content in {
        "src/data/pages/about.md": "about page\n",
        "src/partials/pages/about.html": "<p>about</p>\n",
        "src/data/authors.json": "{}\n",
        "src/data/terms.json": json.dumps(
            {
                "categories": [{"id": 11, "name": "Automation", "slug": "automation"}],
                "tags": [
                    {"id": 21, "name": "Cloudflare", "slug": "cloudflare"},
                    {"id": 7, "name": "Sponsored", "slug": "sponsored"},
                ],
            }
        )
        + "\n",
        "src/data/redirects.json": "[]\n",
        "src/data/home_featured.json": "[]\n",
        "src/data/zero_post_authors.json": "[]\n",
        "src/data/page_seo.json": json.dumps({"pages": {}}) + "\n",
        "src/data/archive_seo.json": json.dumps({"archives": {}}) + "\n",
        # src/lib/feed.js imports this at module load, so the release manifest
        # cannot even be parsed without it.
        "src/data/post_guids.json": json.dumps({"byWpId": {}}) + "\n",
        # src/lib/date-archives.js imports this at module load to prove a post's
        # archive day matches the publish instant its own page advertises.
        "src/data/post_seo.json": json.dumps({"posts": {}}) + "\n",
    }.items():
        corpus_path = site / relative_path
        corpus_path.parent.mkdir(parents=True, exist_ok=True)
        corpus_path.write_text(content)

    # The client's release-manifest contract is now a minimal shape check
    # (schema_version/release_id/contract_hash) with no P05/P13 handoff, Gate
    # A, scanner, or worker-proof binding, so the fixture manifest only needs
    # to satisfy that shape.
    manifest_path = dist / "release-manifest.json"
    manifest = {
        "schema_version": "ata-static-release/v2",
        "inputs": {"corpus_sha256": "0" * 64},
    }
    contract_hash = _artifact_sha256(manifest)
    manifest["release_id"] = f"ata-static-{contract_hash[:24]}"
    manifest["contract_hash"] = contract_hash
    manifest_path.write_text(json.dumps(manifest))

    profile_dir = tmp_path / "profile"
    # _static_build_lock now computes the build-token path directly from
    # _publisher_runtime_root() (profile-relative), not a fixed repo path.
    build_token = profile_dir / "static-publisher" / "build-token.json"
    build_token.parent.mkdir(parents=True)
    build_token.write_text(
        json.dumps(
            {
                "holder": "root-coordinator",
                "released_at": None,
                "release_id": manifest["release_id"],
                "contract_hash": manifest["contract_hash"],
                "build_sha256": "c" * 64,
            }
        )
    )

    monkeypatch.setattr(client_module, "STATIC_REPOSITORY_ROOT", repository)
    monkeypatch.setattr(client_module, "STATIC_SITE_ROOT", site)
    monkeypatch.setattr(client_module, "STATIC_RELEASE_MANIFEST", manifest_path)

    image = tmp_path / "featured.png"
    image.write_bytes(_png_bytes(FIXTURE_IMAGE_WIDTH, FIXTURE_IMAGE_HEIGHT))
    article = {
        "Title": "Journaled Static Publisher",
        "Type": "Standard",
        "Slug": None,
        "Keywords": "static publisher",
        "Category": "Automation",
        "Tags": "Cloudflare",
        "Excerpt": "A deterministic publisher transaction.",
        "Status": "Draft",
        "Published URL": None,
        "Publish Date": None,
    }
    markdown = "# Journaled Static Publisher\n\nDeterministic body.\n"
    counters = {name: 0 for name in ("media", "build", "deploy", "notion")}

    client = object.__new__(AtaBlogClient)
    client.config = _Config(profile_dir)
    # Occupied schedule slots are the Notion pages in Status "Scheduled". The
    # recording stub stands in for that one query and the guard below fails any
    # other Notion call, so no test here can reach the real notion CLI.
    client.scheduled_pages = []
    client.list_calls = []
    client.update_calls = []

    def list_articles(status=None, limit=100, filters=None):
        client.list_calls.append({"status": status, "limit": limit, "filters": filters})
        return list(client.scheduled_pages)

    def run_notion(args, timeout=60):
        pytest.fail(f"unexpected notion CLI call: {args}")

    client.list_articles = list_articles
    client._run_notion = run_notion
    client.get_article = lambda _page_id: dict(article)
    client.get_article_markdown = lambda _page_id: markdown
    client._resolve_featured_image = lambda _page_id, _supplied: image

    def media(stage):
        counters["media"] += 1
        return {"receipt": {"key": stage["object_key"]}, "image_url": stage["image_url"]}

    def build(_release_ref, _staged_corpus_sha256):
        counters["build"] += 1
        assert _release_ref is None or _release_ref == {
            "release_id": manifest["release_id"],
            "contract_hash": manifest["contract_hash"],
        }
        manifest["inputs"]["corpus_sha256"] = _staged_corpus_sha256
        manifest_body = {
            key: value
            for key, value in manifest.items()
            if key not in {"release_id", "contract_hash"}
        }
        contract_hash = _artifact_sha256(manifest_body)
        manifest["release_id"] = f"ata-static-{contract_hash[:24]}"
        manifest["contract_hash"] = contract_hash
        manifest_path.write_text(json.dumps(manifest))
        return {"build_sha256": "d" * 64, "manifest": manifest}

    def deploy(_key, _revision, _release_id="ata-static-testrelease0000"):
        counters["deploy"] += 1
        metadata = _preview_deployment_payload(
            idempotency_key=_key,
            source_revision=_revision,
            release_id=_release_id,
        )
        return {
            "deployment_id": PREVIEW_DEPLOYMENT_ID,
            "deployment_url": PREVIEW_DEPLOYMENT_URL,
            "deployment": metadata,
            "deployment_sha256": _artifact_sha256(metadata),
        }

    def update(_page_id, *, status, properties):
        counters["notion"] += 1
        client.update_calls.append((_page_id, status, dict(properties)))
        article["Status"] = status
        article.update(properties)
        if status == "Scheduled":
            # Read-after-write: the page the scheduler just wrote is what the
            # next Scheduled query returns.
            client.scheduled_pages.append(_scheduled_page(_page_id, properties["Publish Date"]))
        return {"ok": True}

    client._upload_static_media = media
    client._run_static_build = build
    client._deploy_static_preview = deploy
    client.update_article = update
    return client, article, markdown, image, manifest, counters, build_token


def _scheduled_page(page_id, publish_date):
    """Return one row of the Notion Status=Scheduled query."""
    return {
        "id": page_id,
        "Title": "Scheduled post",
        "Status": "Scheduled",
        "Publish Date": publish_date,
    }


def _freeze_utc_now(monkeypatch, utc_now):
    """Pin the client's clock so an auto-picked slot is one exact value."""

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return utc_now.astimezone(tz)

    monkeypatch.setattr(client_module, "datetime", FrozenDatetime)


def _assert_no_publisher_effects(client, counters, corpus_files=()):
    """Scheduling never stages, uploads, builds, deploys, or journals."""
    assert counters["media"] == counters["build"] == counters["deploy"] == 0
    transactions = client._publisher_runtime_root() / "transactions"
    assert list(transactions.glob("*.journal.json")) == []
    assert list(transactions.glob("*.runtime.json")) == []
    posts = client_module.STATIC_SITE_ROOT / "src" / "data" / "posts"
    assert sorted(posts.iterdir()) == sorted(corpus_files)


def _assert_nothing_written(client, counters, corpus_files=()):
    """Every rejected schedule request leaves Notion and the publisher untouched."""
    assert client.update_calls == []
    assert counters["notion"] == 0
    _assert_no_publisher_effects(client, counters, corpus_files)


def _publish(client, **kwargs):
    # Journal-mechanics tests target the static leg directly; publish_article
    # routes a schedule request away and otherwise delegates straight to this
    # transaction (covered separately by its own test).
    call_kwargs = {
        "page_id": PAGE_ID,
        "status": "draft",
        "check_duplicates": False,
        "featured_image": "ignored.png",
        "force": False,
    }
    call_kwargs.update(kwargs)
    return client._publish_static_transaction(**call_kwargs)


def _rotate_static_release(manifest, build_token):
    manifest["inputs"]["corpus_sha256"] = "f" * 64
    manifest_body = {
        key: value
        for key, value in manifest.items()
        if key not in {"release_id", "contract_hash"}
    }
    contract_hash = _artifact_sha256(manifest_body)
    manifest["release_id"] = f"ata-static-{contract_hash[:24]}"
    manifest["contract_hash"] = contract_hash
    client_module.STATIC_RELEASE_MANIFEST.write_text(json.dumps(manifest))
    token = json.loads(build_token.read_text())
    token.update(
        {
            "release_id": manifest["release_id"],
            "contract_hash": manifest["contract_hash"],
        }
    )
    build_token.write_text(json.dumps(token))


def test_p05_idempotency_encoding_is_exact():
    source_revision = "d" * 64
    expected = hashlib.sha256(f"{PAGE_ID}\n{source_revision}\n".encode()).hexdigest()
    assert AtaBlogClient._publisher_idempotency_key(PAGE_ID, source_revision) == expected


def test_completed_same_revision_replay_has_zero_effects_and_no_build_token(publisher):
    client, _article, _markdown, _image, _manifest, counters, build_token = publisher
    first = _publish(client)
    build_token.unlink()

    replay = _publish(client)

    assert replay["deployment_id"] == first["deployment_id"]
    assert replay["replayed"] is True
    assert replay["invocation_effects"] == {
        "corpus_writes": 0,
        "media_upload_sets": 0,
        "builds": 0,
        "deployments": 0,
        "notion_updates": 0,
    }
    assert counters == {"media": 1, "build": 1, "deploy": 1, "notion": 1}


def test_first_staged_build_binds_post_stage_release_identity(publisher):
    client, _article, _markdown, _image, manifest, _counters, _token = publisher
    pre_stage_release_ref = {
        "release_id": manifest["release_id"],
        "contract_hash": manifest["contract_hash"],
    }

    result = _publish(client)

    paths = client._publisher_paths(PAGE_ID, result["idempotency_key"])
    journal = json.loads(paths["journal"].read_text())
    runtime = json.loads(paths["runtime"].read_text())
    assert journal["release_ref"] == runtime["release_ref"] == result["release_ref"]
    assert journal["release_ref"] != pre_stage_release_ref
    # Once the build lands, _sync_build_token advances the live token to it
    # and runtime["build_token_release_ref"] is persisted to match -- so a
    # later retry's staleness check compares against the real, just-built
    # release, not the snapshot read before this transaction ever staged.
    assert runtime["build_token_release_ref"] == journal["release_ref"]
    assert (
        manifest["inputs"]["corpus_sha256"]
        == journal["artifacts"]["staged_corpus_sha256"]
    )


@pytest.mark.parametrize("crash_after", ["journal", "runtime"])
def test_first_build_binding_crash_keeps_immutable_identity(
    publisher, monkeypatch, crash_after
):
    client, article, markdown, image, _manifest, counters, _token = publisher
    revision = client._source_revision(article, markdown, image)
    key = client._publisher_idempotency_key(PAGE_ID, revision)
    paths = client._publisher_paths(PAGE_ID, key)
    original_write = client_module._atomic_write_json
    crashed = False

    def crash_between_binding_writes(path, payload):
        nonlocal crashed
        original_write(path, payload)
        if crashed:
            return
        release_ref = payload.get("release_ref") if isinstance(payload, dict) else None
        bound = isinstance(release_ref, dict) and release_ref.get("release_id")
        if crash_after == "journal" and path == paths["journal"] and bound:
            effects = payload.get("effects", {})
            artifacts = payload.get("artifacts", {})
            if effects.get("builds") == 0 and artifacts.get("build_sha256") != "0" * 64:
                crashed = True
                raise OSError("injected crash after journal binding")
        if crash_after == "runtime" and path == paths["runtime"] and bound:
            if payload.get("build_sha256"):
                crashed = True
                raise OSError("injected crash after runtime binding")

    monkeypatch.setattr(client_module, "_atomic_write_json", crash_between_binding_writes)
    with pytest.raises(ClientError, match="failed during build"):
        _publish(client)
    monkeypatch.setattr(client_module, "_atomic_write_json", original_write)

    failed = json.loads(paths["journal"].read_text())
    bound_release_ref = failed["release_ref"]
    assert failed["state"] == "failed"
    assert failed["effects"]["builds"] == 0
    assert failed["artifacts"]["build_sha256"] != "0" * 64
    assert bound_release_ref["release_id"]

    result = _publish(client)

    assert result["release_ref"] == bound_release_ref
    assert result["journal_state"] == "completed"
    assert counters["media"] == 1
    assert counters["build"] == 2


def test_active_staged_journal_resumes_with_manifest_corpus_hash(publisher):
    client, article, markdown, image, manifest, counters, _token = publisher
    revision = client._source_revision(article, markdown, image)
    key = client._publisher_idempotency_key(PAGE_ID, revision)
    paths = client._publisher_paths(PAGE_ID, key)
    journal = client._new_publisher_journal(
        page_id=PAGE_ID,
        source_revision=revision,
        article=article,
        manifest=manifest,
        prior_deployment_id=PRIOR_DEPLOYMENT_ID,
    )
    runtime = {
        "schema_version": "ata-static-publisher-runtime/v1",
        "page_id": PAGE_ID,
        "source_revision": revision,
        "idempotency_key": key,
        "slug": "journaled-static-publisher",
        "status": "draft",
        "publish_date": "2026-08-31T12:00:00+00:00",
        "release_ref": journal["release_ref"],
        "failure_stage": None,
        "failure_message": None,
        "rollback_error": None,
    }
    stage = client._stage_static_article(
        page_id=PAGE_ID,
        slug=runtime["slug"],
        article=article,
        markdown_content=markdown,
        image_path=image,
        publish_date=runtime["publish_date"],
        paths=paths,
    )
    corpus_files = [
        candidate
        for root in (
            client_module.STATIC_SITE_ROOT / "src" / "data" / "posts",
            client_module.STATIC_SITE_ROOT / "src" / "data" / "pages",
            client_module.STATIC_SITE_ROOT / "src" / "partials" / "pages",
        )
        for candidate in root.rglob("*")
        if candidate.is_file()
    ]
    corpus_files.extend(
        client_module.STATIC_SITE_ROOT / relative_path
        for relative_path in (
            "src/data/authors.json",
            "src/data/terms.json",
            "src/data/redirects.json",
            "src/data/home_featured.json",
            "src/data/zero_post_authors.json",
            "src/data/post_seo.json",
            "src/data/page_seo.json",
            "src/data/archive_seo.json",
            "src/data/post_guids.json",
        )
    )
    records = sorted(
        "{}\t{}".format(
            path.relative_to(client_module.STATIC_SITE_ROOT).as_posix(),
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in corpus_files
    )
    expected_corpus_sha256 = hashlib.sha256(
        ("\n".join(records) + "\n").encode("utf-8")
    ).hexdigest()
    assert stage["corpus_sha256"] == expected_corpus_sha256
    assert stage["corpus_sha256"] != client_module._tree_sha256(
        client_module.STATIC_SITE_ROOT / "src" / "data" / "posts"
    )
    runtime.update(stage)
    runtime["media"] = {"receipt": {"key": stage["object_key"]}, "image_url": stage["image_url"]}
    journal["artifacts"]["staged_corpus_sha256"] = stage["corpus_sha256"]
    journal["effects"]["corpus_writes"] = 1
    journal["effects"]["media_upload_sets"] = 1
    _atomic_write_json(paths["runtime"], runtime)
    _atomic_write_json(paths["journal"], journal)
    client._transition_publisher_journal(journal, "staged", stage["corpus_sha256"], paths["journal"])

    result = _publish(client)

    assert result["journal_state"] == "completed"
    assert counters["media"] == 0
    assert counters["build"] == counters["deploy"] == counters["notion"] == 1


def test_staged_corpus_hash_matches_release_manifest_hash_corpus(publisher, tmp_path):
    """The staged corpus hash must byte-match the build's own hashCorpus().

    Regression guard for agent-issues#85: the publisher's
    `_static_corpus_sha256` once omitted several data files that
    release_manifest.mjs's `hashCorpus()` includes, so the staged corpus hash
    could never equal the build manifest's `inputs.corpus_sha256` and the
    static leg aborted. The two memberships are duplicated across Python and
    JS, so this test cross-checks the real JS `hashCorpus()` (run through node
    against the hermetic contract copy) instead of re-implementing the Python
    hash a second time -- a duplicate would pass even when both sides drift
    from the build.
    """
    client, article, markdown, image, _manifest, _counters, _token = publisher
    revision = client._source_revision(article, markdown, image)
    key = client._publisher_idempotency_key(PAGE_ID, revision)
    paths = client._publisher_paths(PAGE_ID, key)
    stage = client._stage_static_article(
        page_id=PAGE_ID,
        slug="azure-bicep-vs-arm-templates",
        article=article,
        markdown_content=markdown,
        image_path=image,
        publish_date="2026-09-08T12:00:00+00:00",
        paths=paths,
    )

    contract = client_module.STATIC_SITE_ROOT / "scripts" / "release_manifest.mjs"
    contract.parent.mkdir(parents=True, exist_ok=True)
    contract.write_bytes(REAL_RELEASE_MANIFEST_CONTRACT.read_bytes())
    contract_lib = client_module.STATIC_SITE_ROOT / "src" / "lib"
    contract_lib.mkdir(parents=True, exist_ok=True)
    for module_path in sorted(REAL_RELEASE_MANIFEST_CONTRACT_LIB.glob("*.js")):
        (contract_lib / module_path.name).write_bytes(module_path.read_bytes())
    # hashCorpus() is module-local; re-export it from the hermetic copy so the
    # real membership walk runs unchanged against the staged corpus.
    contract.write_bytes(contract.read_bytes() + b"\nexport { hashCorpus };\n")
    wrapper = tmp_path / "hash_corpus.mjs"
    wrapper.write_text(
        f'import {{ hashCorpus }} from "{contract.as_uri()}";\n'
        "console.log(await hashCorpus());\n"
    )
    result = subprocess.run(["node", str(wrapper)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert stage["corpus_sha256"] == result.stdout.strip()


def test_cli_renders_static_result_fields(monkeypatch):
    class _Client:
        def publish_article(self, *_args, **_kwargs):
            return {
                "deployment_id": PREVIEW_DEPLOYMENT_ID,
                "static_url": "https://preview.example.pages.dev/post/",
                "journal_state": "completed",
            }

    monkeypatch.setattr(notion_page, "get_client", lambda: _Client())
    result = CliRunner().invoke(notion_page.app, ["publish", PAGE_ID])

    assert result.exit_code == 0
    assert PREVIEW_DEPLOYMENT_ID in result.output
    assert "https://preview.example.pages.dev/post/" in result.output


def test_cli_renders_scheduled_result(monkeypatch):
    class _Client:
        def publish_article(self, *_args, **_kwargs):
            return {
                "notion_page_id": PAGE_ID,
                "status": "Scheduled",
                "scheduled_date": "2026-09-01T13:00:00+00:00",
                "slug": "journaled-static-publisher",
            }

    monkeypatch.setattr(notion_page, "get_client", lambda: _Client())
    result = CliRunner().invoke(notion_page.app, ["publish", PAGE_ID, "--auto-schedule"])

    assert result.exit_code == 0
    assert "Scheduled for 2026-09-01T13:00:00+00:00" in result.output
    assert '"status": "Scheduled"' in result.output
    assert "Deployment ID" not in result.output
    assert "Static URL" not in result.output


@pytest.mark.parametrize(
    "method_name,stage",
    [
        ("_upload_static_media", "media"),
        ("_run_static_build", "build"),
        ("_deploy_static_preview", "preview upload"),
        ("update_article", "Notion update"),
    ],
)
def test_failure_matrix_rolls_back_and_same_journal_retry_completes(
    publisher, monkeypatch, method_name, stage
):
    client, _article, _markdown, _image, _manifest, _counters, _token = publisher
    original = getattr(client, method_name)
    attempts = 0

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ClientError(f"injected {stage} failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(client, method_name, fail_once)
    with pytest.raises(ClientError, match=f"failed during {stage}"):
        _publish(client)

    journals = list(
        (client._publisher_runtime_root() / "transactions").glob("*.journal.json")
    )
    assert len(journals) == 1
    failed = json.loads(journals[0].read_text())
    assert failed["state"] == "failed"
    assert (
        client_module._static_corpus_sha256()
        == failed["prior_state"]["corpus_sha256"]
    )

    result = _publish(client)
    completed = json.loads(journals[0].read_text())
    assert result["journal_state"] == completed["state"] == "completed"
    assert completed["effects"] == {
        "corpus_writes": 1,
        "media_upload_sets": 1,
        "builds": 1,
        "deployments": 1,
        "notion_updates": 1,
    }
    assert attempts == 2


def test_rolled_back_failed_competing_revision_does_not_block_fresh_source(
    publisher, monkeypatch
):
    client, _article, markdown, _image, manifest, counters, build_token = publisher
    original_update = client.update_article
    update_attempts = 0

    def fail_first_notion_update(*args, **kwargs):
        nonlocal update_attempts
        update_attempts += 1
        if update_attempts == 1:
            raise ClientError("injected Notion update failure")
        return original_update(*args, **kwargs)

    monkeypatch.setattr(client, "update_article", fail_first_notion_update)
    with pytest.raises(ClientError, match="failed during Notion update"):
        _publish(client)

    transaction_root = client._publisher_runtime_root() / "transactions"
    failed_journal_path = next(transaction_root.glob("*.journal.json"))
    failed_runtime_path = failed_journal_path.with_name(
        failed_journal_path.name.replace(".journal.json", ".runtime.json")
    )
    failed_journal = json.loads(failed_journal_path.read_text())
    failed_runtime = json.loads(failed_runtime_path.read_text())
    assert failed_journal["state"] == "failed"
    assert failed_journal["effects"] == {
        "corpus_writes": 0,
        "media_upload_sets": 1,
        "builds": 1,
        "deployments": 1,
        "notion_updates": 0,
    }
    assert failed_runtime["corpus_rolled_back"] is True
    assert failed_runtime["rollback_error"] is None
    historical_release_ref = dict(failed_journal["release_ref"])

    _rotate_static_release(manifest, build_token)
    assert historical_release_ref != {
        "release_id": manifest["release_id"],
        "contract_hash": manifest["contract_hash"],
    }

    client.get_article_markdown = lambda _page_id: markdown + "\nFresh source revision.\n"
    result = _publish(client)

    journals = sorted(transaction_root.glob("*.journal.json"))
    assert len(journals) == 2
    assert json.loads(failed_journal_path.read_text()) == failed_journal
    assert result["journal_state"] == "completed"
    assert result["idempotency_key"] != failed_journal["idempotency"]["key"]
    assert counters["build"] == counters["deploy"] == 2
    assert counters["notion"] == 1


@pytest.mark.parametrize(
    "historical_state,expected_error",
    [
        ("corrupt", "Corrupt publisher journal"),
        ("corrupt_release_ref", "invalid historical release_ref"),
        ("active", "release_ref does not match current manifest"),
        ("completed", "release_ref does not match current manifest"),
        ("unproven", "unproven effects"),
    ],
)
def test_historical_competing_revision_still_fails_closed(
    publisher, monkeypatch, historical_state, expected_error
):
    client, _article, markdown, _image, manifest, counters, build_token = publisher
    original_update = client.update_article
    update_attempts = 0

    def fail_first_notion_update(*args, **kwargs):
        nonlocal update_attempts
        update_attempts += 1
        if update_attempts == 1:
            raise ClientError("injected Notion update failure")
        return original_update(*args, **kwargs)

    if historical_state == "completed":
        _publish(client)
    else:
        monkeypatch.setattr(client, "update_article", fail_first_notion_update)
        with pytest.raises(ClientError, match="failed during Notion update"):
            _publish(client)

    transaction_root = client._publisher_runtime_root() / "transactions"
    journal_path = next(transaction_root.glob("*.journal.json"))
    runtime_path = journal_path.with_name(
        journal_path.name.replace(".journal.json", ".runtime.json")
    )
    journal = json.loads(journal_path.read_text())
    if historical_state == "corrupt":
        journal["events"][-1]["evidence_sha256"] = "invalid"
        _atomic_write_json(journal_path, journal)
    elif historical_state == "corrupt_release_ref":
        journal["release_ref"] = {
            "release_id": "invalid",
            "contract_hash": "invalid",
        }
        _atomic_write_json(journal_path, journal)
    elif historical_state == "active":
        client._transition_publisher_journal(
            journal,
            "reserved",
            {"retry": True},
            journal_path,
        )
    elif historical_state == "unproven":
        runtime = json.loads(runtime_path.read_text())
        runtime["corpus_rolled_back"] = False
        _atomic_write_json(runtime_path, runtime)

    _rotate_static_release(manifest, build_token)
    client.get_article_markdown = lambda _page_id: markdown + "\nFresh source revision.\n"
    prior_counters = dict(counters)

    with pytest.raises(ClientError, match=expected_error):
        _publish(client)

    assert counters == prior_counters
    assert len(list(transaction_root.glob("*.journal.json"))) == 1


def test_failed_built_retry_adopts_exact_preview_without_second_deploy(publisher, monkeypatch):
    client, _article, _markdown, _image, _manifest, counters, _token = publisher
    create_preview = client._deploy_static_preview
    remote_deployment = None

    def reject_created_receipt(idempotency_key, source_revision, release_id):
        nonlocal remote_deployment
        created = create_preview(idempotency_key, source_revision, release_id)
        remote_deployment = created["deployment"]
        raise ClientError("Pages preview receipt identity mismatch")

    monkeypatch.setattr(client, "_deploy_static_preview", reject_created_receipt)
    with pytest.raises(ClientError, match="failed during preview upload"):
        _publish(client)

    journal_path = next(
        (client._publisher_runtime_root() / "transactions").glob("*.journal.json")
    )
    failed = json.loads(journal_path.read_text())
    assert failed["state"] == "failed"
    assert failed["effects"]["builds"] == 1
    assert failed["effects"]["deployments"] == 0
    assert remote_deployment is not None
    list_receipt = json.loads(json.dumps(remote_deployment))
    list_receipt.pop("files")
    commands = []
    run_checked_command = client._run_checked_command

    def run(command, **_kwargs):
        commands.append(command)
        if command[1:4] == ["pages", "deployments", "list"]:
            return SimpleNamespace(stdout=json.dumps([list_receipt]))
        if command[1:4] == ["pages", "deployments", "get"]:
            assert command[-1] == remote_deployment["id"]
            return SimpleNamespace(stdout=json.dumps(remote_deployment))
        if command and command[0] == "cloudflare":
            pytest.fail(f"retry attempted an unexpected Cloudflare command: {command}")
        return run_checked_command(command, **_kwargs)

    monkeypatch.setattr(
        client,
        "_deploy_static_preview",
        AtaBlogClient._deploy_static_preview.__get__(client, AtaBlogClient),
    )
    monkeypatch.setattr(client, "_run_checked_command", run)
    monkeypatch.setattr(
        client,
        "_run_static_build",
        lambda *_args, **_kwargs: pytest.fail(
            "failed-built recovery reran the current publisher-source preflight"
        ),
    )

    result = _publish(client)

    completed = json.loads(journal_path.read_text())
    assert result["journal_state"] == completed["state"] == "completed"
    assert completed["release_ref"] == failed["release_ref"]
    assert completed["artifacts"]["deployment_id"] == remote_deployment["id"]
    assert counters["build"] == counters["deploy"] == 1
    assert counters["notion"] == 1
    assert sum(
        command[1:4] == ["pages", "deployments", "list"] for command in commands
    ) == 1
    assert sum(
        command[1:4] == ["pages", "deployments", "get"] for command in commands
    ) == 1
    assert not any(
        command[1:4] == ["pages", "deployments", "create"] for command in commands
    )


def test_failed_unbuilt_retry_cannot_bypass_current_publisher_source_preflight(
    publisher, monkeypatch
):
    client, _article, _markdown, _image, _manifest, counters, _token = publisher

    def fail_build(*_args, **_kwargs):
        raise ClientError("publisher implementation binding is stale")

    monkeypatch.setattr(client, "_run_static_build", fail_build)

    with pytest.raises(ClientError, match="failed during build"):
        _publish(client)

    journal_path = next(
        (client._publisher_runtime_root() / "transactions").glob("*.journal.json")
    )
    failed = json.loads(journal_path.read_text())
    assert failed["state"] == "failed"
    assert failed["effects"]["builds"] == 0
    assert failed["effects"]["deployments"] == 0

    def reject_cloudflare(*_args, **_kwargs):
        pytest.fail("failed-unbuilt recovery reached Cloudflare before source preflight")

    monkeypatch.setattr(client, "_deploy_static_preview", reject_cloudflare)

    with pytest.raises(ClientError, match="publisher implementation binding is stale"):
        _publish(client)

    assert counters["deploy"] == counters["notion"] == 0


def test_legacy_failed_unbuilt_journal_rebinds_without_duplicate_media(
    publisher, monkeypatch
):
    client, _article, _markdown, _image, manifest, counters, _token = publisher
    original_build = client._run_static_build
    attempts = 0

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ClientError("injected legacy build failure")
        return original_build(*args, **kwargs)

    monkeypatch.setattr(client, "_run_static_build", fail_once)
    with pytest.raises(ClientError, match="failed during build"):
        _publish(client)
    expected_prior_corpus_sha256 = client_module._static_corpus_sha256()

    journal_path = next(
        (client._publisher_runtime_root() / "transactions").glob("*.journal.json")
    )
    runtime_path = journal_path.with_name(
        journal_path.name.replace(".journal.json", ".runtime.json")
    )
    journal = json.loads(journal_path.read_text())
    runtime = json.loads(runtime_path.read_text())
    legacy_release_ref = {
        "release_id": manifest["release_id"],
        "contract_hash": manifest["contract_hash"],
    }
    journal["release_ref"] = legacy_release_ref
    journal["prior_state"]["corpus_sha256"] = client_module._tree_sha256(
        client_module.STATIC_SITE_ROOT / "src" / "data" / "posts"
    )
    journal["artifacts"]["staged_corpus_sha256"] = "e" * 64
    runtime["release_ref"] = legacy_release_ref
    runtime["corpus_sha256"] = "e" * 64
    runtime.pop("build_token_release_ref", None)
    _atomic_write_json(journal_path, journal)
    _atomic_write_json(runtime_path, runtime)

    result = _publish(client)

    assert result["journal_state"] == "completed"
    migrated_journal = json.loads(journal_path.read_text())
    assert migrated_journal["prior_state"][
        "corpus_sha256"
    ] == expected_prior_corpus_sha256
    assert counters["media"] == 1
    assert counters["build"] == 1
    assert attempts == 2


def test_legacy_failed_unbuilt_journal_uses_rotated_build_token(
    publisher, monkeypatch
):
    client, _article, _markdown, _image, manifest, counters, build_token = publisher
    original_build = client._run_static_build

    def fail_build(*_args, **_kwargs):
        raise ClientError("injected legacy build failure")

    monkeypatch.setattr(client, "_run_static_build", fail_build)
    with pytest.raises(ClientError, match="failed during build"):
        _publish(client)

    journal_path = next(
        (client._publisher_runtime_root() / "transactions").glob("*.journal.json")
    )
    runtime_path = journal_path.with_name(
        journal_path.name.replace(".journal.json", ".runtime.json")
    )
    journal = json.loads(journal_path.read_text())
    runtime = json.loads(runtime_path.read_text())
    stale_release_ref = {
        "release_id": manifest["release_id"],
        "contract_hash": manifest["contract_hash"],
    }
    unbound_release_ref = {"release_id": None, "contract_hash": None}
    journal["release_ref"] = unbound_release_ref
    runtime["release_ref"] = unbound_release_ref
    runtime["build_token_release_ref"] = stale_release_ref
    runtime["failure_stage"] = "build-lock acquisition"
    runtime["failure_message"] = "Build token release_id is stale"
    _atomic_write_json(journal_path, journal)
    _atomic_write_json(runtime_path, runtime)

    manifest["inputs"]["corpus_sha256"] = "f" * 64
    manifest_body = {
        key: value
        for key, value in manifest.items()
        if key not in {"release_id", "contract_hash"}
    }
    contract_hash = _artifact_sha256(manifest_body)
    manifest["release_id"] = f"ata-static-{contract_hash[:24]}"
    manifest["contract_hash"] = contract_hash
    client_module.STATIC_RELEASE_MANIFEST.write_text(json.dumps(manifest))
    rotated_release_ref = {
        "release_id": manifest["release_id"],
        "contract_hash": manifest["contract_hash"],
    }
    token = json.loads(build_token.read_text())
    token.update(rotated_release_ref)
    build_token.write_text(json.dumps(token))

    monkeypatch.setattr(client, "_run_static_build", original_build)
    result = _publish(client)

    # The retry's own build re-stages the corpus and produces its own release
    # identity (which need not equal the manually rotated placeholder above).
    # _bind_static_build_release now advances build_token_release_ref to that
    # actual, just-built identity -- the same one _sync_build_token writes
    # into the live token -- so later retries keep matching the real token
    # instead of the pre-build value this test used only to clear staleness.
    post_build_release_ref = {
        "release_id": manifest["release_id"],
        "contract_hash": manifest["contract_hash"],
    }
    migrated_runtime = json.loads(runtime_path.read_text())
    assert migrated_runtime["build_token_release_ref"] == post_build_release_ref
    assert migrated_runtime["build_token_release_ref"] != stale_release_ref
    assert result["journal_state"] == "completed"
    assert counters["media"] == 1


def test_failed_unbuilt_journal_rejects_impossible_deployment_effect(
    publisher, monkeypatch
):
    client, _article, _markdown, _image, _manifest, counters, _token = publisher

    def fail_build(*_args, **_kwargs):
        raise ClientError("injected build failure")

    monkeypatch.setattr(client, "_run_static_build", fail_build)
    with pytest.raises(ClientError, match="failed during build"):
        _publish(client)

    journal_path = next(
        (client._publisher_runtime_root() / "transactions").glob("*.journal.json")
    )
    journal = json.loads(journal_path.read_text())
    journal["effects"]["deployments"] = 1
    _atomic_write_json(journal_path, journal)

    with pytest.raises(ClientError, match="downstream effects exist before build"):
        _publish(client)
    assert counters["deploy"] == counters["notion"] == 0


@pytest.mark.parametrize(
    "recorded_receipt",
    [
        {"etag": "receipt-without-key"},
        {"key": "wp-content/uploads/publisher/wrong.png"},
    ],
    ids=["missing-key", "wrong-key"],
)
def test_failed_unbuilt_journal_requires_matching_recorded_media_key(
    publisher, monkeypatch, recorded_receipt
):
    client, _article, _markdown, _image, _manifest, counters, _token = publisher

    def fail_build(*_args, **_kwargs):
        raise ClientError("injected build failure")

    monkeypatch.setattr(client, "_run_static_build", fail_build)
    with pytest.raises(ClientError, match="failed during build"):
        _publish(client)

    journal_path = next(
        (client._publisher_runtime_root() / "transactions").glob("*.journal.json")
    )
    runtime_path = journal_path.with_name(
        journal_path.name.replace(".journal.json", ".runtime.json")
    )
    runtime = json.loads(runtime_path.read_text())
    runtime["media"]["receipt"] = recorded_receipt
    _atomic_write_json(runtime_path, runtime)

    effects_before_retry = dict(counters)
    with pytest.raises(ClientError, match="recorded media receipt is invalid"):
        _publish(client)
    assert counters["media"] == effects_before_retry["media"] == 1
    assert counters["deploy"] == effects_before_retry["deploy"] == 0
    assert counters["notion"] == effects_before_retry["notion"] == 0


def test_build_token_failure_precedes_journal_and_is_retryable(publisher):
    client, _article, _markdown, _image, manifest, _counters, build_token = publisher
    token = json.loads(build_token.read_text())
    token["holder"] = "p15"
    build_token.write_text(json.dumps(token))

    with pytest.raises(ClientError, match="build-lock acquisition"):
        _publish(client)

    transaction_root = client._publisher_runtime_root() / "transactions"
    assert list(transaction_root.glob("*.journal.json")) == []

    token.update(
        holder="root-coordinator",
        released_at=None,
        release_id=manifest["release_id"],
        contract_hash=manifest["contract_hash"],
    )
    build_token.write_text(json.dumps(token))
    assert _publish(client)["journal_state"] == "completed"


def test_corrupt_completed_journal_cannot_replay(publisher):
    client, *_ = publisher
    result = _publish(client)
    journal_path = Path(result["journal_path"])
    journal = json.loads(journal_path.read_text())
    journal["unexpected"] = True
    journal_path.write_text(json.dumps(journal))

    with pytest.raises(ClientError, match="top-level fields do not match P05"):
        _publish(client)


def test_rollback_failure_cannot_report_success(publisher, monkeypatch):
    client, *_ = publisher

    def fail_build(_release_ref, _staged_corpus_sha256):
        raise ClientError("injected build failure")

    def fail_rollback(*_args, **_kwargs):
        raise ClientError("injected rollback failure")

    monkeypatch.setattr(client, "_run_static_build", fail_build)
    monkeypatch.setattr(client, "_restore_static_corpus", fail_rollback)

    with pytest.raises(ClientError, match="rollback failed: corpus rollback"):
        _publish(client)


def test_concurrent_same_revision_has_one_effect_set(publisher):
    client, _article, _markdown, _image, _manifest, counters, _token = publisher
    barrier = threading.Barrier(2)
    results = []
    errors = []

    def invoke():
        barrier.wait()
        try:
            results.append(_publish(client))
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [threading.Thread(target=invoke) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(results) == 2
    assert sorted(result["replayed"] for result in results) == [False, True]
    assert counters["media"] == counters["build"] == counters["deploy"] == 1
    assert counters["notion"] == 1


def test_media_upload_recovers_content_addressed_receipt_without_second_put(
    tmp_path, monkeypatch
):
    client = object.__new__(AtaBlogClient)
    image = tmp_path / "featured.png"
    image.write_bytes(b"same immutable image")
    stage = {
        "image_path": str(image),
        "image_url": "https://adamtheautomator.com/wp-content/uploads/publisher/image.png",
        "object_key": "wp-content/uploads/publisher/image.png",
    }
    remote_objects = []
    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        if command[1:4] == ["r2", "objects", "list"]:
            return SimpleNamespace(stdout=json.dumps(remote_objects))
        assert command[1:4] == ["r2", "objects", "put"]
        remote_objects.append(
            {
                "key": stage["object_key"],
                "size": image.stat().st_size,
                "etag": hashlib.md5(image.read_bytes()).hexdigest(),
            }
        )
        return SimpleNamespace(stdout=json.dumps({"key": stage["object_key"]}))

    monkeypatch.setattr(client, "_run_checked_command", run)
    first = client._upload_static_media(stage)
    second = client._upload_static_media(stage)

    assert first["image_url"] == second["image_url"] == stage["image_url"]
    assert second["receipt"]["key"] == stage["object_key"]
    assert second["receipt"]["recovered"] is True
    assert sum(command[1:4] == ["r2", "objects", "put"] for command in commands) == 1


def test_preview_deploy_recovers_branch_commit_without_second_create(monkeypatch):
    client = object.__new__(AtaBlogClient)
    source_revision = "a" * 64
    idempotency_key = "b" * 64
    deployments = []
    full_deployments = {}
    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        if command[1:4] == ["pages", "deployments", "list"]:
            return SimpleNamespace(stdout=json.dumps(deployments))
        if command[1:4] == ["pages", "deployments", "get"]:
            return SimpleNamespace(stdout=json.dumps(full_deployments[command[-1]]))
        assert command[1:4] == ["pages", "deployments", "create"]
        deployment = _preview_deployment_payload(
            idempotency_key=idempotency_key,
            source_revision=source_revision,
        )
        deployments.append(
            _preview_deployment_payload(
                idempotency_key=idempotency_key,
                source_revision=source_revision,
                include_files=False,
            )
        )
        full_deployments[deployment["id"]] = deployment
        return SimpleNamespace(stdout=json.dumps(deployment))

    monkeypatch.setattr(client, "_run_checked_command", run)
    first = client._deploy_static_preview(idempotency_key, source_revision, "ata-static-testrelease0000")
    second = client._deploy_static_preview(idempotency_key, source_revision, "ata-static-testrelease0000")

    assert first["deployment_id"] == second["deployment_id"] == PREVIEW_DEPLOYMENT_ID
    assert sum(
        command[1:4] == ["pages", "deployments", "create"] for command in commands
    ) == 1
    assert sum(
        command[1:4] == ["pages", "deployments", "get"] for command in commands
    ) == 1


def test_preview_deploy_hydrates_idle_create_receipt_without_second_create(
    monkeypatch,
):
    client = object.__new__(AtaBlogClient)
    source_revision = "a" * 64
    idempotency_key = "b" * 64
    created = _preview_deployment_payload(
        idempotency_key=idempotency_key,
        source_revision=source_revision,
    )
    created["latest_stage"] = {"name": "queued", "status": "idle"}
    completed = _preview_deployment_payload(
        idempotency_key=idempotency_key,
        source_revision=source_revision,
    )
    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        if command[1:4] == ["pages", "deployments", "list"]:
            return SimpleNamespace(stdout="[]")
        if command[1:4] == ["pages", "deployments", "create"]:
            return SimpleNamespace(stdout=json.dumps(created))
        assert command[1:4] == ["pages", "deployments", "get"]
        assert command[-1] == PREVIEW_DEPLOYMENT_ID
        return SimpleNamespace(stdout=json.dumps(completed))

    monkeypatch.setattr(client, "_run_checked_command", run)
    monkeypatch.setattr(client_module.time, "sleep", lambda _seconds: None)

    result = client._deploy_static_preview(idempotency_key, source_revision, "ata-static-testrelease0000")

    assert result["deployment_id"] == PREVIEW_DEPLOYMENT_ID
    assert sum(
        command[1:4] == ["pages", "deployments", "create"] for command in commands
    ) == 1
    assert sum(
        command[1:4] == ["pages", "deployments", "get"] for command in commands
    ) == 1


def test_preview_deploy_adopts_idle_existing_receipt_by_polling_same_uuid(
    monkeypatch,
):
    client = object.__new__(AtaBlogClient)
    source_revision = "a" * 64
    idempotency_key = "b" * 64
    listed = _preview_deployment_payload(
        idempotency_key=idempotency_key,
        source_revision=source_revision,
        include_files=False,
    )
    listed["latest_stage"] = {"name": "queued", "status": "idle"}
    active = _preview_deployment_payload(
        idempotency_key=idempotency_key,
        source_revision=source_revision,
    )
    active["latest_stage"] = {"name": "deploy", "status": "active"}
    completed = _preview_deployment_payload(
        idempotency_key=idempotency_key,
        source_revision=source_revision,
    )
    receipts = [active, completed]
    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        if command[1:4] == ["pages", "deployments", "list"]:
            return SimpleNamespace(stdout=json.dumps([listed]))
        assert command[1:4] == ["pages", "deployments", "get"]
        assert command[-1] == PREVIEW_DEPLOYMENT_ID
        return SimpleNamespace(stdout=json.dumps(receipts.pop(0)))

    monkeypatch.setattr(client, "_run_checked_command", run)
    monkeypatch.setattr(client_module.time, "sleep", lambda _seconds: None)

    result = client._deploy_static_preview(idempotency_key, source_revision, "ata-static-testrelease0000")

    assert result["deployment_id"] == PREVIEW_DEPLOYMENT_ID
    assert receipts == []
    assert sum(
        command[1:4] == ["pages", "deployments", "get"] for command in commands
    ) == 2
    assert not any(
        command[1:4] == ["pages", "deployments", "create"] for command in commands
    )


def test_preview_deploy_pending_receipt_terminal_failure_fails_closed(monkeypatch):
    client = object.__new__(AtaBlogClient)
    source_revision = "a" * 64
    idempotency_key = "b" * 64
    listed = _preview_deployment_payload(
        idempotency_key=idempotency_key,
        source_revision=source_revision,
        include_files=False,
    )
    listed["latest_stage"]["status"] = "idle"
    failed = _preview_deployment_payload(
        idempotency_key=idempotency_key,
        source_revision=source_revision,
    )
    failed["latest_stage"]["status"] = "failure"
    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        if command[1:4] == ["pages", "deployments", "list"]:
            return SimpleNamespace(stdout=json.dumps([listed]))
        assert command[1:4] == ["pages", "deployments", "get"]
        return SimpleNamespace(stdout=json.dumps(failed))

    monkeypatch.setattr(client, "_run_checked_command", run)

    with pytest.raises(ClientError, match="terminal status failure"):
        client._deploy_static_preview(idempotency_key, source_revision, "ata-static-testrelease0000")

    assert not any(
        command[1:4] == ["pages", "deployments", "create"] for command in commands
    )


def test_preview_deploy_pending_receipt_times_out_without_create(monkeypatch):
    client = object.__new__(AtaBlogClient)
    source_revision = "a" * 64
    idempotency_key = "b" * 64
    pending = _preview_deployment_payload(
        idempotency_key=idempotency_key,
        source_revision=source_revision,
    )
    pending["latest_stage"]["status"] = "idle"
    listed = json.loads(json.dumps(pending))
    listed.pop("files")
    clock = [0.0]
    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        if command[1:4] == ["pages", "deployments", "list"]:
            return SimpleNamespace(stdout=json.dumps([listed]))
        assert command[1:4] == ["pages", "deployments", "get"]
        assert command[-1] == PREVIEW_DEPLOYMENT_ID
        return SimpleNamespace(stdout=json.dumps(pending))

    def sleep(seconds):
        clock[0] += seconds

    monkeypatch.setattr(client, "_run_checked_command", run)
    monkeypatch.setattr(client_module, "STATIC_PAGES_POLL_TIMEOUT_SECONDS", 5)
    monkeypatch.setattr(client_module, "STATIC_PAGES_POLL_INTERVAL_SECONDS", 2)
    monkeypatch.setattr(client_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(client_module.time, "sleep", sleep)

    with pytest.raises(ClientError, match="did not reach success within 5 seconds"):
        client._deploy_static_preview(idempotency_key, source_revision, "ata-static-testrelease0000")

    assert clock[0] == 5
    assert not any(
        command[1:4] == ["pages", "deployments", "create"] for command in commands
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("environment", "production"),
        ("commit_hash", "c" * 40),
        ("commit_message", "unrelated deployment"),
    ],
)
def test_preview_deploy_existing_branch_identity_mismatch_fails_without_create(
    monkeypatch, field, value
):
    client = object.__new__(AtaBlogClient)
    source_revision = "a" * 64
    idempotency_key = "b" * 64
    deployment = _preview_deployment_payload(
        idempotency_key=idempotency_key,
        source_revision=source_revision,
        include_files=False,
    )
    if field in {"commit_hash", "commit_message"}:
        deployment["deployment_trigger"]["metadata"][field] = value
    else:
        deployment[field] = value
    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        assert command[1:4] == ["pages", "deployments", "list"]
        return SimpleNamespace(stdout=json.dumps([deployment]))

    monkeypatch.setattr(client, "_run_checked_command", run)

    with pytest.raises(ClientError, match="Pages preview receipt identity mismatch"):
        client._deploy_static_preview(idempotency_key, source_revision, "ata-static-testrelease0000")

    assert not any(
        command[1:4] in (
            ["pages", "deployments", "create"],
            ["pages", "deployments", "get"],
        )
        for command in commands
    )


@pytest.mark.parametrize("status", ["failure", "canceled"])
def test_preview_deploy_existing_branch_terminal_failure_fails_without_create(
    monkeypatch, status
):
    client = object.__new__(AtaBlogClient)
    source_revision = "a" * 64
    idempotency_key = "b" * 64
    deployment = _preview_deployment_payload(
        idempotency_key=idempotency_key,
        source_revision=source_revision,
        include_files=False,
    )
    deployment["latest_stage"]["status"] = status
    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        assert command[1:4] == ["pages", "deployments", "list"]
        return SimpleNamespace(stdout=json.dumps([deployment]))

    monkeypatch.setattr(client, "_run_checked_command", run)

    with pytest.raises(ClientError, match=f"terminal status {status}"):
        client._deploy_static_preview(idempotency_key, source_revision, "ata-static-testrelease0000")

    assert not any(
        command[1:4] in (
            ["pages", "deployments", "create"],
            ["pages", "deployments", "get"],
        )
        for command in commands
    )


def test_preview_deploy_ambiguous_transaction_branch_fails_without_create(monkeypatch):
    client = object.__new__(AtaBlogClient)
    source_revision = "a" * 64
    idempotency_key = "b" * 64
    deployments = [
        _preview_deployment_payload(
            idempotency_key=idempotency_key,
            source_revision=source_revision,
            deployment_id=deployment_id,
            include_files=False,
        )
        for deployment_id in (
            PREVIEW_DEPLOYMENT_ID,
            "33333333-3333-4333-8333-333333333333",
        )
    ]
    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        assert command[1:4] == ["pages", "deployments", "list"]
        return SimpleNamespace(stdout=json.dumps(deployments))

    monkeypatch.setattr(client, "_run_checked_command", run)

    with pytest.raises(ClientError, match="Multiple Pages previews"):
        client._deploy_static_preview(idempotency_key, source_revision, "ata-static-testrelease0000")

    assert not any(
        command[1:4] in (
            ["pages", "deployments", "create"],
            ["pages", "deployments", "get"],
        )
        for command in commands
    )


def test_static_build_recovers_hash_bound_output_without_second_npm(
    tmp_path, monkeypatch
):
    client = object.__new__(AtaBlogClient)
    site = tmp_path / "static-site"
    dist = site / "dist"
    dist.mkdir(parents=True)
    manifest_path = dist / "release-manifest.json"
    staged_sha256 = "c" * 64
    manifest = {
        "release_id": "ata-static-recovery",
        "contract_hash": "d" * 64,
        "inputs": {"corpus_sha256": staged_sha256},
    }
    expected_ref = {
        "release_id": manifest["release_id"],
        "contract_hash": manifest["contract_hash"],
    }
    npm_calls = []

    def run(command, **_kwargs):
        npm_calls.append(command)
        (dist / "index.html").write_text("built")
        manifest_path.write_text(json.dumps(manifest))
        return SimpleNamespace(stdout="", stderr="")

    monkeypatch.setattr(client_module, "STATIC_SITE_ROOT", site)
    monkeypatch.setattr(client_module, "STATIC_RELEASE_MANIFEST", manifest_path)
    monkeypatch.setattr(client, "_run_checked_command", run)
    monkeypatch.setattr(
        client,
        "_load_static_release_manifest",
        lambda: json.loads(manifest_path.read_text()),
    )

    first = client._run_static_build(expected_ref, staged_sha256)
    second = client._run_static_build(expected_ref, staged_sha256)

    assert first["build_sha256"] == second["build_sha256"]
    assert npm_calls == [["npm", "run", "build"]]


def test_static_build_rejects_bound_post_stage_release_drift(tmp_path, monkeypatch):
    client = object.__new__(AtaBlogClient)
    site = tmp_path / "static-site"
    dist = site / "dist"
    dist.mkdir(parents=True)
    manifest_path = dist / "release-manifest.json"
    staged_sha256 = "c" * 64
    manifest = {
        "release_id": "ata-static-actual",
        "contract_hash": "d" * 64,
        "inputs": {"corpus_sha256": staged_sha256},
    }

    def run(_command, **_kwargs):
        (dist / "index.html").write_text("built")
        manifest_path.write_text(json.dumps(manifest))
        return SimpleNamespace(stdout="", stderr="")

    monkeypatch.setattr(client_module, "STATIC_SITE_ROOT", site)
    monkeypatch.setattr(client_module, "STATIC_RELEASE_MANIFEST", manifest_path)
    monkeypatch.setattr(client, "_run_checked_command", run)
    monkeypatch.setattr(
        client,
        "_load_static_release_manifest",
        lambda: json.loads(manifest_path.read_text()),
    )

    with pytest.raises(ClientError, match="release identity drifted"):
        client._run_static_build(
            {
                "release_id": "ata-static-bound",
                "contract_hash": "e" * 64,
            },
            staged_sha256,
        )


def test_static_build_requires_manifest_regeneration_contract(tmp_path, monkeypatch):
    client = object.__new__(AtaBlogClient)
    site = tmp_path / "static-site"
    dist = site / "dist"
    dist.mkdir(parents=True)
    manifest_path = dist / "release-manifest.json"

    def run(_command, **_kwargs):
        (dist / "index.html").write_text("build without manifest")
        return SimpleNamespace(stdout="", stderr="")

    monkeypatch.setattr(client_module, "STATIC_SITE_ROOT", site)
    monkeypatch.setattr(client_module, "STATIC_RELEASE_MANIFEST", manifest_path)
    monkeypatch.setattr(client, "_run_checked_command", run)

    with pytest.raises(ClientError, match="must regenerate dist/release-manifest.json"):
        client._run_static_build(
            {"release_id": "ata-static-missing", "contract_hash": "d" * 64},
            "c" * 64,
        )


def test_new_journal_captures_corpus_while_global_build_lock_is_held(
    publisher, monkeypatch
):
    client, *_ = publisher
    held = False
    original_new = client._new_publisher_journal

    @contextmanager
    def tracked_lock(*_args, **_kwargs):
        nonlocal held
        assert held is False
        held = True
        try:
            yield
        finally:
            held = False

    def checked_new(**kwargs):
        assert held is True
        return original_new(**kwargs)

    monkeypatch.setattr(client, "_static_build_lock", tracked_lock)
    monkeypatch.setattr(client, "_new_publisher_journal", checked_new)
    # tracked_lock yields no token handle -- it only asserts lock-hold timing
    # around journal creation, so the (unrelated) token sync is a no-op here.
    monkeypatch.setattr(client, "_sync_build_token", lambda *_a, **_k: None)

    assert _publish(client)["journal_state"] == "completed"
    assert held is False


def test_release_manifest_validation_precedes_journal_and_effects(publisher):
    client, _article, _markdown, _image, manifest, counters, _token = publisher
    manifest["schema_version"] = "ata-static-release/v1"
    client_module.STATIC_RELEASE_MANIFEST.write_text(json.dumps(manifest))

    with pytest.raises(
        ClientError, match="Release manifest schema is not ata-static-release/v2"
    ):
        _publish(client)

    assert sum(counters.values()) == 0
    assert not (client._publisher_runtime_root() / "transactions").exists()


def test_publish_status_rejected_before_source_or_external_reads(publisher):
    client, *_ = publisher
    client.get_article = lambda _page_id: pytest.fail("source read must not run")

    with pytest.raises(ClientError, match="Static publish status must be draft or publish"):
        client._publish_static_transaction(
            page_id=PAGE_ID,
            status="invalid-status",
            check_duplicates=False,
            featured_image="ignored.png",
            force=False,
        )


def test_staging_is_byte_identical_for_same_persisted_publish_date(publisher):
    client, article, markdown, image, manifest, _counters, _token = publisher
    revision = client._source_revision(article, markdown, image)
    key = client._publisher_idempotency_key(PAGE_ID, revision)
    paths = client._publisher_paths(PAGE_ID, key)
    publish_date = "2026-08-31T12:34:56+00:00"

    first = client._stage_static_article(
        page_id=PAGE_ID,
        slug="journaled-static-publisher",
        article=article,
        markdown_content=markdown,
        image_path=image,
        publish_date=publish_date,
        paths=paths,
    )
    first_bytes = Path(first["article_path"]).read_bytes()
    second = client._stage_static_article(
        page_id=PAGE_ID,
        slug="journaled-static-publisher",
        article=article,
        markdown_content=markdown,
        image_path=image,
        publish_date=publish_date,
        paths=paths,
    )

    assert Path(second["article_path"]).read_bytes() == first_bytes
    # The corpus stores a naive site-local wall clock, because that is what the
    # static site's resolver reads a corpus timestamp as. Staging the UTC form
    # published the post five hours late unless the harvested published-time
    # override in post_seo.json corrected it -- a record that only ever exists
    # for an imported post.
    assert b"pubDate: 2026-08-31T07:34:56\n" in first_bytes
    assert b"modDate: 2026-08-31T07:34:56\n" in first_bytes
    assert publish_date.encode() not in first_bytes
    # The featured image's real pixel size, measured from the file the publisher
    # is about to upload. The static build emits these as og:image:width and
    # og:image:height for a post that has no harvested head record.
    assert f"featuredImageWidth: {FIXTURE_IMAGE_WIDTH}\n".encode() in first_bytes
    assert f"featuredImageHeight: {FIXTURE_IMAGE_HEIGHT}\n".encode() in first_bytes


def test_corpus_wall_clock_converts_any_offset_to_the_site_local_wall_clock():
    # The one staged post already in the corpus was scheduled at 13:00 UTC and
    # its harvested production head says it published at 08:00-05:00; the
    # conversion has to reproduce that without the harvested record.
    assert _corpus_wall_clock("2026-09-03T13:00:00+00:00") == "2026-09-03T08:00:00"
    assert _corpus_wall_clock("2026-09-03T08:00:00-05:00") == "2026-09-03T08:00:00"
    assert _corpus_wall_clock("2026-09-03T13:00:00Z") == "2026-09-03T08:00:00"
    # Central Standard Time in winter, Central Daylight Time in summer.
    assert _corpus_wall_clock("2026-01-15T14:30:00Z") == "2026-01-15T08:30:00"
    assert _corpus_wall_clock("2026-07-15T14:30:00Z") == "2026-07-15T09:30:00"
    with pytest.raises(ClientError, match="must carry a UTC offset"):
        _corpus_wall_clock("2026-09-03T08:00:00")


def test_image_pixel_size_reads_real_headers_and_refuses_anything_else(tmp_path):
    png = tmp_path / "featured.png"
    png.write_bytes(_png_bytes(1920, 1080))
    assert _image_pixel_size(png) == (1920, 1080)

    # A lossy WebP: RIFF container, VP8 chunk, the 0x9d012a start code, then
    # the 14-bit width and height.
    lossy = tmp_path / "featured.webp"
    vp8 = b"\x00\x00\x00\x9d\x01\x2a" + (1200).to_bytes(2, "little") + (675).to_bytes(2, "little")
    lossy.write_bytes(
        b"RIFF" + (len(vp8) + 12).to_bytes(4, "little") + b"WEBPVP8 "
        + len(vp8).to_bytes(4, "little") + vp8
    )
    assert _image_pixel_size(lossy) == (1200, 675)

    # A lossless WebP: VP8L, its 0x2f signature byte, then 14-bit width-1 and
    # height-1 packed little-endian.
    lossless = tmp_path / "lossless.webp"
    packed = ((1080 - 1) << 14) | (1920 - 1)
    vp8l = b"\x2f" + packed.to_bytes(4, "little")
    lossless.write_bytes(
        b"RIFF" + (len(vp8l) + 12).to_bytes(4, "little") + b"WEBPVP8L"
        + len(vp8l).to_bytes(4, "little") + vp8l
    )
    assert _image_pixel_size(lossless) == (1920, 1080)

    # An extended WebP: VP8X, 24-bit canvas width-1 and height-1.
    extended = tmp_path / "extended.webp"
    vp8x = b"\x00\x00\x00\x00" + (2752 - 1).to_bytes(3, "little") + (1536 - 1).to_bytes(3, "little")
    extended.write_bytes(
        b"RIFF" + (len(vp8x) + 12).to_bytes(4, "little") + b"WEBPVP8X"
        + len(vp8x).to_bytes(4, "little") + vp8x
    )
    assert _image_pixel_size(extended) == (2752, 1536)

    # A baseline JPEG: the SOF0 frame header carries height then width.
    jpeg = tmp_path / "featured.jpg"
    sof0 = b"\xff\xc0" + (17).to_bytes(2, "big") + b"\x08" + (630).to_bytes(2, "big") + (1200).to_bytes(2, "big")
    jpeg.write_bytes(b"\xff\xd8" + b"\xff\xe0" + (16).to_bytes(2, "big") + b"\x00" * 14 + sof0)
    assert _image_pixel_size(jpeg) == (1200, 630)

    # Anything the publisher cannot actually measure stops the publish rather
    # than staging a guessed size into the head.
    unknown = tmp_path / "featured.tiff"
    unknown.write_bytes(b"II*\x00not really a tiff")
    with pytest.raises(ClientError, match="unrecognized image format"):
        _image_pixel_size(unknown)


# --- single-post production promotion --------------------------------------
#
# Promotion is unconditional now: a status="publish" transaction promotes to
# production the moment it reaches the "deployed" state, with no cutover
# gate precondition and no post-promotion content validator. Cloudflare
# Pages rollback (on a later failure in the same transaction) is the only
# safety net.

PRIOR_PRODUCTION_DEPLOYMENT_ID = "44444444-4444-4444-8444-444444444444"
PRODUCTION_DEPLOYMENT_ID = "33333333-3333-4333-8333-333333333333"


def _production_deployment_payload(*, commit_hash, commit_message, deployment_id):
    return {
        "id": deployment_id,
        "short_id": deployment_id[:8],
        "url": "https://ata-blog-static.pages.dev",
        "environment": "production",
        "latest_stage": {"name": "deploy", "status": "success"},
        "deployment_trigger": {
            "metadata": {
                "branch": "main",
                "commit_hash": commit_hash,
                "commit_message": commit_message,
            },
        },
        "files": {
            "/index.html": hashlib.md5(b"accepted build").hexdigest(),
            "/release-manifest.json": "a" * 32,
        },
    }


def _arm_promotion(client):
    """Install the Cloudflare Pages production command seam promotion needs."""
    calls = {
        "production_lookup": 0,
        "promotion_lookup": 0,
        "promotion_create": 0,
        "rollback": 0,
    }
    rollback_targets = []
    production = [
        _production_deployment_payload(
            commit_hash="c" * 40,
            commit_message="ata-blog prior production deployment",
            deployment_id=PRIOR_PRODUCTION_DEPLOYMENT_ID,
        )
    ]

    original_run = client_module.AtaBlogClient._run_checked_command

    def run(command, *, timeout, label, cwd=None):
        if command[:3] != ["cloudflare", "pages", "deployments"]:
            return original_run(command, cwd=cwd, timeout=timeout, label=label)
        action = command[3]
        if action == "list":
            limit = command[command.index("--limit") + 1]
            if limit == "1":
                calls["production_lookup"] += 1
                return SimpleNamespace(
                    returncode=0, stdout=json.dumps(production[:1]), stderr=""
                )
            calls["promotion_lookup"] += 1
            return SimpleNamespace(
                returncode=0, stdout=json.dumps(production), stderr=""
            )
        if action == "create":
            calls["promotion_create"] += 1
            payload = _production_deployment_payload(
                commit_hash=command[command.index("--commit-hash") + 1],
                commit_message=command[command.index("--commit-message") + 1],
                deployment_id=PRODUCTION_DEPLOYMENT_ID,
            )
            production.insert(0, payload)
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
        if action == "rollback":
            calls["rollback"] += 1
            rollback_targets.append(command[5])
            return SimpleNamespace(returncode=0, stdout="{}", stderr="")
        raise AssertionError(f"unexpected command: {command}")

    client._run_checked_command = run
    return calls, rollback_targets


def test_single_post_promotion_publishes_to_production(publisher):
    client, article, _markdown, _image, _manifest, counters, _token = publisher
    calls, _rollbacks = _arm_promotion(client)

    result = _publish(client, status="publish")

    assert counters["build"] == 1
    assert counters["deploy"] == 1
    assert counters["notion"] == 1
    assert calls["production_lookup"] == 1
    assert calls["promotion_lookup"] == 1
    assert calls["promotion_create"] == 1
    assert calls["rollback"] == 0
    assert result["journal_state"] == "completed"
    assert result["promoted"] is True
    assert result["static_url"] == (
        f"{client_module.STATIC_SITE_ORIGIN}/journaled-static-publisher/"
    )
    assert article["Published URL"] == (
        f"{client_module.STATIC_SITE_ORIGIN}/journaled-static-publisher/"
    )
    assert article["Status"] == "Published"

    runtime_path = Path(result["journal_path"]).with_name(
        Path(result["journal_path"]).name.replace(".journal.", ".runtime.")
    )
    runtime = json.loads(runtime_path.read_text())
    assert runtime["promotion_applied"] is True
    assert runtime["prior_production_deployment_id"] == PRIOR_PRODUCTION_DEPLOYMENT_ID
    assert runtime["promotion"]["promotion_id"] == PRODUCTION_DEPLOYMENT_ID


def test_promotion_replay_repeats_no_build_deploy_promotion_or_notion_update(publisher):
    client, _article, _markdown, _image, _manifest, counters, _token = publisher
    calls, _rollbacks = _arm_promotion(client)

    first = _publish(client, status="publish")
    baseline = dict(counters)
    baseline_calls = dict(calls)

    replay = _publish(client, status="publish")

    assert replay["replayed"] is True
    assert replay["idempotency_key"] == first["idempotency_key"]
    assert replay["invocation_effects"] == {field: 0 for field in replay["effects"]}
    assert counters == baseline
    assert calls == baseline_calls
    assert replay["static_url"] == first["static_url"]


def test_resumed_deployed_transaction_promotes_exactly_once(publisher):
    client, article, _markdown, _image, _manifest, counters, _token = publisher
    calls, _rollbacks = _arm_promotion(client)
    committed = client.update_article

    def crash(_page_id, *, status, properties):
        raise KeyboardInterrupt("crash after promotion, before Notion")

    client.update_article = crash
    with pytest.raises(KeyboardInterrupt):
        _publish(client, status="publish")
    assert calls["promotion_create"] == 1

    client.update_article = committed
    result = _publish(client, status="publish")

    assert result["journal_state"] == "completed"
    # Resuming from "deployed" finds promotion_applied already True and does
    # not create a second production deployment.
    assert calls["promotion_create"] == 1
    assert counters["build"] == 1
    assert counters["deploy"] == 1
    assert counters["notion"] == 1
    assert article["Published URL"] == (
        f"{client_module.STATIC_SITE_ORIGIN}/journaled-static-publisher/"
    )


def test_notion_update_failure_after_promotion_rolls_production_back(publisher):
    client, article, _markdown, _image, _manifest, _counters, _token = publisher
    calls, rollback_targets = _arm_promotion(client)

    def fail_notion_update(_page_id, *, status, properties):
        raise ClientError("injected Notion update failure")

    client.update_article = fail_notion_update

    with pytest.raises(ClientError, match="failed during Notion update"):
        _publish(client, status="publish")

    assert calls["promotion_create"] == 1
    assert calls["rollback"] == 1
    assert rollback_targets == [PRIOR_PRODUCTION_DEPLOYMENT_ID]
    assert article["Status"] == "Draft"
    assert article["Published URL"] is None

    revision = client._source_revision(
        article, client.get_article_markdown(PAGE_ID), client._resolve_featured_image(PAGE_ID, None)
    )
    key = client._publisher_idempotency_key(PAGE_ID, revision)
    paths = client._publisher_paths(PAGE_ID, key)
    journal = json.loads(paths["journal"].read_text())
    runtime = json.loads(paths["runtime"].read_text())
    assert journal["state"] == "failed"
    assert journal["effects"]["notion_updates"] == 0
    assert runtime["promotion_applied"] is False
    assert runtime["promotion_rolled_back"] is True


def test_concurrent_promotions_collapse_to_one_transaction(publisher):
    client, _article, _markdown, _image, _manifest, counters, _token = publisher
    calls, _rollbacks = _arm_promotion(client)
    barrier = threading.Barrier(2)
    results = []
    errors = []

    def invoke():
        barrier.wait()
        try:
            results.append(_publish(client, status="publish"))
        except Exception as exc:  # noqa: BLE001 - recorded and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=invoke) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert len(results) == 2
    assert calls["promotion_create"] == 1
    assert counters["build"] == 1
    assert counters["deploy"] == 1
    assert counters["notion"] == 1
    assert {result["journal_state"] for result in results} == {"completed"}
    assert sum(1 for result in results if result["replayed"]) == 1


def test_publish_article_delegates_to_static_transaction(publisher, monkeypatch):
    client, *_ = publisher
    calls = []

    def fake_transaction(**kwargs):
        calls.append(kwargs)
        return {
            "static_url": f"{client_module.STATIC_SITE_ORIGIN}/p/",
            "deployment_id": "dep-2",
            "promoted": True,
        }

    monkeypatch.setattr(client, "_publish_static_transaction", fake_transaction)

    result = client.publish_article(PAGE_ID, status="publish", force=False)

    assert len(calls) == 1
    assert set(calls[0]) == {
        "page_id", "status", "check_duplicates", "featured_image", "force",
    }
    assert calls[0]["page_id"] == PAGE_ID
    assert calls[0]["status"] == "publish"
    assert calls[0]["force"] is False
    assert result == {
        "static_url": f"{client_module.STATIC_SITE_ORIGIN}/p/",
        "deployment_id": "dep-2",
        "promoted": True,
    }


# --- schedule-only mode ------------------------------------------------------
#
# `publish --auto-schedule` / `publish --date` validates the post, picks a slot
# under the schedule lock, and writes Status=Scheduled + Publish Date. It never
# enters the publish transaction: nothing is staged, uploaded, built, deployed,
# or journaled. Promotion (`--status publish`) stays the only path that does.

SLOT = "2026-09-01T13:00:00+00:00"


def test_auto_schedule_writes_scheduled_status_and_publish_date_with_zero_publisher_effects(
    publisher, monkeypatch
):
    client, article, _markdown, _image, _manifest, counters, _token = publisher
    article["Status"] = "Ready to Publish"
    _freeze_utc_now(monkeypatch, datetime(2026, 8, 4, 7, 15, 0, tzinfo=timezone.utc))  # Tuesday

    result = client.publish_article(PAGE_ID, auto_schedule=True)

    slot = "2026-08-04T09:00:00+00:00"
    assert result == {
        "notion_page_id": PAGE_ID,
        "status": "Scheduled",
        "scheduled_date": slot,
        "slug": "journaled-static-publisher",
    }
    assert client.update_calls == [(PAGE_ID, "Scheduled", {"Publish Date": slot})]
    assert counters["notion"] == 1
    _assert_no_publisher_effects(client, counters)


def test_explicit_date_schedules_without_journal_or_runtime_record(publisher):
    client, article, _markdown, _image, _manifest, counters, _token = publisher
    article["Status"] = "Ready to Publish"

    result = client.publish_article(PAGE_ID, date="2026-09-01T08:00:00-05:00")

    assert result["status"] == "Scheduled"
    assert result["scheduled_date"] == SLOT
    assert client.update_calls == [(PAGE_ID, "Scheduled", {"Publish Date": SLOT})]
    _assert_no_publisher_effects(client, counters)


def test_schedule_reads_occupancy_with_status_scheduled_and_no_other_notion_read(publisher):
    client, article, *_ = publisher
    article["Status"] = "Ready to Publish"

    client.publish_article(PAGE_ID, date=SLOT)

    # The fixture fails any direct notion CLI call, so this one query is the
    # only Notion read scheduling makes beyond the page and its markdown.
    assert client.list_calls == [{"status": "Scheduled", "limit": 100, "filters": None}]


def test_second_scheduler_blocked_on_the_lock_sees_the_first_pages_slot(publisher):
    client, article, *_ = publisher
    article["Status"] = "Ready to Publish"
    writes = []

    def update(page_id, *, status, properties):
        # Hold the write open: a scheduler that was not blocked on the lock
        # would read occupancy now, before this page shows up as Scheduled.
        time.sleep(0.05)
        writes.append((page_id, status, dict(properties)))
        client.scheduled_pages.append(_scheduled_page(page_id, properties["Publish Date"]))

    client.update_article = update
    barrier = threading.Barrier(2)
    outcomes = []

    def schedule(page_id):
        barrier.wait()
        try:
            outcomes.append(("ok", client.publish_article(page_id, date=SLOT)["scheduled_date"]))
        except ClientError as exc:
            outcomes.append(("error", str(exc)))

    threads = [
        threading.Thread(target=schedule, args=(page_id,)) for page_id in ("page-a", "page-b")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(kind for kind, _ in outcomes) == ["error", "ok"]
    assert [detail for kind, detail in outcomes if kind == "error"] == [
        f"Schedule slot is already occupied: {SLOT}"
    ]
    assert len(writes) == 1
    assert writes[0][1:] == ("Scheduled", {"Publish Date": SLOT})


def test_promotion_of_a_scheduled_page_writes_published_and_stamps_the_promotion_instant(
    publisher,
):
    client, article, _markdown, _image, _manifest, counters, _token = publisher
    _arm_promotion(client)
    article["Status"] = "Scheduled"
    article["Publish Date"] = SLOT
    before = datetime.now(timezone.utc).replace(microsecond=0)

    result = client.publish_article(PAGE_ID, status="publish")

    after = datetime.now(timezone.utc)
    paths = client._publisher_paths(PAGE_ID, result["idempotency_key"])
    runtime = json.loads(paths["runtime"].read_text())
    assert before <= datetime.fromisoformat(runtime["publish_date"]) <= after
    assert "scheduled_date" not in runtime
    assert "scheduled_date" not in result
    assert result["promoted"] is True
    assert client.update_calls == [
        (
            PAGE_ID,
            "Published",
            {
                "Published URL": f"{client_module.STATIC_SITE_ORIGIN}/journaled-static-publisher/",
                "Publish Date": runtime["publish_date"],
            },
        )
    ]
    staged = Path(runtime["article_path"]).read_text()
    assert f"pubDate: {_corpus_wall_clock(runtime['publish_date'])}\n" in staged
    assert counters == {"media": 1, "build": 1, "deploy": 1, "notion": 1}


def test_schedule_rejects_page_not_ready_to_publish(publisher):
    client, _article, _markdown, _image, _manifest, counters, _token = publisher

    with pytest.raises(ClientError, match="must be 'Ready to Publish'.*'Draft'"):
        client.publish_article(PAGE_ID, auto_schedule=True)

    _assert_nothing_written(client, counters)


@pytest.mark.parametrize("field", ["Keywords", "Category", "Tags", "Excerpt"])
def test_schedule_rejects_missing_required_metadata(publisher, field):
    client, article, _markdown, _image, _manifest, counters, _token = publisher
    article["Status"] = "Ready to Publish"
    article[field] = ""

    with pytest.raises(ClientError, match=f"Missing required Notion fields: {field}$"):
        client.publish_article(PAGE_ID, auto_schedule=True)

    _assert_nothing_written(client, counters)


def test_schedule_rejects_image_placeholder_markdown(publisher):
    client, article, _markdown, _image, _manifest, counters, _token = publisher
    article["Status"] = "Ready to Publish"
    client.get_article_markdown = lambda _page_id: "# Post\n\nIMAGE_PLACEHOLDER: dashboard\n"

    with pytest.raises(ClientError, match="IMAGE_PLACEHOLDER marker"):
        client.publish_article(PAGE_ID, auto_schedule=True)

    _assert_nothing_written(client, counters)


def test_schedule_rejects_missing_featured_image(publisher):
    client, article, _markdown, _image, _manifest, counters, _token = publisher
    article["Status"] = "Ready to Publish"
    # The fixture repository has no posts/<page-id>/ directory.
    client._resolve_featured_image = AtaBlogClient._resolve_featured_image

    with pytest.raises(ClientError, match="Featured image is required for publishing"):
        client.publish_article(PAGE_ID, auto_schedule=True)

    _assert_nothing_written(client, counters)


def test_schedule_rejects_featured_image_flag(publisher):
    client, article, _markdown, image, _manifest, counters, _token = publisher
    article["Status"] = "Ready to Publish"

    with pytest.raises(ClientError, match="--featured-image cannot be used when scheduling"):
        client.publish_article(PAGE_ID, auto_schedule=True, featured_image=str(image))

    _assert_nothing_written(client, counters)


def test_schedule_rejects_unknown_tag(publisher):
    client, article, _markdown, _image, _manifest, counters, _token = publisher
    article["Status"] = "Ready to Publish"
    article["Tags"] = "Cloudflare, Not A Real Tag"

    with pytest.raises(ClientError, match="Unknown static corpus tags name: 'Not A Real Tag'"):
        client.publish_article(PAGE_ID, auto_schedule=True)

    _assert_nothing_written(client, counters)


def test_schedule_rejects_a_slug_already_in_the_corpus(publisher):
    client, article, _markdown, _image, _manifest, counters, _token = publisher
    article["Status"] = "Ready to Publish"
    existing = (
        client_module.STATIC_SITE_ROOT / "src" / "data" / "posts" / "journaled-static-publisher.md"
    )
    existing.write_text('---\nslug: "journaled-static-publisher"\n---\nAn older post.\n')

    with pytest.raises(
        ClientError, match="Static post with slug 'journaled-static-publisher' already exists"
    ):
        client.publish_article(PAGE_ID, auto_schedule=True)

    _assert_nothing_written(client, counters, corpus_files=[existing])


def test_schedule_with_exhausted_window_writes_nothing_to_notion(publisher, monkeypatch):
    client, article, _markdown, _image, _manifest, counters, _token = publisher
    article["Status"] = "Ready to Publish"
    _freeze_utc_now(monkeypatch, datetime(2026, 8, 3, 8, 0, 0, tzinfo=timezone.utc))  # Monday
    client.scheduled_pages.extend(
        [
            _scheduled_page("page-a", "2026-08-04T09:00:00+00:00"),
            _scheduled_page("page-b", "2026-08-04T13:00:00+00:00"),
        ]
    )

    with pytest.raises(
        ClientError, match="No available schedule slot inside the frozen scheduling window"
    ):
        client.publish_article(
            PAGE_ID,
            auto_schedule=True,
            schedule_after="2026-08-04T09:00:00+00:00",
            schedule_before="2026-08-04T17:00:00+00:00",
        )

    _assert_nothing_written(client, counters)


def test_explicit_date_on_an_occupied_slot_leaves_the_page_ready_to_publish(publisher):
    client, article, _markdown, _image, _manifest, counters, _token = publisher
    article["Status"] = "Ready to Publish"
    client.scheduled_pages.append(_scheduled_page("page-a", SLOT))

    with pytest.raises(ClientError, match="Schedule slot is already occupied"):
        client.publish_article(PAGE_ID, date=SLOT)

    assert article["Status"] == "Ready to Publish"
    assert article["Publish Date"] is None
    _assert_nothing_written(client, counters)


def test_schedule_rejects_date_combined_with_auto_schedule(publisher):
    client, article, _markdown, _image, _manifest, counters, _token = publisher
    article["Status"] = "Ready to Publish"

    with pytest.raises(ClientError, match="Use either --date or --auto-schedule, not both"):
        client.publish_article(PAGE_ID, date=SLOT, auto_schedule=True)

    _assert_nothing_written(client, counters)


def test_schedule_rejects_status_publish_combined_with_a_date(publisher):
    client, article, _markdown, _image, _manifest, counters, _token = publisher
    article["Status"] = "Ready to Publish"

    with pytest.raises(ClientError, match="--status publish cannot be combined with"):
        client.publish_article(PAGE_ID, status="publish", date=SLOT)

    _assert_nothing_written(client, counters)


def test_schedule_bounds_without_a_schedule_request_are_rejected(publisher):
    client, _article, _markdown, _image, _manifest, counters, _token = publisher

    with pytest.raises(
        ClientError,
        match="--schedule-after/--schedule-before require --auto-schedule or --date",
    ):
        client.publish_article(
            PAGE_ID,
            schedule_after="2026-08-04T09:00:00+00:00",
            schedule_before="2026-08-04T17:00:00+00:00",
        )

    _assert_nothing_written(client, counters)


# --- Sponsored tag by Notion Type --------------------------------------------
#
# The site disables ads and marks external links by the post's own Sponsored
# tag, so the publisher adds that tag from Notion `Type` -- on a first stage and
# on a restage of a record that already carries a tagIds line.

PUBLISH_DATE = "2026-08-31T12:34:56+00:00"


def _stage(client, article, markdown, image, key):
    return client._stage_static_article(
        page_id=PAGE_ID,
        slug="journaled-static-publisher",
        article=article,
        markdown_content=markdown,
        image_path=image,
        publish_date=PUBLISH_DATE,
        paths=client._publisher_paths(PAGE_ID, key),
    )


def _tag_ids_line(article_path):
    lines = [
        line for line in Path(article_path).read_text().splitlines()
        if line.startswith("tagIds:")
    ]
    assert len(lines) == 1
    return lines[0]


def _existing_record_with_tag_ids(client, article, markdown, image, tag_ids_line):
    """Stage a record, then give it the tagIds line of an already-published post."""
    target = Path(_stage(client, article, markdown, image, "a" * 64)["article_path"])
    target.write_text(target.read_text().replace("tagIds: [21]", tag_ids_line))
    assert _tag_ids_line(target) == tag_ids_line
    return target


@pytest.mark.parametrize("post_type", ["Sponsored", "Sponsored Product Review"])
def test_sponsored_type_stages_the_sponsored_tag(publisher, post_type):
    client, article, markdown, image, *_ = publisher
    article["Type"] = post_type

    stage = _stage(client, article, markdown, image, "a" * 64)

    assert _tag_ids_line(stage["article_path"]) == "tagIds: [21, 7]"


def test_sponsored_restage_appends_the_sponsored_tag_to_existing_tag_ids(publisher):
    client, article, markdown, image, *_ = publisher
    target = _existing_record_with_tag_ids(client, article, markdown, image, "tagIds: [5422]")
    preimage = target.read_text()
    article["Type"] = "Sponsored"

    _stage(client, article, markdown, image, "b" * 64)

    assert target.read_text() == preimage.replace("tagIds: [5422]", "tagIds: [5422, 7]")


def test_sponsored_restage_with_the_sponsored_id_already_present_is_byte_identical(publisher):
    client, article, markdown, image, *_ = publisher
    target = _existing_record_with_tag_ids(client, article, markdown, image, "tagIds: [5422,7]")
    preimage = target.read_bytes()
    article["Type"] = "Sponsored"

    _stage(client, article, markdown, image, "b" * 64)

    assert target.read_bytes() == preimage
    assert _tag_ids_line(target) == "tagIds: [5422,7]"


def test_non_sponsored_restage_leaves_existing_tag_ids_bytes_unchanged(publisher):
    client, article, markdown, image, *_ = publisher
    target = _existing_record_with_tag_ids(client, article, markdown, image, "tagIds: [5422,7]")
    preimage = target.read_bytes()

    _stage(client, article, markdown, image, "b" * 64)

    assert target.read_bytes() == preimage


def test_sponsored_type_without_a_sponsored_term_fails_before_any_corpus_write(publisher):
    client, article, markdown, image, *_ = publisher
    terms_path = client_module.STATIC_SITE_ROOT / "src" / "data" / "terms.json"
    terms = json.loads(terms_path.read_text())
    terms["tags"] = [tag for tag in terms["tags"] if tag["name"] != "Sponsored"]
    terms_path.write_text(json.dumps(terms) + "\n")
    article["Type"] = "Sponsored"

    with pytest.raises(ClientError, match="Unknown static corpus tags name: 'Sponsored'"):
        _stage(client, article, markdown, image, "a" * 64)

    assert list((client_module.STATIC_SITE_ROOT / "src" / "data" / "posts").iterdir()) == []


def test_missing_type_raises_client_error_naming_type(publisher):
    client, article, markdown, image, *_ = publisher
    del article["Type"]

    with pytest.raises(ClientError, match=f"Notion page {PAGE_ID} has no Type"):
        _stage(client, article, markdown, image, "a" * 64)

    assert list((client_module.STATIC_SITE_ROOT / "src" / "data" / "posts").iterdir()) == []


# --- Notion `Slug` is the single supplied-slug source -------------------------


def test_notion_slug_feeds_the_static_slug(publisher):
    client, article, *_ = publisher
    article["Slug"] = "a-slug-chosen-in-notion"

    result = client.publish_article(PAGE_ID)

    assert result["static_url"] == f"{PREVIEW_DEPLOYMENT_URL}/a-slug-chosen-in-notion/"


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_empty_notion_slug_derives_the_slug_from_the_title(publisher, empty):
    client, article, *_ = publisher
    article["Slug"] = empty

    result = client.publish_article(PAGE_ID)

    assert result["static_url"] == f"{PREVIEW_DEPLOYMENT_URL}/journaled-static-publisher/"


@pytest.mark.parametrize("stored", ["Not Normalized!", "a" * 51])
def test_schedule_rejects_a_slug_the_publisher_would_alter(publisher, stored):
    client, article, _markdown, _image, _manifest, counters, _token = publisher
    article["Status"] = "Ready to Publish"
    article["Slug"] = stored

    with pytest.raises(ClientError, match="Notion Slug .* is not a normalized slug"):
        client.publish_article(PAGE_ID, auto_schedule=True)

    _assert_nothing_written(client, counters)


def test_promotion_rejects_a_notion_slug_the_publisher_would_alter(publisher):
    client, article, _markdown, _image, _manifest, counters, _token = publisher
    article["Slug"] = "Not Normalized!"

    with pytest.raises(ClientError, match="Notion Slug .* is not a normalized slug"):
        client.publish_article(PAGE_ID, status="publish")

    _assert_nothing_written(client, counters)


def test_missing_slug_property_raises_client_error_naming_slug(publisher):
    client, article, _markdown, _image, _manifest, counters, _token = publisher
    del article["Slug"]

    with pytest.raises(ClientError, match="has no 'Slug' property"):
        client.publish_article(PAGE_ID, status="publish")

    _assert_nothing_written(client, counters)
