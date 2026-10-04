"""Strict trusted configuration and bounded untrusted model proposals."""
from __future__ import annotations

import hashlib
import json
import math
import shutil
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse


class SafetyError(ValueError):
    """A deterministic safety boundary rejected input."""


PHYSICAL_DISK_RESERVE_BYTES = 1 << 30


def write_allowance(workspace, max_disk_bytes, *, unlinked_bytes=0):
    """Limit writes by workspace ownership and a physical 1 GiB reserve."""
    total = sum(p.stat().st_size for p in Path(workspace).rglob("*") if p.is_file() and not p.is_symlink())
    remaining = min(max_disk_bytes - total - unlinked_bytes,
                    shutil.disk_usage(workspace).free - PHYSICAL_DISK_RESERVE_BYTES)
    if remaining <= 0:
        raise SafetyError("disk_budget_exhausted")
    return remaining


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def strict_json(raw, limit=65536):
    if isinstance(raw, str):
        raw = raw.encode()
    if len(raw) > limit:
        raise SafetyError("payload_too_large")
    def pairs(entries):
        result = {}
        for key, value in entries:
            if key in result:
                raise SafetyError("duplicate_json_key")
            result[key] = value
        return result
    try:
        return json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(SafetyError("nonfinite_number")), object_pairs_hook=pairs)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise SafetyError("invalid_json: " + str(exc)) from exc


def keys(value, required, optional=()):
    if not isinstance(value, dict) or set(value) != set(required) | (set(value) & set(optional)):
        raise SafetyError("schema_keys: expected " + ",".join(sorted(required)))


def number(value, minimum=0, maximum=float("inf"), integer=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not minimum <= value <= maximum:
        raise SafetyError("number_out_of_bounds")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise SafetyError("nonfinite_or_unrepresentable_number")
    if integer and not isinstance(value, int):
        raise SafetyError("integer_required")
    return value


def string(value, maximum=4096):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise SafetyError("invalid_string")
    return value


def timestamp(value):
    string(value, 64)
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SafetyError("invalid_timestamp") from exc
    if result.tzinfo is None:
        raise SafetyError("timestamp_requires_timezone")
    return result.timestamp()


LIMITS = {
    "daily_posts", "daily_model_calls", "daily_runtime_seconds", "min_clip_seconds",
    "max_clip_seconds", "max_attempts", "max_revisions", "lease_seconds", "max_payload_bytes",
    "max_queue", "max_disk_bytes", "work_timeout_seconds", "retry_base_seconds", "retry_max_seconds",
    "circuit_failures", "circuit_cooldown_seconds", "caption_chars", "metrics_batch_size", "metrics_poll_seconds", "metrics_max_age_seconds", "max_clips_per_source",
}
LEARNING = {
    "minimum_samples", "cohort_age_seconds", "cohort_tolerance_seconds", "max_weight_delta",
    "max_exploration", "regression_fraction", "evaluation_minimum_samples", "objective",
}
METRICS = {"views", "likes", "comments", "shares", "watch_seconds", "revenue"}
TARGET_HANDLE = "ata_clipper"
TARGET_ACCOUNT_ID = "7692213003349443597"
TARGET_PROFILE = "clipper"


def validate_config(config):
    keys(config, {"database", "workspace", "account", "sources", "limits", "learning", "baseline", "adapter_module"}, {"visual", "rewards_account"})
    if config.get("visual") is not None:
        visual = config["visual"]
        keys(visual, {"frame_count", "max_frame_bytes", "timeout_seconds", "continuation_seconds", "retention_seconds", "workflow_id"})
        string(visual["workflow_id"], 128)
        number(visual["frame_count"], 1, 8, integer=True)
        number(visual["max_frame_bytes"], 1024, 1048576, integer=True)
        number(visual["timeout_seconds"], 1, config["limits"]["lease_seconds"], integer=True)
        number(visual["continuation_seconds"], 1, 300, integer=True)
        if visual["timeout_seconds"] + visual["continuation_seconds"] > config["limits"]["lease_seconds"]:
            raise SafetyError("visual_lease_headroom_missing")
        number(visual["retention_seconds"], 60, 2592000, integer=True)
    for field in ("database", "workspace"):
        from pathlib import Path
        if not Path(string(config[field])).is_absolute():
            raise SafetyError("absolute_path_required: " + field)
    if config["adapter_module"] is not None:
        string(config["adapter_module"], 256)
    account = config["account"]
    if account is not None:
        keys(account, {"handle", "account_id", "profile", "verified_at", "provenance"})
        if string(account["handle"]).removeprefix("@").casefold() != TARGET_HANDLE:
            raise SafetyError("account_must_be_ata_clipper")
        if string(account["account_id"]) != TARGET_ACCOUNT_ID:
            raise SafetyError("account_id_must_match_verified_target")
        if string(account["profile"]) != TARGET_PROFILE:
            raise SafetyError("account_profile_must_be_clipper")
        string(account["provenance"])
        timestamp(account["verified_at"])
    if config.get("rewards_account") is not None:
        rewards = config["rewards_account"]
        keys(rewards, {"account_id", "username", "profile", "verified_at", "provenance"})
        for field in ("account_id", "username", "profile", "provenance"):
            string(rewards[field])
        if rewards["profile"] != "rewards":
            raise SafetyError("rewards_named_profile_required")
        timestamp(rewards["verified_at"])
    limits = config["limits"]
    keys(limits, LIMITS)
    for key, value in limits.items():
        number(value, 0 if key in {"daily_posts", "daily_model_calls", "daily_runtime_seconds", "max_revisions"} else 1, 10**12, integer=key not in {"min_clip_seconds", "max_clip_seconds", "retry_base_seconds", "retry_max_seconds"})
    if limits["max_clip_seconds"] < limits["min_clip_seconds"] or limits["retry_max_seconds"] < limits["retry_base_seconds"]:
        raise SafetyError("inverted_limits")
    if limits["metrics_batch_size"] > 100 or limits["metrics_max_age_seconds"] < config["learning"]["cohort_age_seconds"]:
        raise SafetyError("invalid_metrics_schedule_limits")
    if limits["lease_seconds"] < limits["work_timeout_seconds"]:
        raise SafetyError("lease_shorter_than_work_timeout")
    if not isinstance(config["sources"], list):
        raise SafetyError("sources_must_be_list")
    ids = set()
    for source in config["sources"]:
        keys(source, {"id", "feed", "allowed_hosts", "reuse_evidence", "campaign"}, {"publication_policy"})
        if source["id"] in ids:
            raise SafetyError("duplicate_source")
        ids.add(string(source["id"]))
        if urlparse(string(source["feed"])).scheme != "https":
            raise SafetyError("https_feed_required")
        if not isinstance(source["allowed_hosts"], list) or not source["allowed_hosts"]:
            raise SafetyError("allowed_hosts_required")
        for host in source["allowed_hosts"]:
            string(host, 253)
            if "/" in host or ":" in host:
                raise SafetyError("invalid_allowed_host")
        string(source["reuse_evidence"])
        campaign = source["campaign"]
        keys(campaign, {"id", "enabled", "categories", "minimum_followers", "expires_at", "provenance", "platform", "submission_window_seconds"})
        for field in ("id", "provenance"):
            string(campaign[field])
        if campaign["platform"] != "whop_content_rewards" or campaign["enabled"] is not True:
            raise SafetyError("verified_active_whop_campaign_required")
        number(campaign["minimum_followers"], 0, 0, integer=True)
        number(campaign["submission_window_seconds"], 1, 1800, integer=True)
        timestamp(campaign["expires_at"])
        if not isinstance(campaign["categories"], list) or not campaign["categories"]:
            raise SafetyError("campaign_categories_required")
        for category in campaign["categories"]:
            string(category, 128)
            if any(term in category.casefold() for term in ("gambl", "casino", "betting", "politic")):
                raise SafetyError("forbidden_campaign_category")
        if "publication_policy" in source:
            from .rights import validate_policy
            validate_policy(source["publication_policy"], source)
    learning = config["learning"]
    keys(learning, LEARNING)
    for field in ("minimum_samples", "evaluation_minimum_samples"):
        number(learning[field], 2, 100000, integer=True)
    number(learning["cohort_age_seconds"], 1)
    number(learning["cohort_tolerance_seconds"], 0, learning["cohort_age_seconds"])
    for field in ("max_weight_delta", "max_exploration", "regression_fraction"):
        number(learning[field], 0, 1)
    if learning["objective"] not in METRICS:
        raise SafetyError("unknown_objective")
    keys(config["baseline"], {"weights", "exploration"})
    validate_strategy(config["baseline"], config)
    return config


def validate_strategy(proposal, config, previous=None):
    keys(proposal, {"weights", "exploration"})
    weights = proposal["weights"]
    if not isinstance(weights, dict) or not 1 <= len(weights) <= 16:
        raise SafetyError("invalid_style_weights")
    if previous is not None and set(weights) != set(previous["weights"]):
        raise SafetyError("strategy_cannot_change_styles")
    for style, weight in weights.items():
        string(style, 64)
        if not all(c.isalnum() or c in "_-" for c in style):
            raise SafetyError("invalid_style_name")
        number(weight, 0, 1)
        if previous is not None and abs(weight - previous["weights"][style]) > config["learning"]["max_weight_delta"] + 1e-9:
            raise SafetyError("strategy_change_too_large")
    if abs(sum(weights.values()) - 1) > 1e-6:
        raise SafetyError("weights_must_sum_to_one")
    number(proposal["exploration"], 0, config["learning"]["max_exploration"])
    return proposal


def validate_source(record, config, now):
    keys(record, {"source_id", "media_id", "media_url", "duration_seconds", "transcript", "observed_at", "provenance", "categories", "transcript_segments"}, {"assigned_style", "strategy_version", "strategy", "excluded_ranges", "clip_sequence", "media_key", "performance_context", "model_feedback"})
    source = next((s for s in config["sources"] if s["id"] == record["source_id"]), None)
    if source is None:
        raise SafetyError("source_not_allowlisted")
    if timestamp(source["campaign"]["expires_at"]) <= now:
        raise SafetyError("campaign_expired")
    for field in ("media_id", "media_url", "provenance"):
        string(record[field])
    if not isinstance(record["transcript"], str) or len(record["transcript"].encode()) > config["limits"]["max_payload_bytes"]:
        raise SafetyError("invalid_transcript")
    parsed = urlparse(record["media_url"])
    if parsed.scheme != "https" or parsed.hostname not in source["allowed_hosts"] or parsed.username or parsed.password:
        raise SafetyError("media_host_not_allowlisted")
    number(record["duration_seconds"], config["limits"]["min_clip_seconds"], 86400)
    segments = record["transcript_segments"]
    if not isinstance(segments, list) or not segments or len(segments) > 10000:
        raise SafetyError("timed_transcript_segments_required")
    previous_end = 0
    for segment in segments:
        keys(segment, {"start_seconds", "end_seconds", "text"})
        start = number(segment["start_seconds"], previous_end, record["duration_seconds"])
        end = number(segment["end_seconds"], start, record["duration_seconds"])
        if end <= start:
            raise SafetyError("negative_or_empty_transcript_segment")
        string(segment["text"], 2000)
        previous_end = end
    if timestamp(record["observed_at"]) > now + 300:
        raise SafetyError("future_source_timestamp")
    if not isinstance(record["categories"], list) or not record["categories"] or not set(record["categories"]).issubset(set(source["campaign"]["categories"])):
        raise SafetyError("source_category_not_allowed")
    return record


def edit_segments(proposal, source_duration=float("inf")):
    """One canonical ordered edit, reserving its full source bounding span."""
    start = number(proposal["start_seconds"], 0, source_duration)
    end = number(proposal["end_seconds"], start, source_duration)
    cuts = proposal.get("segments", [{"start_seconds": start, "end_seconds": end}])
    if not isinstance(cuts, list) or not 1 <= len(cuts) <= 4:
        raise SafetyError("edit_requires_one_to_four_cuts")
    for cut in cuts:
        keys(cut, {"start_seconds", "end_seconds"})
        a = number(cut["start_seconds"], 0, source_duration)
        b = number(cut["end_seconds"], a, source_duration)
        if b <= a:
            raise SafetyError("edit_cut_must_be_positive")
    ordered = sorted(cuts, key=lambda cut: cut["start_seconds"])
    if any(a["end_seconds"] > b["start_seconds"] for a, b in zip(ordered, ordered[1:])):
        raise SafetyError("edit_cuts_overlap_or_repeat")
    if start != ordered[0]["start_seconds"] or end != max(cut["end_seconds"] for cut in cuts):
        raise SafetyError("edit_bounds_must_match_cuts")
    return cuts


def edit_duration(proposal):
    return sum(cut["end_seconds"] - cut["start_seconds"] for cut in edit_segments(proposal))


def validate_proposal(kind, proposal, input_data, config):
    if isinstance(proposal, dict) and "result" in proposal:
        keys(proposal, {"result"}, {"reasoning"})
        if not isinstance(proposal["result"], str):
            raise SafetyError("deepseek_result_must_be_string")
        proposal = strict_json(proposal["result"], config["limits"]["max_payload_bytes"])
    if kind == "clip":
        keys(proposal, {"start_seconds", "end_seconds", "caption", "style"}, {"segments"})
        start = number(proposal["start_seconds"], 0, input_data["duration_seconds"])
        end = number(proposal["end_seconds"], 0, input_data["duration_seconds"])
        edit_segments(proposal, input_data["duration_seconds"])
        number(edit_duration(proposal), config["limits"]["min_clip_seconds"], config["limits"]["max_clip_seconds"])
        string(proposal["caption"], config["limits"]["caption_chars"])
        if proposal["style"] not in config["baseline"]["weights"]:
            raise SafetyError("style_not_allowlisted")
        source = next((s for s in config["sources"] if s["id"] == input_data.get("source_id")), None)
        if source is not None and "publication_policy" in source:
            from .rights import required_overlays
            required_overlays(source["publication_policy"], proposal)
        if "assigned_style" in input_data and proposal["style"] != input_data["assigned_style"]:
            raise SafetyError("style_must_match_assigned_strategy")
    elif kind == "learn":
        validate_strategy(proposal, config, input_data["strategy"])
    else:
        raise SafetyError("metrics_jobs_do_not_accept_model_output")
    canonical(proposal)
    return proposal
