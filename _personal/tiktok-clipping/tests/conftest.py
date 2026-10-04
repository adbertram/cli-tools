import hashlib
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tiktok_clipping_cli.engine import AdapterFailure, Engine


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 3, 12, tzinfo=timezone.utc).timestamp()
    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def config(tmp_path, clock):
    return {
        "database": str(tmp_path / "state.db"), "workspace": str(tmp_path / "media"),
        "account": {"handle": "ata_clipping", "account_id": "test-account", "profile": "test-only", "verified_at": iso(clock()), "provenance": "TEST fixture identity"},
        "sources": [{"id": "source-1", "feed": "https://source.example/feed", "allowed_hosts": ["source.example"], "reuse_evidence": "TEST reuse permission", "campaign": {
            "id": "campaign-1", "enabled": True, "categories": ["education"], "minimum_followers": 0,
            "expires_at": iso(clock() + 86400 * 30), "provenance": "TEST campaign evidence", "platform": "whop_content_rewards", "submission_window_seconds": 600}}],
        "limits": {"daily_posts": 10, "daily_model_calls": 20, "daily_runtime_seconds": 10000, "min_clip_seconds": 10,
            "max_clip_seconds": 60, "max_attempts": 10, "max_revisions": 2, "lease_seconds": 120,
            "max_payload_bytes": 65536, "max_queue": 100, "max_disk_bytes": 1048576, "work_timeout_seconds": 30,
            "retry_base_seconds": 2, "retry_max_seconds": 60, "circuit_failures": 3, "circuit_cooldown_seconds": 300, "caption_chars": 200, "metrics_batch_size": 5, "metrics_poll_seconds": 3600, "metrics_max_age_seconds": 604800, "max_clips_per_source": 3},
        "learning": {"minimum_samples": 2, "evaluation_minimum_samples": 2, "cohort_age_seconds": 3600,
            "cohort_tolerance_seconds": 60, "max_weight_delta": 0.1, "max_exploration": 0.1, "regression_fraction": 0.2, "objective": "views"},
        "baseline": {"weights": {"plain": 0.5, "highlight": 0.5}, "exploration": 0.05}, "adapter_module": None,
    }


class Adapter:
    def __init__(self, config, clock):
        self.config = config
        self.clock = clock
        self.uploads = []
        self.fail_publish = None
        self.on_render = None
        self.quality_passes = True
        self.reconciliation = "published"
        self.calls = []

    def verify_ready(self, job):
        self.calls.append("verify_ready")
        return {"allowed": True, "publish_capable": True, "submission_capable": True, "source_reuse_verified": True, "remaining_budget_cents": 100000, "account_id": self.config["account"]["account_id"], "campaign_id": "campaign-1", "checked_at": iso(self.clock()), "provenance": "TEST preflight"}

    def submit_rewards(self, job, reward):
        self.calls.append("submit_rewards")
        return {"submission_id": "reward-" + job["id"], "campaign_id": reward["campaign_id"], "publication_id": reward["publication_id"], "status": "pending", "submitted_at": iso(self.clock()), "provenance": "TEST submission"}

    def reward_status(self, job, reward):
        return {"status": "pending", "campaign_id": reward["campaign_id"], "publication_id": reward["publication_id"], "observed_at": iso(self.clock()), "provenance": "TEST reward status", "earnings": None}

    def discover(self, source):
        self.calls.append("discover")
        return []

    def render(self, job, proposal):
        self.calls.append("render")
        if self.on_render:
            self.on_render()
        path = Path(self.config["workspace"]) / (job["id"] + ".mp4")
        data = b"TEST fake media; never suitable for live publication" + job["id"].encode()
        path.write_bytes(data)
        return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "provenance": "TEST fixture"}

    def quality(self, job, proposal, asset):
        self.calls.append("quality")
        return {"passed": self.quality_passes, "width": 1080, "height": 1920, "duration_seconds": proposal["end_seconds"] - proposal["start_seconds"], "audio_present": True, "captions_present": True, "coherent_boundaries": True, "provenance": "TEST fixture"}

    def receipt(self, job):
        return {"publication_id": "post-" + job["id"], "publication_url": "https://www.tiktok.com/@ata_clipping/video/123", "account_id": self.config["account"]["account_id"], "handle": "ata_clipping", "published_at": iso(self.clock()), "provenance": "TEST fixture readback"}

    def publish(self, job, asset, key):
        self.calls.append("publish")
        self.uploads.append(key)
        if self.fail_publish:
            raise self.fail_publish
        return self.receipt(job)

    def reconcile(self, job, key):
        self.calls.append("reconcile")
        if self.reconciliation == "published":
            return {"state": "published", "publication": self.receipt(job)}
        if self.reconciliation == "absent":
            return {"state": "absent", "authoritative": True, "provenance": "TEST authoritative absence"}
        return {"state": "unknown", "provenance": "TEST unknown"}

    def metrics(self, publication):
        return {"observed_at": iso(self.clock()), "measured_at": iso(self.clock()), "provenance": "TEST metrics", "views": None, "likes": None, "comments": None, "shares": None, "watch_seconds": None, "revenue": None, "revenue_currency": None}


@pytest.fixture
def adapter(config, clock):
    return Adapter(config, clock)


@pytest.fixture
def engine(config, adapter, clock):
    result = Engine(config, adapter=adapter, clock=clock)
    result.control("running")
    return result


def source(clock, media_id="media-1"):
    return {"source_id": "source-1", "media_id": media_id, "media_url": "https://source.example/video/" + media_id,
            "duration_seconds": 120, "transcript": "TEST educational transcript", "transcript_segments": [{"start_seconds": 0, "end_seconds": 120, "text": "TEST educational transcript"}], "observed_at": iso(clock()), "provenance": "TEST feed readback", "categories": ["education"]}


def claim(engine, clock, media_id="media-1"):
    engine.ingest(source(clock, media_id))
    return engine.prepare("clip")


def payload(envelope, **proposal):
    return {key: envelope[key] for key in ("job_id", "lease_token", "input_digest", "policy_digest")} | {"proposal": {"start_seconds": 10, "end_seconds": 30, "caption": "Test caption", "style": envelope["input"]["assigned_style"]} | proposal}
