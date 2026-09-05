"""Hermetic contracts for the journaled static-site publisher."""

from __future__ import annotations

import hashlib
import json
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import ata_blog_cli.client as client_module
from ata_blog_cli.client import AtaBlogClient, ClientError, _artifact_sha256, _atomic_write_json
from ata_blog_cli.commands import notion_page


PAGE_ID = "31b5d9c85b2b814298a0ea98cb7d78f4"
PRIOR_DEPLOYMENT_ID = "11111111-1111-4111-8111-111111111111"
PREVIEW_DEPLOYMENT_ID = "22222222-2222-4222-8222-222222222222"
PREVIEW_DEPLOYMENT_URL = "https://22222222.example.pages.dev"
P12_MEDIA_EDGE_CONTRACT_SHA256 = (
    "d9aa9ce2c2de411965b587959066ec513547bc48642c5f5578c389b9325e59ef"
)
P05_FIXTURE = Path(
    "/Users/adam/Dropbox/GitRepos/Agents/ATABlogger/static-site/tests/fixtures/"
    "release-contract/valid-interface-set.json"
)
P05_RELEASE_CONTRACT = Path(
    "/Users/adam/Dropbox/GitRepos/Agents/ATABlogger/static-site/scripts/"
    "release_manifest.mjs"
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


def test_static_worker_proof_pin_matches_canonical_bytes():
    assert client_module.STATIC_WORKER_PROOF.is_file()
    assert (
        hashlib.sha256(client_module.STATIC_WORKER_PROOF.read_bytes()).hexdigest()
        == client_module.STATIC_WORKER_PROOF_SHA256
    )


class _Config:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    def get_profile_data_dir(self) -> Path:
        return self.data_dir


def _scanner_result(manifest, deployment, deployment_sha256):
    release_ref = {
        "release_id": manifest["release_id"],
        "contract_hash": manifest["contract_hash"],
    }
    deployment_ref = {
        "deployment_id": deployment["deployment_id"],
        "deployment_sha256": deployment_sha256,
        "worker_version": manifest["worker"]["version"],
        "route_payload_sha256": manifest["worker"]["route_payload_sha256"],
    }
    section_ids = ["routes", "content-media", "vendor-publisher"]
    sections = [
        {
            "schema_version": "ata-static-acceptance-section/v1",
            "section_id": section_id,
            "release_ref": release_ref,
            "deployment_ref": deployment_ref,
            "scanner_implementation_sha256": client_module.STATIC_SCANNER_SHA256,
            "checks": [],
            "failures": [],
        }
        for section_id in section_ids
    ]
    return {
        "schema_version": "ata-static-scanner-result/v1",
        "passed": True,
        "exit_code": 0,
        "release_ref": release_ref,
        "deployment_ref": deployment_ref,
        "scanner_implementation_sha256": client_module.STATIC_SCANNER_SHA256,
        "section_ids": section_ids,
        "sections": sections,
    }


def _rejected_scanner_result(manifest, deployment, deployment_sha256):
    result = _scanner_result(manifest, deployment, deployment_sha256)
    result["passed"] = False
    result["exit_code"] = 1
    result["sections"][0]["failures"] = [
        {
            "failure_id": "routes-http-status",
            "check_id": "http-status",
            "message": "expected HTTP 200, got 404",
            "evidence_sha256": "f" * 64,
        }
    ]
    return result


def _readiness_deployment(dist: Path):
    metadata = _preview_deployment_payload(
        idempotency_key="b" * 64,
        source_revision="a" * 64,
    )
    metadata["files"] = {
        asset_path: f"{index:032x}"
        for index, asset_path in enumerate(
            client_module.STATIC_PAGES_READINESS_ASSET_PATHS,
            start=1,
        )
    }
    for asset_path, file_identifier in metadata["files"].items():
        local_bytes = (dist / asset_path.removeprefix("/")).read_bytes()
        assert file_identifier != hashlib.md5(
            local_bytes,
            usedforsecurity=False,
        ).hexdigest()
    return {
        "deployment_id": PREVIEW_DEPLOYMENT_ID,
        "deployment_url": PREVIEW_DEPLOYMENT_URL,
        "deployment": metadata,
        "deployment_sha256": _artifact_sha256(metadata),
    }


@pytest.fixture
def readiness_preview(tmp_path, monkeypatch):
    site = tmp_path / "static-site"
    dist = site / "dist"
    dist.mkdir(parents=True)
    (dist / "release-manifest.json").write_bytes(b'{"release":"exact"}\n')
    (dist / "index.html").write_bytes(b"<html>exact preview</html>\n")
    monkeypatch.setattr(client_module, "STATIC_SITE_ROOT", site)
    client = object.__new__(AtaBlogClient)
    deployment = _readiness_deployment(dist)
    return client, dist, deployment


@pytest.fixture
def publisher(tmp_path, monkeypatch):
    repository = tmp_path / "ATABlogger"
    site = repository / "static-site"
    release = repository / "agent_workspaces" / "static-cutover-release"
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
                "tags": [{"id": 21, "name": "Cloudflare", "slug": "cloudflare"}],
            }
        )
        + "\n",
        "src/data/redirects.json": "[]\n",
        "src/data/home_featured.json": "[]\n",
    }.items():
        corpus_path = site / relative_path
        corpus_path.parent.mkdir(parents=True, exist_ok=True)
        corpus_path.write_text(content)

    scanner = repository / "scripts" / "validate-published-post.sh"
    scanner.parent.mkdir(parents=True)
    historical_scanner_sha = hashlib.sha256(b"historical P13 scanner\n").hexdigest()
    scanner.write_bytes(b"current resealed scanner\n")
    scanner_sha = hashlib.sha256(scanner.read_bytes()).hexdigest()
    release_contract = site / "scripts" / "release_manifest.mjs"
    release_contract.parent.mkdir(parents=True)
    release_contract.write_bytes(P05_RELEASE_CONTRACT.read_bytes())
    release_contract_sha = hashlib.sha256(release_contract.read_bytes()).hexdigest()

    release_fixture = site / "tests" / "fixtures" / "release-contract" / "valid-interface-set.json"
    release_fixture.parent.mkdir(parents=True)
    release_fixture.write_bytes(P05_FIXTURE.read_bytes())
    release_fixture_sha = hashlib.sha256(release_fixture.read_bytes()).hexdigest()

    p05_handoff = repository / "agent_workspaces" / "p05_scope_v2" / "handoff.json"
    p05_handoff.parent.mkdir(parents=True)
    p05_handoff_document = {
        "package_id": "P05-SCOPE-V2",
        "phase_id": "P05.release_interfaces.scope_amendment_v2",
        "status": "PASS",
        "source_hashes": {
            "static-site/scripts/release_manifest.mjs": (
                client_module.HISTORICAL_P05_RELEASE_MANIFEST_SHA256
            ),
            "static-site/tests/fixtures/release-contract/valid-interface-set.json": release_fixture_sha,
        },
        "release_contract_v2": {"schema_version": "ata-static-release/v2"},
    }
    p05_handoff.write_text(json.dumps(p05_handoff_document))
    p05_handoff_sha = hashlib.sha256(p05_handoff.read_bytes()).hexdigest()

    p13_handoff = repository / "agent_workspaces" / "p13_scope_v2" / "handoff.json"
    p13_handoff.parent.mkdir(parents=True)
    p13_handoff_document = {
        "package_id": "P13-SCOPE-V2",
        "phase_id": "P13.scanner_freeze.scope_amendment_v2",
        "status": "PASS",
        "inputs": {
            "p05_scope_v2_handoff": {"sha256": p05_handoff_sha},
        },
        "source_hashes": {
            "scripts/validate-published-post.sh": historical_scanner_sha,
        },
        "scanner_contract": {
            "release_schema": "ata-static-release/v2",
            "required_options": [
                "--base-url",
                "--media-base-url",
                "--manifest",
                "--publisher-journal",
                "--scheduled-replay",
                "--deployment-metadata",
                "--expected-release-id",
                "--expected-contract-hash",
                "--expected-post-routes",
                "--deployment-id",
                "--deployment-sha256",
                "--worker-version",
                "--route-payload-sha256",
                "--expected-scanner-sha256",
            ],
            "deployment_binding": {
                "source": "saved Cloudflare Pages deployment metadata",
                "artifact_hash": "canonical JSON SHA-256 equals --deployment-sha256",
                "static_identity_headers_required": False,
                "direct_media_worker_headers": [
                    "x-ata-worker-version",
                    "x-ata-route-payload-sha256",
                ],
            },
        },
    }
    p13_handoff.write_text(json.dumps(p13_handoff_document))
    p13_handoff_sha = hashlib.sha256(p13_handoff.read_bytes()).hexdigest()

    fixture_set = json.loads(release_fixture.read_text())
    manifest_body = fixture_set["release_manifest"]
    manifest_body.pop("release_id")
    manifest_body.pop("contract_hash")
    manifest_body["inputs"]["scanner_implementation_sha256"] = scanner_sha
    contract_hash = _artifact_sha256(manifest_body)
    schema_version = manifest_body.pop("schema_version")
    manifest = {
        "schema_version": schema_version,
        "release_id": f"ata-static-{contract_hash[:24]}",
        "contract_hash": contract_hash,
        **manifest_body,
    }
    manifest_path = dist / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest))

    worker_proof = release / "media-edge" / "direct-worker-proof.json"
    worker_proof.parent.mkdir(parents=True)
    worker_proof_document = {
        "artifact_kind": "static_cutover_direct_worker_proof",
        "package_id": "P12",
        "phase_id": "P12.direct_worker_proof",
        "status": "PASS",
        "completion": {"gate_c2": "GREEN", "unresolved_blocker_count": 0},
        "dependency_bindings": {
            "media_edge_contract": {
                "sha256": P12_MEDIA_EDGE_CONTRACT_SHA256,
            },
        },
        "worker_runtime": {
            "direct_endpoint": "https://media-worker.example.workers.dev",
            "deployment": {
                "status": "ACTIVE_EXACT_VERSION",
                "version_id": manifest["worker"]["version"],
            },
            "source": {
                "local_sha256": manifest["worker"]["script_sha256"],
                "remote_sha256": manifest["worker"]["script_sha256"],
                "status": "EXACT_MATCH",
            },
        },
        "next_owner_contract": {
            "worker_version_id": manifest["worker"]["version"],
            "pending_route_sha256": manifest["worker"]["route_payload_sha256"],
        },
        "route_safety_and_precedence": {
            "status": "PASS_ZERO_PRODUCTION_ROUTES",
            "target_worker_route_count": 0,
        },
        "verification": {
            "direct_http": {
                "status": "PASS",
                "objects": [
                    {
                        "key": "wp-content/uploads/proof.png",
                        "status": "PASS",
                    },
                ],
            },
        },
    }
    worker_proof.write_text(json.dumps(worker_proof_document))
    worker_proof_sha = hashlib.sha256(worker_proof.read_bytes()).hexdigest()
    manifest["inputs"]["media_edge_proof_sha256"] = worker_proof_sha
    manifest_body = {
        key: value
        for key, value in manifest.items()
        if key not in {"release_id", "contract_hash"}
    }
    contract_hash = _artifact_sha256(manifest_body)
    manifest["release_id"] = f"ata-static-{contract_hash[:24]}"
    manifest["contract_hash"] = contract_hash
    manifest_path.write_text(json.dumps(manifest))

    checkpoint = release / "checkpoints" / "checkpoint-1.json"
    checkpoint.parent.mkdir(parents=True)
    bindings = fixture_set["bindings"]
    checkpoint.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "package_id": "P06",
                "phase_id": "P06.checkpoint_1",
                "checkpoint_id": "CHECKPOINT_1",
                "status": "PASS",
                "gate_a": {
                    "status": "PASS",
                    "baseline_index_sha256": bindings["baseline_index_sha256"],
                    "baseline_oracle_sha256": bindings["baseline_oracle_sha256"],
                    "direct_result": {
                        "valid": True,
                        "summary": {"pages_deployment_id": PRIOR_DEPLOYMENT_ID},
                        "gates": {
                            "baseline": {
                                "status": "pass",
                                "sha256": bindings["baseline_index_sha256"],
                            },
                            "redirect": {
                                "status": "pass",
                                "sha256": bindings["redirect_export_sha256"],
                            },
                            "media": {
                                "status": "pass",
                                "sha256": bindings["media_inventory_sha256"],
                            },
                            "provenance": {
                                "status": "pass",
                                "sha256": bindings["provenance_ledger_sha256"],
                            },
                        },
                    },
                },
            }
        )
    )
    build_token = release / "build-token.json"
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
    monkeypatch.setattr(client_module, "STATIC_RELEASE_ROOT", release)
    monkeypatch.setattr(client_module, "STATIC_RELEASE_MANIFEST", manifest_path)
    monkeypatch.setattr(client_module, "STATIC_RELEASE_CONTRACT", release_contract)
    monkeypatch.setattr(client_module, "STATIC_RELEASE_FIXTURE", release_fixture)
    monkeypatch.setattr(client_module, "STATIC_P05_HANDOFF", p05_handoff)
    monkeypatch.setattr(client_module, "STATIC_SCANNER", scanner)
    monkeypatch.setattr(client_module, "STATIC_SCANNER_HANDOFF", p13_handoff)
    monkeypatch.setattr(client_module, "STATIC_WORKER_PROOF", worker_proof)
    monkeypatch.setattr(client_module, "STATIC_CHECKPOINT", checkpoint)
    monkeypatch.setattr(client_module, "STATIC_BUILD_TOKEN", build_token)
    monkeypatch.setattr(client_module, "STATIC_P05_HANDOFF_SHA256", p05_handoff_sha)
    monkeypatch.setattr(client_module, "P11_RELEASE_MANIFEST_SHA256", release_contract_sha)
    monkeypatch.setattr(client_module, "STATIC_RELEASE_FIXTURE_SHA256", release_fixture_sha)
    monkeypatch.setattr(
        client_module,
        "HISTORICAL_P13_SCANNER_SHA256",
        historical_scanner_sha,
    )
    monkeypatch.setattr(client_module, "STATIC_SCANNER_SHA256", scanner_sha)
    monkeypatch.setattr(client_module, "STATIC_SCANNER_HANDOFF_SHA256", p13_handoff_sha)
    monkeypatch.setattr(client_module, "STATIC_WORKER_PROOF_SHA256", worker_proof_sha)

    image = tmp_path / "featured.png"
    image.write_bytes(b"image")
    article = {
        "Title": "Journaled Static Publisher",
        "Keywords": "static publisher",
        "Category": "Automation",
        "Tags": "Cloudflare",
        "Excerpt": "A deterministic publisher transaction.",
        "Status": "Draft",
        "Published URL": None,
        "Publish Date": None,
    }
    markdown = "# Journaled Static Publisher\n\nDeterministic body.\n"
    counters = {name: 0 for name in ("media", "build", "deploy", "scanner", "notion", "lock")}

    client = object.__new__(AtaBlogClient)
    client.config = _Config(tmp_path / "profile")
    client._RESERVATION_DIR = tmp_path / "schedule-reservations"
    client._p05_gate_a_bindings = lambda: {
        "expectedBaselineIndexSha256": bindings["baseline_index_sha256"],
        "expectedBaselineOracleSha256": bindings["baseline_oracle_sha256"],
        "expectedRedirectExportSha256": bindings["redirect_export_sha256"],
        "expectedMediaInventorySha256": bindings["media_inventory_sha256"],
        "expectedProvenanceLedgerSha256": bindings[
            "provenance_ledger_sha256"
        ],
    }
    client.get_article = lambda _page_id: dict(article)
    client.get_article_markdown = lambda _page_id: markdown
    client._resolve_featured_image = lambda _page_id, _supplied: image
    client._probe_static_worker_endpoint = lambda *_args, **_kwargs: None

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

    def scanner_call(**kwargs):
        counters["scanner"] += 1
        assert kwargs["media_base_url"] == "https://media-worker.example.workers.dev"
        deployment_metadata = json.loads(kwargs["deployment_metadata_path"].read_text())
        assert _artifact_sha256(deployment_metadata) == kwargs["deployment_sha256"]
        result = _scanner_result(manifest, kwargs["deployment"], kwargs["deployment_sha256"])
        _atomic_write_json(kwargs["scanner_path"], result)
        return result

    def update(_page_id, *, status, properties):
        counters["notion"] += 1
        article["Status"] = status
        article.update(properties)
        return {"ok": True}

    client._upload_static_media = media
    client._run_static_build = build
    client._deploy_static_preview = deploy
    client._run_static_scanner = scanner_call
    client.update_article = update
    return client, article, markdown, image, manifest, counters, build_token


def _publish(client, **kwargs):
    # Journal-mechanics tests target the static leg directly; publish_article
    # is now the dual-publish orchestrator (static transaction + classic
    # WordPress publish) covered by its own routing test.
    call_kwargs = {
        "page_id": PAGE_ID,
        "status": "draft",
        "slug": "journaled-static-publisher",
        "date": None,
        "auto_schedule": False,
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


def test_current_gate_a_bindings_replace_historical_checkpoint_baseline(
    tmp_path, monkeypatch
):
    historical_baseline = "1" * 64
    current_baseline = "2" * 64
    oracle = "3" * 64
    current_gates = {
        "baseline": {"status": "pass", "sha256": current_baseline},
        "redirect": {"status": "pass", "sha256": "4" * 64},
        "media": {"status": "pass", "sha256": "5" * 64},
        "provenance": {"status": "pass", "sha256": "6" * 64},
    }
    checkpoint = tmp_path / "checkpoint-1.json"
    checkpoint.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "package_id": "P06",
                "phase_id": "P06.checkpoint_1",
                "checkpoint_id": "CHECKPOINT_1",
                "status": "PASS",
                "gate_a": {
                    "status": "PASS",
                    "baseline_index_sha256": historical_baseline,
                    "baseline_oracle_sha256": oracle,
                    "direct_result": {
                        "valid": True,
                        "gates": {
                            "baseline": {
                                "status": "pass",
                                "sha256": historical_baseline,
                            }
                        },
                    },
                },
            }
        )
    )
    client = object.__new__(AtaBlogClient)

    def run(command, **kwargs):
        assert kwargs["label"] == "current Gate A validation"
        assert "validateProductionGateABaseline" in command[3]
        assert "CURRENT_BASELINE_VALIDATOR_SHA256" in command[3]
        return SimpleNamespace(
            stdout=json.dumps({"valid": True, "errors": [], "gates": current_gates})
        )

    monkeypatch.setattr(client_module, "STATIC_CHECKPOINT", checkpoint)
    monkeypatch.setattr(client, "_run_checked_command", run)

    assert client._p05_gate_a_bindings() == {
        "expectedBaselineIndexSha256": current_baseline,
        "expectedBaselineOracleSha256": client_module.STATIC_BASELINE_ORACLE_SHA256,
        "expectedRedirectExportSha256": "4" * 64,
        "expectedMediaInventorySha256": "5" * 64,
        "expectedProvenanceLedgerSha256": "6" * 64,
    }


def test_p05_idempotency_encoding_is_exact():
    source_revision = "d" * 64
    expected = hashlib.sha256(f"{PAGE_ID}\n{source_revision}\n".encode()).hexdigest()
    assert AtaBlogClient._publisher_idempotency_key(PAGE_ID, source_revision) == expected


def test_completed_same_revision_replay_has_zero_effects_and_no_build_token(publisher):
    client, _article, _markdown, _image, _manifest, counters, build_token = publisher
    first = _publish(client)
    build_token.unlink()

    replay = _publish(client, auto_schedule=True)

    assert replay["deployment_id"] == first["deployment_id"]
    assert replay["replayed"] is True
    assert replay["invocation_effects"] == {
        "corpus_writes": 0,
        "media_upload_sets": 0,
        "builds": 0,
        "deployments": 0,
        "notion_updates": 0,
    }
    assert counters == {"media": 1, "build": 1, "deploy": 1, "scanner": 1, "notion": 1, "lock": 0}


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


def test_pages_deployment_metadata_is_saved_and_hash_bound(publisher):
    client, *_ = publisher

    result = _publish(client)

    paths = client._publisher_paths(PAGE_ID, result["idempotency_key"])
    metadata = json.loads(paths["deployment_metadata"].read_text())
    runtime = json.loads(paths["runtime"].read_text())
    assert metadata["id"] == PREVIEW_DEPLOYMENT_ID
    assert runtime["deployment_sha256"] == _artifact_sha256(metadata)


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
        "scheduled_date": None,
        "publish_date": "2026-08-31T12:00:00+00:00",
        "release_ref": journal["release_ref"],
        "scanner_handoff_sha256": client_module.STATIC_SCANNER_HANDOFF_SHA256,
        "media_base_url": "https://media-worker.example.workers.dev",
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
    assert counters["build"] == counters["deploy"] == counters["scanner"] == counters["notion"] == 1


def test_explicit_schedule_slot_contention_is_atomic(publisher):
    client, *_ = publisher
    slot = "2026-09-01T13:00:00+00:00"
    barrier = threading.Barrier(2)
    outcomes = []

    def reserve():
        barrier.wait()
        try:
            outcomes.append(("ok", client._reserve_explicit_schedule_slot(slot)))
        except ClientError as exc:
            outcomes.append(("error", str(exc)))

    threads = [threading.Thread(target=reserve) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(kind for kind, _ in outcomes) == ["error", "ok"]


def test_cli_renders_static_result_fields(monkeypatch):
    class _Client:
        def publish_article(self, *_args, **_kwargs):
            return {
                "scheduled_date": None,
                "deployment_id": PREVIEW_DEPLOYMENT_ID,
                "static_url": "https://preview.example.pages.dev/post/",
                "journal_state": "completed",
            }

    monkeypatch.setattr(notion_page, "get_client", lambda: _Client())
    result = CliRunner().invoke(notion_page.app, ["publish", PAGE_ID])

    assert result.exit_code == 0
    assert PREVIEW_DEPLOYMENT_ID in result.output
    assert "https://preview.example.pages.dev/post/" in result.output
    assert "wordpress_post" not in result.output


@pytest.mark.parametrize(
    "method_name,stage",
    [
        ("_upload_static_media", "media"),
        ("_run_static_build", "build"),
        ("_deploy_static_preview", "preview upload"),
        ("_run_static_scanner", "preview acceptance"),
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


def test_readiness_timeout_same_journal_retry_reuses_one_deployment(
    publisher,
    monkeypatch,
):
    client, _article, _markdown, _image, _manifest, counters, _token = publisher
    original_scanner = client._run_static_scanner
    scanner_attempts = 0

    def timeout_once(**kwargs):
        nonlocal scanner_attempts
        scanner_attempts += 1
        if scanner_attempts == 1:
            raise ClientError(
                "Pages preview readiness timed out for exact deployment "
                f"{kwargs['deployment']['deployment_id']}"
            )
        return original_scanner(**kwargs)

    monkeypatch.setattr(client, "_run_static_scanner", timeout_once)
    with pytest.raises(ClientError, match="failed during preview acceptance"):
        _publish(client)

    journals = list(
        (client._publisher_runtime_root() / "transactions").glob("*.journal.json")
    )
    assert len(journals) == 1
    failed = json.loads(journals[0].read_text())
    assert failed["state"] == "failed"
    assert failed["effects"]["deployments"] == 1
    assert failed["artifacts"]["deployment_id"] == PREVIEW_DEPLOYMENT_ID
    assert counters["deploy"] == 1

    monkeypatch.setattr(
        client,
        "_deploy_static_preview",
        lambda *_args, **_kwargs: pytest.fail("same-journal retry redeployed"),
    )
    result = _publish(client)

    assert result["journal_state"] == "completed"
    assert result["deployment_id"] == PREVIEW_DEPLOYMENT_ID
    assert scanner_attempts == 2
    assert counters["deploy"] == 1
    assert counters["scanner"] == 1


def test_rolled_back_failed_competing_revision_does_not_block_fresh_source(
    publisher, monkeypatch
):
    client, _article, markdown, _image, manifest, counters, build_token = publisher
    original_scanner = client._run_static_scanner
    scanner_attempts = 0

    def fail_first_acceptance(*args, **kwargs):
        nonlocal scanner_attempts
        scanner_attempts += 1
        if scanner_attempts == 1:
            raise ClientError("injected preview acceptance failure")
        return original_scanner(*args, **kwargs)

    monkeypatch.setattr(client, "_run_static_scanner", fail_first_acceptance)
    with pytest.raises(ClientError, match="failed during preview acceptance"):
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
    original_scanner = client._run_static_scanner
    scanner_attempts = 0

    def fail_first_acceptance(*args, **kwargs):
        nonlocal scanner_attempts
        scanner_attempts += 1
        if scanner_attempts == 1:
            raise ClientError("injected preview acceptance failure")
        return original_scanner(*args, **kwargs)

    if historical_state == "completed":
        _publish(client)
    else:
        monkeypatch.setattr(client, "_run_static_scanner", fail_first_acceptance)
        with pytest.raises(ClientError, match="failed during preview acceptance"):
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
            "failed-built recovery reran the current P14 publisher-source preflight"
        ),
    )

    result = _publish(client)

    completed = json.loads(journal_path.read_text())
    assert result["journal_state"] == completed["state"] == "completed"
    assert completed["release_ref"] == failed["release_ref"]
    assert completed["artifacts"]["deployment_id"] == remote_deployment["id"]
    assert counters["build"] == counters["deploy"] == 1
    assert counters["scanner"] == counters["notion"] == 1
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

    assert counters["deploy"] == counters["scanner"] == counters["notion"] == 0


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
    assert counters["scanner"] == counters["notion"] == 1


def test_static_worker_proof_is_hash_bound_before_any_mutation(publisher):
    client, _article, _markdown, _image, manifest, counters, _token = publisher
    proof = json.loads(client_module.STATIC_WORKER_PROOF.read_text())
    proof["worker_runtime"]["source"]["remote_sha256"] = "0" * 64
    client_module.STATIC_WORKER_PROOF.write_text(json.dumps(proof))
    client_module.STATIC_WORKER_PROOF_SHA256 = hashlib.sha256(
        client_module.STATIC_WORKER_PROOF.read_bytes()
    ).hexdigest()
    manifest["inputs"]["media_edge_proof_sha256"] = (
        client_module.STATIC_WORKER_PROOF_SHA256
    )

    with pytest.raises(ClientError, match="Worker source does not match"):
        client._resolve_static_media_base_url(manifest)

    assert counters == {
        "media": 0,
        "build": 0,
        "deploy": 0,
        "scanner": 0,
        "notion": 0,
        "lock": 0,
    }
    assert not (client._publisher_runtime_root() / "transactions").exists()


def test_static_worker_proof_hash_matches_release_manifest_before_any_mutation(
    publisher,
):
    client, _article, _markdown, _image, manifest, counters, _token = publisher
    manifest["inputs"]["media_edge_proof_sha256"] = "0" * 64

    with pytest.raises(ClientError, match="hash-current zero-route PASS"):
        client._resolve_static_media_base_url(manifest)

    assert sum(counters.values()) == 0
    assert not (client._publisher_runtime_root() / "transactions").exists()


def test_static_worker_must_be_reachable_before_journal_creation(
    publisher, monkeypatch
):
    client, _article, _markdown, _image, _manifest, counters, _token = publisher

    def unreachable(*_args, **_kwargs):
        raise ClientError("Direct Worker endpoint is unreachable")

    monkeypatch.setattr(client, "_probe_static_worker_endpoint", unreachable)
    with pytest.raises(ClientError, match="unreachable"):
        _publish(client)

    assert sum(counters.values()) == 0
    assert not (client._publisher_runtime_root() / "transactions").exists()


def test_static_worker_probe_requires_p13_identity_headers(publisher, monkeypatch):
    client, _article, _markdown, _image, manifest, _counters, _token = publisher
    requests = []

    class _Response:
        status = 200
        headers = {
            "x-ata-worker-version": manifest["worker"]["version"],
            "x-ata-route-payload-sha256": manifest["worker"]["route_payload_sha256"],
        }

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def open_request(request, **_kwargs):
        requests.append(request)
        return _Response()

    monkeypatch.setattr(client_module, "urlopen", open_request)
    AtaBlogClient._probe_static_worker_endpoint(
        "https://media-worker.example.workers.dev",
        "wp-content/uploads/proof.png",
        manifest,
    )

    request = requests[0]
    assert request.get_method() == "HEAD"
    assert request.get_header("Accept") == "*/*"
    assert request.get_header("Connection") == "close"
    assert request.get_header("User-agent") == "ata-static-publisher/1"

    _Response.headers = {"x-ata-worker-version": manifest["worker"]["version"]}
    with pytest.raises(ClientError, match="route payload header"):
        AtaBlogClient._probe_static_worker_endpoint(
            "https://media-worker.example.workers.dev",
            "wp-content/uploads/proof.png",
            manifest,
        )


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


def test_preview_readiness_waits_for_404_then_two_stable_exact_rounds(
    readiness_preview,
):
    client, dist, deployment = readiness_preview
    asset_bytes = {
        asset_path: (dist / asset_path.removeprefix("/")).read_bytes()
        for asset_path in client_module.STATIC_PAGES_READINESS_ASSET_PATHS
    }
    responses = [
        *[(404, b"") for _path in client_module.STATIC_PAGES_READINESS_ASSET_PATHS],
        *[
            (200, asset_bytes[asset_path])
            for asset_path in client_module.STATIC_PAGES_READINESS_ASSET_PATHS
        ],
        *[
            (200, asset_bytes[asset_path])
            for asset_path in client_module.STATIC_PAGES_READINESS_ASSET_PATHS
        ],
    ]
    clock = [0.0]
    fetches = []
    progress = []
    side_effects = []

    def fetch(url, timeout):
        fetches.append((url, timeout))
        return responses.pop(0)

    def sleep(seconds):
        clock[0] += seconds

    client._deploy_static_preview = lambda *_args, **_kwargs: side_effects.append(
        "deploy"
    )
    client._run_checked_command = lambda *_args, **_kwargs: side_effects.append(
        "command"
    )

    client._wait_for_static_preview_readiness(
        deployment=deployment,
        deployment_sha256=deployment["deployment_sha256"],
        fetcher=fetch,
        clock=lambda: clock[0],
        sleeper=sleep,
        emit=progress.append,
    )

    assert responses == []
    assert clock[0] == 4
    assert side_effects == []
    assert [url for url, _timeout in fetches] == [
        f"{PREVIEW_DEPLOYMENT_URL}{asset_path}"
        for _round in range(3)
        for asset_path in client_module.STATIC_PAGES_READINESS_ASSET_PATHS
    ]
    assert all(0 < timeout <= 10 for _url, timeout in fetches)
    assert any("stable=0/2" in message and "http=404" in message for message in progress)
    assert any("stable=1/2" in message for message in progress)
    assert progress[-1].startswith("Pages preview readiness passed:")


@pytest.mark.parametrize(
    ("status", "body", "expected_evidence"),
    [
        (404, b"", "http=404"),
        (200, b"stale deployment bytes", "expected="),
    ],
)
def test_preview_readiness_times_out_on_permanent_unready_or_hash_drift(
    readiness_preview,
    monkeypatch,
    status,
    body,
    expected_evidence,
):
    client, _dist, deployment = readiness_preview
    clock = [0.0]
    fetch_count = 0
    side_effects = []

    def fetch(_url, _timeout):
        nonlocal fetch_count
        fetch_count += 1
        return status, body

    def sleep(seconds):
        clock[0] += seconds

    client._deploy_static_preview = lambda *_args, **_kwargs: side_effects.append(
        "deploy"
    )
    monkeypatch.setattr(client_module, "STATIC_PAGES_READINESS_TIMEOUT_SECONDS", 5)
    monkeypatch.setattr(client_module, "STATIC_PAGES_READINESS_POLL_INTERVAL_SECONDS", 2)

    with pytest.raises(ClientError, match="readiness timed out") as exc_info:
        client._wait_for_static_preview_readiness(
            deployment=deployment,
            deployment_sha256=deployment["deployment_sha256"],
            fetcher=fetch,
            clock=lambda: clock[0],
            sleeper=sleep,
            emit=lambda _message: None,
        )

    assert expected_evidence in str(exc_info.value)
    assert PREVIEW_DEPLOYMENT_ID in str(exc_info.value)
    assert clock[0] == 5
    assert fetch_count == 6
    assert side_effects == []


def test_preview_readiness_rejects_deployment_url_identity_before_fetch(
    readiness_preview,
):
    client, _dist, deployment = readiness_preview
    deployment["deployment_url"] = "https://different.example.pages.dev"

    with pytest.raises(ClientError, match="deployment URL identity mismatch"):
        client._wait_for_static_preview_readiness(
            deployment=deployment,
            deployment_sha256=deployment["deployment_sha256"],
            fetcher=lambda *_args: pytest.fail("identity drift reached HTTP fetch"),
            emit=lambda _message: None,
        )


def test_scanner_rejection_persists_bound_receipt_before_raising(
    publisher,
    monkeypatch,
    tmp_path,
):
    client, _article, _markdown, _image, manifest, _counters, _token = publisher
    metadata = _preview_deployment_payload(
        idempotency_key="b" * 64,
        source_revision="a" * 64,
    )
    deployment = {
        "deployment_id": PREVIEW_DEPLOYMENT_ID,
        "deployment_url": PREVIEW_DEPLOYMENT_URL,
        "deployment": metadata,
        "deployment_sha256": _artifact_sha256(metadata),
    }
    rejected = _rejected_scanner_result(
        manifest,
        deployment,
        deployment["deployment_sha256"],
    )
    scanner_path = tmp_path / "scanner-result.json"
    events = []

    monkeypatch.setattr(
        client,
        "_wait_for_static_preview_readiness",
        lambda **kwargs: events.append(
            ("readiness", kwargs["deployment"]["deployment_id"])
        ),
    )

    def run(command, **kwargs):
        events.append(("scanner", command[0]))
        assert kwargs["cwd"] == client_module.STATIC_REPOSITORY_ROOT
        assert kwargs["timeout"] == 14400
        assert command[0] == str(client_module.STATIC_SCANNER)
        assert command[command.index("--base-url") + 1] == PREVIEW_DEPLOYMENT_URL
        return SimpleNamespace(
            returncode=1,
            stdout=json.dumps(rejected),
            stderr="scanner rejected: 1 checks failed",
        )

    monkeypatch.setattr(client_module.subprocess, "run", run)
    run_scanner = AtaBlogClient._run_static_scanner.__get__(client, AtaBlogClient)

    with pytest.raises(ClientError, match="result saved to"):
        run_scanner(
            manifest=manifest,
            journal_path=tmp_path / "journal.json",
            replay_path=tmp_path / "replay.json",
            deployment_metadata_path=tmp_path / "deployment.json",
            scanner_path=scanner_path,
            deployment=deployment,
            deployment_sha256=deployment["deployment_sha256"],
            media_base_url="https://media-worker.example.workers.dev",
        )

    assert json.loads(scanner_path.read_text()) == rejected
    assert events == [
        ("readiness", PREVIEW_DEPLOYMENT_ID),
        ("scanner", str(client_module.STATIC_SCANNER)),
    ]
    assert (
        client._load_existing_scanner_result(
            scanner_path,
            manifest=manifest,
            deployment=deployment,
            deployment_sha256=deployment["deployment_sha256"],
        )
        is None
    )


@pytest.mark.parametrize(
    ("stdout", "expected_error"),
    [
        ("", "returned no JSON result"),
        ("{", "returned invalid JSON"),
    ],
)
def test_scanner_missing_or_invalid_stdout_fails_closed_without_receipt(
    publisher,
    monkeypatch,
    tmp_path,
    stdout,
    expected_error,
):
    client, _article, _markdown, _image, manifest, _counters, _token = publisher
    metadata = _preview_deployment_payload(
        idempotency_key="b" * 64,
        source_revision="a" * 64,
    )
    deployment = {
        "deployment_id": PREVIEW_DEPLOYMENT_ID,
        "deployment_url": PREVIEW_DEPLOYMENT_URL,
        "deployment": metadata,
        "deployment_sha256": _artifact_sha256(metadata),
    }
    scanner_path = tmp_path / "scanner-result.json"
    monkeypatch.setattr(
        client,
        "_wait_for_static_preview_readiness",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        client_module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1,
            stdout=stdout,
            stderr="scanner runtime error",
        ),
    )
    run_scanner = AtaBlogClient._run_static_scanner.__get__(client, AtaBlogClient)

    with pytest.raises(ClientError, match=expected_error):
        run_scanner(
            manifest=manifest,
            journal_path=tmp_path / "journal.json",
            replay_path=tmp_path / "replay.json",
            deployment_metadata_path=tmp_path / "deployment.json",
            scanner_path=scanner_path,
            deployment=deployment,
            deployment_sha256=deployment["deployment_sha256"],
            media_base_url="https://media-worker.example.workers.dev",
        )

    assert not scanner_path.exists()


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


def test_p05_manifest_validation_precedes_journal_and_effects(publisher):
    client, _article, _markdown, _image, manifest, counters, _token = publisher
    manifest["worker"]["route_payload_sha256"] = "invalid"
    client_module.STATIC_RELEASE_MANIFEST.write_text(json.dumps(manifest))

    with pytest.raises(ClientError, match="P05 release manifest validation failed"):
        _publish(client)

    assert sum(counters.values()) == 0
    assert not (client._publisher_runtime_root() / "transactions").exists()


def test_current_p11_release_manifest_matches_external_binding():
    assert (
        hashlib.sha256(client_module.STATIC_RELEASE_CONTRACT.read_bytes()).hexdigest()
        == client_module.P11_RELEASE_MANIFEST_SHA256
    )


def test_historical_p05_evidence_and_current_p11_bytes_are_independent(publisher):
    client, _article, _markdown, _image, manifest, counters, _token = publisher
    p05_handoff = json.loads(client_module.STATIC_P05_HANDOFF.read_text())

    assert (
        p05_handoff["source_hashes"]["static-site/scripts/release_manifest.mjs"]
        == client_module.HISTORICAL_P05_RELEASE_MANIFEST_SHA256
    )
    assert (
        hashlib.sha256(client_module.STATIC_RELEASE_CONTRACT.read_bytes()).hexdigest()
        == client_module.P11_RELEASE_MANIFEST_SHA256
    )
    assert (
        client_module.HISTORICAL_P05_RELEASE_MANIFEST_SHA256
        != client_module.P11_RELEASE_MANIFEST_SHA256
    )
    assert client._load_static_release_manifest()["release_id"] == manifest["release_id"]
    assert sum(counters.values()) == 0


def test_historical_p13_evidence_and_current_scanner_are_independent(publisher):
    client, _article, _markdown, _image, manifest, counters, _token = publisher
    p13_handoff = json.loads(client_module.STATIC_SCANNER_HANDOFF.read_text())
    current_scanner_sha = hashlib.sha256(
        client_module.STATIC_SCANNER.read_bytes()
    ).hexdigest()

    assert (
        p13_handoff["source_hashes"]["scripts/validate-published-post.sh"]
        == client_module.HISTORICAL_P13_SCANNER_SHA256
    )
    assert manifest["inputs"]["scanner_implementation_sha256"] == current_scanner_sha
    assert current_scanner_sha == client_module.STATIC_SCANNER_SHA256
    assert (
        client_module.HISTORICAL_P13_SCANNER_SHA256
        != client_module.STATIC_SCANNER_SHA256
    )
    assert client._load_static_release_manifest()["release_id"] == manifest["release_id"]
    assert sum(counters.values()) == 0


def test_current_scanner_drift_fails_before_mutation(publisher):
    client, _article, _markdown, _image, _manifest, counters, _token = publisher
    client_module.STATIC_SCANNER.write_bytes(b"drifted current scanner\n")

    with pytest.raises(ClientError, match="Current scanner bytes changed"):
        _publish(client)

    assert sum(counters.values()) == 0
    assert not (client._publisher_runtime_root() / "transactions").exists()


def test_current_p11_release_manifest_drift_fails_before_mutation(publisher):
    client, _article, _markdown, _image, _manifest, counters, _token = publisher
    client_module.STATIC_RELEASE_CONTRACT.write_bytes(b"drifted P11 release manifest\n")

    with pytest.raises(ClientError, match="Final P11 release manifest bytes changed"):
        _publish(client)

    assert sum(counters.values()) == 0
    assert not (client._publisher_runtime_root() / "transactions").exists()


def test_historical_p05_source_hash_drift_fails_before_mutation(
    publisher, monkeypatch
):
    client, _article, _markdown, _image, _manifest, counters, _token = publisher
    p05_handoff = json.loads(client_module.STATIC_P05_HANDOFF.read_text())
    p05_handoff["source_hashes"]["static-site/scripts/release_manifest.mjs"] = (
        client_module.P11_RELEASE_MANIFEST_SHA256
    )
    client_module.STATIC_P05_HANDOFF.write_text(json.dumps(p05_handoff))
    monkeypatch.setattr(
        client_module,
        "STATIC_P05_HANDOFF_SHA256",
        hashlib.sha256(client_module.STATIC_P05_HANDOFF.read_bytes()).hexdigest(),
    )

    with pytest.raises(ClientError, match="P05 v2 handoff does not bind"):
        _publish(client)

    assert sum(counters.values()) == 0
    assert not (client._publisher_runtime_root() / "transactions").exists()


def test_publish_status_rejected_before_source_or_external_reads(publisher):
    client, *_ = publisher
    client.get_article = lambda _page_id: pytest.fail("source read must not run")

    with pytest.raises(ClientError, match="Production promotion is owned by P20"):
        client._publish_static_transaction(
            page_id=PAGE_ID,
            status="publish",
            slug="journaled-static-publisher",
            date=None,
            auto_schedule=False,
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
    assert f"modDate: {publish_date}".encode() in first_bytes


def test_schedule_cleanup_failure_never_transitions_completed_to_failed(
    publisher, monkeypatch
):
    client, _article, _markdown, _image, _manifest, counters, _token = publisher
    original_clear = client.clear_schedule_reservation
    attempts = 0

    def fail_once():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ClientError("injected schedule cleanup failure")
        return original_clear()

    monkeypatch.setattr(client, "clear_schedule_reservation", fail_once)
    with pytest.raises(ClientError, match="committed Notion but journal finalization failed"):
        _publish(client)

    journal_path = next(
        (client._publisher_runtime_root() / "transactions").glob("*.journal.json")
    )
    assert json.loads(journal_path.read_text())["state"] == "notion_updated"

    assert _publish(client)["journal_state"] == "completed"
    assert counters["notion"] == 1


def test_publish_article_dual_publishes_static_then_classic(publisher):
    client, *_ = publisher
    calls = []
    client._static_cutover_active = lambda: True

    def fake_static(page_id, **kwargs):
        calls.append(("static", kwargs["status"], kwargs["force"]))
        return {"static_url": "https://static.example/p/", "deployment_id": "dep-1"}

    def fake_classic(page_id, **kwargs):
        calls.append(("classic", kwargs["status"], kwargs["force"]))
        return {"wordpress_post": {"id": 7}, "wordpress_url": "https://wp.example/p/"}

    client._publish_static_transaction = fake_static
    client._publish_article_classic = fake_classic
    result = client.publish_article(PAGE_ID, status="publish", force=False)
    assert calls == [("static", "draft", False), ("classic", "publish", True)]
    assert result["wordpress_post"]["id"] == 7
    assert result["static_url"] == "https://static.example/p/"
    assert result["static_publish"]["deployment_id"] == "dep-1"


def test_publish_article_classic_only_when_cutover_inactive(publisher):
    client, *_ = publisher
    client._static_cutover_active = lambda: False
    client._publish_static_transaction = (
        lambda *a, **k: pytest.fail("static leg must not run")
    )
    client._publish_article_classic = lambda page_id, **kwargs: {
        "wordpress_post": {"id": 8}
    }
    result = client.publish_article(PAGE_ID, status="draft")
    assert result == {"wordpress_post": {"id": 8}}


def test_publish_article_static_only_restores_wordpress_notion_state(publisher):
    client, *_ = publisher
    calls = []
    client._static_cutover_active = lambda: True
    client.get_article = lambda page_id: {
        "Status": "Published",
        "Published URL": "https://adamtheautomator.com/?p=7",
        "Publish Date": "2026-09-03T08:00:00.000+00:00",
    }

    def fake_static(page_id, **kwargs):
        calls.append(("static", kwargs["status"]))
        return {"static_url": "https://static.example/p/", "deployment_id": "dep-9"}

    def fake_update(page_id, status=None, properties=None):
        calls.append(("restore", status, properties))

    client._publish_static_transaction = fake_static
    client._publish_article_classic = (
        lambda *a, **k: pytest.fail("classic leg must not run in static-only mode")
    )
    client.update_article = fake_update
    result = client.publish_article(
        PAGE_ID, status="publish", force=True, static_only=True
    )
    assert calls == [
        ("static", "draft"),
        (
            "restore",
            "Published",
            {
                "Published URL": "https://adamtheautomator.com/?p=7",
                "Publish Date": "2026-09-03T08:00:00.000+00:00",
            },
        ),
    ]
    assert result["deployment_id"] == "dep-9"
    assert result["notion_restored"]["published_url"] == "https://adamtheautomator.com/?p=7"
