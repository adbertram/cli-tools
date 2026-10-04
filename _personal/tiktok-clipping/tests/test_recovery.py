"""Regression guards from independent fault injection review."""
import threading
import pytest
from conftest import claim, payload, iso
from tiktok_clipping_cli.engine import Engine, AdapterFailure
from tiktok_clipping_cli.safety import SafetyError

def build_six(config,adapter,clock,ambiguous=False):
    config['limits']['circuit_failures']=100
    current=Engine(config,adapter=adapter,clock=clock)
    current.control('running')
    if ambiguous:
        adapter.fail_publish=AdapterFailure('ambiguous','connection_lost_after_upload')
    jobs=[]
    for i in range(6):
        envelope=claim(current,clock,'rotation-'+str(i))
        assert current.apply(payload(envelope))['state']==('ambiguous' if ambiguous else 'published')
        jobs.append(envelope['job_id'])
        clock.now+=1
    return current,jobs


def test_unknown_reconciliation_rotates_all_six(config,adapter,clock):
    current,jobs=build_six(config,adapter,clock,True)
    seen=[]
    def reconcile(job,key):
        seen.append(job['id'])
        return {'state':'unknown','provenance':'TEST readback pending'}
    adapter.reconcile=reconcile
    current.maintain()
    clock.now+=300
    current.maintain()
    assert set(seen)==set(jobs)


def test_reward_readback_failures_rotate_all_six(config,adapter,clock):
    current,jobs=build_six(config,adapter,clock)
    seen=[]
    original=adapter.reward_status
    def reward_status(job,reward):
        seen.append(job['id'])
        if job['id'] in jobs[:5]:
            raise AdapterFailure('transient','upstream_timeout')
        return {**original(job,reward),'status':'accepted'}
    adapter.reward_status=reward_status
    current.maintain()
    clock.now+=300
    current.maintain()
    assert set(seen)==set(jobs)
    assert current.rewards(jobs[5])['state']=='accepted'


def test_concurrent_reconciliation_has_single_owner(config,adapter,clock):
    current=Engine(config,adapter=adapter,clock=clock)
    current.control('running')
    adapter.fail_publish=AdapterFailure('ambiguous','connection_lost_after_upload')
    envelope=claim(current,clock)
    assert current.apply(payload(envelope))['state']=='ambiguous'
    first=Engine(config,adapter=adapter,clock=clock)
    entered=threading.Event()
    release=threading.Event()
    results=[]
    def reconcile(job,key):
        entered.set()
        assert release.wait(5)
        return {'state':'absent','authoritative':True,'provenance':'TEST absent'}
    adapter.reconcile=reconcile
    thread=threading.Thread(target=lambda:results.append(first.reconcile(envelope['job_id'])))
    thread.start()
    try:
        assert entered.wait(5)
        with pytest.raises(SafetyError,match='job_not_ambiguous'):
            current.reconcile(envelope['job_id'])
    finally:
        release.set()
        thread.join(5)
    assert results[0]['state']=='ready'
    adapter.fail_publish=None
    assert current.run(envelope['job_id'])['state']=='published'
    assert adapter.calls.count('publish')==2


def test_expired_campaign_still_records_past_earnings(engine,config,adapter,clock):
    lease=claim(engine,clock)
    assert engine.apply(payload(lease))['state']=='published'
    clock.now+=31*86400
    original=adapter.reward_status
    def accepted(job,reward):
        return {**original(job,reward),'status':'accepted','earnings':{'amount':7.5,'currency':'USD','provenance':'TEST payout readback','observed_at':iso(clock())}}
    adapter.reward_status=accepted
    observed=engine.reward_status(lease['job_id'])
    assert observed['state']=='accepted' and observed['earnings']['amount']==7.5


def test_asset_cleanup_rotates_past_first_hundred(engine, config, clock):
    from pathlib import Path
    from conftest import source
    from tiktok_clipping_cli.safety import canonical
    paths = []
    with engine.transaction() as db:
        for i in range(101):
            job_id = engine._new_job(db, "clip", source(clock, "cleanup-" + str(i)))
            path = Path(config["workspace"]) / (job_id + ".mp4")
            path.write_bytes(b"TEST confirmed asset")
            paths.append(path)
            asset = {"path": str(path), "sha256": "test-digest", "bytes": path.stat().st_size, "provenance": "TEST confirmed asset"}
            db.execute("UPDATE jobs SET status='published',asset=? WHERE id=?", (canonical(asset), job_id))
            db.execute("INSERT INTO rewards(job_id,publication_id,campaign_id,state,deadline,updated_at) VALUES(?,?,?,'submitted',?,?)", (job_id, "post-" + job_id, "campaign-1", clock() + 600, clock()))
    assert engine.prune_confirmed_assets() > 0
    assert sum(path.exists() for path in paths) == 1
    assert engine.prune_confirmed_assets() > 0
    assert not any(path.exists() for path in paths)
    with engine.transaction() as db:
        assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 101
        assert db.execute("SELECT count(*) FROM rewards").fetchone()[0] == 101
