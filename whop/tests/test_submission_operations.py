import json
import os
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4
import pytest
from cli_tools_shared.exceptions import ClientError
from whop_cli.client import WhopClient,READ_ACTIONS
from whop_cli import submission_operations as op

ACTOR='user_TEST';TIKTOK='7692213003349443597';CAMPAIGN='campaign_TEST';REQUEST='9b3f4dc5-1072-4d2a-9738-3a1a6a275dce'

@pytest.fixture
def client(tmp_path):
    config=SimpleNamespace(rewards_url='https://example.apps.whop.com/c/exp_TEST',get_browser=lambda:Mock(),get_active_profile_name=lambda:'rewards',get_profile_data_dir=lambda:tmp_path)
    c=WhopClient(config)
    c.account=Mock(return_value={'id':ACTOR,'username':'whopuser','profile':'rewards'})
    c.linked_accounts=Mock(return_value=[{'accountId':TIKTOK,'platform':'tiktok','status':'active','username':'ata_clipper','id':'linked_TEST'}])
    c.campaign=Mock(return_value={'id':CAMPAIGN,'name':'Test','description':'Actual requirements','referenceMaterials':[],'platforms':['tiktok'],'status':'active','private':False,'requiresApplication':False,
       'payouts':[{'platform':'tiktok','payoutType':'cpm','rateCents':100,'minPayoutCents':100,'maxPayoutCents':35000,'budgetCents':15000,'spentCents':0}]})
    c._rest=Mock(return_value={'data':[{'campaignId':CAMPAIGN,'creatorMaxReached':False,'intake':'open','platformIntake':{'tiktok':'open'}}]})
    c._action_document=Mock(return_value=Mock())
    c._discover_action=Mock(return_value='a'*40)
    c._action=Mock(return_value={'success':True,'data':[],'nextCursor':None})
    return c

@pytest.fixture
def receipt():
    return {'publication_id':'1234567890123456789','publication_url':'https://www.tiktok.com/@ata_clipper/video/1234567890123456789','account_id':TIKTOK,'handle':'ata_clipper',
       'published_at':(datetime.now(timezone.utc)-timedelta(minutes=1)).replace(microsecond=0).isoformat(),
       'provenance':op.canonical({'kind':'studio_verified','request_id':REQUEST,'post_project_id':'123','asset_sha256':'a'*64,'policy_digest':'b'*64,'readback':op.STUDIO_READBACK})}

def stored(c):
    with op.journal_lock(c.config) as db: return op.load(db,REQUEST)

def ready(c,**kwargs):
    return c.submission_readiness(CAMPAIGN,expected_account_id=ACTOR,expected_tiktok_account_id=TIKTOK,**kwargs)

def send(c,receipt,request=REQUEST,**kwargs):
    requirements=ready(c)['requirements_digest']
    return c.create_submission(request,CAMPAIGN,receipt,expected_account_id=ACTOR,expected_tiktok_account_id=TIKTOK,accepted_requirements_digest=requirements,confirm=kwargs.pop('confirm',True),**kwargs)

def remote(receipt,id='submission_TEST'):
    return {'id':id,'campaignId':CAMPAIGN,'status':'pending','socialMediaPost':{'platform':'tiktok','postId':receipt['publication_id']}}

def test_ready_binds_actual_brief_and_excludes_mutable_spend(client):
    first=ready(client)
    client.campaign.return_value['payouts'][0]['spentCents']=100
    assert ready(client)['requirements_digest']==first['requirements_digest']
    client.campaign.return_value['description']='Changed brief'
    with pytest.raises(ClientError,match='requirements_changed'):ready(client,expected_requirements_digest=first['requirements_digest'])
    assert READ_ACTIONS=={'listSocialMediaAccounts','listMySubmissionsAction','countMySubmissionsAction'}

@pytest.mark.parametrize('field,value,match',[('status','closed','not_active'),('requiresApplication',True,'application_required'),('private',True,'not_active'),('platforms',['youtube'],'not_tiktok'),('description',None,'schema_changed')])
def test_campaign_readiness_closed_or_unknown(client,field,value,match):
    client.campaign.return_value[field]=value
    with pytest.raises(ClientError,match=match):ready(client)
    client._action_document.assert_not_called()

def test_actor_and_linked_guard(client):
    client.account.return_value['id']='user_OTHER'
    with pytest.raises(ClientError,match='actor_changed'):ready(client)
    client.account.return_value['id']=ACTOR
    client.linked_accounts.return_value[0]['status']='inactive'
    with pytest.raises(ClientError,match='linked_tiktok'):ready(client)
    client.linked_accounts.return_value*=2
    with pytest.raises(ClientError,match='linked_tiktok'):ready(client)

@pytest.mark.parametrize('key,value',[('creatorMaxReached',True),('creatorMaxReached',None),('intake','closed'),('platformIntake',{'tiktok':'closed'})])
def test_closed_intake_fails(client,key,value):
    client._rest.return_value['data'][0][key]=value
    with pytest.raises(ClientError,match='intake_not_open'):ready(client)

def test_no_funding(client):
    client.campaign.return_value['payouts'][0]['spentCents']=15000
    with pytest.raises(ClientError,match='not_funded'):ready(client)

def test_dynamic_form_chunk_loaded_only_after_missing_action(client):
    client._discover_action.side_effect=[ClientError('read_action_discovery_missing: sources=60, matches=0, failures=0'),'b'*40]
    document=client._action_document.return_value;document.evaluate.side_effect=[True,True]
    assert ready(client)['action']['reference']=='b'*40
    assert client._discover_action.call_count==2
    assert document.evaluate.call_args_list[0].kwargs['request_timeout']==2
    assert document.evaluate.call_args_list[1].kwargs['request_timeout']==12

def test_failed_form_predicate_survives_close_with_typed_safe_diagnostics(client):
    client._discover_action.side_effect=ClientError('read_action_discovery_missing: sources=60, matches=0, failures=0')
    facts={'origin':'https://example.apps.whop.com','path':'/c/exp_TEST/campaigns/'+CAMPAIGN,
           'ready_state':'complete','exact_buttons':2,'enabled_buttons':0,
           'visible_buttons':1,'visible_enabled_buttons':0,'dialogs':1,'private_body':'SECRET'}
    document=client._action_document.return_value
    document.evaluate.return_value={'opened':False,'diagnostics':facts}
    with pytest.raises(op.WhopError,match='submission_form_unavailable') as caught:ready(client)
    client.close()
    error=caught.value
    assert error.category=='transient' and error.status is None and error.retry_after_seconds is None
    assert error.diagnostics=={'kind':'submission_form_predicate','available':True,'context_origin':'expected_app','route_match':True,
        **{k:v for k,v in facts.items() if k!='private_body'}}
    assert 'SECRET' not in json.dumps(error.diagnostics)
    assert document.evaluate.call_count==1
    assert not hasattr(client,'_submission_context')

@pytest.mark.parametrize('change',[{'origin':'https://whop.com'}, {'path':'/auth/SECRET?token=SECRET'},
    {'ready_state':'SECRET'},{'exact_buttons':True},{'dialogs':100001}])
def test_form_diagnostics_reject_unscoped_or_malformed_values(change):
    origin='https://example.apps.whop.com';path='/c/exp_TEST/campaigns/'+CAMPAIGN
    raw={'origin':origin,'path':path,'ready_state':'complete','exact_buttons':0,'enabled_buttons':0,
        'visible_buttons':0,'visible_enabled_buttons':0,'dialogs':0,**change}
    error=op.form_failure({'opened':False,'diagnostics':raw},origin,path)
    assert error.diagnostics['available'] is False
    assert error.diagnostics['context_origin']==('whop_wrapper' if raw['origin']=='https://whop.com' else 'expected_app')
    assert error.diagnostics['route_match']==(raw['origin']==origin and raw['path']==path)
    assert 'SECRET' not in json.dumps(error.diagnostics)

@pytest.mark.parametrize('origin',['https://evil.test/SECRET?token=SECRET',None])
def test_form_diagnostics_other_origin_is_enum_only(origin):
    error=op.form_failure({'opened':False,'diagnostics':{'origin':origin,'path':'/SECRET'}},
                         'https://example.apps.whop.com','/c/exp_TEST/campaigns/'+CAMPAIGN)
    assert error.diagnostics=={'kind':'submission_form_predicate','available':False,
                              'context_origin':'other_or_missing','route_match':False}
    assert 'SECRET' not in json.dumps(error.diagnostics)

@pytest.mark.parametrize('buttons,clicked',[
    ([],0),([{'disabled':True,'visible':True}],0),
    ([{'disabled':False,'visible':True},{'disabled':False,'visible':False}],0),
    ([{'disabled':False,'visible':False}],1),
])
def test_actual_js_atomic_form_predicate_counts_and_unchanged_click(buttons,clicked):
    import subprocess
    script='''let clicks=0;
    globalThis.location={origin:'https://example.apps.whop.com',pathname:'/c/exp_TEST/campaigns/campaign_TEST',search:'?token=SECRET',hash:'#SECRET'};
    const buttons='''+json.dumps(buttons)+'''.map(b=>({...b,innerText:'Submit clip',
       getBoundingClientRect:()=>({width:b.visible?10:0,height:10}),click:()=>{clicks++}}));
    globalThis.getComputedStyle=()=>({display:'block',visibility:'visible'});
    globalThis.document={readyState:'interactive',querySelectorAll:s=>s==='button'?buttons:[{}]};
    const result=('''+op.OPEN_SUBMISSION_FORM_JS+''')();
    console.log(JSON.stringify({result,clicks}));'''
    run=subprocess.run(['node','--input-type=module'],input=script,text=True,capture_output=True,timeout=3)
    assert run.returncode==0,run.stderr
    result=json.loads(run.stdout)
    assert result['clicks']==clicked
    if clicked:assert result['result'] is True
    else:
        facts=result['result']['diagnostics']
        assert facts['exact_buttons']==len(buttons)
        assert facts['enabled_buttons']==sum(not b['disabled'] for b in buttons)
        assert facts['visible_buttons']==sum(b['visible'] for b in buttons)
        assert facts['visible_enabled_buttons']==sum(b['visible'] and not b['disabled'] for b in buttons)
        assert 'SECRET' not in run.stdout

@pytest.mark.parametrize('code',['ambiguous','script_fetch_failed','scripts_changed'])
def test_discovery_failure_does_not_open_form(client,code):
    client._discover_action.side_effect=ClientError('read_action_discovery_'+code+': diagnostic')
    with pytest.raises(ClientError):ready(client)
    client._action_document.return_value.evaluate.assert_not_called()

@pytest.mark.parametrize('key,value',[('publication_id','0'),('account_id','123'),('publication_url','https://evil.test/video/123'),('handle','ata_clipper?'),('published_at','2026-10-04'),('published_at','2026-10-04T00:00:00+01:00'),('provenance','{}')])
def test_receipt_strict_binding(client,receipt,key,value):
    receipt[key]=value
    with pytest.raises(ClientError):send(client,receipt)
    client._action_document.return_value.evaluate.assert_not_called()

@pytest.mark.parametrize('age',[-10,1801])
def test_publication_age_checked_after_callback(client,receipt,age):
    receipt['published_at']=(datetime.now(timezone.utc)-timedelta(seconds=age)).replace(microsecond=0).isoformat()
    callback=Mock(return_value=True)
    with pytest.raises(ClientError,match='30_minute'):send(client,receipt,confirm=callback)
    callback.assert_called_once();client._action_document.return_value.evaluate.assert_not_called()

def test_callback_pause_retains_reserved_without_dispatch(client,receipt):
    callback=Mock(return_value=False)
    with pytest.raises(ClientError,match='confirmation_required'):send(client,receipt,confirm=callback)
    row=stored(client)
    assert row['state']=='reserved' and row['public_action_dispatched'] is False
    client._action_document.return_value.evaluate.assert_not_called()

@pytest.mark.parametrize('response',[{'status':429,'text':'private'},{'status':500,'text':'private'},{'status':0,'errorClass':'TimeoutError'}, {'status':200,'text':'garbage'}])
def test_uncertain_write_never_replayed(client,receipt,response,monkeypatch):
    document=client._action_document.return_value;document.evaluate.return_value=response
    first=send(client,receipt)
    assert first['state']=='uncertain' and first['public_action_dispatched'] is True
    second=send(client,receipt)
    assert second['state']=='uncertain' and document.evaluate.call_count==1
    assert 'private' not in op.canonical(second)
    monkeypatch.setattr(op.time,'time',lambda:10**12)
    row=remote(receipt);client._action.return_value={'success':True,'data':[row],'nextCursor':None}
    result=client.reconcile_submission(REQUEST)
    assert result['state']=='submitted_verified' and result['submission']['status']=='pending'
    assert result['submission']['totalEarnedCents'] is None
    assert document.evaluate.call_count==1

def test_changed_request_or_second_uuid_cannot_write(client,receipt):
    client._action_document.return_value.evaluate.return_value={'status':0}
    send(client,receipt)
    changed=dict(receipt,publication_id='123',publication_url='https://www.tiktok.com/@ata_clipper/video/123')
    with pytest.raises(ClientError,match='binding_changed'):send(client,changed)
    with pytest.raises(ClientError,match='already_reserved'):send(client,receipt,request=str(uuid4()))
    assert client._action_document.return_value.evaluate.call_count==1

def test_success_needs_exact_readback_and_id(client,receipt):
    document=client._action_document.return_value
    document.evaluate.return_value={'status':200,'text':'0:{"a":"$@1"}\n1:{"success":true,"data":{"id":"submission_TEST"}}'}
    replies=[{'data':[],'nextCursor':None}]*2+[{'data':[remote(receipt)],'nextCursor':None}]
    client._action.side_effect=replies
    result=send(client,receipt)
    assert result['state']=='submitted_verified' and result['submission_id']=='submission_TEST'
    assert document.evaluate.call_count==1
    assert document.evaluate.call_args.kwargs['request_timeout']==22
    body=document.evaluate.call_args.args[1]['body']
    assert body==[{'campaignId':CAMPAIGN,'url':receipt['publication_url']}]

def test_duplicate_remote_rows_rejected(client,receipt):
    client._action.return_value={'data':[remote(receipt),remote(receipt,'submission_OTHER')],'nextCursor':None}
    with pytest.raises(ClientError,match='duplicate_remote'):send(client,receipt)
    assert client._action_document.return_value.evaluate.call_count==1

def test_reconciliation_exact_post_and_campaign_only(client,receipt):
    client._action_document.return_value.evaluate.return_value={'status':0}
    send(client,receipt)
    rows=[remote(dict(receipt,publication_id='987')),dict(remote(receipt),campaignId='other')]
    client._action.return_value={'data':rows,'nextCursor':None}
    assert client.reconcile_submission(REQUEST)['state']=='uncertain'
    client.account.return_value['id']='user_OTHER'
    with pytest.raises(ClientError,match='actor_changed'):client.reconcile_submission(REQUEST)

def test_crash_after_durable_dispatch_cannot_resend(client,receipt):
    client._action_document.return_value.evaluate.side_effect=KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):send(client,receipt)
    assert stored(client)['state']=='dispatching'
    client._action_document.return_value.evaluate.reset_mock()
    assert send(client,receipt)['state']=='uncertain'
    client._action_document.return_value.evaluate.assert_not_called()

def test_private_journal_rejects_symlink_and_foreign_mode(client,receipt,tmp_path):
    root=tmp_path/'submission-operations';root.mkdir(mode=0o700)
    outside=tmp_path/'outside';outside.write_text('unchanged')
    (root/'operations.sqlite3').symlink_to(outside)
    with pytest.raises(ClientError,match='file_unsafe'):send(client,receipt)
    assert outside.read_text()=='unchanged'
    (root/'operations.sqlite3').unlink();root.chmod(0o755)
    with pytest.raises(ClientError,match='directory_unsafe'):send(client,receipt)

def test_publication_receipt_file_bounded_and_nofollow(tmp_path,receipt):
    path=tmp_path/'receipt.json';path.write_text(op.canonical(receipt))
    assert op.read_receipt(path)==receipt
    link=tmp_path/'link';link.symlink_to(path)
    with pytest.raises(ClientError):op.read_receipt(link)
    path.write_text('x'*65537)
    with pytest.raises(ClientError):op.read_receipt(path)

def test_bounded_campaign_recovery_continues_without_a_history_cap(client,receipt):
    calls=[]
    def page(name,args,suffix):
        calls.append(args[0]);return {'data':[{'id':'unrelated'}]*50,'nextCursor':'cursor'+str(len(calls))}
    client._action.side_effect=page
    client._action_document.return_value.evaluate.return_value={'status':0}
    first=send(client,receipt)
    assert first['state']=='uncertain' and first['inspection_complete'] is False
    cursor=first['reconciliation']['cursor']
    # Next pass refreshes head, then resumes the persisted position.
    count=len(calls);second=client.reconcile_submission(REQUEST)
    assert calls[count].get('cursor') is None and calls[count+1]['cursor']==cursor
    assert second['reconciliation']['cursor']!=cursor
    assert client._action_document.return_value.evaluate.call_count==1

def test_cursor_cycle_and_oversized_page_fail_closed(client,receipt):
    client._action.return_value={'data':[{}],'nextCursor':'same'}
    client._action_document.return_value.evaluate.return_value={'status':0}
    with pytest.raises(ClientError,match='cursor_cycle'):send(client,receipt)
    client._action.return_value={'data':[{}]*51,'nextCursor':None}
    with pytest.raises(ClientError,match='schema_changed'):send(client,receipt)
    assert client._action_document.return_value.evaluate.call_count==1

def test_rejected_provider_response_never_resends(client,receipt):
    document=client._action_document.return_value
    document.evaluate.return_value={'status':200,'text':'0:{"a":"$@1"}\n1:{"success":false,"code":"SUBMISSIONS_ON_HOLD","error":"private"}'}
    row=send(client,receipt)
    assert row['state']=='rejected' and row['failure_code']=='SUBMISSIONS_ON_HOLD'
    assert send(client,receipt)['state']=='rejected' and document.evaluate.call_count==1
    assert 'private' not in op.canonical(row)

def test_crash_before_dispatch_leaves_reservation_retryable(client,receipt,monkeypatch):
    original=op.save
    def fail(root,row):
        if row['state']=='dispatching': raise OSError('disk unavailable')
        return original(root,row)
    monkeypatch.setattr(op,'save',fail)
    with pytest.raises(OSError):send(client,receipt)
    client._action_document.return_value.evaluate.assert_not_called()
    assert stored(client)['state']=='reserved'

def test_lock_is_exclusive_and_readiness_does_not_create_journal(client,receipt):
    ready(client)
    root=client.config.get_profile_data_dir()/'submission-operations'
    assert not root.exists()
    with op.journal_lock(client.config):
        with pytest.raises(ClientError,match='busy'):send(client,receipt)
    with op.journal_lock(client.config) as db:
        assert db.execute('SELECT count(*) FROM operations').fetchone()[0]==0

def test_cli_confirmation_guard_before_receipt_or_client(monkeypatch):
    from typer.testing import CliRunner
    from whop_cli.commands import submissions
    read=Mock();monkeypatch.setattr(submissions,'read',read)
    result=CliRunner().invoke(submissions.app,['create',REQUEST,CAMPAIGN,'--publication-receipt','missing.json','--expected-account-id',ACTOR,'--expected-tiktok-account-id',TIKTOK,'--requirements-digest','a'*64])
    assert result.exit_code!=0 and 'submission_confirmation_required' in result.stderr
    read.assert_not_called()

def test_discovery_budget_and_unseen_script_failure():
    assert 'AbortSignal.timeout(10000)' in op.SUBMISSION_DISCOVERY_JS
    assert 'size>8000000||total>32000000' in op.SUBMISSION_DISCOVERY_JS
    assert "failures||signal.aborted?'script_fetch_failed'" in op.SUBMISSION_DISCOVERY_JS


def test_complete_linked_registry_required_before_ready(client):
    client.linked_accounts.side_effect=ClientError('linked_accounts_inspection_incomplete')
    with pytest.raises(ClientError,match='inspection_incomplete'):ready(client)
    client.linked_accounts.assert_called_once_with(1000,require_complete=True)

@pytest.mark.parametrize('field,value',[('account_id','user_OTHER'),('campaign_id','other_campaign'),('requirements_digest','c'*64)])
def test_existing_uuid_rejects_changed_explicit_binding(client,receipt,field,value):
    client._action_document.return_value.evaluate.return_value={'status':0}
    row=send(client,receipt)
    bound=dict(row['binding']);bound[field]=value
    with pytest.raises(ClientError,match='binding_changed'):
        client.create_submission(REQUEST,bound['campaign_id'],receipt,expected_account_id=bound['account_id'],expected_tiktok_account_id=TIKTOK,accepted_requirements_digest=bound['requirements_digest'],confirm=True)
    assert client._action_document.return_value.evaluate.call_count==1

def test_unknown_provenance_rejected_but_known_close_issue_preserved(receipt):
    provenance=json.loads(receipt['provenance']);provenance['cleanup_issue']={'kind':'studio_browser_close_failed','error_type':'TimeoutError','recoverable':True}
    receipt['provenance']=op.canonical(provenance)
    assert op.publication(receipt,TIKTOK)['provenance']==receipt['provenance']
    provenance['unexpected']='private';receipt['provenance']=op.canonical(provenance)
    with pytest.raises(ClientError,match='provenance_invalid'):op.publication(receipt,TIKTOK)

def test_created_id_cannot_adopt_a_different_matching_row(client,receipt):
    client._action_document.return_value.evaluate.return_value={'status':200,'text':'0:{"a":"$@1"}\n1:{"success":true,"data":{"id":"submission_EXPECTED"}}'}
    client._action.side_effect=[{'data':[],'nextCursor':None}]*2+[{'data':[remote(receipt)],'nextCursor':None}]
    with pytest.raises(ClientError,match='binding_changed'):send(client,receipt)
    with op.journal_lock(client.config) as root:
        row=op.load(root,REQUEST)
    assert row['state']=='created_unverified' and row['submission_id']=='submission_EXPECTED'

def test_fifo_database_refused_without_blocking(client,tmp_path):
    root=tmp_path/'submission-operations';root.mkdir(mode=0o700)
    os.mkfifo(root/'operations.sqlite3',0o600)
    with pytest.raises(ClientError,match='file_unsafe'):
        with op.journal_lock(client.config):pass

def test_more_than_1000_indexed_operations_do_not_stop(client,receipt):
    requirements=ready(client)['requirements_digest']
    bound=op.binding(client,CAMPAIGN,receipt,ACTOR,TIKTOK,requirements)
    with op.journal_lock(client.config) as db:
        for index in range(1005):
            item=json.loads(op.canonical(bound));item['publication']['publication_id']=str(100000+index)
            row={'version':1,'request_id':str(uuid4()),'binding':item,'state':'reserved','public_action_dispatched':False}
            op.save(db,row)
        assert db.execute('SELECT count(*) FROM operations').fetchone()[0]==1005
        assert op.load(db,row['request_id'])==row
        plan=db.execute('EXPLAIN QUERY PLAN SELECT request_id FROM operations WHERE actor=? AND experience=? AND campaign=? AND post=?',(ACTOR,bound['experience'],CAMPAIGN,'100004')).fetchall()
        assert any('INDEX' in str(value) for value in plan)

def test_callback_cannot_replace_captured_action_context(client,receipt):
    first=client._action_document.return_value
    first.evaluate.return_value={'status':0}
    other=Mock()
    def callback(snapshot):
        client._submission_context=(other,'b'*40,'/c/exp_OTHER')
        return True
    result=send(client,receipt,confirm=callback)
    assert result['state']=='uncertain'
    first.evaluate.assert_called_once();other.evaluate.assert_not_called()

@pytest.mark.parametrize('raw,expected',[('172801',172801),('900000',900000),('bad',None),('-1',None),('1.5',None)])
def test_retry_after_preserves_provider_minimum(raw,expected):
    from whop_cli.client import retry_after_seconds
    assert retry_after_seconds(raw)==expected

def test_retry_after_http_date_and_typed_read_error(client):
    from whop_cli.client import retry_after_seconds,WhopError
    now=datetime(2026,10,4,tzinfo=timezone.utc)
    assert retry_after_seconds('Tue, 06 Oct 2026 00:00:01 GMT',now)==172801
    page=Mock();page.evaluate.return_value={'status':429,'retryAfter':'172801'}
    with pytest.raises(WhopError) as caught:client._request(page,'/read')
    assert caught.value.category=='rate_limit' and caught.value.status==429 and caught.value.retry_after_seconds==172801
    assert page.evaluate.call_count==1

def test_uncertain_receipt_keeps_retry_after_without_retry(client,receipt):
    document=client._action_document.return_value
    document.evaluate.return_value={'status':429,'retryAfter':'172801','text':'private'}
    row=send(client,receipt)
    assert row['failure']=={'code':'http_429','category':'rate_limit','status':429,'retry_after_seconds':172801}
    assert stored(client)['failure']==row['failure']
    assert document.evaluate.call_count==1

def test_response_stream_is_cancelled_at_byte_limit():
    import subprocess
    from whop_cli.client import FETCH_JS
    script='''let reads=0,cancels=0,calls=0;
    globalThis.fetch=async()=>{calls++;return {status:429,headers:{get:()=> '172801'},body:{getReader:()=>({read:async()=>{reads++;if(reads>1)throw Error('over-read');return {done:false,value:new Uint8Array(8000001)}},cancel:async()=>{cancels++}})}}};
    const fn=('''+FETCH_JS+''');const result=await fn({path:'/owned',action:'a',body:[]});
    if(calls!==1||reads!==1||cancels!==1||result.text!==null||result.retryAfter!=='172801')throw Error('byte-bound failure');
    '''
    result=subprocess.run(['node','--input-type=module'],input=script,text=True,capture_output=True,timeout=3)
    assert result.returncode==0,result.stderr

def test_unknown_recovery_paginates_beyond_1000_with_fresh_head(client,receipt):
    calls=[]
    def page(name,args,suffix):
        query=args[0];calls.append(query)
        index=int(query.get('cursor','0'))
        rows=[{'id':'unrelated'}]*50 if index<22 else [remote(receipt)]
        return {'data':rows,'nextCursor':str(index+1) if index<22 else None}
    client._action.side_effect=page
    client._action_document.return_value.evaluate.return_value={'status':0}
    first=send(client,receipt)
    assert first['reconciliation']['cursor']=='11' and first['state']=='uncertain'
    second=client.reconcile_submission(REQUEST)
    assert second['reconciliation']['cursor']=='21' and second['state']=='uncertain'
    third=client.reconcile_submission(REQUEST)
    assert third['state']=='submitted_verified' and third['submission_id']=='submission_TEST'
    assert all(q.get('campaignId')==CAMPAIGN and 'status' not in q and 'isDeleted' not in q for q in calls)
    assert client._action_document.return_value.evaluate.call_count==1

def test_visibility_after_complete_pass_restarts_at_head(client,receipt):
    client._action_document.return_value.evaluate.return_value={'status':0}
    first=send(client,receipt)
    assert first['state']=='uncertain' and first['reconciliation']['completed_scans']==1
    client._action.return_value={'data':[remote(receipt)],'nextCursor':None}
    assert client.reconcile_submission(REQUEST)['state']=='submitted_verified'
    assert client._action_document.return_value.evaluate.call_count==1

def test_known_id_verifies_head_without_full_campaign_scan(client,receipt):
    document=client._action_document.return_value
    document.evaluate.return_value={'status':200,'text':'0:{"a":"$@1"}\n1:{"success":true,"data":{"id":"submission_TEST"}}'}
    client._action.side_effect=[{'data':[],'nextCursor':None}]*2+[{'data':[remote(receipt)],'nextCursor':'still_more'}]
    result=send(client,receipt)
    assert result['state']=='submitted_verified' and result['inspection_complete'] is False
    assert client._action.call_count==3

def test_cursor_progress_survives_interruption(client,receipt):
    document=client._action_document.return_value;document.evaluate.return_value={'status':0}
    def page(name,args,suffix):
        cursor=args[0].get('cursor')
        if cursor=='2':raise KeyboardInterrupt()
        return {'data':[{'id':'unrelated'}],'nextCursor':'1' if cursor is None else '2'}
    client._action.side_effect=page
    with pytest.raises(KeyboardInterrupt):send(client,receipt)
    assert stored(client)['reconciliation']['cursor']=='2'
    seen=[]
    def resume(name,args,suffix):
        seen.append(args[0].get('cursor'))
        return {'data':[],'nextCursor':None} if args[0].get('cursor') is None else {'data':[remote(receipt)],'nextCursor':None}
    client._action.side_effect=resume
    result=client.reconcile_submission(REQUEST)
    assert seen==[None,'2'] and result['state']=='submitted_verified'
    assert document.evaluate.call_count==1

def test_rate_limit_cooldown_persists_before_any_new_read(client,receipt,monkeypatch):
    monkeypatch.setattr(op.time,'time',lambda:1000)
    document=client._action_document.return_value;document.evaluate.return_value={'status':429,'retryAfter':'172801'}
    row=send(client,receipt)
    assert row['retry_not_before']==173801
    client.account.reset_mock();client._action.reset_mock()
    assert client.reconcile_submission(REQUEST)['state']=='uncertain'
    client.account.assert_not_called();client._action.assert_not_called()
    monkeypatch.setattr(op.time,'time',lambda:173801)
    client._action.return_value={'data':[remote(receipt)],'nextCursor':None}
    assert client.reconcile_submission(REQUEST)['state']=='submitted_verified'
    assert document.evaluate.call_count==1

def test_non_head_rate_limit_does_not_poison_resume_cursor(client,receipt,monkeypatch):
    from whop_cli.client import WhopError
    monkeypatch.setattr(op.time,'time',lambda:1000)
    document=client._action_document.return_value;document.evaluate.return_value={'status':0}
    def page(name,args,suffix):
        cursor=args[0].get('cursor')
        if cursor=='2':raise WhopError('upstream_read_failed_http_429',category='rate_limit',status=429,retry_after_seconds=20)
        return {'data':[{'id':'unrelated'}],'nextCursor':'1' if cursor is None else '2'}
    client._action.side_effect=page
    row=send(client,receipt)
    assert row['reconciliation']['cursor']=='2' and row['retry_not_before']==1020
    monkeypatch.setattr(op.time,'time',lambda:1020)
    seen=[]
    def resume(name,args,suffix):
        cursor=args[0].get('cursor');seen.append(cursor)
        return {'data':[],'nextCursor':None} if cursor is None else {'data':[remote(receipt)],'nextCursor':None}
    client._action.side_effect=resume
    assert client.reconcile_submission(REQUEST)['state']=='submitted_verified'
    assert seen==[None,'2'] and document.evaluate.call_count==1

def test_known_match_page_is_revisited_and_absence_does_not_fake_freshness(client,receipt):
    document=client._action_document.return_value
    document.evaluate.return_value={'status':200,'text':'0:{"a":"$@1"}\n1:{"success":true,"data":{"id":"submission_TEST"}}'}
    client._action.side_effect=[{'data':[],'nextCursor':None}]*2+[{'data':[{'id':'unrelated'}],'nextCursor':'target'},{'data':[remote(receipt)],'nextCursor':'later'}]
    row=send(client,receipt)
    assert row['state']=='submitted_verified' and row['reconciliation']['match_page_cursor']=='target'
    observed=row['observed_at'];seen=[]
    def refresh(name,args,suffix):
        cursor=args[0].get('cursor');seen.append(cursor)
        return {'data':[remote(receipt)] if cursor=='target' else [{'id':'unrelated'}],'nextCursor':'target' if cursor is None else 'later'}
    client._action.side_effect=refresh
    assert client.reconcile_submission(REQUEST)['readback_fresh'] is True
    assert seen==[None,'target']
    before=stored(client)['observed_at']
    client._action.side_effect=None;client._action.return_value={'data':[],'nextCursor':None}
    result=client.reconcile_submission(REQUEST)
    assert result['state']=='submitted_verified' and result['readback_fresh'] is False
    assert result['observed_at']==before
