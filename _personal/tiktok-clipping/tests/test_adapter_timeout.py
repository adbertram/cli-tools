import os
import signal
import subprocess
import sys
from pathlib import Path
import pytest
from conftest import config, clock
from tiktok_clipping_cli import adapters
from tiktok_clipping_cli.engine import AdapterFailure


def test_ps_timeout_still_kills_and_reaps_real_worker(config, monkeypatch):
    scratch = Path(__file__).parent
    Path(config['workspace']).mkdir(parents=True)
    config['adapter_module'] = 'worker_fixture'
    monkeypatch.setenv('PYTHONPATH', str(scratch) + os.pathsep + str(scratch.parent))
    real_popen = subprocess.Popen
    captured = []
    def capture_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        captured.append(process)
        return process
    def ps_timeout(command, **kwargs):
        assert command == ['ps', '-axo', 'pid=,ppid=']
        raise subprocess.TimeoutExpired(command, 2)
    monkeypatch.setattr(adapters.subprocess, 'Popen', capture_popen)
    monkeypatch.setattr(adapters.subprocess, 'run', ps_timeout)
    adapter = adapters.ExternalAdapter(config)
    adapter.timeout = 0.5
    alive = started = False
    try:
        with pytest.raises(AdapterFailure, match='adapter_work_timeout'):
            adapter.call('discover', (config['sources'][0],))
        process = captured[0]
        alive = process.poll() is None
        started = Path(config['workspace'], 'worker-started').is_file()
        print('PS_TIMEOUT', 'worker_pid', process.pid, 'worker_started', started, 'worker_alive_after_timeout', alive, flush=True)
    finally:
        for process in captured:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.communicate(timeout=2)
    assert started and not alive


def test_real_worker_preserves_typed_provider_failure_across_process_boundary(config, monkeypatch):
    scratch = Path(__file__).parent
    Path(config['workspace']).mkdir(parents=True)
    config['adapter_module'] = 'worker_fixture'
    monkeypatch.setenv('PYTHONPATH', str(scratch) + os.pathsep + str(scratch.parent))
    adapter = adapters.ExternalAdapter(config)
    with pytest.raises(AdapterFailure) as caught:
        adapter.call('verify_ready', ({},))
    failure = caught.value
    assert (failure.category, failure.provider, failure.code, failure.status, failure.retry_after) == ('rate_limit', 'whop', 'read_throttled', 429, 172800.25)


def test_real_worker_preserves_safe_diagnostics(config, monkeypatch):
    scratch = Path(__file__).parent
    config['adapter_module'] = 'worker_fixture'
    monkeypatch.setenv('PYTHONPATH', str(scratch) + os.pathsep + str(scratch.parent))
    with pytest.raises(AdapterFailure) as caught:
        adapters.ExternalAdapter(config).call('quality', ({},))
    assert caught.value.diagnostics == {'kind':'submission_form_predicate', 'available':False, 'context_origin':'whop_wrapper', 'route_match':False}
