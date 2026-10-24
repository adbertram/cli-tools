"""Exact full-video acquisition into a caller-owned private empty directory."""
import hashlib
from itertools import islice
import json
import math
import os
from pathlib import Path
import resource
import re
import shutil
import stat
import sys
import time

from cli_tools_shared.bounded_read import run_bounded_read
from .source_acquisition import SourceAcquisitionError, QuietLogger, positive, fail, typed_provider_failure
from .source_metadata import canonical_video

PHYSICAL_RESERVE = 1073741824
WRITE_HEADROOM = 1048576
BUFFER_BYTES = 65536


def validate(request,*,worker=False):
    fields={'url','expected_video_id','duration_seconds','output_dir','max_source_bytes','max_stage_bytes','max_resolution','timeout_seconds'}
    if type(request) is not dict or set(request)-{'ownership_path','owner_attempt'}!=fields:fail('source_media_request_invalid','invalid_request')
    identifier,canonical=canonical_video(request['url'])
    if identifier!=request['expected_video_id']:fail('source_media_identity_invalid','invalid_request')
    positive(request['duration_seconds'],86400)
    positive(request['max_source_bytes'],10*1073741824,integer=True)
    positive(request['max_stage_bytes'],30*1073741824,integer=True)
    if request['max_resolution'] not in (240,360,480):fail('source_media_resolution_invalid','invalid_request')
    if positive(request['timeout_seconds'],3600)<=(.75 if worker else 15):fail('source_media_deadline_insufficient','invalid_request')
    if request['max_stage_bytes']<3*request['max_source_bytes']+WRITE_HEADROOM:
        fail('source_media_merge_peak_not_reserved','invalid_request')
    directory=Path(request['output_dir'])
    if not directory.is_absolute():fail('source_media_stage_invalid','invalid_request')
    try:info=directory.stat(follow_symlinks=False)
    except OSError:fail('source_media_private_stage_required','invalid_request')
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode & 0o077:
        fail('source_media_private_stage_required','invalid_request')
    return identifier,canonical,directory,(info.st_dev,info.st_ino)


def guard(directory,identity,request,*,initial=False):
    current=directory.stat(follow_symlinks=False)
    if not stat.S_ISDIR(current.st_mode) or (current.st_dev,current.st_ino)!=identity:fail('source_media_stage_changed')
    entries=list(islice(directory.iterdir(),17))
    if len(entries)>16:fail('source_media_file_count_exceeded')
    total=0
    for path in entries:
        info=path.stat(follow_symlinks=False)
        if not path.name.startswith('source.') or not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.getuid():
            fail('source_media_stage_contents_changed')
        if info.st_size>request['max_source_bytes']:fail('source_media_file_exceeds_bound')
        total+=info.st_size
    if total>request['max_stage_bytes']-WRITE_HEADROOM:fail('source_media_stage_exceeds_bound')
    reserve=PHYSICAL_RESERVE+(request['max_stage_bytes'] if initial else WRITE_HEADROOM)
    if shutil.disk_usage(directory).free<reserve:fail('source_media_physical_reserve_exhausted','not_ready')


def download(request):
    identifier,canonical,directory,identity=validate(request,worker=True)
    if any(directory.iterdir()):fail('source_media_empty_stage_required','invalid_request')
    if 'ownership_path' in request:
        from .source_media_recovery import await_owner
        owner=await_owner(request,identity)
    guard(directory,identity,request,initial=True)
    os.umask(0o077)
    # Per-file hard cap includes ffmpeg descendants. A merge can concurrently
    # retain two input tracks and one output; caller reserves that whole peak.
    resource.setrlimit(resource.RLIMIT_FSIZE,(request['max_source_bytes'],request['max_source_bytes']))
    import yt_dlp
    deadline=time.monotonic()+request['timeout_seconds']
    def progress(_):
        if time.monotonic()>=deadline:fail('source_media_deadline_exceeded','transient')
        guard(directory,identity,request)
    def match(info,**kwargs):
        if info.get('id')!=identifier and not kwargs.get('incomplete',False):
            fail('source_media_metadata_identity_changed')
    resolution=request['max_resolution']
    options={'logger':QuietLogger(),'quiet':True,'noplaylist':True,'cachedir':False,
             'outtmpl':str(directory/'source.%(ext)s'),'format':f'bestvideo[height<={resolution}][vcodec^=avc][protocol=https]+bestaudio[acodec^=mp4a][protocol=https]',
             'merge_output_format':'mp4','fixup':'never','overwrites':False,'continuedl':False,'nopart':True,
             'max_filesize':request['max_source_bytes'],'buffersize':BUFFER_BYTES,'noresizebuffer':True,
             'http_chunk_size':BUFFER_BYTES,'concurrent_fragment_downloads':1,'progress_delta':0,
             'retries':0,'fragment_retries':0,'extractor_retries':0,'file_access_retries':0,
             'socket_timeout':min(20,request['timeout_seconds']),'progress_hooks':[progress],'postprocessor_hooks':[progress],
             'match_filter':match,'postprocessor_args':{'Merger+ffmpeg_o':['-fs',str(request['max_source_bytes'])]}}
    with yt_dlp.YoutubeDL(options) as ydl:
        info=ydl.extract_info(canonical,download=True)
    if type(info) is not dict or info.get('id')!=identifier or info.get('duration')!=request['duration_seconds']:
        fail('source_media_metadata_identity_changed')
    progress(None)
    path=directory/'source.mp4'
    if not path.is_file():fail('source_media_expected_file_missing')
    if 'ownership_path' in request:
        from .source_media_recovery import completed_download
        completed_download(request,owner)
    return {'video_id':identifier,'filename':'source.mp4','duration_seconds':request['duration_seconds']}


def _regular_digest(path,maximum,deadline):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_uid!=os.getuid() or not 0<before.st_size<=maximum:
            fail('source_media_regular_file_required')
        hasher=hashlib.sha256();size=0
        while chunk:=os.read(fd,min(1048576,maximum-size+1)):
            if time.monotonic()>=deadline:fail('source_media_deadline_exceeded','transient')
            hasher.update(chunk);size+=len(chunk)
            if size>maximum:fail('source_media_file_exceeds_bound')
        after=os.fstat(fd);current=path.stat(follow_symlinks=False)
        identity=lambda i:(i.st_dev,i.st_ino,i.st_size,i.st_mtime_ns,i.st_ctime_ns)
        if identity(before)!=identity(after) or identity(after)!=identity(current) or size!=before.st_size:
            fail('source_media_changed_during_read')
        os.fsync(fd)
        if time.monotonic()>=deadline:fail('source_media_deadline_exceeded','transient')
        return hasher.hexdigest(),size
    finally:os.close(fd)


def acquire_source_media(url,*,expected_video_id,duration_seconds,output_dir,max_source_bytes,max_stage_bytes,max_resolution,timeout_seconds,ownership_path=None):
    started=time.monotonic()
    request=dict(url=url,expected_video_id=expected_video_id,duration_seconds=duration_seconds,output_dir=str(output_dir),max_source_bytes=max_source_bytes,max_stage_bytes=max_stage_bytes,max_resolution=max_resolution,timeout_seconds=timeout_seconds)
    if ownership_path is not None:request['ownership_path']=str(ownership_path)
    identifier,canonical,directory,identity=validate(request)
    if any(directory.iterdir()):fail('source_media_empty_stage_required','invalid_request')
    guard(directory,identity,request,initial=True)
    executable=shutil.which('ffprobe')
    if executable is None or shutil.which('ffmpeg') is None:fail('source_media_probe_executable_missing','not_ready')
    deadline=started+timeout_seconds
    # Reserve cleanup/probe/hash capacity within the single caller deadline.
    worker=request|{'timeout_seconds':deadline-time.monotonic()-12}
    if worker['timeout_seconds']<=.75:fail('source_media_deadline_insufficient','transient')
    start_hook=None
    if ownership_path is not None:
        from .source_media_recovery import begin,launched
        owner=begin(request,identity);worker['owner_attempt']=owner['attempt']
        start_hook=lambda pid,child_deadline:launched(request,owner,pid,child_deadline)
    result=run_bounded_read([sys.executable,'-m',__name__,json.dumps(worker,separators=(',',':'))],timeout_seconds=worker['timeout_seconds']-.75,max_stdout_bytes=16384,
                            on_poll=lambda _:guard(directory,identity,request),on_start=start_hook)
    try:
        envelope=json.loads(result.stdout.decode('utf-8'))
        if result.returncode==1 and set(envelope)=={'failure'}:
            failure=envelope['failure']
            if type(failure) is not dict or set(failure)!={'code','category','status','retry_after_seconds'}:raise ValueError()
            if type(failure['code']) is not str or not re.fullmatch('[a-z0-9_]{1,128}',failure['code']):raise ValueError()
            if failure['category'] not in ('invalid_data','invalid_request','transient','not_ready','access_denied','rate_limit','upstream'):raise ValueError()
            status,delay=failure['status'],failure['retry_after_seconds']
            if status is not None and (type(status) is not int or not 100<=status<=599):raise ValueError()
            if delay is not None and (type(delay) not in (int,float) or not math.isfinite(delay) or delay<0):raise ValueError()
            raise SourceAcquisitionError(**failure)
        if result.returncode!=0 or envelope!={'result':{'video_id':identifier,'filename':'source.mp4','duration_seconds':duration_seconds}}:raise ValueError()
    except (ValueError,TypeError,KeyError,UnicodeError):raise SourceAcquisitionError('source_media_worker_schema_changed','invalid_data') from None
    return verify_media(request,deadline,identity)


def verify_media(request,deadline,identity):
    identifier,canonical,directory,_=validate(request)
    executable=shutil.which('ffprobe')
    guard(directory,identity,request)
    remaining=deadline-time.monotonic()-.75
    if remaining<=0:fail('source_media_deadline_exceeded','transient')
    probe=run_bounded_read([executable,'-v','error','-protocol_whitelist','file,pipe','-show_entries','stream=codec_type,width,height:format=duration','-of','json',str(directory/'source.mp4')],timeout_seconds=min(10,remaining),max_stdout_bytes=65536)
    try:
        measured=json.loads(probe.stdout.decode());streams=measured['streams'];videos=[s for s in streams if s['codec_type']=='video']
        duration=float(measured['format']['duration'])
        if probe.returncode or len(videos)!=1 or not any(s['codec_type']=='audio' for s in streams) or not math.isfinite(duration) or abs(duration-request['duration_seconds'])>1:
            raise ValueError()
        width,height=videos[0]['width'],videos[0]['height']
        if type(width) is not int or type(height) is not int or not 0<width<=8192 or not 0<height<=request['max_resolution']:raise ValueError()
    except (ValueError,TypeError,KeyError,UnicodeError):fail('source_media_full_video_probe_mismatch')
    sha,size=_regular_digest(directory/'source.mp4',request['max_source_bytes'],deadline)
    guard(directory,identity,request)
    if time.monotonic()>=deadline:fail('source_media_deadline_exceeded','transient')
    receipt={'video_id':identifier,'url':canonical,'file_path':str(directory/'source.mp4'),'source_sha256':sha,'source_bytes':size,
            'duration_seconds':duration,'width':width,'height':height,'audio_present':True,
            'provenance':{'kind':'owning_youtube_full_source_acquisition','timebase':'original_full_video_seconds','metadata_duration_seconds':request['duration_seconds'],'resolution_limit':request['max_resolution']}}
    if 'ownership_path' in request:
        from .source_media_recovery import completed_verification
        completed_verification(request,receipt)
    return receipt


def main():
    try:
        if len(sys.argv)!=2 or len(sys.argv[1].encode())>8192:fail('source_media_request_invalid','invalid_request')
        print(json.dumps({'result':download(json.loads(sys.argv[1]))},separators=(',',':')))
        return 0
    except Exception as error:
        error=typed_provider_failure(error,'source_media')
        print(json.dumps({'failure':{k:getattr(error,k) for k in ('code','category','status','retry_after_seconds')}}))
        return 1


if __name__=='__main__':raise SystemExit(main())
