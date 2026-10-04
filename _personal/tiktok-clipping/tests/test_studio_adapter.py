"""Real coordinator mutations cannot pass the immediate public-action callback."""
from copy import deepcopy
import hashlib

import pytest

from conftest import claim,payload
from tiktok_clipping_cli.engine import decoded_job
from tiktok_clipping_cli.safety import SafetyError,canonical,digest
from tiktok_clipping_cli.studio_adapter import StudioPublicActionGuard,publication_request_id,studio_reservation_identity


def guard_fixture(engine, config, adapter, clock):
    envelope=claim(engine,clock)
    engine.apply(payload(envelope),execute=False)
    proposal=engine.get(envelope['job_id'])['proposal']
    asset=adapter.render(engine.get(envelope['job_id']),proposal)
    key=digest({'account_id':config['account']['account_id'],'asset_digest':asset['sha256']})
    with engine.transaction() as db:
        db.execute("UPDATE jobs SET status='running',stage='publish',asset=?,lease_until=? WHERE id=?",(canonical(asset),clock()+120,envelope['job_id']))
        db.execute("INSERT INTO publications VALUES(?,?,?,?,?,'uploading',NULL,1)",(key,envelope['job_id'],config['account']['account_id'],asset['sha256'],key))
        job=decoded_job(engine._job(db,envelope['job_id']))
    policy={'caption':proposal['caption'],'music_rights_confirmed':True}
    actor={'account_id':config['account']['account_id'],'username':'ata_clipper','profile':'clipper'}
    binding={'request_id':publication_request_id(key),'asset_sha256':asset['sha256'],'policy_digest':digest(policy),'actor':actor,'draft_id':'EXACT','project_id':'0'}
    with engine.transaction() as db:
        db.execute('UPDATE publications SET data=? WHERE job_id=?',(canonical(studio_reservation_identity(binding)),job['id']))
    pending={**binding,'draft':{'creation_id':'EXACT','video_id':'EXACT_MEDIA'},'state':'dispatch_pending','public_action_dispatched':False,'policy':policy,'binding':digest({'asset_sha256':asset['sha256'],'policy':policy})}
    guard=StudioPublicActionGuard(config,job,asset,key,policy,deepcopy(pending),lambda request:deepcopy(pending),clock=clock)
    return guard,binding,pending,job,asset,key


def test_callback_reads_real_reserved_job_and_public_get_stays_redacted(engine,config,adapter,clock):
    guard,binding,_,job,_,_=guard_fixture(engine,config,adapter,clock)
    assert 'lease_token' not in engine.get(job['id'])
    assert engine._adapter_job(job['id'],job['lease_token'])['lease_token']==job['lease_token']
    guard(binding)
    with engine.transaction() as db:
        row=db.execute('SELECT state,data FROM publications WHERE job_id=?',(job['id'],)).fetchone()
        assert row['state']=='dispatch_pending'
        assert 'dispatch_authorized_at' in row['data']


@pytest.mark.parametrize('change', ['expired','reclaimed','control','asset','policy','input','proposal','reservation_state','reservation_account','reservation_hash','reservation_key','stage','status'])
def test_changed_authoritative_state_blocks_post(engine,config,adapter,clock,change):
    guard,binding,_,job,asset,key=guard_fixture(engine,config,adapter,clock)
    with engine.transaction() as db:
        if change=='expired':db.execute('UPDATE jobs SET lease_until=? WHERE id=?',(clock(),job['id']))
        elif change=='reclaimed':db.execute('UPDATE jobs SET lease_token=? WHERE id=?',('another-live-worker',job['id']))
        elif change=='control':db.execute("UPDATE settings SET value='paused' WHERE key='control'")
        elif change=='asset':db.execute('UPDATE jobs SET asset=? WHERE id=?',(canonical({**asset,'sha256':'f'*64}),job['id']))
        elif change=='policy':db.execute('UPDATE jobs SET policy_digest=? WHERE id=?',('changed',job['id']))
        elif change=='input':db.execute('UPDATE jobs SET input=? WHERE id=?',(canonical({'changed':True}),job['id']))
        elif change=='proposal':db.execute('UPDATE jobs SET proposal=? WHERE id=?',(canonical({'changed':True}),job['id']))
        elif change=='reservation_state':db.execute("UPDATE publications SET state='ambiguous'")
        elif change=='reservation_account':db.execute("UPDATE publications SET account_id='FOREIGN'")
        elif change=='reservation_hash':db.execute("UPDATE publications SET asset_digest='FOREIGN'")
        elif change=='reservation_key':db.execute("UPDATE publications SET idempotency_key='FOREIGN'")
        elif change=='stage':db.execute("UPDATE jobs SET stage='render'")
        elif change=='status':db.execute("UPDATE jobs SET status='ready'")
    sends=[]
    with pytest.raises(SafetyError):
        guard(binding)
        sends.append('Post')
    assert sends==[]
    if change in ['expired','reclaimed']:
        with pytest.raises(SafetyError,match='worker_lease_changed'):engine._adapter_job(job['id'],job['lease_token'])


@pytest.mark.parametrize('field,value',[('request_id','OTHER'),('asset_sha256','OTHER'),('policy_digest','OTHER'),('actor',{}),('draft_id','OTHER'),('project_id','OTHER')])
def test_private_operation_binding_cannot_authorize_other_media(engine,config,adapter,clock,field,value):
    guard,binding,_,_,_,_=guard_fixture(engine,config,adapter,clock)
    binding[field]=value
    with pytest.raises(SafetyError):guard(binding)


@pytest.mark.parametrize('change', [{'state':'prepared'},{'public_action_dispatched':True},{'draft':{'creation_id':'OTHER'}},{'policy':{}},{'binding':'OTHER'}])
def test_private_journal_boundary_cannot_be_substituted(engine,config,adapter,clock,change):
    guard,binding,pending,_,_,_=guard_fixture(engine,config,adapter,clock)
    pending.update(change)
    with pytest.raises(SafetyError):guard(binding)


def test_request_uuid_is_stable_from_exact_idempotency_key():
    key=hashlib.sha256(b'publication').hexdigest()
    assert publication_request_id(key)==publication_request_id(key)
    with pytest.raises(SafetyError):publication_request_id('arbitrary UUID or command')


def test_lease_expiry_during_dispatch_second_worker_reconciles_without_second_post(engine,config,adapter,clock):
    guard,binding,_,job,_,_=guard_fixture(engine,config,adapter,clock)
    sends=[]
    guard(binding)
    sends.append('one native Post')
    clock.now+=121
    from tiktok_clipping_cli.engine import Engine
    second=Engine(config,adapter=adapter,clock=clock)
    with second.transaction() as db:second._recover(db)
    assert second.run(job['id'])['state']=='ambiguous'
    assert adapter.uploads==[]
    # A delayed original receipt is read back, never another public mutation.
    result=second.reconcile(job['id'])
    assert result['state']=='published'
    assert sends==['one native Post'] and adapter.uploads==[]


def test_original_worker_failure_cannot_overwrite_reclaimed_live_job(engine,config,adapter,clock):
    _,_,_,job,_,_=guard_fixture(engine,config,adapter,clock)
    with engine.transaction() as db:db.execute("UPDATE jobs SET lease_token='another-worker' WHERE id=?",(job['id'],))
    from tiktok_clipping_cli.engine import AdapterFailure
    result=engine._fail(job['id'],'publish',AdapterFailure('ambiguous','lost transport'),job['lease_token'])
    assert result['reason']=='worker_lease_lost'
    with engine.transaction() as db:
        current=engine._job(db,job['id'])
        assert current['status']=='running' and current['lease_token']=='another-worker'
        assert db.execute('SELECT state FROM publications WHERE job_id=?',(job['id'],)).fetchone()[0]=='uploading'


class SDK:
    def __init__(self, operation, clock):
        self.operation=operation
        self.clock=clock
        self.calls=[]
        self.fail=None
        self.close_fail=False

    def status(self, request):
        self.calls.append('status')
        if self.operation is None:raise KeyError('missing journal')
        return deepcopy(self.operation)

    def prepare(self, path, policy, request):
        self.calls.append('prepare')
        if self.fail=='prepare':raise TimeoutError()
        return deepcopy(self.operation)

    def publish(self, request, *, before_public_action):
        self.calls.append('publish')
        self.operation['state']='dispatch_pending'
        binding={k:self.operation[k] for k in ('request_id','asset_sha256','policy_digest','actor','draft_id','project_id')}
        before_public_action(binding)
        self.calls.append('native-send')
        self.operation['public_action_dispatched']=True
        self.operation['post_project_id']='123'
        self.operation['state']='project_accepted'
        if self.fail=='post':raise TimeoutError()
        return self.reconcile(request)

    def reconcile(self, request):
        self.calls.append('reconcile')
        if self.fail=='pending':return deepcopy(self.operation)
        op=self.operation
        op.update(state='published_verified',item_id='1234',url='https://www.tiktok.com/@ata_clipper/video/1234')
        op['verification']={'id':op['item_id'],'url':op['url'],'account_id':op['actor']['account_id'],'author':op['actor']['username'],
            'profile':op['actor']['profile'],'caption':op['policy']['caption'],'visibility':1,'posted_at':int(self.clock()),'provenance':'TEST exact Studio readback'}
        return deepcopy(op)

    def close(self):
        self.calls.append('close')
        if self.close_fail:raise TimeoutError('close')


def bridge_fixture(engine, config, adapter, clock):
    from tiktok_clipping_cli.studio_adapter import StudioPublicationAdapter
    _,binding,operation,job,asset,key=guard_fixture(engine,config,adapter,clock)
    policy={'schema_version':1,'profile':'clipper','account_id':config['account']['account_id'],'username':'ata_clipper',
        'caption':job['proposal']['caption'],'audience':'Everyone','timing':'now','disclosure':'branded_content','music_rights_confirmed':True}
    operation.update(policy=policy,policy_digest=digest(policy),binding=digest({'asset_sha256':asset['sha256'],'policy':policy}),state='prepared')
    sdk=SDK(operation,clock)
    with engine.transaction() as db:db.execute('UPDATE publications SET data=NULL')
    bridge=StudioPublicationAdapter(config,publisher_factory=lambda:sdk,clock=clock)
    return bridge,sdk,job,asset,key,policy


def test_sdk_bridge_uses_one_session_and_durable_dispatch_guard(engine,config,adapter,clock):
    bridge,sdk,job,asset,key,policy=bridge_fixture(engine,config,adapter,clock)
    receipt=bridge.publish(job,asset,key,policy)
    assert receipt['publication_id']=='1234'
    assert sdk.calls==['status','prepare','publish','status','native-send','reconcile','close']
    with engine.transaction() as db:
        row=db.execute('SELECT state,data FROM publications').fetchone()
        assert row['state']=='dispatch_pending'
        assert publication_request_id(key) in row['data']


@pytest.mark.parametrize('phase,category',[('prepare','transient'),('post','ambiguous')])
def test_sdk_bridge_classifies_only_exact_pre_action_proof(engine,config,adapter,clock,phase,category):
    from tiktok_clipping_cli.engine import AdapterFailure
    bridge,sdk,job,asset,key,policy=bridge_fixture(engine,config,adapter,clock)
    sdk.fail=phase
    with pytest.raises(AdapterFailure) as failure:bridge.publish(job,asset,key,policy)
    assert failure.value.category==category
    assert sdk.calls.count('native-send')==(phase=='post')
    assert sdk.calls[-1]=='close'


def test_accepted_receipt_after_close_failure_reconciles_without_prepare_or_send(engine,config,adapter,clock):
    from tiktok_clipping_cli.engine import AdapterFailure
    bridge,sdk,job,asset,key,policy=bridge_fixture(engine,config,adapter,clock)
    sdk.close_fail=True
    with pytest.raises(AdapterFailure) as failure:bridge.publish(job,asset,key,policy)
    assert failure.value.category=='ambiguous'
    sdk.close_fail=False
    sdk.calls=[]
    result=bridge.reconcile(job,asset,key,policy)
    assert result['state']=='published'
    assert sdk.calls==['status','reconcile','close']


def test_persistent_close_issue_retains_verified_publication_in_reconciliation(engine,config,adapter,clock):
    from tiktok_clipping_cli.engine import AdapterFailure
    bridge,sdk,job,asset,key,policy=bridge_fixture(engine,config,adapter,clock)
    sdk.close_fail=True
    with pytest.raises(AdapterFailure):bridge.publish(job,asset,key,policy)
    sdk.calls=[]
    result=bridge.reconcile(job,asset,key,policy)
    assert result['state']=='published'
    assert 'studio_browser_close_failed' in result['publication']['provenance']
    assert 'prepare' not in sdk.calls and 'native-send' not in sdk.calls


@pytest.mark.parametrize('state', ['dispatch_pending','project_accepted','project_pending','project_failed','outcome_unknown'])
def test_existing_uncertain_operation_never_prepares_or_posts_again(engine,config,adapter,clock,state):
    from tiktok_clipping_cli.engine import AdapterFailure
    bridge,sdk,job,asset,key,policy=bridge_fixture(engine,config,adapter,clock)
    sdk.operation['state']=state
    sdk.operation['public_action_dispatched']=state!='dispatch_pending'
    sdk.fail='pending'
    with pytest.raises(AdapterFailure) as failure:bridge.publish(job,asset,key,policy)
    assert failure.value.category=='ambiguous'
    assert 'prepare' not in sdk.calls and 'publish' not in sdk.calls and 'native-send' not in sdk.calls


@pytest.mark.parametrize('change', ['missing','wrong_hash','wrong_policy','wrong_actor','dispatch_pending','dispatched','pre_action'])
def test_absence_requires_exact_journal_and_explicit_pre_action_boundary(engine,config,adapter,clock,change):
    bridge,sdk,job,asset,key,policy=bridge_fixture(engine,config,adapter,clock)
    if change=='missing':sdk.operation=None
    elif change=='wrong_hash':sdk.operation['asset_sha256']='f'*64
    elif change=='wrong_policy':sdk.operation['policy']={}
    elif change=='wrong_actor':sdk.operation['actor']={}
    elif change=='dispatch_pending':sdk.operation['state']='dispatch_pending';sdk.fail='pending'
    elif change=='dispatched':sdk.operation['public_action_dispatched']=True;sdk.fail='pending'
    result=bridge.reconcile(job,asset,key,policy)
    assert result['state']==('absent' if change=='pre_action' else 'unknown')
    assert 'native-send' not in sdk.calls and 'prepare' not in sdk.calls


def test_policy_music_confirmation_is_never_defaulted(engine,config,adapter,clock):
    bridge,sdk,job,asset,key,policy=bridge_fixture(engine,config,adapter,clock)
    del policy['music_rights_confirmed']
    with pytest.raises(Exception):bridge.publish(job,asset,key,policy)
    assert sdk.calls==[]
