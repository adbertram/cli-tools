import fcntl,json,os
from pathlib import Path
from types import SimpleNamespace
import pytest
from whop_cli import catalog_reads as cr
from whop_cli.client import WhopClient
from cli_tools_shared.auth import BrowserAutomation
from cli_tools_shared.bounded_read import BoundedReadError

REAL_STOP_WORKER=cr.stop_worker
REAL_IDENTITY=cr.identity

@pytest.fixture
def setup(tmp_path,monkeypatch):
 directory=tmp_path.resolve();data=directory/'browser-data'
 browser=SimpleNamespace()
 browser.daemon_endpoint_path=lambda:BrowserAutomation.daemon_endpoint_path(browser)
 browser.cleanup_daemon_endpoint=lambda:BrowserAutomation.cleanup_daemon_endpoint(browser)
 config=SimpleNamespace(get_active_profile_name=lambda:'rewards',get_profile_data_dir=lambda:directory,get_persistent_profile_dir=lambda:data,rewards_url='https://example.apps.whop.com/c/exp_TEST',get_browser=lambda:browser)
 monkeypatch.setattr(cr,'list_process_commands',lambda **kwargs:[])
 monkeypatch.setattr(cr,'daemon_pid',lambda browser:None)
 monkeypatch.setattr(cr,'identity',lambda pid,budget:None)
 monkeypatch.setattr(cr,'stop_worker',lambda *args:None)
 return config,directory,browser

def marker(config,phase='owned'):
 return {'version':1,'attempt_id':'a'*32,'binding':{'profile':'rewards','experience':config.rewards_url,'user_data_dir':str(config.get_persistent_profile_dir()),'expected_account_id':'user_TEST'},'operation':'page','args':{'limit':50,'sort':'newest','cursor':None},'phase':phase,'owners':{'chrome':[{'pid':101,'start_identity':'first'}],'daemon':[{'pid':202,'start_identity':'second'}]},'max_bytes':65536,'worker':{'pid':404,'start_identity':'worker'},'worker_deadline':999999999999.0}

def invoke(config):return WhopClient.campaigns_page_bounded(config,expected_account_id='user_TEST',timeout_seconds=20,max_bytes=65536)

def test_canonical_sdk_static_avoids_constructor_and_preserves_terminal_page(setup,monkeypatch):
 config,directory,_=setup;calls=[]
 monkeypatch.setattr(WhopClient,'__init__',lambda *args:pytest.fail('parent interactive browser constructor'))
 def runner(argv,**kwargs):
  calls.append((argv,kwargs));path=Path(argv[-1]);record=cr.private_read(path);record.update(phase='closed',owners=marker(config)['owners']);cr.write_marker(path,record)
  return SimpleNamespace(stdout=json.dumps({'result':{'rows':[{'id':'campaign_TEST'}],'next_cursor':None,'provider_end':True,'scope':'collapsed_groups'}}).encode(),returncode=0)
 monkeypatch.setattr(cr,'run_bounded_read',runner);monkeypatch.setattr(cr,'clean',lambda *args,**kwargs:True)
 result=invoke(config)
 assert result['provider_end'] is True and result['next_cursor'] is None
 assert calls[0][0][1:3]==['-m','whop_cli.catalog_reads']
 assert 0<calls[0][1]['timeout_seconds']<20-cr.CLEANUP_RESERVE and callable(calls[0][1]['on_start'])
 assert not (directory/'catalog-read-owner.json').exists()


def test_crash_before_owner_marker_with_live_profile_process_holds_durable_recovery_barrier(setup,monkeypatch):
 config,directory,_=setup
 launched=[]
 def runner(*args,**kwargs):launched.append(1);raise BoundedReadError('read_process_deadline_exceeded')
 monkeypatch.setattr(cr,'run_bounded_read',runner)
 # An unrecorded browser outlived the killed worker.
 monkeypatch.setattr(cr,'profile_process_pids',lambda *args,**kwargs:[303] if launched else [])
 monkeypatch.setattr(cr,'terminate_process',lambda *args,**kwargs:pytest.fail('unknown-owner signal'))
 with pytest.raises(cr.CatalogReadError,match='catalog_reader_cleanup_unproven'):invoke(config)
 assert cr.private_read(directory/'catalog-read-owner.json')['phase']=='launching'
 with pytest.raises(cr.CatalogReadError,match='catalog_reader_recovery_required'):invoke(config)


def test_crash_before_owner_marker_on_empty_profile_closes_and_keeps_the_read_error(setup,monkeypatch):
 # Live 2026-10-07: a worker killed at its deadline before any browser opened left a
 # 'launching' marker that neither the read nor explicit recovery could ever close.
 config,directory,_=setup
 def runner(*args,**kwargs):raise BoundedReadError('read_process_deadline_exceeded')
 monkeypatch.setattr(cr,'run_bounded_read',runner)
 monkeypatch.setattr(cr,'terminate_process',lambda *args,**kwargs:pytest.fail('nothing recorded to signal'))
 with pytest.raises(BoundedReadError,match='read_process_deadline_exceeded'):invoke(config)
 assert not (directory/'catalog-read-owner.json').exists()


def test_explicit_recovery_closes_retained_unrecorded_attempt_only_on_empty_profile(setup,monkeypatch):
 config,directory,_=setup;row=marker(config,'launching');row['owners']=None;path=directory/'catalog-read-owner.json';cr.write_marker(path,row)
 monkeypatch.setattr(cr,'terminate_process',lambda *args,**kwargs:pytest.fail('nothing recorded to signal'))
 monkeypatch.setattr(cr,'daemon_pid',lambda browser:202);monkeypatch.setattr(cr,'identity',lambda pid,budget:{'pid':pid,'start_identity':'live'})
 with pytest.raises(cr.CatalogReadError,match='catalog_reader_ownership_unrecorded'):cr.recover(config,expected_account_id='user_TEST',attempt_id=row['attempt_id'])
 assert path.exists()
 monkeypatch.setattr(cr,'identity',lambda pid,budget:None)
 assert cr.recover(config,expected_account_id='user_TEST',attempt_id=row['attempt_id'])['recovered'] and not path.exists()


def test_concurrent_named_profile_lease_refuses_before_worker(setup,monkeypatch):
 config,directory,_=setup
 fd=os.open(directory/'catalog-read.lock',os.O_RDWR|os.O_CREAT,0o600);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
 monkeypatch.setattr(cr,'run_bounded_read',lambda *args,**kwargs:pytest.fail('concurrent worker'))
 try:
  with pytest.raises(cr.CatalogReadError,match='catalog_reader_profile_leased'):invoke(config)
 finally:os.close(fd)


def test_changed_pid_start_identity_refuses_without_signal(setup,monkeypatch):
 config,_,browser=setup;record=marker(config)
 monkeypatch.setattr(cr,'identity',lambda pid,budget:{'pid':pid,'start_identity':'REUSED'})
 monkeypatch.setattr(cr,'terminate_process',lambda *args,**kwargs:pytest.fail('wrong-owner signal'))
 with pytest.raises(cr.CatalogReadError,match='catalog_reader_owner_changed'):cr.clean(record,config,browser)


def test_unmarked_crash_does_not_guess_profile_pid_owner(setup,monkeypatch):
 config,_,browser=setup
 monkeypatch.setattr(cr,'terminate_process',lambda *args,**kwargs:pytest.fail('unknown-owner signal'))
 with pytest.raises(cr.CatalogReadError,match='catalog_reader_ownership_unrecorded'):cr.clean(marker(config,'launching'),config,browser)


def test_detached_daemon_cleanup_only_exact_recorded_identity(setup,monkeypatch):
 config,directory,browser=setup;record=marker(config);running={202};stopped=[]
 browser._get_service=lambda:SimpleNamespace(_bh=SimpleNamespace(h=None),session='test')
 monkeypatch.setattr(cr,'identity',lambda pid,budget:{'pid':pid,'start_identity':'second'} if pid in running else None)
 monkeypatch.setattr(cr,'daemon_pid',lambda b:202)
 monkeypatch.setattr(cr,'daemon_path',lambda b:directory/'absent.pid')
 def terminate(pid,**kwargs):assert kwargs['ownership_check'](1) is True;stopped.append(pid);running.remove(pid)
 monkeypatch.setattr(cr,'terminate_process',terminate)
 assert cr.clean(record,config,browser) and stopped==[202]


def test_cleanup_error_retains_marker_for_recovery(setup,monkeypatch):
 config,directory,_=setup
 def runner(argv,**kwargs):
  path=Path(argv[-1]);value=cr.private_read(path);value.update(phase='owned',owners=marker(config)['owners']);cr.write_marker(path,value)
  return SimpleNamespace(stdout=b'{"result":{}}',returncode=0)
 monkeypatch.setattr(cr,'run_bounded_read',runner)
 monkeypatch.setattr(cr,'clean',lambda *args:(_ for _ in ()).throw(OSError('SECRET')))
 with pytest.raises(cr.CatalogReadError,match='catalog_reader_cleanup_unproven') as exc:invoke(config)
 assert (directory/'catalog-read-owner.json').exists() and 'SECRET' not in str(exc.value)


def test_unknown_additional_profile_pid_refuses_no_broad_termination(setup,monkeypatch):
 config,_,browser=setup
 monkeypatch.setattr(cr,'identity',lambda *args:None)
 monkeypatch.setattr(cr,'profile_process_pids',lambda *args,**kwargs:[303])
 monkeypatch.setattr(cr,'terminate_process',lambda *args,**kwargs:pytest.fail('foreign pid signal'))
 with pytest.raises(cr.CatalogReadError,match='catalog_reader_browser_not_closed'):cr.clean(marker(config),config,browser)


def test_private_marker_fifo_refuses_without_waiting(tmp_path):
 path=tmp_path/'fifo';os.mkfifo(path)
 with pytest.raises(cr.CatalogReadError,match='catalog_reader_marker_unsafe'):cr.private_read(path)

@pytest.mark.parametrize('cursor', ['', 'SECRET'*1000, True])
def test_malformed_or_overlong_cursor_refused_before_worker(setup,monkeypatch,cursor):
 config,_,_=setup
 monkeypatch.setattr(cr,'run_bounded_read',lambda *args,**kwargs:pytest.fail('invalid request worker'))
 with pytest.raises(cr.CatalogReadError,match='catalog_reader_page_arguments_invalid'):
  WhopClient.campaigns_page_bounded(config,expected_account_id='user_TEST',cursor=cursor,timeout_seconds=20,max_bytes=65536)


def test_provider_cooldown_preserved_after_verified_cleanup(setup,monkeypatch):
 config,_,_=setup
 def runner(argv,**kwargs):
  path=Path(argv[-1]);value=cr.private_read(path);value.update(phase='closed',owners=marker(config)['owners']);cr.write_marker(path,value)
  return SimpleNamespace(stdout=json.dumps({'failure':{'code':'upstream_read_failed_http_429','category':'rate_limit','status':429,'retry_after_seconds':172800}}).encode(),returncode=1)
 monkeypatch.setattr(cr,'run_bounded_read',runner);monkeypatch.setattr(cr,'clean',lambda *args,**kwargs:True)
 with pytest.raises(cr.CatalogReadError) as exc:invoke(config)
 assert exc.value.category=='rate_limit' and exc.value.status==429 and exc.value.retry_after_seconds==172800

@pytest.mark.parametrize('rc,payload',[(1,{'result':{}}),(0,{'failure':{}})])
def test_exit_status_must_match_envelope(setup,monkeypatch,rc,payload):
 config,directory,_=setup
 def runner(argv,**kwargs):
  path=Path(argv[-1]);value=cr.private_read(path);value.update(phase='closed',owners=marker(config)['owners']);cr.write_marker(path,value)
  return SimpleNamespace(stdout=json.dumps(payload).encode(),returncode=rc)
 monkeypatch.setattr(cr,'run_bounded_read',runner);monkeypatch.setattr(cr,'clean',lambda *a,**k:True)
 with pytest.raises(cr.CatalogReadError,match='catalog_reader_worker_response_invalid'):invoke(config)
 assert not (directory/'catalog-read-owner.json').exists()

@pytest.mark.parametrize('key,value',[('operation','campaign'),('args',{'limit':1}),('max_bytes',1024)])
def test_immutable_worker_request_tamper_retains_marker(setup,monkeypatch,key,value):
 config,directory,_=setup
 def runner(argv,**kwargs):
  path=Path(argv[-1]);row=cr.private_read(path);row[key]=value;cr.write_marker(path,row)
  return SimpleNamespace(stdout=b'{"result":{}}',returncode=0)
 monkeypatch.setattr(cr,'run_bounded_read',runner)
 with pytest.raises(cr.CatalogReadError,match='catalog_reader_marker_changed'):invoke(config)
 assert (directory/'catalog-read-owner.json').exists()

@pytest.mark.parametrize('phase',['owned','closed'])
def test_explicit_known_owner_recovery_and_interrupted_final_unlink(setup,monkeypatch,phase):
 config,directory,_=setup;row=marker(config,phase);path=directory/'catalog-read-owner.json';cr.write_marker(path,row);calls=[]
 monkeypatch.setattr(cr,'stop_worker',lambda current,deadline:calls.append('worker'))
 monkeypatch.setattr(cr,'clean',lambda *a,**k:calls.append('browser'))
 result=WhopClient.recover_catalog_read(config,expected_account_id='user_TEST',attempt_id=row['attempt_id'])
 assert calls==['worker','browser'] and result['browser_closed'] and not path.exists()


def test_recovery_worker_pid_reuse_retains_all_browser_state(setup,monkeypatch):
 config,directory,_=setup;row=marker(config);path=directory/'catalog-read-owner.json';cr.write_marker(path,row)
 monkeypatch.setattr(cr,'stop_worker',REAL_STOP_WORKER)
 monkeypatch.setattr(cr,'identity',lambda pid,timeout:{'pid':pid,'start_identity':'reused'})
 monkeypatch.setattr(cr,'terminate_process',lambda *a,**k:pytest.fail('reused worker signal'))
 monkeypatch.setattr(cr,'clean',lambda *a,**k:pytest.fail('browser cleanup before worker stopped'))
 with pytest.raises(cr.CatalogReadError,match='catalog_reader_worker_owner_changed'):
  cr.recover(config,expected_account_id='user_TEST',attempt_id=row['attempt_id'])
 assert path.exists()


def test_surviving_worker_after_parent_lease_loss_is_stopped_before_browser(setup,monkeypatch):
 import subprocess,sys,time
 config,directory,_=setup
 child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],start_new_session=True)
 try:
  monkeypatch.setattr(cr,'identity',REAL_IDENTITY);monkeypatch.setattr(cr,'stop_worker',REAL_STOP_WORKER)
  row=marker(config);row['worker']=cr.identity(child.pid,2);path=directory/'catalog-read-owner.json';cr.write_marker(path,row)
  # No flock survives a dead parent; the durable worker record still prevents takeover.
  monkeypatch.setattr(cr,'clean',lambda *a,**k:child.poll() is not None or pytest.fail('browser cleanup while worker alive'))
  assert cr.recover(config,expected_account_id='user_TEST',attempt_id=row['attempt_id'])['recovered']
  assert child.wait(timeout=1)<0 and not path.exists()
 finally:
  if child.poll() is None:child.kill();child.wait()


def test_actual_child_waits_for_delayed_exact_start_marker(tmp_path):
 import sys,time
 from cli_tools_shared.bounded_read import run_bounded_read
 path=tmp_path/'catalog-read-owner.json';crossed=tmp_path/'crossed';row={'worker':None,'worker_deadline':time.monotonic()+5}
 cr.write_marker(path,row)
 code='from pathlib import Path;from whop_cli.catalog_reads import await_worker;await_worker(Path('+repr(str(path))+'));Path('+repr(str(crossed))+').write_text("ready");print("ok")'
 def started(pid,deadline):
  time.sleep(.25)
  assert not crossed.exists()
  row['worker']=REAL_IDENTITY(pid,2);cr.write_marker(path,row)
 result=run_bounded_read([sys.executable,'-c',code],timeout_seconds=5,max_stdout_bytes=1024,on_start=started)
 assert result.returncode==0 and result.stdout==b'ok\n' and crossed.exists()


def test_whole_deadline_reserves_cleanup_without_reset(setup,monkeypatch):
 config,_,_=setup;clock=[100.0];monkeypatch.setattr(cr.time,'monotonic',lambda:clock[0])
 def rows(**kwargs):clock[0]+=2;return []
 monkeypatch.setattr(cr,'list_process_commands',rows)
 def runner(argv,**kwargs):
  assert kwargs['timeout_seconds']==20-cr.CLEANUP_RESERVE-2
  clock[0]+=kwargs['timeout_seconds']+.75
  path=Path(argv[-1]);row=cr.private_read(path);row.update(phase='closed',owners=marker(config)['owners']);cr.write_marker(path,row)
  return SimpleNamespace(stdout=b'{"result":{}}',returncode=0)
 def clean(*args,**kwargs):
  assert kwargs['timeout']<=10
  clock[0]+=kwargs['timeout']-.01
 monkeypatch.setattr(cr,'run_bounded_read',runner);monkeypatch.setattr(cr,'clean',clean)
 assert invoke(config)=={} and clock[0]<=120

@pytest.mark.parametrize('launcher_pid',[101,999])
def test_owned_chrome_port_binding_uses_real_browser_not_darwin_open_launcher(setup,monkeypatch,launcher_pid):
 from cli_tools_shared.browser.processes import ProcessCommand
 config,_,browser=setup;service=SimpleNamespace(_chrome_proc=SimpleNamespace(pid=launcher_pid),_cdp_port=9229,_opened=True)
 browser._get_service=lambda:service
 rows=[ProcessCommand(101,1,'S','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --user-data-dir='+str(config.get_persistent_profile_dir())+' --remote-debugging-port=9229')]
 monkeypatch.setattr(cr,'list_process_commands',lambda **kwargs:rows)
 monkeypatch.setattr(cr,'daemon_pid',lambda b:202)
 monkeypatch.setattr(cr,'identity',lambda pid,budget:{'pid':pid,'start_identity':'started'})
 owners=cr.owned_processes(browser,str(config.get_persistent_profile_dir()),cr.time.monotonic()+10)
 assert owners['chrome']==[{'pid':101,'start_identity':'started'}]

@pytest.mark.parametrize('port_arg',['--remote-debugging-port=1234','--remote-debugging-port=9229 --remote-debugging-port=1234',''])
def test_wrong_or_ambiguous_port_refuses_browser_owner(setup,monkeypatch,port_arg):
 from cli_tools_shared.browser.processes import ProcessCommand
 config,_,browser=setup;browser._get_service=lambda:SimpleNamespace(_chrome_proc=SimpleNamespace(pid=999),_cdp_port=9229,_opened=True)
 rows=[ProcessCommand(101,1,'S','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --user-data-dir='+str(config.get_persistent_profile_dir())+' '+port_arg)]
 monkeypatch.setattr(cr,'list_process_commands',lambda **kwargs:rows)
 with pytest.raises(cr.CatalogReadError,match='catalog_reader_browser_main_ambiguous'):cr.owned_processes(browser,str(config.get_persistent_profile_dir()),cr.time.monotonic()+10)


def family_rows(config,*,foreign=False,second_main=False):
 from cli_tools_shared.browser.processes import ProcessCommand
 base='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --user-data-dir='+str(config.get_persistent_profile_dir())+' --remote-debugging-port=9229'
 return [ProcessCommand(101,1,'S',base),ProcessCommand(102,999 if foreign else 101,'S',base+('' if second_main else ' --type=renderer')),ProcessCommand(103,102,'S',base+' --type=utility')]


def test_inherited_ports_do_not_make_helpers_main_and_complete_ancestry_is_recorded(setup,monkeypatch):
 config,_,browser=setup;browser._get_service=lambda:SimpleNamespace(_chrome_proc=SimpleNamespace(pid=999),_cdp_port=9229,_opened=True)
 monkeypatch.setattr(cr,'list_process_commands',lambda **kwargs:family_rows(config))
 monkeypatch.setattr(cr,'daemon_pid',lambda b:202);monkeypatch.setattr(cr,'identity',lambda pid,budget:{'pid':pid,'start_identity':'started'})
 result=cr.owned_processes(browser,str(config.get_persistent_profile_dir()),cr.time.monotonic()+10)
 assert [record['pid'] for record in result['chrome']]==[101,102,103]

@pytest.mark.parametrize('foreign,second_main,code',[(True,False,'catalog_reader_browser_ancestry_unknown'),(False,True,'catalog_reader_browser_main_ambiguous')])
def test_foreign_ancestry_or_multiple_main_cannot_grant_ownership(setup,monkeypatch,foreign,second_main,code):
 config,_,browser=setup;browser._get_service=lambda:SimpleNamespace(_chrome_proc=SimpleNamespace(pid=999),_cdp_port=9229,_opened=True)
 monkeypatch.setattr(cr,'list_process_commands',lambda **kwargs:family_rows(config,foreign=foreign,second_main=second_main))
 with pytest.raises(cr.CatalogReadError,match=code):cr.owned_processes(browser,str(config.get_persistent_profile_dir()),cr.time.monotonic()+10)


def test_children_already_ended_when_main_closes_are_not_signaled_again(setup,monkeypatch):
 config,directory,browser=setup;record=marker(config);record['owners']['chrome']=[{'pid':101,'start_identity':'first'},{'pid':102,'start_identity':'child'}];running={101,102};stopped=[]
 browser._get_service=lambda:SimpleNamespace(_bh=SimpleNamespace(h=None),session='test')
 monkeypatch.setattr(cr,'identity',lambda pid,budget:next((r for r in record['owners']['chrome'] if r['pid']==pid),None) if pid in running else None)
 monkeypatch.setattr(cr,'list_process_commands',lambda **kwargs:family_rows(config) if running else [])
 monkeypatch.setattr(cr,'daemon_path',lambda b:directory/'absent.pid')
 def terminate(pid,**kwargs):
  assert kwargs['ownership_check'](1);stopped.append(pid);running.clear()
 monkeypatch.setattr(cr,'terminate_process',terminate)
 assert cr.clean(record,config,browser) and stopped==[101]


def test_reused_recorded_helper_pid_refuses_signal_after_main_ended(setup,monkeypatch):
 config,_,browser=setup;record=marker(config);record['owners']['chrome'].append({'pid':102,'start_identity':'child'})
 monkeypatch.setattr(cr,'identity',lambda pid,budget:{'pid':pid,'start_identity':'reused'} if pid==102 else None)
 monkeypatch.setattr(cr,'terminate_process',lambda *args,**kwargs:pytest.fail('reused helper signal'))
 with pytest.raises(cr.CatalogReadError,match='catalog_reader_owner_changed'):cr.clean(record,config,browser)
