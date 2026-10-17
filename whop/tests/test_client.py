import json
from types import SimpleNamespace
from unittest.mock import Mock, ANY
import pytest
from typer.testing import CliRunner
from cli_tools_shared.exceptions import ClientError
from whop_cli.client import WhopClient, decode_action, identifier, bounds, strict_json, READ_ACTIONS
from whop_cli.main import app


def action_page(values, suffix='/settings'):
    page=Mock()
    page.frame_documents.return_value=[{'id':'root','origin':'https://example.apps.whop.com','path':'/c/exp_TEST'+suffix}]
    replies=iter(values)
    def evaluate(selector,script,arg=None,**options):
        value=next(replies)
        return {'scopeMatched':True,'value':value} if 'scopeMatched' in script else value
    page.evaluate_in_iframe.side_effect=evaluate
    return page

@pytest.fixture
def client():
    browser=Mock()
    config=SimpleNamespace(rewards_url='https://example.apps.whop.com/c/exp_TEST',get_browser=lambda:browser,get_active_profile_name=lambda:'rewards')
    return WhopClient(config)

@pytest.mark.parametrize('url',['https://evil.com/c/exp_TEST','https://example.apps.whop.com@evil.com/c/exp_TEST','http://example.apps.whop.com/c/exp_TEST','https://example.apps.whop.com:443/c/exp_TEST','https://example.apps.whop.com/c/exp_TEST?a=1','https://example.apps.whop.com/c/exp_TEST#x','https://example.apps.whop.com/c/exp_TEST/../settings'])
def test_reject_location(client,url):
    client.config.rewards_url=url
    with pytest.raises(ClientError):client._location()

def test_missing_location(client):
    client.config.rewards_url=None
    with pytest.raises(ClientError,match='unconfigured'):client._location()

@pytest.mark.parametrize('value',['../foo','x/y','x?y','x\n','', '\x00'])
def test_invalid_ids(value):
    with pytest.raises(ClientError):identifier(value)

@pytest.mark.parametrize('n',[0,-1,1001,True,float('inf')])
def test_limits(n):
    with pytest.raises(ClientError):bounds(n)

def test_action_wire():
    assert decode_action('0:{"a":"$@1"}\n1:{"data":[],"nextCursor":null,"success":true}\n')['data']==[]

@pytest.mark.parametrize('wire',['{}','0:{"a":"$@1"}\n1:E{"message":"secret"}','0:{"a":"$@1"}\n1:{"data":"$2"}','0:{"a":"$@1"}\n0:{}','0:{"a":"$@2"}\n1:{}','0:{"a":"$@1"}\n1:{"data":NaN}'])
def test_bad_flight(wire):
    with pytest.raises(ClientError):decode_action(wire)

@pytest.mark.parametrize('text',['NaN','Infinity','-Infinity','{"a":NaN}','1e999','{"a":1,"a":2}', 'a'*8_000_001])
def test_bad_json(text):
    with pytest.raises(ClientError):strict_json(text)

def test_64bit_identity(client):
    row={'id':'user_TEST','username':'test','extra':{'userId':'7692213003349443597'},'balance':None}
    client._request=Mock(return_value=row)
    result=client.account()
    assert result['id']==row['id'] and result['balance'] is None and result['profile']=='rewards'
    assert 'extra' not in result

@pytest.mark.parametrize('row',[{}, {'id':'user_TEST'}, {'id':None,'username':'test'}])
def test_missing_identity(client,row):
    client._request=Mock(return_value=row)
    with pytest.raises(ClientError):client.account()

def test_auth_failure_is_safe(client):
    page=Mock();page.evaluate.return_value={'status':403,'text':'private session-token'}
    with pytest.raises(ClientError) as e:client._request(page,'/api/v1/users/me')
    assert 'private' not in str(e.value)

def test_retry_bounded(client,monkeypatch):
    sleeps=[];monkeypatch.setattr('whop_cli.client.time.sleep',sleeps.append)
    page=Mock();page.evaluate.return_value={'status':503,'text':'secret'}
    with pytest.raises(ClientError):client._request(page,'/read')
    assert page.evaluate.call_count==3 and sleeps==[1.0,2.0]

def test_retry_after_bounds(client,monkeypatch):
    page=Mock();page.evaluate.return_value={'status':429,'retryAfter':'900'}
    with pytest.raises(ClientError,match='exceeds_bound'):client._request(page,'/read')
    assert page.evaluate.call_count==1

@pytest.mark.parametrize('category',['AbortError','TimeoutError','TypeError','secret-response-body'])
def test_transport_failure_class_is_bounded_and_sanitized(client,monkeypatch,category):
    monkeypatch.setattr('whop_cli.client.time.sleep',lambda _:None)
    page=Mock();page.evaluate.return_value={'status':0,'text':'secret-response-body','errorClass':category}
    expected=category if category in ('AbortError','TimeoutError','TypeError') else 'Error'
    with pytest.raises(ClientError,match=f'upstream_read_failed_transport_{expected}') as error:
        client._request(page,'/read')
    assert page.evaluate.call_count==3 and 'secret-response-body' not in str(error.value)

@pytest.mark.parametrize('status',[True,None,'secret-response-body',-1,600])
def test_invalid_transport_status_never_echoed(client,status):
    page=Mock();page.evaluate.return_value={'status':status}
    with pytest.raises(ClientError,match='invalid_transport_response'):
        client._request(page,'/read')

def test_partial_fails():
    with pytest.raises(ClientError,match='partial'):WhopClient._success({'success':True,'data':{'partialFailure':True}})

def test_no_mutations(client):
    assert READ_ACTIONS=={'listSocialMediaAccounts','listMySubmissionsAction','countMySubmissionsAction'}
    with pytest.raises(ClientError,match='allowlisted'):client._action('createSubmissionAction',[], '/submissions')
    for name in ['create','submit','withdraw','apply','link']:
        assert not hasattr(client,name)

def test_page_limit_sent(client):
    requests=[]
    def fetch(n,c):
        requests.append((n,c));return {'data':[{'id':str(len(requests))} for _ in range(n)],'pagination':{'nextCursor':'next' if c is None else None}}
    assert len(client._pages(fetch,51))==51
    assert requests==[(50,None),(1,'next')]

def test_cursor_cycle(client):
    with pytest.raises(ClientError,match='cycle'):
        client._pages(lambda n,c:{'data':[{}],'nextCursor':'repeat'},100)

def test_missing_stats_unknown(client):
    client.linked_accounts=Mock(return_value=[{'userId':'creator_TEST'}])
    client._rest=Mock(return_value={'success':True,'data':{'overview':{'lifetime':{'netPayouts':None}}}})
    assert client.earnings('2026-10-01T00:00:00Z','2026-10-02T00:00:00Z')['overview']['lifetime']['netPayouts'] is None

@pytest.mark.parametrize('a,b',[('bad','bad'),('2026-10-01','2026-10-02'),('2026-10-02T00:00Z','2026-10-01T00:00Z')])
def test_dates_fail(client,a,b):
    with pytest.raises(ClientError):client.earnings(a,b)

def test_history_not_status(client):
    calls=[]
    client._action=lambda *args:(calls.append(args) or {'data':[],'nextCursor':None})
    assert client.submissions(1,'history')==[]
    assert calls[0][1]==[{'retainer':False,'limit':1,'isDeleted':True}]

def test_ambiguous_creator(client):
    client.linked_accounts=Mock(return_value=[{'userId':'one'},{'userId':'two'}])
    with pytest.raises(ClientError,match='ambiguous'):client.payouts()

def test_whole_read_closes(monkeypatch):
    from whop_cli import render
    c=Mock();c.account.side_effect=ClientError('boom');monkeypatch.setattr(render,'WhopClient',lambda:c)
    with pytest.raises(ClientError):render.read('account')
    c.close.assert_called_once()

def test_help_tree():
    for group in ['account','linked-accounts','campaigns','submissions','earnings']:
        assert CliRunner().invoke(app,[group,'--help']).exit_code==0

def test_action_routes_and_discovery(client):
    page=action_page([True,{'action':'a'*40,'reason':'ready','sources':62,'matches':1,'failures':0}])
    client._reward_page=Mock(return_value=page)
    client._request=Mock(return_value={'success':True,'data':{'socialMediaAccounts':[]}})
    assert client.linked_accounts()==[]
    client._reward_page.assert_called_once_with('/settings')
    assert client._request.call_args.args[1]=='/c/exp_TEST/settings'

@pytest.mark.parametrize('reason',['missing','ambiguous','script_fetch_failed','scripts_changed','script_limit'])
def test_action_discovery_failure_is_explicit_and_safe(client,reason):
    page=action_page([True,{'action':None,'reason':reason,'sources':62,'matches':0,'failures':1,'private':'secret'}])
    client._reward_page=Mock(return_value=page);client._request=Mock()
    with pytest.raises(ClientError,match=f'read_action_discovery_{reason}') as error:
        client.linked_accounts()
    assert 'secret' not in str(error.value) and client._actions=={}
    client._request.assert_not_called()

@pytest.mark.parametrize('value',[None,'a'*40,{'action':'a'*40,'reason':'ready','sources':62,'matches':2,'failures':0},
    {'action':'a'*40,'reason':'secret','sources':62,'matches':1,'failures':0},
    {'action':'a'*40,'reason':'ready','sources':True,'matches':1,'failures':0}])
def test_invalid_discovery_result_fails_closed(client,value):
    page=action_page([True,value]);client._reward_page=Mock(return_value=page)
    with pytest.raises(ClientError,match='invalid_action_discovery_response'):client.linked_accounts()

def test_account_security_fields_excluded(client):
    client._request=Mock(return_value={'id':'user_TEST','username':'test','email':'example@example.test',
        'access_token':'secret','session_token':'secret','intercom_identity':'secret',
        'verification':{'private':'secret'},'identity_risk':{'private':'secret'},
        'balance':{'total_usd':'0.00'},'earnings_usd':None})
    row=client.account()
    assert not any(key in row for key in ['access_token','session_token','intercom_identity','verification','identity_risk'])
    assert row['balance']=={'total_usd':'0.00'} and row['earnings_usd'] is None
    assert row['email']=='example@example.test'

def test_missing_cursor_fails(client):
    with pytest.raises(ClientError,match='pagination_schema_changed'):
        client._pages(lambda n,c:{'data':[{'id':'one'}],'pagination':{}},100)

def test_list_options_consume_values(monkeypatch):
    from whop_cli.commands import linked_accounts
    calls=[]
    monkeypatch.setattr(linked_accounts,'read',lambda *args,**kwargs:(calls.append((args,kwargs)) or [{'id':'one','platform':'tiktok'}]))
    result=CliRunner().invoke(linked_accounts.app,['list','--limit','1','--filter','platform:eq:tiktok','--properties','id'])
    assert result.exit_code==0,result.output
    assert json.loads(result.stdout)==[{'id':'one'}]
    assert calls[0][1]['filters']==['platform:eq:tiktok']


def test_rewards_url_is_tool_configuration_not_a_profile_field(tmp_path, monkeypatch):
    from whop_cli.config import Config
    from cli_tools_shared.config import BaseConfig, root_config_field_names_for
    tool = tmp_path / "whop"
    tool.mkdir()
    (tool / ".env.example").write_text("ACTIVE=true\nREWARDS_URL=\n")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("REWARDS_URL", raising=False)
    class IsolatedConfig(Config):
        def __init__(self, profile=None):
            BaseConfig.__init__(self, tool_dir=tool, profile=profile)
    config = IsolatedConfig(profile="default")
    assert "REWARDS_URL" in root_config_field_names_for(Config)
    assert "REWARDS_URL" not in config.env_file_path.read_text()
    config._set("REWARDS_URL", "https://example.apps.whop.com/c/exp_TEST")
    monkeypatch.delenv("REWARDS_URL")
    assert IsolatedConfig(profile="default").rewards_url == "https://example.apps.whop.com/c/exp_TEST"


def test_action_waits_for_script_document(client,monkeypatch):
    sleeps=[];monkeypatch.setattr('whop_cli.client.time.sleep',sleeps.append)
    page=action_page([False,False,True,{'action':'a'*40,'reason':'ready','sources':62,'matches':1,'failures':0}])
    client._reward_page=Mock(return_value=page)
    client._request=Mock(return_value={'success':True,'data':{'socialMediaAccounts':[]}})
    assert client.linked_accounts()==[]
    assert sleeps==[0.1,0.1]
    assert page.evaluate_in_iframe.call_args_list[0].args[2]=={'origin':'https://example.apps.whop.com','path':'/c/exp_TEST/settings'}

def test_action_document_readiness_timeout(client,monkeypatch):
    ticks=iter([0,0,0,11]);monkeypatch.setattr('whop_cli.client.time.monotonic',lambda:next(ticks))
    page=action_page([False]);client._reward_page=Mock(return_value=page);client._request=Mock()
    with pytest.raises(ClientError,match='read_action_page_not_ready'):client.linked_accounts()
    client._request.assert_not_called()


@pytest.mark.parametrize('suffix,name', [('/settings','listSocialMediaAccounts'),('/submissions','listMySubmissionsAction')])
def test_shell_routes_matched_experience_frame_and_reacquires_exact_context(client,monkeypatch,suffix,name):
    monkeypatch.setattr('whop_cli.client.time.sleep',lambda _:None)
    page=action_page([True,{'action':'a'*40,'reason':'ready','sources':62,'matches':1,'failures':0}],suffix)
    shell={'id':'shell','origin':'https://whop.com','path':'/community/app/'}
    child={'id':'app','origin':'https://example.apps.whop.com','path':'/c/exp_TEST/discover'}
    page.frame_documents.side_effect=[[shell,child],[shell,{**child,'path':'/c/exp_TEST'+suffix}]]
    client._reward_page=Mock(return_value=page);client._request=Mock(return_value={'success':True,'data':[]})
    assert client._action(name,[],suffix)['data']==[]
    page.goto_frame.assert_called_once_with('app','https://example.apps.whop.com/c/exp_TEST'+suffix,request_timeout=ANY)
    assert 0<page.goto_frame.call_args.kwargs['request_timeout']<=10
    assert all(c.args[0]=='https://example.apps.whop.com/c/exp_TEST'+suffix for c in page.evaluate_in_iframe.call_args_list)


def test_direct_action_document_has_no_extra_navigation(client):
    page=action_page([True,{'action':'a'*40,'reason':'ready','sources':62,'matches':1,'failures':0}])
    client._reward_page=Mock(return_value=page);client._request=Mock(return_value={'success':True,'data':{'socialMediaAccounts':[]}})
    client.linked_accounts()
    page.goto_frame.assert_not_called()


@pytest.mark.parametrize('origin,path', [('https://wrong.apps.whop.com','/c/exp_TEST/settings'),('https://example.apps.whop.com','/c/exp_TESTevil/settings')])
def test_wrong_app_or_experience_is_never_navigated_or_requested(client,monkeypatch,origin,path):
    ticks=iter([0,0,11]);monkeypatch.setattr('whop_cli.client.time.monotonic',lambda:next(ticks))
    page=action_page([]);page.frame_documents.return_value=[{'id':'wrong','origin':origin,'path':path}]
    client._reward_page=Mock(return_value=page);client._request=Mock()
    with pytest.raises(ClientError,match='read_action_page_not_ready'):client.linked_accounts()
    page.goto_frame.assert_not_called();page.evaluate_in_iframe.assert_not_called();client._request.assert_not_called()


def test_ambiguous_experience_frames_fail_closed(client):
    page=action_page([]);row=page.frame_documents.return_value[0]
    page.frame_documents.return_value=[row,{**row,'id':'second'}]
    client._reward_page=Mock(return_value=page);client._request=Mock()
    with pytest.raises(ClientError,match='document_ambiguous'):client.linked_accounts()
    page.goto_frame.assert_not_called();client._request.assert_not_called()


def test_redirect_out_of_scope_before_discovery_fails_closed(client):
    page=action_page([]);page.evaluate_in_iframe.side_effect=[True,{'scopeMatched':False}]
    client._reward_page=Mock(return_value=page);client._request=Mock()
    with pytest.raises(ClientError,match='document_scope_changed'):client.linked_accounts()
    client._request.assert_not_called()


def test_transport_rechecks_scope_after_valid_discovery(client):
    page=action_page([]);page.evaluate_in_iframe.side_effect=[True,{'scopeMatched':True,'value':{'action':'a'*40,'reason':'ready','sources':62,'matches':1,'failures':0}},{'scopeMatched':False}]
    client._reward_page=Mock(return_value=page)
    with pytest.raises(ClientError,match='document_scope_changed'):client.linked_accounts()


def test_readiness_budget_exhausted_after_navigation_prevents_discovery(client,monkeypatch):
    ticks=iter([0,0,0,0,11]);monkeypatch.setattr('whop_cli.client.time.monotonic',lambda:next(ticks))
    monkeypatch.setattr('whop_cli.client.time.sleep',lambda _:None)
    page=action_page([])
    page.frame_documents.return_value=[{'id':'app','origin':'https://example.apps.whop.com','path':'/c/exp_TEST/discover'}]
    client._reward_page=Mock(return_value=page);client._request=Mock()
    with pytest.raises(ClientError,match='readiness_deadline_exceeded'):client.linked_accounts()
    page.goto_frame.assert_called_once()
    page.evaluate_in_iframe.assert_not_called();client._request.assert_not_called()

def test_rest_direct_app_keeps_one_account_preflight_and_original_transport(client):
    from whop_cli.client import FETCH_JS
    account=Mock();account.evaluate.return_value={'status':200,'text':json.dumps({'id':'user_TEST','username':'test'})}
    page=action_page([True,{'status':200,'text':json.dumps({'success':True,'data':[]})}],suffix='/discover')
    client.browser.get_page.side_effect=[account,page]
    assert client._rest('/api/campaign/campaigns/discover',{'collapseGroups':'true','limit':50,'sortBy':'newest'})['data']==[]
    assert client.browser.get_page.call_args_list[0].args==('https://whop.com/',)
    assert client.browser.get_page.call_args_list[1].args==('https://example.apps.whop.com/c/exp_TEST/discover',)
    assert account.evaluate.call_count==1
    assert account.evaluate.call_args.args[1]['path']=='/api/v1/users/me'
    page.goto_frame.assert_not_called();page.evaluate.assert_not_called()
    transport=page.evaluate_in_iframe.call_args_list[-1]
    assert FETCH_JS in transport.args[1]
    assert transport.args[2]['arg']=={'path':'/api/campaign/campaigns/discover?collapseGroups=true&limit=50&sortBy=newest','action':None,'body':None}

def test_rest_wrapper_routes_only_matched_app_and_fetches_guarded_context(client,monkeypatch):
    monkeypatch.setattr('whop_cli.client.time.sleep',lambda _:None)
    client.account=Mock(return_value={'id':'user_TEST','username':'test'})
    page=action_page([True,{'status':200,'text':json.dumps({'success':True,'data':{'id':'campaign_TEST'}})}],suffix='/discover')
    shell={'id':'shell','origin':'https://whop.com','path':'/clippingculture/exp_TEST/app/'}
    app={'id':'app','origin':'https://example.apps.whop.com','path':'/c/exp_TEST/settings'}
    page.frame_documents.side_effect=[[shell,app],[shell,{**app,'path':'/c/exp_TEST/discover'}]]
    client.browser.get_page.return_value=page
    assert client.campaign('campaign_TEST')['id']=='campaign_TEST'
    client.account.assert_called_once_with()
    page.goto_frame.assert_called_once_with('app','https://example.apps.whop.com/c/exp_TEST/discover',request_timeout=ANY)
    assert 0<page.goto_frame.call_args.kwargs['request_timeout']<=10
    page.evaluate.assert_not_called()
    assert all(call.args[0]=='https://example.apps.whop.com/c/exp_TEST/discover' for call in page.evaluate_in_iframe.call_args_list)
    assert page.evaluate_in_iframe.call_args.args[2]['arg']['path']=='/api/campaign/campaigns/discover/campaign_TEST'

def test_rest_scope_change_refuses_request_without_retry(client):
    client.account=Mock(return_value={'id':'user_TEST','username':'test'})
    page=action_page([],suffix='/discover');page.evaluate_in_iframe.side_effect=[True,{'scopeMatched':False}]
    client.browser.get_page.return_value=page
    with pytest.raises(ClientError,match='document_scope_changed'):client.campaign('campaign_TEST')
    assert page.evaluate_in_iframe.call_count==2
    page.evaluate.assert_not_called()

def test_rest_ambiguous_app_context_refuses_fetch(client):
    page=action_page([],suffix='/discover');row=page.frame_documents.return_value[0]
    page.frame_documents.return_value=[row,{**row,'id':'second'}]
    client._reward_page=Mock(return_value=page)
    with pytest.raises(ClientError,match='document_ambiguous'):client.campaign('campaign_TEST')
    page.goto_frame.assert_not_called();page.evaluate.assert_not_called();page.evaluate_in_iframe.assert_not_called()

@pytest.mark.parametrize('origin,path',[('https://whop.com','/clippingculture/exp_TEST/app/'),
    ('https://example.apps.whop.com','/c/exp_TESTevil'),('https://wrong.apps.whop.com','/c/exp_TEST')])
def test_rest_wrong_context_hits_owning_readiness_deadline_without_fetch(client,monkeypatch,origin,path):
    ticks=iter([0,0,11]);monkeypatch.setattr('whop_cli.client.time.monotonic',lambda:next(ticks))
    page=action_page([],suffix='/discover');page.frame_documents.return_value=[{'id':'wrong','origin':origin,'path':path}]
    client._reward_page=Mock(return_value=page)
    with pytest.raises(ClientError,match='read_action_page_not_ready'):client.campaign('campaign_TEST')
    page.goto_frame.assert_not_called();page.evaluate.assert_not_called();page.evaluate_in_iframe.assert_not_called()

def test_rest_budget_exhausted_after_navigation_never_fetches(client,monkeypatch):
    ticks=iter([0,0,0,0,11]);monkeypatch.setattr('whop_cli.client.time.monotonic',lambda:next(ticks))
    monkeypatch.setattr('whop_cli.client.time.sleep',lambda _:None)
    page=action_page([],suffix='/discover');page.frame_documents.return_value=[{'id':'app','origin':'https://example.apps.whop.com','path':'/c/exp_TEST/settings'}]
    client._reward_page=Mock(return_value=page)
    with pytest.raises(ClientError,match='readiness_deadline_exceeded'):client.campaign('campaign_TEST')
    page.goto_frame.assert_called_once();page.evaluate.assert_not_called();page.evaluate_in_iframe.assert_not_called()
