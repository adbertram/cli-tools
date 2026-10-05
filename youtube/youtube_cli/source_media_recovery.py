"""Durable exact acquisition ownership, handshake and ended-worker recovery."""
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import stat
import time

from cli_tools_shared.bounded_read import run_bounded_read, _group_has_no_live_members
from .source_acquisition import fail


def read(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or info.st_mode&0o077 or not 0<info.st_size<=16384:fail('source_media_owner_unsafe')
        raw=os.read(fd,16385)
        if len(raw)!=info.st_size:fail('source_media_owner_changed')
        value=json.loads(raw)
        required={'version','attempt','binding','stage_identity','worker','phase'}
        if type(value) is not dict or not required<=set(value) or set(value)-required-{'receipt','partial_files'} or value['version']!=1 or not re.fullmatch('[a-f0-9]{32}',str(value['attempt'])) or not re.fullmatch('[a-f0-9]{64}',str(value['binding'])):
            fail('source_media_owner_invalid')
        if type(value['stage_identity']) is not list or len(value['stage_identity'])!=2 or any(type(v) is not int or v<0 for v in value['stage_identity']):fail('source_media_owner_invalid')
        worker=value['worker']
        if worker is not None and (type(worker) is not dict or set(worker)!={'pid','start_identity'} or type(worker['pid']) is not int or worker['pid']<=0 or type(worker['start_identity']) is not str or not 0<len(worker['start_identity'])<=128):fail('source_media_owner_invalid')
        if value['phase'] not in ('intent','download_complete','complete','retiring','retired'):fail('source_media_owner_invalid')
        partial=value.get('partial_files',[])
        if type(partial) is not list or len(partial)>16:fail('source_media_owner_invalid')
        for item in partial:
            if type(item) is not dict or set(item)!={'name','dev','ino','size','sha256'} or type(item['name']) is not str or not re.fullmatch(r'source(?:\.f[0-9]+)?\.(mp4|m4a)',item['name']) or any(type(item[k]) is not int or item[k]<0 for k in ('dev','ino','size')) or not re.fullmatch('[a-f0-9]{64}',str(item['sha256'])):fail('source_media_owner_invalid')
        return value
    finally:os.close(fd)


def write(path,value):
    raw=json.dumps(value,separators=(',',':')).encode()
    if len(raw)>16384:fail('source_media_owner_exceeds_bound')
    temp=path.with_name(path.name+'.'+secrets.token_hex(8))
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,path)
        parent=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(parent)
        finally:os.close(parent)
    finally:
        if temp.exists():temp.unlink()


def path_for(request):
    path=Path(request['ownership_path']);stage=Path(request['output_dir'])
    if not path.is_absolute() or path!=stage.with_name(stage.name+'.owner.json') or path.is_symlink():fail('source_media_owner_path_invalid')
    return path


def binding(request,identity):
    values={key:value for key,value in request.items() if key not in ('timeout_seconds','owner_attempt','ownership_path')}
    return hashlib.sha256(json.dumps({'request':values,'stage_identity':list(identity)},sort_keys=True,separators=(',',':')).encode()).hexdigest()


def process_identity(pid,deadline):
    remaining=deadline-time.monotonic()
    if remaining<=.75:fail('source_media_owner_inspection_deadline','transient')
    result=run_bounded_read(['/usr/bin/env','LC_ALL=C','/bin/ps','-p',str(pid),'-o','stat=,lstart='],timeout_seconds=min(2,remaining-.75),max_stdout_bytes=1024)
    if result.returncode==1 and not result.stdout.strip():return None
    if result.returncode!=0:fail('source_media_owner_inspection_unknown','transient')
    try:state,start=result.stdout.decode('ascii').strip().split(None,1)
    except (ValueError,UnicodeError):fail('source_media_owner_inspection_unknown','transient')
    if state.startswith('Z'):return None
    return {'pid':pid,'start_identity':start}


def begin(request,identity):
    path=path_for(request)
    expected=binding(request,identity)
    if path.exists():
        old=read(path)
        if old.get('binding')!=expected or old.get('phase')!='retired':fail('source_media_existing_owner_requires_recovery')
    value={'version':1,'attempt':secrets.token_hex(16),'binding':expected,'stage_identity':list(identity),'worker':None,'phase':'intent'}
    write(path,value)
    return value


def launched(request,owner,pid,deadline):
    path=path_for(request);actual=read(path)
    if actual!=owner:fail('source_media_owner_changed')
    worker=process_identity(pid,deadline)
    if worker is None:fail('source_media_worker_ended_before_handshake','transient')
    owner['worker']=worker;write(path,owner)


def await_owner(request,identity):
    path=path_for(request);deadline=time.monotonic()+min(3,request['timeout_seconds'])
    while time.monotonic()<deadline:
        owner=read(path)
        if owner.get('attempt')!=request['owner_attempt'] or owner.get('binding')!=binding(request,identity):fail('source_media_child_owner_changed')
        if owner.get('worker') is not None:
            if owner['worker'].get('pid')!=os.getpid() or owner.get('phase')!='intent':fail('source_media_child_owner_changed')
            return owner
        time.sleep(.02)
    fail('source_media_child_handshake_timeout','transient')


def completed_download(request,owner):
    fd=os.open(Path(request['output_dir'])/'source.mp4',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1:fail('source_media_regular_file_required')
        os.fsync(fd)
    finally:os.close(fd)
    path=path_for(request)
    if read(path)!=owner:fail('source_media_owner_changed')
    write(path,owner|{'phase':'download_complete'})


def completed_verification(request,receipt):
    path=path_for(request);owner=read(path)
    if owner.get('phase')!='download_complete':fail('source_media_download_completion_missing')
    write(path,owner|{'phase':'complete','receipt':receipt})


def recover(request):
    """Caller holds its workspace lock; never signal or adopt unknown ownership."""
    import re
    from .source_media import validate,guard,_regular_digest,verify_media
    deadline=time.monotonic()+request['timeout_seconds']
    _,_,stage,identity=validate(request)
    path=path_for(request);owner=read(path)
    if owner.get('version')!=1 or owner.get('binding')!=binding(request,identity) or owner.get('stage_identity')!=list(identity):fail('source_media_recovery_binding_changed')
    worker=owner.get('worker')
    if type(worker) is not dict or set(worker)!={'pid','start_identity'} or type(worker['pid']) is not int or worker['pid']<=0:fail('source_media_worker_owner_unknown','transient')
    current=process_identity(worker['pid'],deadline)
    if current is not None:
        fail('source_media_worker_still_active' if current==worker else 'source_media_worker_pid_reused','transient')
    if not _group_has_no_live_members(worker['pid']):fail('source_media_worker_group_unknown_or_live','transient')
    if read(path)!=owner:fail('source_media_owner_changed')
    guard(stage,identity,request)
    phase=owner.get('phase')
    if phase in ('download_complete','complete'):
        if phase=='complete':
            # Verify the durable receipt again, without renewing source evidence.
            saved=owner.get('receipt')
            if type(saved) is not dict:fail('source_media_receipt_missing')
            actual=verify_media({key:value for key,value in request.items() if key!='ownership_path'},deadline,identity)
            if actual!=saved:fail('source_media_completed_receipt_changed')
            return {'state':'complete','media':actual}
        return {'state':'complete','media':verify_media(request,deadline,identity)}
    if phase not in ('intent','retiring','retired'):fail('source_media_recovery_phase_invalid')
    if phase=='intent':
        files=[]
        for item in stage.iterdir():
            if not re.fullmatch(r'source(?:\.f[0-9]+)?\.(mp4|m4a)',item.name):fail('source_media_partial_file_unknown')
            info=item.stat(follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.getuid():fail('source_media_partial_file_changed')
            sha,size=_regular_digest(item,request['max_source_bytes'],deadline) if info.st_size else (hashlib.sha256(b'').hexdigest(),0)
            files.append({'name':item.name,'dev':info.st_dev,'ino':info.st_ino,'size':size,'sha256':sha})
        owner=owner|{'phase':'retiring','partial_files':files};write(path,owner)
    for expected in owner.get('partial_files',[]):
        item=stage/expected['name']
        if not item.exists() and not item.is_symlink():continue
        info=item.stat(follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.getuid():fail('source_media_partial_file_changed')
        sha,size=_regular_digest(item,request['max_source_bytes'],deadline) if info.st_size else (hashlib.sha256(b'').hexdigest(),0)
        if (info.st_dev,info.st_ino,size,sha)!=(expected['dev'],expected['ino'],expected['size'],expected['sha256']):fail('source_media_partial_file_changed')
        fresh=item.stat(follow_symlinks=False)
        if (fresh.st_dev,fresh.st_ino,fresh.st_size,fresh.st_mtime_ns)!=(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns):fail('source_media_partial_file_changed')
        item.unlink()
    if any(stage.iterdir()):fail('source_media_partial_file_unknown')
    owner['phase']='retired';write(path,owner)
    return {'state':'retired'}
