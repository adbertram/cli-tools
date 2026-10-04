from copy import deepcopy

import pytest

from tiktok_clipping_cli.engine import Engine, AdapterFailure
from tiktok_clipping_cli.health import observe
from conftest import claim
from test_text_attempts import native


def monitored(engine):
    engine.config['monitoring']={'enabled':True,'ambiguity_age_seconds':60,'stalled_job_age_seconds':120}
    return engine


def test_staged_install_never_alerts_and_operational_unconfigured_is_visible(config,clock):
    e=Engine(config,clock=clock)
    assert e.status()['health']['state']=='staged'
    config=deepcopy(config);config['account']=None
    config['monitoring']={'enabled':True,'ambiguity_age_seconds':60,'stalled_job_age_seconds':120}
    assert Engine(config,clock=clock).status()['health']['actionable'] is True


def test_explicit_pause_is_quiet_without_erasing_operational_evidence(engine):
    monitored(engine)
    with engine.transaction() as db: observe(db,'publish',engine.clock(),category='auth',code='session_expired')
    assert engine.status()['health']['actionable']
    engine.control('paused')
    h=engine.status()['health']
    assert not h['actionable'] and h['state']=='paused' and h['observed_issues']


def test_failure_success_restart_and_no_provider_messages(engine,config,adapter,clock):
    monitored(engine)
    adapter.discover=lambda *args: (_ for _ in ()).throw(AdapterFailure('auth','PRIVATE cookie=secret',code='session_expired'))
    with pytest.raises(AdapterFailure): engine._call('discover',config['sources'][0])
    restarted=Engine(engine.config,adapter=adapter,clock=clock)
    h=restarted.status()['health']
    assert h['actionable'] and h['capabilities'][0]['code']=='session_expired'
    assert 'PRIVATE' not in str(h) and 'secret' not in str(h)
    adapter.discover=lambda *args: []
    restarted._call('discover',config['sources'][0])
    assert not restarted.status()['health']['actionable']
    assert restarted.status()['health']['last_success']['discovery_call']==clock()


def test_source_specific_failure_is_not_global_auth_or_empty_supply(engine):
    monitored(engine)
    with engine.transaction() as db: observe(db,'discover',engine.clock(),category='permanent',code='source_access_denied')
    h=engine.status()['health']
    assert not h['actionable'] and h['capabilities'][0]['state']=='source_failure'
    assert h['last_success']['discovery_call'] is None


def test_cooldown_and_bounded_transient_recovery(engine,clock):
    monitored(engine)
    with engine.transaction() as db:
        observe(db,'metrics',clock(),category='rate_limit',code='rate_limit')
        db.execute("INSERT INTO circuits VALUES('metrics',1,?)",(clock()+172800,))
    h=engine.status()['health'];assert not h['actionable'] and h['state']=='cooldown'
    clock.now+=172801
    assert engine.status()['health']['capabilities'][0]['state']=='retry_pending'
    with engine.transaction() as db:
        for _ in range(engine.config['limits']['max_attempts']): observe(db,'metrics',clock(),category='transient')
    assert engine.status()['health']['actionable']


def test_old_ambiguous_request_remains_actionable_after_readback_and_does_not_fence_recovery(engine,clock):
    monitored(engine)
    envelope=claim(engine,clock)
    with engine.transaction() as db:
        db.execute("UPDATE jobs SET status='ambiguous' WHERE id=?",(envelope['job_id'],))
        engine.event(db,envelope['job_id'],'upload_started',{'idempotency_key':'test'})
    clock.now+=61
    with engine.transaction() as db: db.execute('UPDATE jobs SET updated_at=? WHERE id=?',(clock(),envelope['job_id']))
    h=engine.status()['health']
    assert h['actionable'] and h['issues'][0]['age_seconds']==61
    with engine.transaction() as db: engine._active(db)
    assert engine.status()['state']=='running'


def test_catalog_partial_empty_and_unit_access_never_claim_global_empty_or_auth(engine):
    monitored(engine)
    summary={'last_refresh':{'failures':[]},'cooldowns':{},'eligible_count':0,'pending_dependency_count':0,
             'refresh_interrupted_or_in_progress':False,'global_empty_proven':False,
             'unit_failures':[{'provider':'google','category':'access_denied','count':1}],
             'scan':{'current_pass_provider_end':True,'last_successful_page':{'provider_observed_at':engine.clock(),'recorded_at':engine.clock()}}}
    engine.discovery_status=lambda:summary
    h=engine.status()['health']
    assert h['state']=='idle_observed_catalog' and not h['actionable']
    assert h['discovery']['global_empty_proven'] is False
    summary['scan']['current_pass_provider_end']=False
    assert engine.status()['health']['state']=='discovery_incomplete'
    summary['last_refresh']['failures']=[{'provider':'whop','category':'auth'}]
    assert engine.status()['health']['actionable']
    summary['last_refresh']['failures']=[]
    summary['unit_failures']=[{'provider':'google','category':'auth','count':1}]
    assert engine.status()['health']['actionable']
    summary['unit_failures']=[]
    assert not engine.status()['health']['actionable']


def test_provider_wide_cooldown_overrides_exhausted_short_method_delay(engine,clock):
    monitored(engine)
    with engine.transaction() as db:
        for _ in range(engine.config['limits']['max_attempts']):
            observe(db,'metrics',clock(),category='transient',provider='tiktok')
        db.execute("INSERT INTO circuits VALUES('metrics',10,?)",(clock()+60,))
        db.execute("INSERT INTO circuits VALUES('provider:tiktok',1,?)",(clock()+172800,))
    clock.now+=61
    h=engine.status()['health']
    assert not h['actionable'] and h['state']=='cooldown'
    assert h['capabilities'][0]['retry_at']==clock()+172739
    clock.now+=172740
    assert engine.status()['health']['actionable']


def test_terminal_rejected_jobs_do_not_make_recovered_service_permanently_red(engine,clock):
    monitored(engine)
    envelope=claim(engine,clock)
    with engine.transaction() as db:
        db.execute("UPDATE jobs SET status='failed',attempts=? WHERE id=?",(engine.config['limits']['max_attempts'],envelope['job_id']))
        for _ in range(engine.config['limits']['max_attempts']): observe(db,'render',clock(),category='transient')
    assert engine.status()['health']['actionable']
    with engine.transaction() as db: observe(db,'render',clock())
    for _ in range(20):
        h=engine.status()['health']
        assert h['terminal_failed_jobs']==1 and not h['actionable']
        clock.now+=3600


def test_stuck_discovery_uses_real_progress_not_failed_refresh_and_respects_cooldown(engine,clock):
    monitored(engine)
    summary={'last_refresh':{'failures':[{'provider':'whop','category':'transient'}]},'cooldowns':{},'eligible_count':0,
             'pending_dependency_count':0,'unit_failures':[],'refresh_interrupted_or_in_progress':True,
             'scan':{'current_pass_provider_end':False,'last_successful_page':None,'last_progress':None,'first_refresh_started':clock()}}
    engine.discovery_status=lambda:summary
    assert not engine.status()['health']['actionable']
    clock.now+=121
    assert engine.status()['health']['actionable']
    summary['last_refresh']['finished_at']=clock() # failure alone is not progress
    assert engine.status()['health']['actionable']
    summary['cooldowns']['whop']=clock()+172800
    assert not engine.status()['health']['actionable']
    summary['cooldowns']={}
    summary['scan']['last_progress']={'recorded_at':clock(),'kind':'brief'}
    assert not engine.status()['health']['actionable']


@pytest.mark.parametrize('field',['model_calls','runtime_seconds'])
def test_prepare_daily_budget_wait_rolls_back_claim_and_reservation(native,field,monkeypatch,tmp_path):
    import json
    from typer.testing import CliRunner
    from tiktok_clipping_cli import main
    native.config['limits']['daily_'+field]=0
    path=tmp_path/'config.json';path.write_text(json.dumps(native.config))
    monkeypatch.setattr(main,'_native_engine',lambda *a,**k:native)
    result=CliRunner().invoke(main.app,['jobs','prepare','--kind','clip','--config',str(path),'--native-text',
                                      '--n8n-execution-id','123','--n8n-workflow-id','clip-native'])
    assert result.exit_code==0, result.output
    data=json.loads(result.stdout)
    assert data['state']=='waiting' and data['budget']==field and data['ready'] is False
    assert data['retry_at']==native.status()['health']['budget_window']['reset_at']
    with native.transaction() as db:
        assert db.execute("SELECT count(*) FROM jobs WHERE status='queued' AND lease_token IS NULL").fetchone()[0]==1
        assert db.execute('SELECT count(*) FROM text_attempts').fetchone()[0]==0
        table=db.execute("SELECT 1 FROM sqlite_master WHERE name='runtime_reservations'").fetchone()
        assert table is None or db.execute('SELECT count(*) FROM runtime_reservations').fetchone()[0]==0
        assert db.execute('SELECT coalesce(sum(model_calls+runtime_seconds),0) FROM budgets').fetchone()[0]==0
    model_root=native.workspace/'model'
    assert not model_root.exists()
    bad=CliRunner().invoke(main.app,['jobs','prepare','--kind','invalid','--config',str(path)])
    assert bad.exit_code!=0 and 'daily_budget_exhausted' not in bad.output


def test_budget_health_reset_is_utc_and_does_not_retime_existing_charges(engine,clock):
    monitored(engine)
    with engine.transaction() as db: engine._budget(db,'model_calls',engine.config['limits']['daily_model_calls'])
    h=engine.status()['health']
    assert h['state']=='budget_waiting' and h['budget_window']['timezone']=='UTC'
    assert h['budget_window']['exhausted']==['model_calls']
    old_day=h['budget_window']['day']
    clock.now=h['budget_window']['reset_at']+1
    assert engine.status()['health']['state']=='healthy'
    with engine.transaction() as db:
        assert db.execute('SELECT model_calls FROM budgets WHERE day=?',(old_day,)).fetchone()[0]==engine.config['limits']['daily_model_calls']


def test_budget_wait_keeps_previous_owned_reservation_honestly(native,monkeypatch,tmp_path):
    import json
    from typer.testing import CliRunner
    from tiktok_clipping_cli import main
    with native.transaction() as db:
        reservation=native._reserve_model_attempt(db,'prior-owned-attempt','clip',30)
        native._budget(db,'model_calls',native.config['limits']['daily_model_calls']-1)
        before=dict(db.execute('SELECT * FROM budgets').fetchone())
    path=tmp_path/'config.json';path.write_text(json.dumps(native.config))
    monkeypatch.setattr(main,'_native_engine',lambda *a,**k:native)
    result=CliRunner().invoke(main.app,['jobs','prepare','--kind','clip','--config',str(path),'--native-text'])
    assert result.exit_code==0 and json.loads(result.stdout)['state']=='waiting'
    with native.transaction() as db:
        assert dict(db.execute('SELECT * FROM budgets').fetchone())==before
        row=dict(db.execute('SELECT * FROM runtime_reservations').fetchone())
        assert row['id']==reservation['reservation_id'] and row['settled_at'] is None
        assert db.execute('SELECT count(*) FROM text_attempts').fetchone()[0]==0
