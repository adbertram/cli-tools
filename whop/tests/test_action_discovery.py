"""Execute the actual browser scanner under deterministic script growth."""
import json
import subprocess
from unittest.mock import Mock
import pytest
from whop_cli.client import DISCOVER_ACTION_JS, WhopClient, WhopError
from whop_cli.submission_operations import SUBMISSION_DISCOVERY_JS

HARNESS = r"""
const {script,scenario}=JSON.parse(require('fs').readFileSync(0,'utf8'));
const origin='https://example.apps.whop.com';global.location={origin};
let sources=['one'],calls=[],signals=[],attempt=0,cancels=0;
const ref=id=>'createServerReference)("'+id.repeat(40)+'",0,"createSubmissionAction"';
if(scenario==='limit')sources=Array.from({length:121},(_,i)=>'s'+i);
if(scenario==='total')sources=['one','two','three','four'];
global.document={get scripts(){return sources.map(s=>({src:origin+'/'+s}));}};
const signal={aborted:false};global.AbortSignal={timeout(ms){signals.push(ms);return signal;}};
global.fetch=async(url,opts)=>{
 calls.push({url,signal:opts.signal===signal,redirect:opts.redirect});
 const name=new URL(url).pathname.slice(1);let text=ref('a');
 if(scenario==='growth_missing'&&name==='one'){text='';if(!sources.includes('two'))sources.push('two');}
 if(scenario==='growth_ambiguous'&&name==='one'&&!sources.includes('two'))sources.push('two');
 if(scenario==='growth_ambiguous'&&name==='two')text=ref('b');
 if(scenario==='unstable'&&name==='one')sources.push('added'+(++attempt));
 if(scenario==='failed')return {ok:false};
 if(scenario==='timeout')signal.aborted=true;
 if(scenario==='total'&&name==='one'&&!sources.includes('five'))sources.push('five');
 let read=false;const bytes=scenario==='oversize'?new Uint8Array(8000001):scenario==='total'?new Uint8Array(8000000):new TextEncoder().encode(text);
 return {ok:true,body:{getReader(){return {
  async read(){if(read)return {done:true};read=true;return {done:false,value:bytes};},
  async cancel(){cancels++;}
 };}}};
};
(async()=>{const result=await eval('('+script+')')('createSubmissionAction');
console.log(JSON.stringify({result,calls,signals,cancels}));})().catch(e=>{console.error(e.name);process.exit(1);});
"""

def scan(scenario):
    result=subprocess.run(['node','-e',HARNESS],input=json.dumps({'script':DISCOVER_ACTION_JS,'scenario':scenario}),text=True,capture_output=True,timeout=15,check=True)
    return json.loads(result.stdout)

@pytest.mark.parametrize('scenario,reason,attempts',[
    ('stable','ready',1),('growth_missing','ready',2),('growth_ambiguous','ambiguous',2),
    ('unstable','scripts_changed',3),('failed','script_fetch_failed',1),
    ('timeout','script_fetch_failed',1),('oversize','script_fetch_failed',1),
    ('total','script_fetch_failed',2),('limit','script_limit',None),
])
def test_actual_scanner(scenario,reason,attempts):
    value=scan(scenario);result=value['result']
    assert result['reason']==reason
    if attempts is not None: assert result['attempts']==attempts
    assert result['action']==('a'*40 if reason=='ready' else None)
    assert value['signals']==[10000]
    assert all(c['signal'] and c['redirect']=='error' for c in value['calls'])
    if scenario=='limit': assert value['calls']==[]
    if scenario in ('oversize','total'): assert value['cancels']==len(value['calls'])
    if scenario=='growth_missing': assert len(value['calls'])==3
    if scenario=='unstable': assert result['sources']==3 and result['afterSources']==4

def test_scanner_shared_with_submission_discovery():
    assert SUBMISSION_DISCOVERY_JS is DISCOVER_ACTION_JS

@pytest.mark.parametrize('reason',['scripts_changed','script_fetch_failed'])
def test_exhausted_discovery_is_transient_uncached(reason):
    c=WhopClient(Mock(),browser=Mock());document=Mock()
    document.evaluate.return_value={'action':None,'reason':reason,'sources':60,'matches':0,'failures':0}
    with pytest.raises(WhopError) as error: c._discover_action(document,'createSubmissionAction','/campaigns/test')
    assert error.value.code=='read_action_discovery_'+reason and error.value.category=='transient'
    assert c._actions=={}
    document.evaluate.assert_called_once_with(DISCOVER_ACTION_JS,'createSubmissionAction',request_timeout=12.0)

def test_only_stable_ready_result_is_cached():
    c=WhopClient(Mock(),browser=Mock());document=Mock()
    document.evaluate.return_value={'action':'a'*40,'reason':'ready','sources':60,'matches':1,'failures':0}
    assert c._discover_action(document,'listSocialMediaAccounts','/settings')=='a'*40
    assert c._discover_action(document,'listSocialMediaAccounts','/settings')=='a'*40
    assert document.evaluate.call_count==1
