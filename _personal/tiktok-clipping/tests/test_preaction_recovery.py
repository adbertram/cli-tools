"""Durable readiness failures cannot lose diagnostics or replay public work."""
from copy import deepcopy
import pytest
from conftest import claim, payload
from tiktok_clipping_cli.engine import AdapterFailure
from tiktok_clipping_cli.safety import SafetyError, canonical


DIAGNOSTIC = {'kind':'submission_form_predicate','available':True,'context_origin':'expected_app','route_match':True,
    'origin':'https://abc123.apps.whop.com','path':'/c/exp_fixture/campaigns/188c3e39-7850-4896-94df-e7a5be0cfec3',
    'ready_state':'complete','exact_buttons':0,'enabled_buttons':0,'visible_buttons':0,'visible_enabled_buttons':0,'dialogs':0}


@pytest.mark.parametrize('change', [lambda d:d.update(text='secret'), lambda d:d.update(origin='https://other.example'),
    lambda d:d.update(path=d['path']+'?secret=1'),lambda d:d.update(dialogs=True),lambda d:d.update(dialogs=100001),
    lambda d:d.update(context_origin='arbitrary'),lambda d:d.update(available=False),lambda d:d.update(route_match=False)])
def test_diagnostics_refuse_unbounded_or_unapproved_fields(change):
    data=deepcopy(DIAGNOSTIC);change(data)
    with pytest.raises((SafetyError,ValueError)):
        AdapterFailure('transient','whop:submission_form_unavailable', diagnostics=data)


def failed_visual(engine,adapter,clock,legacy=False):
    envelope=claim(engine,clock)
    engine.apply(payload(envelope),execute=False)
    job=engine.get(envelope['job_id'])
    asset=adapter.render(job,job['proposal'])
    with engine.transaction() as db:
        db.execute("UPDATE jobs SET status='running',stage='visual',asset=?,lease_token='fixture',lease_until=? WHERE id=?",(canonical(asset),clock()+120,job['id']))
    failure=AdapterFailure('permanent','whop:submission_form_unavailable',provider='whop',code='submission_form_unavailable',diagnostics=DIAGNOSTIC)
    assert engine._fail(job['id'],'verify_ready',failure,'fixture')['state']=='failed'
    if legacy:
        with engine.transaction() as db:
            db.execute("UPDATE events SET data=? WHERE job_id=? AND event='adapter_failure'",(canonical({'category':'permanent','stage':'verify_ready','state':'failed'}),job['id']))
    return job['id']


def test_diagnostics_persist_and_revalidate_without_budget_or_asset_reset(engine,adapter,clock):
    job=failed_visual(engine,adapter,clock)
    before=engine.get(job)
    assert before['last_failure']['diagnostics']==DIAGNOSTIC
    with engine.transaction() as db: budgets=[tuple(r) for r in db.execute('SELECT * FROM budgets')]
    with pytest.raises(SafetyError,match='pre_publication_proof'):engine.retry(job)
    clock.now+=121
    assert engine.retry(job)['state']=='ready'
    after=engine.get(job)
    assert all(before[k]==after[k] for k in ('attempts','revisions','asset','proposal','input'))
    assert after['last_failure']==before['last_failure']
    with engine.transaction() as db:assert budgets==[tuple(r) for r in db.execute('SELECT * FROM budgets')]
    assert adapter.uploads==[]


def test_observed_legacy_readiness_failure_requires_exact_job_event(engine,adapter,clock):
    job=failed_visual(engine,adapter,clock,legacy=True);clock.now+=121
    assert engine.retry(job)['state']=='ready'


@pytest.mark.parametrize('history',['publication','approval','dispatch','missing_proof','binding_changed','wrong_stage','ambiguous','attempts_exhausted','asset_changed'])
def test_recovery_denies_public_or_unproven_history(engine,adapter,clock,config,history):
    job=failed_visual(engine,adapter,clock);clock.now+=121
    with engine.transaction() as db:
        if history=='publication':db.execute("INSERT INTO publications VALUES(?,?,?,?,?,'absent',NULL,1)",('p',job,'actor','hash','key'))
        elif history=='approval':db.execute("INSERT INTO visual_attempts(id,job_id,state,envelope,created_at,expires_at) VALUES(?,?,'approved','{}',?,?)",('a',job,clock(),clock()))
        elif history=='dispatch':engine.event(db,job,'upload_started',{})
        elif history=='missing_proof':db.execute("DELETE FROM events WHERE job_id=?",(job,))
        elif history=='binding_changed':db.execute("UPDATE jobs SET proposal_digest='changed' WHERE id=?",(job,))
        elif history=='wrong_stage':db.execute("UPDATE jobs SET stage='publish' WHERE id=?",(job,))
        elif history=='ambiguous':db.execute("UPDATE jobs SET status='ambiguous' WHERE id=?",(job,))
        elif history=='attempts_exhausted':db.execute("UPDATE jobs SET attempts=? WHERE id=?",(config['limits']['max_attempts'],job))
    if history=='asset_changed':
        from pathlib import Path
        Path(engine.get(job)['asset']['path']).write_bytes(b'changed')
    with pytest.raises(SafetyError):engine.retry(job)
    assert adapter.uploads==[]


def test_actual_live_boundary_keeps_diagnostic_after_close(engine,config):
    from types import SimpleNamespace
    from tiktok_clipping_cli.live import LiveAdapter
    config['rewards_account']={'account_id':'user_fixture','username':'fixture','profile':'rewards','verified_at':config['account']['verified_at'],'provenance':'TEST'}
    config['sources'][0]['campaign']['id']='188c3e39-7850-4896-94df-e7a5be0cfec3'
    class Client:
        config=SimpleNamespace(rewards_url='https://abc123.apps.whop.com/c/exp_fixture')
        submission_readiness=create_submission=reconcile_submission=lambda *a:None
        closed=False
        def close(self):self.closed=True
    client=Client()
    failure=SimpleNamespace(category='transient',code='submission_form_unavailable',status=None,retry_after_seconds=None,diagnostics=DIAGNOSTIC)
    class Error(Exception):pass
    error=Error('fixed');error.__dict__.update(vars(failure))
    def fail(_):raise error
    with pytest.raises(AdapterFailure) as caught:LiveAdapter(config,whop_factory=lambda:client)._participant_call(fail)
    assert client.closed and caught.value.category=='transient' and caught.value.diagnostics==DIAGNOSTIC
