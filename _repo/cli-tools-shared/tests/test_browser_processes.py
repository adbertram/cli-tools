from cli_tools_shared.browser.processes import (
    ProcessCommand,
    command_user_data_dir,
    is_chromium_process_command,
    profile_lifecycle_lock_path,
    profile_process_owner,
    profile_process_pids,
    protected_process_ids,
    safe_process_command_summary,
    terminate_profile_processes,
)


def test_profile_process_pids_excludes_current_process_ancestors_when_wrapper_mentions_profile(tmp_path):
    profile = tmp_path / "chromium-profile"
    rows = [
        ProcessCommand(
            100,
            1,
            "S",
            f"/bin/bash -lc python3 <<'PY' Google Chrome --user-data-dir={profile} PY",
        ),
        ProcessCommand(
            200,
            100,
            "S",
            f"python3 -c marker='Chromium --user-data-dir={profile}'",
        ),
        ProcessCommand(
            300,
            1,
            "S",
            f"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --user-data-dir={profile}",
        ),
        ProcessCommand(
            301,
            1,
            "S",
            f"/Applications/Google Chrome Helper --user-data-dir {profile}",
        ),
    ]

    assert protected_process_ids(rows, current_pid=200, parent_pid=100) == {200, 100, 1}
    assert profile_process_pids(profile, processes=rows, current_pid=200, parent_pid=100) == [300, 301]


def test_profile_process_pids_reports_no_targets_for_self_matching_wrapper_only(tmp_path):
    profile = tmp_path / "chromium-profile"
    rows = [
        ProcessCommand(
            100,
            1,
            "S",
            f"/bin/bash -lc python3 <<'PY' Google Chrome --user-data-dir={profile} PY",
        ),
        ProcessCommand(
            200,
            100,
            "S",
            f"python3 -c marker='Chromium --user-data-dir={profile}'",
        ),
    ]

    assert profile_process_pids(profile, processes=rows, current_pid=200, parent_pid=100) == []


def test_profile_process_pids_never_targets_unrelated_wrapper_outside_ancestry(tmp_path):
    profile = tmp_path / "chromium-profile"
    rows = [
        ProcessCommand(50, 1, "S", f"/bin/bash -lc cleanup --user-data-dir={profile}"),
        ProcessCommand(51, 50, "S", f"node helper.js --user-data-dir={profile}"),
        ProcessCommand(
            300,
            1,
            "S",
            f"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --user-data-dir={profile}",
        ),
    ]

    assert profile_process_pids(profile, processes=rows, current_pid=200, parent_pid=100) == [300]


def test_is_chromium_process_command_checks_executable_not_argument_text(tmp_path):
    profile = tmp_path / "chromium-profile"

    assert is_chromium_process_command(
        f"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --user-data-dir={profile}"
    )
    assert is_chromium_process_command(f"/usr/bin/chromium --user-data-dir={profile}")
    assert not is_chromium_process_command(
        f"/bin/bash -lc 'Google Chrome --user-data-dir={profile}'"
    )
    assert not is_chromium_process_command(f"node helper.js --user-data-dir={profile}")


def test_profile_process_pids_matches_unquoted_macos_app_bundle_executable(tmp_path):
    profile = tmp_path / "chromium-profile"
    command = (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
        f"--disable-sync --user-data-dir={profile} --remote-debugging-pipe about:blank"
    )

    assert profile_process_pids(
        profile,
        processes=[ProcessCommand(13510, 13509, "Ss", command)],
        current_pid=200,
        parent_pid=100,
    ) == [13510]


def test_command_user_data_dir_supports_equals_space_and_quotes(tmp_path):
    profile = tmp_path / "profile with spaces"
    compact_profile = tmp_path / "profile"

    assert command_user_data_dir(f"chrome --user-data-dir={compact_profile}") == str(compact_profile)
    assert command_user_data_dir(f"chrome --user-data-dir '{profile}'") == str(profile)
    assert command_user_data_dir(f'chrome --user-data-dir="{profile}"') == str(profile)


def test_profile_lifecycle_lock_path_uses_resolved_profile_path(tmp_path):
    profile = tmp_path / "nested" / ".." / "chromium-profile"

    assert profile_lifecycle_lock_path(profile) == tmp_path / ".chromium-profile.lifecycle.lock"


def test_profile_owner_reports_root_chrome_and_redacts_parent_secret(tmp_path):
    profile = tmp_path / "chromium-profile"
    rows = [
        ProcessCommand(700, 1, "S", "python external-cli.py --token super-secret"),
        ProcessCommand(
            701,
            700,
            "S",
            f"/Applications/Google Chrome --user-data-dir={profile.resolve()}",
        ),
        ProcessCommand(
            702,
            701,
            "S",
            f"/Applications/Google Chrome Helper --user-data-dir={profile.resolve()}",
        ),
    ]

    owner = profile_process_owner(profile, processes=rows, current_pid=200, parent_pid=100)

    assert owner is not None
    assert owner.pid == 701
    assert owner.parent_pid == 700
    assert owner.parent_command == "python external-cli.py --token <redacted>"
    assert "super-secret" not in safe_process_command_summary(
        "python external-cli.py https://example.invalid/?token=super-secret&x=1"
    )


def test_profile_owner_matches_equivalent_user_data_dir_path(tmp_path):
    profile = tmp_path / "chromium-profile"
    profile.mkdir()
    (tmp_path / "profiles").mkdir()
    equivalent_profile = tmp_path / "profiles" / ".." / "chromium-profile"
    rows = [
        ProcessCommand(700, 1, "S", "python external-cli.py"),
        ProcessCommand(
            701,
            700,
            "S",
            f"/Applications/Google Chrome --user-data-dir={equivalent_profile}",
        ),
    ]

    owner = profile_process_owner(profile, processes=rows, current_pid=200, parent_pid=100)

    assert owner is not None
    assert owner.pid == 701


def test_terminate_profile_processes_stops_only_profile_owned_pids(tmp_path, monkeypatch):
    profile = tmp_path / "chromium-profile"
    alive = {300, 301, 400}
    signals = []

    rows = [
        ProcessCommand(
            300,
            1,
            "S",
            f"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --user-data-dir={profile}",
        ),
        ProcessCommand(
            301,
            300,
            "S",
            f"/Applications/Google Chrome Helper --user-data-dir={profile}",
        ),
        ProcessCommand(
            400,
            1,
            "S",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --user-data-dir=/tmp/other",
        ),
    ]

    def fake_list_process_commands():
        return [row for row in rows if row.pid in alive]

    def fake_kill(pid, sig):
        signals.append((pid, sig))
        alive.discard(pid)

    monkeypatch.setattr("cli_tools_shared.browser.processes.list_process_commands", fake_list_process_commands)
    monkeypatch.setattr("cli_tools_shared.browser.processes.os.kill", fake_kill)

    stopped = terminate_profile_processes(profile, poll_interval=0)

    assert stopped == [300, 301]
    assert [pid for pid, _sig in signals] == [300, 301]
    assert alive == {400}


def _mock_process_bytes(monkeypatch, raw):
    from types import SimpleNamespace
    from cli_tools_shared.browser import processes
    def run(argv, **options):
        assert argv==['ps','ax','-o','pid=,ppid=,stat=,command=']
        assert options['capture_output'] is True and options['check'] is True
        return SimpleNamespace(stdout=raw.decode(options.get('encoding','utf-8'),options.get('errors','strict')))
    monkeypatch.setattr(processes.subprocess,'run',run)
    return processes


def test_invalid_unrelated_argv_does_not_hide_exact_owned_browser(monkeypatch,tmp_path):
    import json
    profile=tmp_path/'chromium-profile'
    raw=b'50 1 S /usr/bin/python unrelated-\xe2-byte\n'+f'300 1 S /usr/bin/chromium --user-data-dir={profile}\n'.encode()
    processes=_mock_process_bytes(monkeypatch,raw)
    rows=processes.list_process_commands()
    assert rows[0].command.encode('utf-8','surrogateescape')==b'/usr/bin/python unrelated-\xe2-byte'
    pids=profile_process_pids(profile,processes=rows,current_pid=200,parent_pid=100)
    assert pids==[300]
    assert json.dumps({'browser_pids':pids})=='{"browser_pids": [300]}'


def test_valid_nonascii_owned_profile_survives_process_decode(monkeypatch,tmp_path):
    profile=tmp_path/'账户-é-chromium-profile'
    raw=f'300 1 S /usr/bin/chromium --user-data-dir={profile}\n'.encode('utf-8')+b'50 1 S /bin/other \xff\n'
    processes=_mock_process_bytes(monkeypatch,raw)
    assert processes.profile_process_pids(profile,current_pid=200,parent_pid=100)==[300]


def test_malformed_owned_path_cannot_match_valid_or_replacement_profile(monkeypatch,tmp_path):
    profile=tmp_path/'chromium-profile'
    raw=f'300 1 S /usr/bin/chromium --user-data-dir={profile}'.encode()+b'\xe2-byte\n'
    processes=_mock_process_bytes(monkeypatch,raw)
    assert processes.profile_process_pids(profile,current_pid=200,parent_pid=100)==[]
    assert processes.profile_process_pids(str(profile)+'�-byte',current_pid=200,parent_pid=100)==[]


def test_bounded_inspection_hung_ps_does_not_signal(monkeypatch):
    import subprocess
    import pytest
    from cli_tools_shared.browser import processes as p
    def hung(*args,**kwargs):
        assert 0<kwargs['timeout']<=.2
        raise subprocess.TimeoutExpired('SECRET ARGV',kwargs['timeout'])
    monkeypatch.setattr(p.subprocess,'run',hung)
    monkeypatch.setattr(p.os,'kill',lambda *args:pytest.fail('signal after unknown inspection'))
    with pytest.raises(p.ProcessTableUnavailableError,match='inspection timed out') as exc:
        p.terminate_process(123,timeout=.3,inspection_timeout=.2)
    assert 'SECRET' not in str(exc.value)


def test_bounded_termination_rechecks_owner_before_each_signal_and_rejects_pid_reuse(monkeypatch):
    import signal
    import pytest
    from cli_tools_shared.browser import processes as p
    signals=[];checks=iter([True,False])
    monkeypatch.setattr(p,'_pid_running',lambda *args,**kwargs:True)
    monkeypatch.setattr(p.os,'kill',lambda pid,sig:signals.append(sig))
    with pytest.raises(RuntimeError,match='ownership changed'):
        p.terminate_process(123,timeout=.02,poll_interval=.002,inspection_timeout=.01,ownership_check=lambda remaining:next(checks))
    assert signals==[signal.SIGTERM]


def test_bounded_termination_uses_decreasing_remaining_budget(monkeypatch):
    import pytest,time
    from cli_tools_shared.browser import processes as p
    budgets=[]
    def inspection(pid,*,timeout):budgets.append(timeout);time.sleep(min(timeout,.006));return True
    monkeypatch.setattr(p,'_pid_running',inspection)
    monkeypatch.setattr(p.os,'kill',lambda *args:None)
    with pytest.raises((RuntimeError,p.ProcessTableUnavailableError)):
        p.terminate_process(123,timeout=.2,poll_interval=.001,inspection_timeout=1)
    assert all(b<=.2 for b in budgets) and budgets[-1]<budgets[0]
