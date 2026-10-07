"""Bounded catalog-only reads with durable exact named browser ownership."""
import fcntl
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import time
from datetime import datetime,timezone

from cli_tools_shared.bounded_read import run_bounded_read
from cli_tools_shared.browser.processes import list_process_commands,profile_process_pids,terminate_process
from .client import WhopError,WhopClient,strict_json,identifier
from .config import Config,rewards_location

MAX_MARKER=16384
CLEANUP_RESERVE=10.75
MIN_TIMEOUT=14
IMMUTABLE=('version','attempt_id','binding','operation','args','max_bytes','worker','worker_deadline')
class CatalogReadError(WhopError):pass

def failure(code,category='transient'):
 return CatalogReadError(code,category=category)

def private_read(path):
 fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
 try:
  info=os.fstat(fd)
  if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or info.st_mode&0o077 or not 0<info.st_size<=MAX_MARKER:raise failure('catalog_reader_marker_unsafe')
  raw=os.read(fd,MAX_MARKER+1)
  if len(raw)!=info.st_size:raise failure('catalog_reader_marker_changed')
 finally:os.close(fd)
 try:return strict_json(raw.decode('utf-8'))
 except (UnicodeError,ValueError):raise failure('catalog_reader_marker_invalid') from None

def write_marker(path,data):
 raw=json.dumps(data,separators=(',',':')).encode()
 if len(raw)>MAX_MARKER:raise failure('catalog_reader_marker_exceeds_bound')
 temporary=path.with_name(path.name+'.'+secrets.token_hex(8))
 fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 try:
  with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
  os.replace(temporary,path)
  directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
  try:os.fsync(directory)
  finally:os.close(directory)
 finally:
  if temporary.exists():temporary.unlink()

def identity(pid,timeout):
 if type(pid) is not int or pid<=0:raise failure('catalog_reader_pid_invalid')
 if timeout<=.75:raise failure('catalog_reader_inspection_deadline_exceeded')
 result=run_bounded_read(['/usr/bin/env','LC_ALL=C','/bin/ps','-p',str(pid),'-o','stat=,lstart='],timeout_seconds=timeout-.75,max_stdout_bytes=1024)
 if result.returncode==1 and not result.stdout.strip():return None
 if result.returncode!=0:raise failure('catalog_reader_process_identity_unavailable')
 try:state,started=result.stdout.decode('ascii').strip().split(None,1)
 except (UnicodeError,ValueError):raise failure('catalog_reader_process_identity_unavailable') from None
 if state.startswith('Z'):return None
 if not started or len(started)>128:raise failure('catalog_reader_process_identity_unavailable')
 return {'pid':pid,'start_identity':started}

def daemon_path(browser):
 return browser.daemon_endpoint_path()

def daemon_pid(browser):
 path=daemon_path(browser)
 if not path.exists():return None
 try:
  raw=path.read_text()
  if len(raw)>64 or not re.fullmatch(r'[0-9]+\s*',raw):raise ValueError()
  return int(raw)
 except (OSError,ValueError):raise failure('catalog_reader_daemon_owner_unknown') from None

def owned_processes(browser,profile,deadline):
 def remaining():return budget(deadline)
 service=browser._get_service()
 rows=list_process_commands(timeout=min(2,remaining()))
 pids=profile_process_pids(profile,processes=rows)
 launcher=service._chrome_proc;port=service._cdp_port
 if launcher is None or service._opened is not True or type(port) is not int or not 1<=port<=65535 or not 1<=len(pids)<=64:raise failure('catalog_reader_browser_owner_unknown')
 selected=[row for row in rows if row.pid in pids]
 mains=[row for row in selected if not re.search(r'(?:^|\s)--type(?:=|\s|$)',row.command) and re.findall(r'(?:^|\s)--remote-debugging-port=([0-9]+)(?=\s|$)',row.command)==[str(port)]]
 if len(mains)!=1:raise failure('catalog_reader_browser_main_ambiguous')
 main=mains[0].pid;parents={row.pid:row.ppid for row in rows}
 for pid in pids:
  seen=set();current=pid
  while current!=main:
   if current in seen or current not in parents or len(seen)>=64:raise failure('catalog_reader_browser_ancestry_unknown')
   seen.add(current);current=parents[current]
 daemon=daemon_pid(browser)
 if daemon is None:raise failure('catalog_reader_daemon_owner_unknown')
 chrome=[identity(pid,min(2,remaining())) for pid in [main]+sorted(set(pids)-{main})]
 daemon_owner=identity(daemon,min(2,remaining()))
 if any(record is None for record in chrome) or daemon_owner is None:raise failure('catalog_reader_owner_ended_before_capture')
 return {'chrome':chrome,'daemon':[daemon_owner]}

def clean(marker,config,browser,timeout=10):
 profile=str(config.get_persistent_profile_dir())
 binding=marker.get('binding',{})
 if binding!={'profile':config.get_active_profile_name(),'experience':config.rewards_url,'user_data_dir':profile,'expected_account_id':binding.get('expected_account_id')} or not isinstance(binding.get('expected_account_id'),str):raise failure('catalog_reader_binding_changed')
 deadline=time.monotonic()+timeout
 def remaining():
  value=deadline-time.monotonic()
  if value<=0:raise failure('catalog_reader_cleanup_deadline_exceeded')
  return value
 if marker.get('phase')=='launching' and marker.get('owners') is None:
  # The worker (already proven ended by the caller) never recorded a browser.
  # Nothing is signalled: the attempt closes only when the profile provably has
  # no browser process and no live daemon left; anything else stays unknown.
  rows=list_process_commands(timeout=min(2,remaining()))
  pid=daemon_pid(browser)
  if profile_process_pids(profile,processes=rows) or (pid is not None and identity(pid,min(2,remaining())) is not None):raise failure('catalog_reader_ownership_unrecorded')
  return True
 if marker.get('phase') not in ('owned','closed'):raise failure('catalog_reader_ownership_unrecorded')
 owned=marker.get('owners')
 if type(owned) is not dict or set(owned)!={'chrome','daemon'} or type(owned['chrome']) is not list or not 1<=len(owned['chrome'])<=64 or type(owned['daemon']) is not list or len(owned['daemon'])!=1:raise failure('catalog_reader_owner_record_invalid')
 def same(record,kind,budget):
  observed=identity(record['pid'],min(2,budget))
  if observed!=record:return False
  if kind=='chrome':
   rows=list_process_commands(timeout=min(2,remaining()))
   return record['pid'] in profile_process_pids(profile,processes=rows)
  pid=daemon_pid(browser)
  return pid==record['pid']
 for kind in ('chrome','daemon'):
  for record in owned[kind]:
   if type(record) is not dict or set(record)!={'pid','start_identity'} or type(record['pid']) is not int or type(record['start_identity']) is not str:raise failure('catalog_reader_owner_record_invalid')
   current=identity(record['pid'],min(2,remaining()))
   if current is None:continue
   if current!=record or not same(record,kind,remaining()):raise failure('catalog_reader_owner_changed')
   terminate_process(record['pid'],timeout=remaining(),inspection_timeout=min(2,remaining()),ownership_check=lambda budget,r=record,k=kind:same(r,k,budget))
 rows=list_process_commands(timeout=min(2,remaining()))
 if profile_process_pids(profile,processes=rows):raise failure('catalog_reader_browser_not_closed')
 pid=daemon_pid(browser)
 if pid is not None and identity(pid,min(2,remaining())) is not None:raise failure('catalog_reader_daemon_not_closed')
 # Remove only the recorded daemon endpoint after its exact process is absent.
 path=daemon_path(browser)
 if path.exists() and daemon_pid(browser)==owned['daemon'][0]['pid']:path.unlink();browser.cleanup_daemon_endpoint()
 return True

def budget(deadline):
 value=deadline-time.monotonic()
 if value<=0:raise failure('catalog_reader_deadline_exceeded')
 return value

def validate_arguments(operation,args,max_bytes):
 if type(max_bytes) is not int or not 1024<=max_bytes<=8_000_000:raise failure('catalog_reader_bounds_invalid','invalid_request')
 if operation=='page':
  if type(args) is not dict or set(args)!={'limit','sort','cursor'} or type(args['limit']) is not int or not 1<=args['limit']<=50 or args['sort'] not in ('featured','trending','newest') or (args['cursor'] is not None and (type(args['cursor']) is not str or not 0<len(args['cursor'].encode())<=4096)):raise failure('catalog_reader_page_arguments_invalid','invalid_request')
 elif operation=='campaign':
  if type(args) is not dict or set(args)!={'campaign_id'}:raise failure('catalog_reader_campaign_arguments_invalid','invalid_request')
  identifier(args['campaign_id'])
 else:raise failure('catalog_reader_operation_invalid','invalid_request')


def context(config,expected_account_id,timeout_seconds):
 deadline=time.monotonic()+timeout_seconds if type(timeout_seconds) in (int,float) else 0
 profile=config.get_active_profile_name();directory=config.get_profile_data_dir()
 if type(profile) is not str or not re.fullmatch('[A-Za-z0-9_-]{1,64}',profile):raise failure('catalog_reader_profile_invalid','invalid_request')
 if type(expected_account_id) is not str or not re.fullmatch('user_[A-Za-z0-9]+',expected_account_id):raise failure('catalog_reader_actor_invalid','invalid_request')
 if type(timeout_seconds) not in (int,float) or not math.isfinite(timeout_seconds) or not MIN_TIMEOUT<=timeout_seconds<=3600:raise failure('catalog_reader_bounds_invalid','invalid_request')
 rewards_location(config.rewards_url)
 if directory.resolve()!=directory or not directory.is_dir():raise failure('catalog_reader_profile_path_unsafe')
 binding={'profile':profile,'experience':config.rewards_url,'user_data_dir':str(config.get_persistent_profile_dir()),'expected_account_id':expected_account_id}
 return directory,binding,deadline

def lease(directory):
 fd=os.open(directory/'catalog-read.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
 try:
  info=os.fstat(fd)
  if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or info.st_mode&0o077:raise failure('catalog_reader_lease_unsafe')
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise failure('catalog_reader_profile_leased','not_ready') from None
  return fd
 except BaseException:os.close(fd);raise

def same_marker(current,original):
 if type(current) is not dict or any(current.get(key)!=original.get(key) for key in IMMUTABLE):raise failure('catalog_reader_marker_changed')

def finish(path,current,config,browser,deadline):
 clean(current,config,browser,timeout=budget(deadline))
 current['phase']='closed';write_marker(path,current)
 path.unlink()
 fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
 try:os.fsync(fd)
 finally:os.close(fd)

def stop_worker(current,deadline):
 record=current.get('worker')
 if type(record) is not dict or set(record)!={'pid','start_identity'}:raise failure('catalog_reader_worker_ownership_unrecorded')
 observed=identity(record['pid'],min(2,budget(deadline)))
 if observed is None:return
 if observed!=record:raise failure('catalog_reader_worker_owner_changed')
 terminate_process(record['pid'],timeout=budget(deadline),inspection_timeout=min(2,budget(deadline)),ownership_check=lambda allowance:identity(record['pid'],min(2,allowance))==record)
 if identity(record['pid'],min(2,budget(deadline))) is not None:raise failure('catalog_reader_worker_not_closed')

def recover(config,*,expected_account_id,attempt_id,timeout_seconds=30):
 """Explicit recovery; a known original worker must end before browser cleanup."""
 directory,binding,deadline=context(config,expected_account_id,timeout_seconds)
 if type(attempt_id) is not str or not re.fullmatch('[a-f0-9]{32}',attempt_id):raise failure('catalog_reader_attempt_invalid','invalid_request')
 lock=lease(directory);path=directory/'catalog-read-owner.json'
 try:
  current=private_read(path)
  if current.get('version')!=1 or current.get('attempt_id')!=attempt_id or current.get('binding')!=binding:raise failure('catalog_reader_binding_changed')
  validate_arguments(current.get('operation'),current.get('args'),current.get('max_bytes'))
  stop_worker(current,deadline)
  latest=private_read(path);same_marker(latest,current)
  finish(path,latest,config,config.get_browser(),deadline)
  return {'attempt_id':attempt_id,'recovered':True,'browser_closed':True}
 finally:os.close(lock)

def read(config,operation,args,*,expected_account_id,timeout_seconds,max_bytes):
 directory,binding,deadline=context(config,expected_account_id,timeout_seconds)
 validate_arguments(operation,args,max_bytes)
 lock=lease(directory);marker_path=directory/'catalog-read-owner.json';browser=config.get_browser()
 try:
  if marker_path.exists() or marker_path.is_symlink():raise failure('catalog_reader_recovery_required','not_ready')
  work_deadline=deadline-CLEANUP_RESERVE
  rows=list_process_commands(timeout=min(2,budget(work_deadline)))
  if profile_process_pids(binding['user_data_dir'],processes=rows):raise failure('catalog_reader_profile_in_use','not_ready')
  daemon=daemon_pid(browser)
  if daemon is not None and identity(daemon,min(2,budget(work_deadline))) is not None:raise failure('catalog_reader_daemon_in_use','not_ready')
  marker={'version':1,'attempt_id':secrets.token_hex(16),'binding':binding,'operation':operation,'args':args,'phase':'launching','owners':None,'max_bytes':max_bytes,'worker':None,'worker_deadline':work_deadline}
  write_marker(marker_path,marker)
  def started(pid,child_deadline):
   worker=identity(pid,min(2,budget(work_deadline)))
   if worker is None:raise failure('catalog_reader_worker_not_started')
   current=private_read(marker_path);same_marker(current,marker)
   marker['worker']=worker;write_marker(marker_path,marker)
  response=None;error=None
  try:
   result=run_bounded_read([sys.executable,'-m','whop_cli.catalog_reads',str(marker_path)],timeout_seconds=budget(work_deadline),max_stdout_bytes=max_bytes,on_start=started)
   response=strict_json(result.stdout.decode('utf-8'))
   if type(response) is not dict or (set(response)=={'result'} and result.returncode!=0) or (set(response)=={'failure'} and result.returncode!=1) or set(response) not in ({'result'},{'failure'}):raise failure('catalog_reader_worker_response_invalid')
  except Exception as caught:error=caught
  current=private_read(marker_path);same_marker(current,marker)
  try:
   stop_worker(current,deadline)
   latest=private_read(marker_path);same_marker(latest,current)
   finish(marker_path,latest,config,browser,deadline)
  except Exception:raise failure('catalog_reader_cleanup_unproven') from None
  if error:raise error
  if 'failure' in response:
   row=response['failure']
   if type(row) is not dict or set(row)!={'code','category','status','retry_after_seconds'} or type(row['code']) is not str or not re.fullmatch('[a-zA-Z0-9_]{1,100}',row['code']) or row['category'] not in ('auth','rate_limit','transient','upstream','invalid_request','not_ready'):raise failure('catalog_reader_worker_failure_invalid')
   if row['status'] is not None and (type(row['status']) is not int or not 0<=row['status']<=599):raise failure('catalog_reader_worker_failure_invalid')
   if row['retry_after_seconds'] is not None and (type(row['retry_after_seconds']) not in (int,float) or not math.isfinite(row['retry_after_seconds']) or row['retry_after_seconds']<0):raise failure('catalog_reader_worker_failure_invalid')
   raise CatalogReadError(**row)
  return response['result']
 finally:os.close(lock)

def await_worker(path):
 """Do not instantiate Config/browser until durable ownership handshake."""
 original=private_read(path);deadline=original.get('worker_deadline')
 if type(deadline) not in (int,float) or not math.isfinite(deadline) or not 0<deadline-time.monotonic()<=3600:raise failure('catalog_reader_worker_deadline_invalid')
 if original.get('worker') is None:
  while budget(deadline)>0:
   current=private_read(path)
   for key in IMMUTABLE:
    if key!='worker' and current.get(key)!=original.get(key):raise failure('catalog_reader_marker_changed')
   if current.get('worker') is not None:break
   time.sleep(min(.01,budget(deadline)))
 else:current=original
 record=current['worker']
 if type(record) is not dict or record.get('pid')!=os.getpid() or identity(os.getpid(),min(2,budget(deadline)))!=record:raise failure('catalog_reader_worker_owner_changed')
 return current

def worker(marker_path):
 marker=await_worker(marker_path)
 if type(marker) is not dict or marker.get('version')!=1 or marker.get('phase')!='launching' or not re.fullmatch('[a-f0-9]{32}',marker.get('attempt_id','')) or type(marker.get('binding')) is not dict:raise failure('catalog_reader_worker_marker_invalid')
 config=Config(profile=marker['binding']['profile'])
 if marker_path!=config.get_profile_data_dir()/'catalog-read-owner.json' or marker['binding']['experience']!=config.rewards_url or marker['binding']['user_data_dir']!=str(config.get_persistent_profile_dir()) or not re.fullmatch('user_[A-Za-z0-9]+',marker['binding'].get('expected_account_id','')):raise failure('catalog_reader_worker_binding_changed')
 validate_arguments(marker.get('operation'),marker.get('args'),marker.get('max_bytes'))
 browser=config.get_browser();client=WhopClient(config,browser);client.max_retries=0
 original_account=client.account
 def exact_account():
  actor=original_account()
  if actor['id']!=marker['binding']['expected_account_id']:raise failure('catalog_reader_actor_changed','auth')
  return actor
 client.account=exact_account
 original=browser.get_page
 def get_page(*args,**kwargs):
  page=original(*args,**kwargs)
  if marker['phase']=='launching':
   marker.update(phase='owned',owners=owned_processes(browser,marker['binding']['user_data_dir'],marker['worker_deadline']));write_marker(marker_path,marker)
  return page
 browser.get_page=get_page
 try:
  actor=client.account()
  if actor['id']!=marker['binding']['expected_account_id']:raise failure('catalog_reader_actor_changed','auth')
  if marker['operation']=='campaign':result=client.campaign(marker['args']['campaign_id'])
  elif marker['operation']=='page':
   args=marker['args'];params={'collapseGroups':'true','limit':args['limit'],'sortBy':args['sort']}
   if args['cursor'] is not None:params['cursor']=args['cursor']
   raw=client._rest('/api/campaign/campaigns/discover',params);rows=raw.get('data');pagination=raw.get('pagination',raw)
   if type(rows) is not list or len(rows)>args['limit'] or any(type(row) is not dict for row in rows) or type(pagination) is not dict or 'nextCursor' not in pagination:raise failure('catalog_reader_campaign_page_schema_changed','upstream')
   cursor=pagination['nextCursor']
   if cursor is not None and (type(cursor) is not str or not 0<len(cursor.encode())<=4096 or not rows or cursor==args['cursor']):raise failure('catalog_reader_campaign_cursor_changed','upstream')
   result={'rows':rows,'next_cursor':cursor,'provider_end':cursor is None,'scope':'collapsed_groups','observed_at':datetime.now(timezone.utc).isoformat()}
  else:raise failure('catalog_reader_operation_invalid','invalid_request')
  payload={'result':result}
 except Exception as error:
  code=getattr(error,'code',None) or str(error).split(':',1)[0]
  if type(code) is not str or not re.fullmatch('[A-Za-z0-9_]{1,100}',code):code='catalog_reader_provider_failed'
  payload={'failure':{'code':code,'category':getattr(error,'category','transient'),'status':getattr(error,'status',None),'retry_after_seconds':getattr(error,'retry_after_seconds',None)}}
  marker['failure']=payload['failure'];write_marker(marker_path,marker)
 finally:
  try:
   client.close()
   if marker['phase']=='owned':
    clean(marker,config,browser,timeout=budget(marker['worker_deadline']));marker['phase']='closed';write_marker(marker_path,marker)
  except Exception:pass
 raw=json.dumps(payload).encode()
 if len(raw)>marker['max_bytes']:payload={'failure':{'code':'catalog_reader_response_exceeds_bound','category':'upstream','status':None,'retry_after_seconds':None}}
 print(json.dumps(payload));return 1 if 'failure' in payload else 0

if __name__=='__main__':
 try:raise SystemExit(worker(Path(sys.argv[1])))
 except Exception:print(json.dumps({'failure':{'code':'catalog_reader_worker_failed','category':'transient','status':None,'retry_after_seconds':None}}));raise SystemExit(1)
