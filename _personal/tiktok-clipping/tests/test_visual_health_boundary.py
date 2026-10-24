import json
from pathlib import Path

import pytest

from conftest import payload
from test_visual import visual_engine, issue, receipt
from tiktok_clipping_cli.safety import SafetyError


def test_unknown_visual_wrapper_receipt_accounts_once_without_continuation(visual_engine,adapter,clock):
    e=issue(visual_engine,clock)
    failed=receipt(e,clock,outcome='failed',decision=None,usage_observed=False,usage=None,
                   failure={'category':'model_failed','code':'native_receipt_missing','status':None,'retry_after_ms':None})
    with visual_engine.transaction() as db: before=dict(db.execute('SELECT * FROM budgets').fetchone())
    assert visual_engine.apply_visual(failed)['state']=='ready'
    assert visual_engine.apply_visual(failed)['deduplicated']
    with visual_engine.transaction() as db:
        after=dict(db.execute('SELECT * FROM budgets').fetchone())
        saved=json.loads(db.execute('SELECT result FROM visual_attempts WHERE id=?',(e['attempt_id'],)).fetchone()[0])
    assert after==before and saved['usage'] is None
    assert not adapter.uploads
    # A later successful response cannot replace an already accounted attempt.
    with pytest.raises(SafetyError,match='duplicate_result_changed'):
        visual_engine.apply_visual(receipt(e,clock))


def test_final_allowed_visual_revision_can_publish_under_prepared_attempt_cap(visual_engine,adapter,clock):
    limits=json.loads((Path(__file__).parents[1]/'deploy/config.json').read_text())['limits']
    visual_engine.config['limits']['max_attempts']=limits['max_attempts']
    e=issue(visual_engine,clock)
    for _ in range(visual_engine.config['limits']['max_revisions']):
        rejected=receipt(e,clock,decision={'passed':False,'checks':dict.fromkeys(receipt(e,clock)['decision']['checks'],False),'reason':'TEST improve captions'})
        assert visual_engine.apply_visual(rejected)['state']=='queued'
        proposed=visual_engine.prepare('clip')
        e=visual_engine.apply(payload(proposed))['visual']
    result=visual_engine.apply_visual(receipt(e,clock))
    assert result['state']=='published' and len(adapter.uploads)==1
    job=visual_engine.get(e['job_id'])
    assert job['revisions']==2 and job['attempts']<limits['max_attempts']


def test_delayed_wrapper_failure_retains_original_reservation_and_unknown_usage(visual_engine,adapter,clock):
    e=issue(visual_engine,clock)
    with visual_engine.transaction() as db: before=dict(db.execute('SELECT * FROM budgets').fetchone())
    clock.now=e['expires_at']+1
    failed=receipt(e,clock,outcome='timeout',decision=None,usage_observed=False,usage=None,
                   failure={'category':'timeout','code':'native_timeout','status':None,'retry_after_ms':None})
    with pytest.raises(SafetyError,match='expired_or_reclaimed'):
        visual_engine.apply_visual(failed)
    with visual_engine.transaction() as db:
        assert dict(db.execute('SELECT * FROM budgets').fetchone())==before
        saved=json.loads(db.execute('SELECT result FROM visual_attempts WHERE id=?',(e['attempt_id'],)).fetchone()[0])
        assert saved['envelope']==e and saved['usage'] is None
    assert not adapter.uploads
