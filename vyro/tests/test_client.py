from types import SimpleNamespace
import pytest
from cli_tools_shared.exceptions import ClientError
from vyro_cli.client import VyroClient, bounded_limit, slug_path


def client(responses):
    c = VyroClient(config=SimpleNamespace(), browser=SimpleNamespace(close=lambda: None))
    calls = []
    def get(path):
        calls.append(path)
        return responses.pop(0)
    c._get = get
    return c, calls


@pytest.mark.parametrize('value', [0, -1, 1001, True, '1', None])
def test_limit_rejects_invalid_input(value):
    with pytest.raises(ClientError):
        bounded_limit(value)


@pytest.mark.parametrize('value', ['', '../auth/me', 'a?b', 'a/b', 'x'*201, None])
def test_slug_cannot_escape_route(value):
    with pytest.raises(ClientError):
        slug_path(value)


def test_native_fields_and_pagination_preserved():
    extra = {'requirements': {'text': {'hashtags': ['#example']}}, 'budget': {'remaining': 1.5}}
    c, calls = client([
        {'data': [{'id': 'one', **extra}], 'meta': {'page': {'next': 2}}},
        {'data': [{'id': 'two'}], 'meta': {'page': {'next': None}}},
    ])
    result = c.campaigns(2)
    assert result[0]['requirements'] == extra['requirements']
    assert len(result) == 2
    assert calls == ['/catalog/campaigns?sort=startDate.desc&limit=2&page=1', '/catalog/campaigns?sort=startDate.desc&limit=1&page=2']


@pytest.mark.parametrize('page', [
    {'data': [], 'meta': {'page': {'next': 2}}},
    {'data': [{'id': 'one'}], 'meta': {'page': {'next': 1}}},
    {'data': [{'id': 'one'}], 'meta': {'page': {'next': '2'}}},
    {'data': [{'id': 'one'}, {'id': 'one'}], 'meta': {'page': {'next': None}}},
    {'data': ['bad'], 'meta': {'page': {'next': None}}},
])
def test_malformed_campaign_pages_fail(page):
    c, _ = client([page])
    with pytest.raises(ClientError):
        c.campaigns(10)


def test_repeated_ids_across_pages_fail():
    c, _ = client([{'data':[{'id':'one'}], 'meta':{'page':{'next':2}}}, {'data':[{'id':'one'}], 'meta':{'page':{'next':None}}}])
    with pytest.raises(ClientError, match='duplicate'):
        c.campaigns(2)


def test_oversized_campaign_page_is_not_silently_truncated():
    c, _ = client([{'data':[{'id':'one'}, {'id':'two'}], 'meta':{'page':{'next':None}}}])
    with pytest.raises(ClientError, match='exceeds'):
        c.campaigns(1)


def test_no_linked_social_accounts_is_valid_empty_data():
    c, _ = client([{'data':[], 'meta':{'page':{'next':None}}}])
    assert c.social_accounts() == []


def test_social_pagination_fails_instead_of_omitting_accounts():
    c, _ = client([{'data':[], 'meta':{'page':{'next':2}}}])
    with pytest.raises(ClientError, match='pagination'):
        c.social_accounts()


@pytest.mark.parametrize('meta', [None, [], {'page': None}, {'page': []}])
@pytest.mark.parametrize('method', ['campaigns', 'social_accounts'])
def test_malformed_pagination_is_client_error(meta, method):
    c, _ = client([{'data': [], 'meta': meta}])
    with pytest.raises(ClientError, match='pagination'):
        getattr(c, method)()


def test_requirements_digest_changes_for_rules_but_not_live_budget():
    from vyro_cli.client import requirements_digest
    row = {'id':'campaign', 'requirements':{'text':{'hashtags':['#one']}},
           'targeting':{'platforms':['tiktok']}, 'payoutModel':{'model':'CPM','payRate':2},
           'budget':{'remaining':100}, 'media':{'links':[{'url':'https://example.com/a'}]}}
    original = requirements_digest(row)
    row['budget']['remaining'] = 99
    assert requirements_digest(row) == original
    row['requirements']['text']['hashtags'] = ['#two']
    assert requirements_digest(row) != original


@pytest.mark.parametrize('url', ['https://evil.com/@ata_clipper/video/123',
    'https://www.tiktok.com/@someone/video/123', 'https://www.tiktok.com/@ata_clipper/video/not-id',
    'http://www.tiktok.com/@ata_clipper/video/123', 'https://www.tiktok.com@evil.com/@ata_clipper/video/123'])
def test_submission_url_refuses_unbound_post(url):
    from vyro_cli.client import tiktok_post
    with pytest.raises(ClientError):
        tiktok_post(url, 'ata_clipper')


def test_submission_url_canonicalizes_tracking_query():
    from vyro_cli.client import tiktok_post
    assert tiktok_post('https://www.tiktok.com/@ata_clipper/video/123?x=tracking', '@ata_clipper') == ('https://www.tiktok.com/@ata_clipper/video/123', '123')


def test_actor_requires_exact_vyro_id_social_id_and_username():
    c, _ = client([])
    c.account = lambda: {'id':'actor'}
    row = {'id':'social','platform':'tiktok','platformUsername':'ata_clipper','status':{'id':'active'}, 'platformUserId':'opaque'}
    c.social_accounts = lambda: [row]
    assert c.actor('actor','social','@ata_clipper') == row
    for args in [('wrong','social','ata_clipper'),('actor','wrong','ata_clipper'),('actor','social','someone')]:
        with pytest.raises(ClientError): c.actor(*args)
    row['status']['id']='disabled'
    with pytest.raises(ClientError): c.actor('actor','social','ata_clipper')


@pytest.mark.parametrize('reply', [{'status':503}, {'error':'vyro_request_failed'}])
def test_write_never_retries_ambiguous_failure(reply):
    calls=[]
    urls=[]
    def evaluate(*args):
        calls.append(args)
        return reply
    browser=SimpleNamespace(get_page=lambda url: urls.append(url) or SimpleNamespace(evaluate=evaluate))
    c=VyroClient(config=SimpleNamespace(), browser=browser)
    with pytest.raises(ClientError): c._request('/clips/v2', 'POST', {}, 'actor')
    assert len(calls)==1
    assert urls == ['https://app.vyro.com/favicon.ico']
    assert calls[0][1]['expectedAccountId']=='actor'


def test_write_browser_exception_marks_outcome_unknown():
    def evaluate(*args): raise RuntimeError('private implementation details')
    browser=SimpleNamespace(get_page=lambda _: SimpleNamespace(evaluate=evaluate))
    c=VyroClient(config=SimpleNamespace(), browser=browser)
    with pytest.raises(ClientError, match='outcome_unknown_reconcile'):
        c._request('/clips/v2','POST',{},'actor')


def submission_client(tmp_path):
    c,_=client([])
    c.config=SimpleNamespace(get_profile_data_dir=lambda:tmp_path)
    social={'id':'social','platform':'tiktok','platformUserId':'opaque','platformUsername':'ata_clipper','status':{'id':'active'}}
    campaign={'id':'a'*24,'enrolled':True,'isLocked':False,'status':{'id':'active'},'targeting':{'platforms':['tiktok']},'budget':{'remaining':1},'requirements':{},'type':'clipping','startDate':'2020-01-01T00:00:00Z','endDate':'2099-01-01T00:00:00Z'}
    c.actor=lambda *args:social
    c.campaign=lambda slug:campaign
    c.eligibility=lambda slug:{'inviteMode':'open','eligibleAccounts':[]}
    c._get=lambda path:{'isBlocked':False} if 'throttle' in path else {'currentCount':0,'limit':5}
    return c,campaign,social


def test_readiness_distinguishes_join_from_restrictions(tmp_path):
    c,campaign,_=submission_client(tmp_path)
    assert c.readiness('slug','actor','social','ata_clipper')['ready']
    campaign['enrolled']=False
    c._get=lambda path:pytest.fail('member-only limits must not be read before enrollment')
    state=c.readiness('slug','actor','social','ata_clipper')
    assert state['reason']=='campaign_not_joined'
    assert state['rate_limit'] is None
    assert state['throttle'] is None
    campaign['budget']['remaining']=0
    assert c.readiness('slug','actor','social','ata_clipper')['reason']=='campaign_budget_unavailable'


def test_reconcile_requires_exact_campaign_and_opaque_account(tmp_path):
    c,campaign,social=submission_client(tmp_path)
    url='https://www.tiktok.com/@ata_clipper/video/123'
    receipt={'id':'r','campaignId':campaign['id'],'platform':'tiktok','platformUserId':'opaque','videoUrl':url}
    c.submissions=lambda *a,**kw:[receipt]
    assert c.reconcile('slug',url,'actor','social','ata_clipper')['status']=='existing'
    receipt['platformUserId']='wrong'
    with pytest.raises(ClientError,match='identity_mismatch'):c.reconcile('slug',url,'actor','social','ata_clipper')


def test_submission_marker_survives_failure_and_prevents_repeat(tmp_path):
    from vyro_cli.client import requirements_digest
    c,campaign,_=submission_client(tmp_path)
    c.reconcile=lambda *a:{'status':'not_found','submission':None}
    writes=[]
    def request(path,*args):
        if path.endswith('pre-check'):return {}
        writes.append(path)
        raise ClientError('timeout')
    c._request=request
    args=('slug','https://www.tiktok.com/@ata_clipper/video/123',requirements_digest(campaign),'actor','social','ata_clipper',True)
    assert c.create_submission(*args)['status']=='uncertain'
    assert c.create_submission(*args)['status']=='uncertain'
    assert writes==['/clips/v2']
    assert len(list((tmp_path/'vyro-submissions').glob('*.json')))==1


def test_submission_requires_rules_digest_before_any_dispatch(tmp_path):
    c,_,_=submission_client(tmp_path)
    c.reconcile=lambda *a:{'status':'not_found','submission':None}
    c._request=lambda *a:pytest.fail('must not dispatch')
    with pytest.raises(ClientError,match='digest_changed'):
        c.create_submission('slug','https://www.tiktok.com/@ata_clipper/video/123','wrong','actor','social','ata_clipper',True)


def test_precheck_required_fields_fail_closed():
    from vyro_cli.client import validate_precheck
    campaign={'requirements':{'video':{'minLength':20}}}
    with pytest.raises(ClientError,match='videoLength'):validate_precheck({},campaign)
    with pytest.raises(ClientError,match='videoLength'):validate_precheck({'videoLength':{'applicable':True,'pass':False}},campaign)
    validate_precheck({'videoLength':{'applicable':True,'pass':True}},campaign)


def test_concurrent_create_dispatches_at_most_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from vyro_cli.client import requirements_digest
    barrier=Barrier(2)
    writes=[]
    def run():
        c,campaign,_=submission_client(tmp_path)
        c.reconcile=lambda *a:{'status':'not_found','submission':None}
        def request(path,*args):
            if path.endswith('pre-check'):
                barrier.wait(timeout=3)
                return {}
            writes.append(path)
            raise ClientError('timeout')
        c._request=request
        return c.create_submission('slug','https://www.tiktok.com/@ata_clipper/video/123',requirements_digest(campaign),'actor','social','ATA_CLIPPER',True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(run) for _ in range(2)]
        results=[f.result() for f in futures]
    assert writes==['/clips/v2']
    assert all(r['status']=='uncertain' for r in results)


def test_receipt_reconciliation_prevents_dispatch_even_without_local_marker(tmp_path):
    c,_,_=submission_client(tmp_path)
    c.reconcile=lambda *a:{'status':'existing','submission':{'id':'receipt'}}
    c._request=lambda *a:pytest.fail('duplicate must not dispatch')
    assert c.create_submission('slug','https://www.tiktok.com/@ata_clipper/video/123','old-digest','actor','social','ata_clipper',True)['status']=='existing'


def test_changed_rules_after_precheck_prevent_dispatch(tmp_path):
    from vyro_cli.client import requirements_digest
    c,campaign,_=submission_client(tmp_path)
    c.reconcile=lambda *a:{'status':'not_found','submission':None}
    digest=requirements_digest(campaign)
    def request(path,*args):
        assert path.endswith('pre-check')
        campaign['requirements']={'text':{'hashtags':['#new']}}
        return {'hashtags':{'applicable':True,'pass':True}}
    c._request=request
    with pytest.raises(ClientError,match='digest_changed'):
        c.create_submission('slug','https://www.tiktok.com/@ata_clipper/video/123',digest,'actor','social','ata_clipper',True)
    assert not (tmp_path/'vyro-submissions').exists()


@pytest.mark.parametrize('value', [None, '', '   ', 123])
def test_actor_requires_native_platform_identity(value):
    c,_=client([])
    c.account=lambda:{'id':'actor'}
    c.social_accounts=lambda:[{'id':'social','platform':'tiktok','platformUsername':'ata_clipper','platformUserId':value,'status':{'id':'active'}}]
    with pytest.raises(ClientError,match='missing_linked_platform_user_id'):
        c.actor('actor','social','ata_clipper')


def test_max_length_only_requires_precheck():
    from vyro_cli.client import validate_precheck
    with pytest.raises(ClientError,match='videoLength'):
        validate_precheck({}, {'requirements':{'video':{'maxLength':40}}})


@pytest.mark.parametrize('missing', ['campaignId','platform','platformUserId','videoUrl'])
def test_reconcile_cannot_claim_absence_from_incomplete_rows(tmp_path,missing):
    c,campaign,_=submission_client(tmp_path)
    row={'id':'receipt','campaignId':campaign['id'],'platform':'tiktok','platformUserId':'opaque','videoUrl':'https://www.tiktok.com/@ata_clipper/video/123'}
    del row[missing]
    c.submissions=lambda *a,**kw:[row]
    with pytest.raises(ClientError,match='incomplete_submission_receipt'):
        c.reconcile('slug','https://www.tiktok.com/@ata_clipper/video/123','actor','social','ata_clipper')


@pytest.mark.parametrize('payload', [{}, {'videoUrl':'https://www.tiktok.com/@ata_clipper/video/123','socialAccountId':'social','campaignId':'campaign'}, {'label':'café 🎬'}, {'label':'a'*400}])
def test_mutation_wire_matches_sdk_cbor_base64_json(payload):
    import base64,json,shutil,subprocess
    from vyro_cli.client import READ_JS
    node=shutil.which('node')
    assert node, 'Node is required to validate the browser wire encoder'
    script='''let sent;
    global.fetch=async(url,options)=>{
      if(url.endsWith('/auth/refresh'))return {ok:true,status:200,text:async()=>JSON.stringify({accessToken:'test'})};
      if(url.endsWith('/auth/me'))return {ok:true,status:200,text:async()=>JSON.stringify({id:'actor',workspaces:[{id:'workspace',type:'clipper',access:'member'}]})};
      sent={type:options.headers['content-type'],bytes:Array.from(options.body)};
      return {ok:true,status:200,text:async()=>JSON.stringify({id:'receipt'})};
    };
    const run=('''+READ_JS+''');
    run({path:'/clips/v2',method:'POST',expectedAccountId:'actor',body:'''+json.dumps(payload)+'''}).then(()=>console.log(JSON.stringify(sent)));'''
    result=json.loads(subprocess.run([node],input=script,text=True,capture_output=True,check=True).stdout)
    encoded=base64.b64encode(json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode())
    n=len(encoded)
    prefix=bytes([0x60+n]) if n<24 else bytes([0x78,n]) if n<256 else bytes([0x79,n>>8,n&255])
    assert result['type']=='application/octet-stream'
    assert bytes(result['bytes'])==prefix+encoded


def test_transport_preserves_safe_native_machine_error():
    browser=SimpleNamespace(get_page=lambda _:SimpleNamespace(evaluate=lambda *a:{'status':403,'code':'CLIP_SOCIAL_ACCOUNT_NOT_ELIGIBLE'}))
    c=VyroClient(config=SimpleNamespace(),browser=browser)
    with pytest.raises(ClientError,match='vyro_http_403:CLIP_SOCIAL_ACCOUNT_NOT_ELIGIBLE'):
        c._request('/clips/pre-check','POST',{},'actor')


@pytest.mark.parametrize(
    ('status', 'code', 'expected'),
    [
        (401, None, 'session_expired: run vyro auth login'),
        (403, 'AUTOMATION_REJECTED', 'vyro_refresh_forbidden:AUTOMATION_REJECTED'),
        (403, None, 'vyro_refresh_forbidden'),
        (429, None, 'vyro_refresh_rate_limited'),
        (503, None, 'vyro_refresh_unavailable'),
    ],
)
def test_refresh_failures_are_not_all_reported_as_expired(status, code, expected):
    import json
    import shutil
    import subprocess

    from vyro_cli.client import READ_JS

    node = shutil.which('node')
    assert node, 'Node is required to validate refresh failure classification'
    payload = {'errorCode': code} if code else {}
    script = f'''global.fetch=async()=>({{
      ok:false,status:{status},json:async()=>({json.dumps(payload)}),text:async()=>''
    }});
    const run=({READ_JS});
    run({{path:'/auth/me'}}).then(result=>console.log(JSON.stringify(result)));'''
    result = json.loads(subprocess.run(
        [node], input=script, text=True, capture_output=True, check=True
    ).stdout)
    assert result == {'error': expected}
