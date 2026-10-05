"""Crash-safe acquisition ownership; no provider I/O in fixtures."""
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest

from cli_tools_shared.bounded_read import run_bounded_read
from youtube_cli import source_media as media,source_media_recovery as recovery
from youtube_cli.source_acquisition import SourceAcquisitionError
from test_source_media import args


def owned(tmp_path):
    request=args(tmp_path);stage=Path(request['output_dir']);request['ownership_path']=str(stage.with_name(stage.name+'.owner.json'))
    _,_,_,identity=media.validate(request)
    owner=recovery.begin(request,identity);owner['worker']={'pid':12345,'start_identity':'TEST exact original start'}
    recovery.write(Path(request['ownership_path']),owner)
    return request,owner


def ended(monkeypatch):
    monkeypatch.setattr(recovery,'process_identity',lambda *a:None)
    monkeypatch.setattr(recovery,'_group_has_no_live_members',lambda pid:True)


def test_crash_after_download_before_coordinator_commit_recovers_verified_bytes(tmp_path,monkeypatch):
    request,owner=owned(tmp_path);ended(monkeypatch)
    Path(request['output_dir'],'source.mp4').write_bytes(b'TEST completed source')
    owner['phase']='download_complete';recovery.write(Path(request['ownership_path']),owner)
    monkeypatch.setattr(media.shutil,'which',lambda _: '/usr/bin/tool')
    monkeypatch.setattr(media,'run_bounded_read',lambda *a,**k:SimpleNamespace(returncode=0,stdout=json.dumps({'streams':[{'codec_type':'video','width':854,'height':480},{'codec_type':'audio'}],'format':{'duration':'3522'}}).encode()))
    result=recovery.recover(request)
    assert result['state']=='complete' and result['media']['source_bytes']==21
    assert recovery.read(Path(request['ownership_path']))['phase']=='complete'
    assert recovery.recover(request)==result


def test_exact_ended_partial_retirement_is_resumable(tmp_path,monkeypatch):
    request,owner=owned(tmp_path);ended(monkeypatch)
    path=Path(request['output_dir'],'source.f134.mp4');path.write_bytes(b'TEST partial')
    original=recovery.write;states=[]
    def interruption(marker,value):
        original(marker,value);states.append(value['phase'])
        if value['phase']=='retiring':raise InterruptedError('TEST crash before unlink')
    monkeypatch.setattr(recovery,'write',interruption)
    with pytest.raises(InterruptedError):recovery.recover(request)
    assert path.exists()
    monkeypatch.setattr(recovery,'write',original)
    assert recovery.recover(request)=={'state':'retired'}
    assert not path.exists() and recovery.read(Path(request['ownership_path']))['phase']=='retired'


@pytest.mark.parametrize('case',['unknown','active','reused','group','binding','foreign','symlink'])
def test_unknown_or_changed_ownership_never_adopted_or_deleted(tmp_path,monkeypatch,case):
    request,owner=owned(tmp_path);ended(monkeypatch)
    path=Path(request['output_dir'],'source.mp4');path.write_bytes(b'keep')
    if case=='unknown':owner['worker']=None
    elif case=='active':monkeypatch.setattr(recovery,'process_identity',lambda *a:owner['worker'])
    elif case=='reused':monkeypatch.setattr(recovery,'process_identity',lambda *a:owner['worker']|{'start_identity':'different'})
    elif case=='group':monkeypatch.setattr(recovery,'_group_has_no_live_members',lambda pid:False)
    elif case=='binding':owner['binding']='f'*64
    elif case=='foreign':Path(request['output_dir'],'foreign').write_bytes(b'keep')
    elif case=='symlink':path.unlink();path.symlink_to(tmp_path/'foreign');(tmp_path/'foreign').write_bytes(b'keep')
    recovery.write(Path(request['ownership_path']),owner)
    with pytest.raises(SourceAcquisitionError):recovery.recover(request)
    assert path.read_bytes()==b'keep'


def test_real_delayed_marker_gates_child_before_any_artifact(tmp_path):
    request=args(tmp_path);stage=Path(request['output_dir']);request['ownership_path']=str(stage.with_name(stage.name+'.owner.json'))
    _,_,_,identity=media.validate(request);owner=recovery.begin(request,identity)
    request['owner_attempt']=owner['attempt'];path=stage/'source.mp4'
    code="from youtube_cli.source_media_recovery import await_owner;import json,sys;from pathlib import Path;r=json.loads(sys.argv[1]);await_owner(r,tuple(json.loads(sys.argv[2])));Path(r['output_dir'],'source.mp4').write_bytes(b'owned');print('ready')"
    def on_start(pid,deadline):
        time.sleep(.25)
        assert not path.exists()
        recovery.launched(request,owner,pid,deadline)
    result=run_bounded_read([sys.executable,'-c',code,json.dumps(request),json.dumps(identity)],timeout_seconds=10,max_stdout_bytes=1024,on_start=on_start)
    assert result.returncode==0 and result.stdout==b'ready\n' and path.read_bytes()==b'owned'


def test_real_child_cannot_write_without_marker_handshake(tmp_path):
    request=args(tmp_path);stage=Path(request['output_dir']);request['ownership_path']=str(stage.with_name(stage.name+'.owner.json'))
    _,_,_,identity=media.validate(request);owner=recovery.begin(request,identity)
    request.update(owner_attempt=owner['attempt'],timeout_seconds=.15)
    code="from youtube_cli.source_media_recovery import await_owner;import json,sys;from pathlib import Path;r=json.loads(sys.argv[1]);await_owner(r,tuple(json.loads(sys.argv[2])));Path(r['output_dir'],'source.mp4').write_bytes(b'forbidden')"
    result=run_bounded_read([sys.executable,'-c',code,json.dumps(request),json.dumps(identity)],timeout_seconds=5,max_stdout_bytes=1024)
    assert result.returncode!=0 and not (stage/'source.mp4').exists()


def test_repeated_recovery_changed_playable_bytes_never_rewrites_saved_receipt(tmp_path,monkeypatch):
    request,owner=owned(tmp_path);ended(monkeypatch)
    path=Path(request['output_dir'],'source.mp4');path.write_bytes(b'TEST original completed')
    owner['phase']='download_complete';marker=Path(request['ownership_path']);recovery.write(marker,owner)
    monkeypatch.setattr(media.shutil,'which',lambda _: '/usr/bin/tool')
    monkeypatch.setattr(media,'run_bounded_read',lambda *a,**k:SimpleNamespace(returncode=0,stdout=json.dumps({'streams':[{'codec_type':'video','width':854,'height':480},{'codec_type':'audio'}],'format':{'duration':'3522'}}).encode()))
    original=recovery.recover(request);before=marker.read_bytes()
    path.write_bytes(b'TEST changed playable bytes')
    for _ in range(2):
        with pytest.raises(SourceAcquisitionError,match='completed_receipt_changed'):recovery.recover(request)
        assert marker.read_bytes()==before and recovery.read(marker)['receipt']==original['media']
