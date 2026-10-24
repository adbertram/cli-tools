import copy

import pytest

from conftest import claim, iso, payload
from tiktok_clipping_cli.engine import Engine
from tiktok_clipping_cli.safety import SafetyError, canonical


def publish(engine, clock, media_id):
    envelope = claim(engine, clock, media_id)
    result = engine.apply(payload(envelope))
    assert result["state"] == "published"
    return result["publication"]


def metric(clock, publication, views=100, age=3600, observed=None, revenue=None, currency=None):
    return {"publication_id": publication["publication_id"], "observed_at": iso(clock() if observed is None else observed),
            "measured_at": iso(__import__('datetime').datetime.fromisoformat(publication["published_at"]).timestamp() + age),
            "provenance": "TEST metrics from readback", "views": views, "likes": None, "comments": None, "shares": None,
            "watch_seconds": None, "revenue": revenue, "revenue_currency": currency}


def model_payload(envelope, proposal):
    return {k: envelope[k] for k in ("job_id", "lease_token", "input_digest", "policy_digest")} | {"proposal": proposal}


def test_missing_metrics_remain_unknown_and_small_samples_not_learned(engine, clock):
    publication = publish(engine, clock, "one")
    clock.now += 3600
    engine.snapshot(metric(clock, publication, views=None))
    assert engine.cohorts() == []
    assert engine.prepare("learn")["state"] == "insufficient_samples"
    engine.snapshot(metric(clock, publication, views=100, observed=clock() + 1))
    assert len(engine.cohorts()) == 1
    assert engine.prepare("learn")["state"] == "insufficient_samples"


def test_metric_revision_to_unknown_overrides_known_value(engine, clock):
    publication = publish(engine, clock, "one")
    clock.now += 3600
    engine.snapshot(metric(clock, publication, views=100))
    assert engine.cohorts()[0]["value"] == 100
    clock.now += 1
    engine.snapshot(metric(clock, publication, views=None))
    assert engine.cohorts() == []


def test_snapshot_unknown_is_not_zero(engine, clock):
    publication = publish(engine, clock, "one")
    clock.now += 3600
    record = metric(clock, publication, views=None)
    engine.snapshot(record)
    with engine.transaction() as db:
        value = __import__('json').loads(db.execute("SELECT data FROM snapshots").fetchone()[0])
    assert value["revenue"] is None and value["views"] is None


def test_cohort_age_comparability(engine, clock):
    one = publish(engine, clock, "one")
    two = publish(engine, clock, "two")
    clock.now += 86400
    engine.snapshot(metric(clock, one, age=3600))
    engine.snapshot(metric(clock, two, age=86400))
    assert len(engine.cohorts()) == 1
    assert engine.prepare("learn")["state"] == "insufficient_samples"


def test_learning_applies_once_and_clip_uses_active_strategy(engine, clock, config):
    publications = [publish(engine, clock, str(i)) for i in range(2)]
    clock.now += 3600
    for publication in publications:
        engine.snapshot(metric(clock, publication))
    envelope = engine.prepare("learn")
    assert envelope["ready"]
    assert {"source_id", "style", "revenue", "revenue_currency", "provenance"} <= set(envelope["input"]["samples"][0])
    strategy = {"weights": {"plain": 0.6, "highlight": 0.4}, "exploration": 0.05}
    request = model_payload(envelope, strategy)
    assert engine.apply(request)["strategy_version"] == 2
    assert engine.apply(request)["deduplicated"]
    assert engine.prepare("learn")["state"] == "insufficient_samples"
    clip = claim(engine, clock, "new-style")
    assert clip["input"]["strategy"] == strategy
    assert clip["input"]["strategy_version"] == 2
    assert clip["input"]["assigned_style"] in strategy["weights"]
    assert "assigned_style" in clip["prompt"]


def test_assigned_style_is_enforced(engine, clock):
    clip = claim(engine, clock)
    other_style = "highlight" if clip["input"]["assigned_style"] == "plain" else "plain"
    with pytest.raises(SafetyError, match="style_must_match_assigned_strategy"):
        engine.apply(payload(clip, style=other_style))


def test_upload_keeps_strategy_version_from_proposal(engine, clock):
    clip = claim(engine, clock)
    engine.apply(payload(clip), execute=False)
    with engine.transaction() as db:
        db.execute("INSERT INTO strategies VALUES(2,?,?,0)", (canonical({"weights": {"plain": 0.6, "highlight": 0.4}, "exploration": 0.05}), clock()))
        db.execute("UPDATE settings SET value='2' WHERE key='strategy_version'")
    result = engine.run(clip["job_id"])
    with engine.transaction() as db:
        version = db.execute("SELECT version FROM publications WHERE id=?", (result["publication"]["publication_id"],)).fetchone()[0]
    assert version == 1


def test_strategy_bounds_cannot_change_policy(engine, clock):
    publications = [publish(engine, clock, str(i)) for i in range(2)]
    clock.now += 3600
    for publication in publications:
        engine.snapshot(metric(clock, publication))
    envelope = engine.prepare("learn")
    for proposal in ({"weights": {"plain": 1, "highlight": 0}, "exploration": 0.05}, {"weights": {"plain": 0.5, "highlight": 0.5}, "exploration": 0.2}, {"weights": {"plain": 0.5, "highlight": 0.5}, "exploration": 0.05, "daily_posts": 1000}):
        with pytest.raises(SafetyError):
            engine.apply(model_payload(envelope, proposal))


def test_measured_regression_automatically_rolls_back(engine, clock):
    baseline = [publish(engine, clock, "base-" + str(i)) for i in range(2)]
    clock.now += 3600
    for publication in baseline:
        engine.snapshot(metric(clock, publication, views=100))
    envelope = engine.prepare("learn")
    engine.apply(model_payload(envelope, {"weights": {"plain": 0.6, "highlight": 0.4}, "exploration": 0.05}))
    experiment = [publish(engine, clock, "new-" + str(i)) for i in range(2)]
    clock.now += 3600
    for publication in experiment:
        engine.snapshot(metric(clock, publication, views=10))
    assert engine.prepare("learn")["ready"] is False
    assert engine.status()["strategy_version"] == 1


def test_revenue_currency_is_required_and_mixed_currency_not_compared(engine, config, adapter, clock):
    config["learning"]["objective"] = "revenue"
    current = Engine(config, adapter=adapter, clock=clock)
    publications = [publish(current, clock, str(i)) for i in range(2)]
    clock.now += 3600
    with pytest.raises(SafetyError):
        current.snapshot(metric(clock, publications[0], revenue=5))
    current.snapshot(metric(clock, publications[0], revenue=5, currency="USD"))
    current.snapshot(metric(clock, publications[1], revenue=5, currency="EUR"))
    assert current.cohorts() == []


def test_revised_metrics_invalidate_pending_learning(engine, clock):
    publications = [publish(engine, clock, str(i)) for i in range(2)]
    clock.now += 3600
    for publication in publications:
        engine.snapshot(metric(clock, publication))
    envelope = engine.prepare("learn")
    clock.now += 1
    engine.snapshot(metric(clock, publications[0], views=None))
    with pytest.raises(SafetyError, match="stale_learning_evidence"):
        engine.apply(model_payload(envelope, {"weights": {"plain": 0.6, "highlight": 0.4}, "exploration": 0.05}))


def test_metrics_polling_batches_and_rotation(engine, config, adapter, clock):
    config["limits"]["metrics_batch_size"] = 1
    current = Engine(config, adapter=adapter, clock=clock)
    publications = [publish(current, clock, str(i)) for i in range(3)]
    clock.now += 3600
    assert current.prepare("metrics")["action_result"]["snapshots"] == 1
    assert current.prepare("metrics")["action_result"]["snapshots"] == 1
    assert current.prepare("metrics")["action_result"]["snapshots"] == 1
    with current.transaction() as db:
        measured = db.execute("SELECT count(DISTINCT publication_id) FROM snapshots").fetchone()[0]
    assert measured == 3


def test_measured_source_performance_changes_future_queue_order(config, adapter, clock):
    from conftest import source
    config["sources"].append(copy.deepcopy(config["sources"][0]))
    config["sources"][1]["id"] = "source-2"
    config["baseline"]["exploration"] = 0
    current = Engine(config, adapter=adapter, clock=clock)
    current.control("running")
    publications = []
    for source_id, value in (("source-1", 10), ("source-2", 100)):
        for i in range(2):
            record = source(clock, source_id + "-" + str(i))
            record["source_id"] = source_id
            current.ingest(record)
            envelope = current.prepare("clip")
            result = current.apply(payload(envelope))
            publications.append((result["publication"], value))
    clock.now += 3600
    for publication, value in publications:
        current.snapshot(metric(clock, publication, views=value))
    low = source(clock, "low-new")
    current.ingest(low)
    clock.now += 1
    high = source(clock, "high-new")
    high["source_id"] = "source-2"
    current.ingest(high)
    chosen = current.prepare("clip")
    assert chosen["input"]["source_id"] == "source-2"
    context = chosen["input"]["performance_context"]
    means = {entry["source_id"]: entry["mean"] for entry in context["sources"]}
    assert means == {"source-1": 10, "source-2": 100}
    assert {"caption", "clip_seconds", "style", "revenue", "provenance"} <= set(context["recent_age_comparable_results"][0])


def test_authoritative_rewards_feed_revenue_cohorts_without_remote_metrics_reads(config, adapter, clock):
    config["learning"]["objective"] = "revenue"
    current = Engine(config, adapter=adapter, clock=clock)
    current.control("running")
    publications = [publish(current, clock, str(i)) for i in range(2)]
    job_ids = [r["id"] for r in current.list()]
    clock.now += 3600
    observations = 0
    def earned(job, reward):
        nonlocal observations
        observations += 1
        return {"status": "accepted", "publication_id": reward["publication_id"], "campaign_id": reward["campaign_id"], "observed_at": iso(clock()), "provenance": "TEST Whop accepted readback", "earnings": {"amount": 7.5, "currency": "USD", "provenance": "TEST authoritative paid amount, not CPM projection", "observed_at": iso(clock())}}
    adapter.reward_status = earned
    adapter.metrics = lambda publication: (_ for _ in ()).throw(AssertionError("unnecessary remote metrics read"))
    for job_id in job_ids:
        current.reward_status(job_id)
    assert observations == 2
    cohorts = current.cohorts()
    assert len(cohorts) == 2 and all(row["value"] == 7.5 and row["revenue_currency"] == "USD" for row in cohorts)
    assert all("not CPM projection" in row["provenance"] for row in cohorts)
    assert current.prepare("learn")["ready"]


def test_reward_revenue_snapshot_does_not_erase_performance_view_snapshot(engine, adapter, clock):
    publication = publish(engine, clock, "one")
    job_id = engine.list()[0]["id"]
    clock.now += 3600
    engine.snapshot(metric(clock, publication, views=100))
    engine.reward_status(job_id)
    assert engine.cohorts()[0]["value"] == 100
    assert engine.rewards(job_id)["earnings"] is None
