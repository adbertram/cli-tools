"""Real children exercise byte bounds, deadlines, and owned cleanup."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from cli_tools_shared.bounded_read import BoundedReadError, run_bounded_read


def run(code, **options):
    return run_bounded_read([sys.executable, '-c', code], timeout_seconds=options.pop('timeout_seconds', 2),
                            max_stdout_bytes=options.pop('max_stdout_bytes', 4096), **options)


def test_early_exit_returns_exact_bytes_and_discards_stderr():
    result=run("import os;os.write(1,b'ok');os.write(2,b'PRIVATE');raise SystemExit(7)")
    assert result.stdout==b'ok' and result.returncode==7 and result.stderr_bytes==7
    assert 'PRIVATE' not in repr(result)


def test_partial_and_invalid_utf8_stay_raw_for_strict_service_decoding():
    result=run("import os;os.write(1,b'\\xe2\\x82');os.write(1,b'\\xff')")
    assert result.stdout==b'\xe2\x82\xff'
    with pytest.raises(UnicodeDecodeError):result.stdout.decode('utf-8')


@pytest.mark.parametrize('fd,code',[(1,'stdout'),(2,'stderr')])
def test_byte_flood_is_stopped_without_private_output_in_error(fd,code):
    start=time.monotonic()
    with pytest.raises(BoundedReadError,match='read_process_'+code+'_exceeds_bound') as error:
        run(f"import os;\nwhile True:os.write({fd},b'PRIVATE'*1000)",max_stdout_bytes=1024,max_stderr_bytes=1024)
    assert time.monotonic()-start<2.75 and 'PRIVATE' not in str(error.value)


def test_simultaneous_pipe_flood_cannot_deadlock():
    with pytest.raises(BoundedReadError,match='exceeds_bound'):
        run("import os,threading;threading.Thread(target=lambda:os.write(2,b'E'*1000000)).start();os.write(1,b'O'*1000000)",
            max_stdout_bytes=1024,max_stderr_bytes=1024)


def test_timeout_during_slow_drain_is_bounded():
    start=time.monotonic()
    with pytest.raises(BoundedReadError,match='deadline_exceeded'):
        run("import os,time;\nwhile True:os.write(1,b'x');time.sleep(.02)",timeout_seconds=.15)
    assert time.monotonic()-start<.9


def test_hanging_child_and_descendant_are_killed_and_leader_reaped(tmp_path,monkeypatch):
    pids=tmp_path/'pids';real_popen=subprocess.Popen;children=[]
    def launch(*args,**kwargs):
        child=real_popen(*args,**kwargs);children.append(child);return child
    monkeypatch.setattr(subprocess,'Popen',launch)
    code=("import os,time;from pathlib import Path;child=os.fork();"
          f"Path({str(pids)!r}+'.'+str(os.getpid())).write_text(str(os.getpid()));time.sleep(30)")
    with pytest.raises(BoundedReadError,match='deadline_exceeded'):
        run(code,timeout_seconds=.4)
    assert len(children)==1 and children[0].returncode==-signal.SIGKILL
    assert children[0].stdout.closed and children[0].stderr.closed
    ids=[int(p.read_text()) for p in tmp_path.glob('pids.*')]
    assert len(ids)==2
    # The direct child is reaped. A reparented descendant may briefly be zombie;
    # ps verifies it cannot execute and is never signaled by guessed argv.
    listing=subprocess.run(['ps','-o','stat=','-p',','.join(map(str,ids))],capture_output=True,text=True,check=False,timeout=2)
    assert all(row.strip().startswith('Z') for row in listing.stdout.splitlines())


def test_success_closes_descriptors_and_reaps_without_pid_reuse(monkeypatch):
    real_popen=subprocess.Popen;children=[]
    def launch(*args,**kwargs):
        child=real_popen(*args,**kwargs);children.append(child);return child
    monkeypatch.setattr(subprocess,'Popen',launch)
    assert run("print('ok')").stdout==b'ok\n'
    child=children[0]
    assert child.returncode==0 and child.stdout.closed and child.stderr.closed
    with pytest.raises(ChildProcessError):os.waitpid(child.pid,os.WNOHANG)


def test_exited_leader_with_closed_pipe_descendant_still_kills_owned_group(tmp_path):
    marker=tmp_path/'child'
    code=("import os,time;from pathlib import Path;p=os.fork();\n"
          f"if p==0:Path({str(marker)!r}).write_text(str(os.getpid()));os.close(1);os.close(2);time.sleep(30)\n"
          "else:time.sleep(.1);os._exit(0)")
    assert run(code).returncode==0
    child=int(marker.read_text())
    status=subprocess.run(['/bin/ps','-o','stat=','-p',str(child)],capture_output=True,text=True,timeout=1,check=False)
    assert all(s.strip().startswith('Z') for s in status.stdout.splitlines())


def test_membership_probe_fails_closed_on_live_unknown_or_unavailable(monkeypatch):
    from cli_tools_shared import bounded_read as br
    for output in (b'',b'321 S\n',b'invalid row extra\n',b'\xff'):
        monkeypatch.setattr(br,'_run',lambda *a,_output=output,**k:br.ReadResult(_output,0,0))
        assert not br._group_has_no_live_members(321)
    monkeypatch.setattr(br,'_run',lambda *a,**k:br.ReadResult(b'321 Z\n123 S\n',0,0))
    assert br._group_has_no_live_members(321)


@pytest.mark.parametrize('options',[{'timeout_seconds':True},{'timeout_seconds':float('inf')},
    {'max_stdout_bytes':0},{'max_stderr_bytes':True}])
def test_invalid_bounds_refuse_before_spawn(options,monkeypatch):
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:pytest.fail('spawned'))
    with pytest.raises(BoundedReadError):run('pass',**options)


def test_start_callback_failure_kills_reaps_and_closes_pipes(monkeypatch):
 real_popen=subprocess.Popen;children=[]
 def launch(*args,**kwargs):
  child=real_popen(*args,**kwargs);children.append(child);return child
 monkeypatch.setattr(subprocess,'Popen',launch)
 def callback(pid,deadline):
  assert pid==children[0].pid and deadline>time.monotonic()
  raise ValueError('marker unavailable')
 with pytest.raises(ValueError,match='marker unavailable'):run('import time;time.sleep(30)',on_start=callback)
 child=children[0]
 assert child.returncode==-signal.SIGKILL and child.stdout.closed and child.stderr.closed
 with pytest.raises(ChildProcessError):os.waitpid(child.pid,os.WNOHANG)


def test_poll_guard_failure_preserves_error_and_kills_reaps_owned_group(tmp_path,monkeypatch):
 marker=tmp_path/'owned-child';real_popen=subprocess.Popen;leaders=[]
 def launch(*args,**kwargs):
  p=real_popen(*args,**kwargs);leaders.append(p);return p
 monkeypatch.setattr(subprocess,'Popen',launch)
 class GuardError(Exception):pass
 failure=GuardError('disk guard')
 def poll(deadline):
  assert deadline>time.monotonic()
  if marker.exists():raise failure
 code="import os,time;from pathlib import Path;p=os.fork();\nif p==0:Path("+repr(str(marker))+").write_text(str(os.getpid()));os.close(1);os.close(2);time.sleep(30)\nelse:time.sleep(30)"
 with pytest.raises(GuardError) as caught:run(code,on_poll=poll)
 assert caught.value is failure and leaders[0].returncode==-signal.SIGKILL
 assert leaders[0].stdout.closed and leaders[0].stderr.closed
 with pytest.raises(ChildProcessError):os.waitpid(leaders[0].pid,os.WNOHANG)
 listing=subprocess.run(['/bin/ps','-o','stat=','-p',marker.read_text()],capture_output=True,text=True,timeout=1,check=False)
 assert all(s.strip().startswith('Z') for s in listing.stdout.splitlines())


def test_poll_time_counts_against_original_deadline():
 started=time.monotonic();calls=[]
 def poll(deadline):calls.append(deadline);time.sleep(.04)
 with pytest.raises(BoundedReadError,match='deadline_exceeded'):run('import time;time.sleep(30)',timeout_seconds=.1,on_poll=poll)
 assert len(set(calls))==1 and time.monotonic()-started<.3


@pytest.mark.skipif(sys.platform != 'darwin', reason='the kqueue exit watch is the macOS fallback')
def test_macos_without_waitid_uses_a_non_reaping_kqueue_exit_watch(monkeypatch):
    """macOS has os.waitid only from Python 3.13; the package supports 3.11 and 3.12 too."""
    from cli_tools_shared import bounded_read

    monkeypatch.delattr(bounded_read.os, 'waitid', raising=False)
    result=run("import os;os.write(1,b'ok');raise SystemExit(3)")
    assert result.stdout==b'ok' and result.returncode==3
    with pytest.raises(BoundedReadError,match='read_process_deadline_exceeded'):
        run("import time;time.sleep(5)",timeout_seconds=.3)
    # A child that is already a zombie when the watch registers has exited, and stays unreaped.
    child=subprocess.Popen(['/usr/bin/true'])
    time.sleep(.3)
    watch=bounded_read._ExitWatch(child.pid)
    try:
        assert watch.poll() is True
    finally:
        watch.close()
    assert child.wait(timeout=1)==0
