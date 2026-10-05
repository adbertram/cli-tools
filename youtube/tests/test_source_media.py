import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from youtube_cli import source_media as media
from youtube_cli.source_acquisition import SourceAcquisitionError


def args(tmp_path):
 stage=tmp_path/'stage';stage.mkdir(mode=0o700)
 return dict(url='https://www.youtube.com/watch?v=h1FbFhWkcGI',expected_video_id='h1FbFhWkcGI',duration_seconds=3522,
             output_dir=str(stage),max_source_bytes=1048576,max_stage_bytes=4*1048576,max_resolution=480,timeout_seconds=60)


def test_actual_file_hash_and_full_timeline_probe_return_not_metadata_only(tmp_path,monkeypatch):
 request=args(tmp_path);calls=[];monkeypatch.setattr(media.shutil,'which',lambda tool:'/usr/bin/'+tool)
 def run(argv,**kw):
  calls.append((argv,kw))
  if len(calls)==1:
   Path(request['output_dir'],'source.mp4').write_bytes(b'actual owned media')
   kw['on_poll'](0)
   return SimpleNamespace(returncode=0,stdout=json.dumps({'result':{'video_id':'h1FbFhWkcGI','filename':'source.mp4','duration_seconds':3522}}).encode())
  return SimpleNamespace(returncode=0,stdout=json.dumps({'streams':[{'codec_type':'video','width':854,'height':480},{'codec_type':'audio'}],'format':{'duration':'3521.96'}}).encode())
 monkeypatch.setattr(media,'run_bounded_read',run)
 result=media.acquire_source_media(**request)
 assert result['source_sha256']==hashlib.sha256(b'actual owned media').hexdigest()
 assert result['source_bytes']==18 and result['duration_seconds']==3521.96
 assert result['provenance']['timebase']=='original_full_video_seconds'
 assert calls[0][1]['timeout_seconds']<48 and calls[1][1]['timeout_seconds']<=10


@pytest.mark.parametrize('change', ['peak','private','nonempty','physical','missing_binary','wrong_id'])
def test_preflight_refuses_before_child_or_provider_io(tmp_path,monkeypatch,change):
 request=args(tmp_path);monkeypatch.setattr(media.shutil,'which',lambda _: '/usr/bin/tool')
 monkeypatch.setattr(media,'run_bounded_read',lambda *a,**k:pytest.fail('must not launch'))
 if change=='peak':request['max_stage_bytes']=3*request['max_source_bytes']
 elif change=='private':Path(request['output_dir']).chmod(0o755)
 elif change=='nonempty':Path(request['output_dir'],'foreign.mp4').write_bytes(b'keep')
 elif change=='physical':monkeypatch.setattr(media.shutil,'disk_usage',lambda _:SimpleNamespace(free=media.PHYSICAL_RESERVE))
 elif change=='missing_binary':monkeypatch.setattr(media.shutil,'which',lambda _:None)
 elif change=='wrong_id':request['expected_video_id']='abcdefghijk'
 with pytest.raises(SourceAcquisitionError):media.acquire_source_media(**request)


def test_bounded_guard_rejects_symlink_hardlink_oversize_and_unknown_file(tmp_path):
 request=args(tmp_path);_,_,stage,identity=media.validate(request)
 outside=tmp_path/'outside';outside.write_bytes(b'keep')
 path=stage/'source.mp4';path.symlink_to(outside)
 with pytest.raises(SourceAcquisitionError):media.guard(stage,identity,request)
 path.unlink();os.link(outside,path)
 with pytest.raises(SourceAcquisitionError):media.guard(stage,identity,request)
 path.unlink();path.write_bytes(b'x'*(request['max_source_bytes']+1))
 with pytest.raises(SourceAcquisitionError):media.guard(stage,identity,request)
 path.unlink();(stage/'foreign').write_text('keep')
 with pytest.raises(SourceAcquisitionError):media.guard(stage,identity,request)
 assert outside.read_bytes()==b'keep'


def test_stage_identity_and_bounded_entry_count(tmp_path):
 request=args(tmp_path);_,_,stage,identity=media.validate(request)
 for i in range(17):(stage/f'source.{i}').write_bytes(b'x')
 with pytest.raises(SourceAcquisitionError,match='file_count'):media.guard(stage,identity,request)
 replacement=tmp_path/'replacement';replacement.mkdir(mode=0o700)
 with pytest.raises(SourceAcquisitionError,match='stage_changed'):media.guard(replacement,identity,request)


def test_shortened_media_is_never_full_source_success(tmp_path,monkeypatch):
 request=args(tmp_path);monkeypatch.setattr(media.shutil,'which',lambda _: '/usr/bin/tool');calls=[]
 def run(*a,**k):
  calls.append(1)
  if len(calls)==1:
   Path(request['output_dir'],'source.mp4').write_bytes(b'cut')
   return SimpleNamespace(returncode=0,stdout=json.dumps({'result':{'video_id':'h1FbFhWkcGI','filename':'source.mp4','duration_seconds':3522}}).encode())
  return SimpleNamespace(returncode=0,stdout=json.dumps({'streams':[{'codec_type':'video','width':854,'height':480},{'codec_type':'audio'}],'format':{'duration':'30'}}).encode())
 monkeypatch.setattr(media,'run_bounded_read',run)
 with pytest.raises(SourceAcquisitionError,match='full_video_probe_mismatch'):media.acquire_source_media(**request)


def test_file_hash_refuses_fifo_without_blocking(tmp_path):
 fifo=tmp_path/'fifo';os.mkfifo(fifo)
 with pytest.raises(SourceAcquisitionError,match='regular_file'):media._regular_digest(fifo,1000,float('inf'))


def test_preflight_work_consumes_single_deadline_and_cannot_launch_after_expiry(tmp_path,monkeypatch):
 request=args(tmp_path);clock=[100.0]
 monkeypatch.setattr(media.time,'monotonic',lambda:clock[0])
 monkeypatch.setattr(media.shutil,'which',lambda _: '/usr/bin/tool')
 real_guard=media.guard
 def slow_guard(*a,**k):
  real_guard(*a,**k);clock[0]+=50
 monkeypatch.setattr(media,'guard',slow_guard)
 monkeypatch.setattr(media,'run_bounded_read',lambda *a,**k:pytest.fail('expired preflight must not launch'))
 with pytest.raises(SourceAcquisitionError,match='deadline_insufficient'):media.acquire_source_media(**request)
