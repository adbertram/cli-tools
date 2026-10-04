"""Caller-owned inventory checkpoints and native transport boundaries."""
import copy
import json
import os
import subprocess

import pytest

from tiktok_cli.client import ClientError
from tiktok_cli.studio import SEMANTICS_JS, STUDIO_ITEMS_PATH, CAPTURE_JS, FETCH_JS
from tiktok_cli.studio_inventory import validate_request
from test_studio import FakePage, instance, OWNER, ID, page, raw_item

SEMANTICS = {"path": STUDIO_ITEMS_PATH, "size": 50,
             "query": {"sort_orders": [{"field_name": "post_time", "order": 2}],
                       "conditions": [], "is_recent_posts": False}}


class InventoryPage(FakePage):
    def __init__(self, responses, semantics=None):
        super().__init__(responses)
        self.semantics = SEMANTICS if semantics is None else semantics
        self.captures = 0
    def evaluate(self, script, value=None):
        if script == SEMANTICS_JS:
            return self.semantics
        if script == FETCH_JS and self.responses and isinstance(self.responses[0], dict) and "status" in self.responses[0] and "body" in self.responses[0]:
            self.requests.append(value)
            return self.responses.pop(0)
        if script == CAPTURE_JS:
            self.captures += 1
        return super().evaluate(script, value)


def feed(start, *, more, cursor, count=50, measured=1):
    value = page()
    value.update(item_list=[dict(raw_item(), item_id=str(i)) for i in range(start, start+count)],
                 has_more=more, cursor=cursor, extra={"now": measured})
    return value


def read(fake, ids, **kwargs):
    return instance(fake).get_studio_videos(OWNER['username'], ids, expected_account_id=OWNER['account_id'], **kwargs)


def test_batch_uses_one_capture_and_two_owner_checks_for_many_ids():
    fake = InventoryPage([feed(1, more=False, cursor=50)])
    client = instance(fake)
    result = client.get_studio_videos(OWNER['username'], ['1','2','99'], expected_account_id=OWNER['account_id'])
    assert [r['id'] for r in result['records']] == ['1','2']
    assert result['unresolved_ids'] == ['99'] and result['unresolved_state'] == 'unknown'
    assert result['provider_end'] and result['continuation'] is None
    assert not result['requested_complete']
    assert fake.captures == 1 and len(client.guards) == 2 and fake.cleaned


def test_checkpoint_resumes_beyond_1000_with_fresh_head_without_retiming_prior_matches():
    first = InventoryPage([feed(n*50+1, more=True, cursor=(n+1)*50, measured=n) for n in range(20)])
    initial = read(first, ['51','1001','9999'])
    old = initial['records'][0].copy()
    assert initial['continuation']['cursor'] == 1000
    assert initial['pages_read'] == 20
    second = InventoryPage([feed(1,more=True,cursor=50,measured=200), feed(1001,more=False,cursor=1050,measured=201)])
    final = read(second, ['9999','1001','51'], continuation=initial['continuation'])
    assert [c['cursor'] for c in second.requests] == [0,1000]
    assert [r['id'] for r in final['records']] == ['1001']
    assert final['records'][0]['server_timestamp_ms'] == 201
    assert old == initial['records'][0] and old['server_timestamp_ms'] == 1
    assert final['unresolved_ids'] == ['9999'] and final['provider_end']
    assert second.cleaned


def checkpoint():
    return read(InventoryPage([feed(1,more=True,cursor=50)]), ['1','99'], max_pages=1)['continuation']


@pytest.mark.parametrize('ids', [[],['0'],[1],[True],['1','1'],['1']*1001, '1', ('1',)])
def test_invalid_manifest_fails_before_browser(ids):
    fake=InventoryPage([])
    with pytest.raises(ClientError):read(fake, ids)
    assert fake.captures == 0 and not fake.requests


@pytest.mark.parametrize('field,value', [('cursor',True),('cursor',0),('cursor',2**53),('version',True),
    ('request_digest','bad'),('semantics_digest','z'*64),('found_ids',['99','99']),('found_ids',['999'])])
def test_invalid_checkpoint_fails_before_browser(field,value):
    cp=checkpoint();cp[field]=value
    fake=InventoryPage([])
    with pytest.raises(ClientError):read(fake,['1','99'],continuation=cp)
    assert fake.captures == 0


@pytest.mark.parametrize('change', ['actor','profile','ids','semantics'])
def test_changed_bindings_refuse_resume_without_fetch(change):
    cp=checkpoint();fake=InventoryPage([]);ids=['1','99']
    if change=='actor':cp['actor']['account_id']='2'
    if change=='profile':cp['actor']['profile']='other'
    if change=='ids':ids=['1','98']
    if change=='semantics':cp['semantics_digest']='0'*64
    with pytest.raises(ClientError,match='changed'):read(fake,ids,continuation=cp)
    assert not fake.requests


@pytest.mark.parametrize('change', ['conditions','recent','sort','size','extra'])
def test_unobserved_native_semantics_fail_closed(change):
    semantics=copy.deepcopy(SEMANTICS)
    if change=='conditions':semantics['query']['conditions']=[{'unknown':1}]
    if change=='recent':semantics['query']['is_recent_posts']=True
    if change=='sort':semantics['query']['sort_orders'][0]['order']=True
    if change=='size':semantics['size']=True
    if change=='extra':semantics['signed_token']='DO_NOT_OUTPUT'
    fake=InventoryPage([],semantics)
    with pytest.raises(ClientError,match='semantics changed'):read(fake,['1'])
    assert fake.cleaned and not fake.requests


@pytest.mark.parametrize('kind', ['nonadvancing','limited','malformed','duplicate','http'])
def test_provider_failure_never_reports_missing_or_deletion(kind):
    value=feed(1,more=True,cursor=50)
    if kind=='nonadvancing':value['cursor']=0
    if kind=='limited':value['is_limited']=True
    if kind=='malformed':value['extra']['now']=True
    if kind=='duplicate':value['item_list'][1]=value['item_list'][0]
    if kind=='http':value={'status':429,'body':'{}'}
    fake=InventoryPage([value])
    with pytest.raises(ClientError):read(fake,['99'])
    assert fake.cleaned


def test_owner_change_after_read_discards_result_and_cleans_capture():
    fake=InventoryPage([page()]);client=instance(fake);original=client.get_account
    def guard(**kwargs):
        if len(client.guards):raise ClientError('owner changed')
        return original(**kwargs)
    client.get_account=guard
    with pytest.raises(ClientError,match='owner changed'):
        client.get_studio_videos(OWNER['username'],[ID],expected_account_id=OWNER['account_id'])
    assert fake.cleaned


def test_bounded_regular_input_rejects_fifo_symlink_oversize_and_invalid_utf8(tmp_path):
    from tiktok_cli.commands.studio import _read_inventory_input
    fifo=tmp_path/'fifo';os.mkfifo(fifo)
    good=tmp_path/'good';good.write_text('["1"]')
    link=tmp_path/'link';link.symlink_to(good)
    large=tmp_path/'large';large.write_bytes(b' '*65537)
    invalid=tmp_path/'invalid';invalid.write_bytes(b'\xff')
    for path in (fifo,link,large,invalid):
        with pytest.raises(ClientError):_read_inventory_input(path)
    assert _read_inventory_input(good)==['1']


def run_node(script):
    result=subprocess.run(['node','-e',script],capture_output=True,text=True,timeout=10,check=True)
    return result.stdout.strip()


def test_native_capture_freezes_first_ready_request_and_never_exports_signed_material():
    script='''
    global.window={};global.location={href:'https://www.tiktok.com/tiktokstudio/content'};
    class XHR {open(){} setRequestHeader(){} send(){} addEventListener(n,f){this.finish=f}}
    global.XMLHttpRequest=XHR;
    const install=CAPTURE;install({key:'owned',path:'/tiktok/creator/manage/item_list/v1/',page_size:50});
    const body={cursor:0,size:50,query:{sort_orders:[{field_name:'post_time',order:2}],conditions:[],is_recent_posts:false}};
    let a=new XHR(),b=new XHR();a.open('POST','/tiktok/creator/manage/item_list/v1/?token=FIRST');a.send(JSON.stringify(body));
    b.open('POST','/tiktok/creator/manage/item_list/v1/?token=SECOND');b.send(JSON.stringify(body));
    a.status=b.status=200;a.responseType=b.responseType='';a.finish();b.finish();
    if(!window.owned.request.url.includes('FIRST'))throw Error('capture overwritten');
    const semantics=SEMANTICS;if(JSON.stringify(semantics('owned')).includes('token'))throw Error('secret exported');
    console.log('FROZEN_NO_SIGNING_EXPORT');
    '''.replace('CAPTURE','('+CAPTURE_JS+')').replace('SEMANTICS','('+SEMANTICS_JS+')')
    assert run_node(script)=='FROZEN_NO_SIGNING_EXPORT'


def test_native_fetch_streams_cancels_oversize_and_aborts_with_one_request():
    script='''
    let calls=0,cancels=0,releases=0,clears=0,aborts=0;
    global.window={owned:{request:{url:'https://www.tiktok.com/signed',headers:{},body:{cursor:0}}}};
    global.setTimeout=f=>{global.timer=f;return 1};global.clearTimeout=()=>clears++;
    global.AbortController=class{constructor(){this.signal={}}abort(){aborts++}};
    let parts=[];
    global.fetch=async(url,opts)=>{calls++;if(opts.redirect!=='error'||opts.method!=='POST')throw Error('unsafe fetch');
      return {status:200,body:{getReader(){return {async read(){return parts.length?{done:false,value:parts.shift()}:{done:true}},async cancel(){cancels++},releaseLock(){releases++}}}}};};
    (async()=>{const read=FETCH;
      parts=[new TextEncoder().encode('{}')];let a=await read({key:'owned',cursor:50,max_body:2});if(a.body!=='{}')throw Error('valid');
      parts=[new Uint8Array(3)];let b=await read({key:'owned',cursor:50,max_body:2});if(b.body!==null||cancels!==1)throw Error('uncancelled');
      global.fetch=async()=>{calls++;timer();throw new DOMException('PRIVATE','AbortError')};const c=await read({key:'owned',cursor:50,max_body:2});if(c.status!==0||c.transport!=='timeout'||JSON.stringify(c).includes('PRIVATE'))throw Error('timeout not sanitized');
      if(calls!==3||releases!==2||clears!==3||aborts!==1)throw Error('bound failed');console.log('STREAMED_CANCELLED_ONE_FETCH');
    })().catch(e=>{console.error(e);process.exitCode=1});
    '''.replace('const read=FETCH;', 'const read=('+FETCH_JS+');')
    assert run_node(script)=='STREAMED_CANCELLED_ONE_FETCH'


def test_cli_inventory_dispatches_manifest_and_checkpoint_then_closes(monkeypatch,tmp_path):
    from typer.testing import CliRunner
    from tiktok_cli.main import app
    import tiktok_cli.client as module
    manifest=tmp_path/'ids.json';manifest.write_text('["1","99"]')
    cp=checkpoint();checkpoint_file=tmp_path/'cp.json';checkpoint_file.write_text(json.dumps(cp))
    calls=[];closed=[]
    class Client:
        def get_studio_videos(self,username,ids,**kwargs):
            calls.append((username,ids,kwargs));return {'records':[],'unresolved_ids':['99'],'provider_end':False}
        def close(self):closed.append(True)
    monkeypatch.setattr(module,'get_web_client',Client)
    result=CliRunner().invoke(app,['studio','inventory',str(manifest),'--username',OWNER['username'],
        '--account-id',OWNER['account_id'],'--continuation',str(checkpoint_file),'--max-pages','2','--profile','clipper'])
    assert result.exit_code==0,result.output
    assert calls==[(OWNER['username'],['1','99'],{'expected_account_id':OWNER['account_id'],'continuation':cp,'max_pages':2})]
    assert closed==[True] and json.loads(result.stdout)['unresolved_ids']==['99']


def test_resumed_head_overlap_returns_current_actual_measurement_not_old_record():
    first=read(InventoryPage([feed(1,more=True,cursor=50,measured=1)]),['1','99'],max_pages=1)
    second=read(InventoryPage([feed(1,more=True,cursor=50,measured=2),feed(51,more=False,cursor=100,measured=3)]),
                ['1','99'],continuation=first['continuation'])
    assert {r['id']:r['server_timestamp_ms'] for r in second['records']}=={'1':2,'99':3}
    assert second['requested_complete'] and second['provider_end']
    assert first['records'][0]['server_timestamp_ms']==1


@pytest.mark.parametrize('value', [True,0,21,'2'])
def test_page_budget_fails_before_native_capture(value):
    fake=InventoryPage([])
    with pytest.raises(ClientError):read(fake,['1'],max_pages=value)
    assert fake.captures==0


def test_manifest_and_checkpoint_byte_bounds_fail_before_capture():
    fake=InventoryPage([])
    with pytest.raises(ClientError):read(fake,['1'+str(n).zfill(63) for n in range(1000)])
    cp=checkpoint();cp['actor']['username']='x'*65536
    with pytest.raises(ClientError):read(fake,['1','99'],continuation=cp)
    assert fake.captures==0


def test_profile_change_after_read_is_not_accepted(monkeypatch):
    fake=InventoryPage([page()]);client=instance(fake);original=client.get_account
    def guard(**kwargs):
        result=original(**kwargs)
        if len(client.guards)>1:result['profile']='other'
        return result
    client.get_account=guard
    with pytest.raises(ClientError,match='profile changed'):
        client.get_studio_videos(OWNER['username'],[ID],expected_account_id=OWNER['account_id'])
    assert fake.cleaned


@pytest.mark.parametrize('status,category',[(429,'rate_limit'),(503,'transient'),(401,'auth'),(403,'auth')])
def test_typed_provider_failures_preserve_minimum_delay_without_body_leak(status,category):
    fake=InventoryPage([{'status':status,'body':'SECRET_SESSION_MATERIAL','retryAfter':'172801'}])
    with pytest.raises(ClientError) as failure:read(fake,['1'])
    error=failure.value
    assert error.category==category and error.code==f'studio_http_{status}' and error.status==status
    assert error.retry_after_seconds==172801 and error.retry_after==172801
    assert 'SECRET' not in str(error) and fake.cleaned


def test_http_date_retry_after_and_malformed_values():
    from datetime import datetime,timezone
    from tiktok_cli.studio import retry_after_seconds
    now=datetime(2026,10,4,tzinfo=timezone.utc)
    assert retry_after_seconds('Tue, 06 Oct 2026 00:00:01 GMT',now)==172801
    for value in ('inf','-1',1,None,'x'*201,'NaN'):
        assert retry_after_seconds(value,now) is None


def test_transport_timeout_is_typed_and_not_retried():
    fake=InventoryPage([{'status':0,'body':None,'transport':'timeout'}])
    with pytest.raises(ClientError) as failure:read(fake,['1'])
    assert failure.value.category=='transient' and failure.value.code=='studio_transport_timeout'
    assert len(fake.requests)==1 and fake.cleaned


def test_worst_case_checkpoint_capacity_rejects_valid_64k_manifest_before_browser():
    ids=['1'+str(n).zfill(63) for n in range(950)]
    assert len(json.dumps(ids,separators=(',',':')).encode())<65536
    fake=InventoryPage([])
    with pytest.raises(ClientError,match='continuation capacity'):read(fake,ids)
    assert fake.captures==0


def test_native_http_failure_returns_only_typed_header_status_without_reading_body():
    script='''
    global.window={owned:{request:{url:'https://www.tiktok.com/signed',headers:{},body:{cursor:0}}}};
    let cancelled=0;global.fetch=async()=>({status:429,headers:{get:k=>'172801'},body:{async cancel(){cancelled++},getReader(){throw Error('error body read')}}});
    (async()=>{const read=FETCH;const result=await read({key:'owned',cursor:0,max_body:8});
      if(result.status!==429||result.retryAfter!=='172801'||result.body!==null||cancelled!==1)throw Error('metadata lost');console.log('ONLY_TYPED_HEADER');
    })().catch(e=>{console.error(e);process.exitCode=1});
    '''.replace('const read=FETCH;','const read=('+FETCH_JS+');')
    assert run_node(script)=='ONLY_TYPED_HEADER'


def test_error_stream_cancel_failure_preserves_provider_cooldown_without_read():
    script='''
    global.window={owned:{request:{url:'https://www.tiktok.com/signed',headers:{},body:{cursor:0}}}};
    global.fetch=async()=>({status:503,headers:{get:k=>'172801'},body:{async cancel(){throw Error('PRIVATE')},getReader(){throw Error('read')}}});
    (async()=>{const read=FETCH;const result=await read({key:'owned',cursor:0,max_body:8});
      if(result.status!==503||result.retryAfter!=='172801'||JSON.stringify(result).includes('PRIVATE'))throw Error('cooldown lost');console.log('CANCEL_FAILURE_SANITIZED');
    })().catch(e=>{console.error(e);process.exitCode=1});
    '''.replace('const read=FETCH;','const read=('+FETCH_JS+');')
    assert run_node(script)=='CANCEL_FAILURE_SANITIZED'
