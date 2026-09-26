from cli_tools_shared.browser.processes import (
    ProfileLifecycleLock,
    ProcessCommand,
    command_remote_debugging_port,
    command_user_data_dir,
    is_chromium_process_command,
    profile_process_pids,
    protected_process_ids,
    remove_stale_profile_lock_files,
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


def test_command_remote_debugging_port_supports_equals_and_space():
    assert command_remote_debugging_port("chrome --remote-debugging-port=48321") == 48321
    assert command_remote_debugging_port("chrome --remote-debugging-port 48322") == 48322
    assert command_remote_debugging_port("chrome --remote-debugging-address=127.0.0.1") is None


def test_profile_process_pids_requires_matching_profile_and_port(tmp_path):
    profile = tmp_path / "chromium-profile"
    rows = [
        ProcessCommand(
            300,
            1,
            "S",
            f"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
            f"--user-data-dir={profile} --remote-debugging-port=48321",
        ),
        ProcessCommand(
            301,
            1,
            "S",
            f"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
            f"--user-data-dir={profile} --remote-debugging-port=48322",
        ),
        ProcessCommand(
            302,
            1,
            "S",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
            "--user-data-dir=/tmp/other --remote-debugging-port=48321",
        ),
    ]

    assert profile_process_pids(
        profile,
        processes=rows,
        current_pid=200,
        parent_pid=100,
        remote_debugging_port=48321,
    ) == [300]


def test_profile_lifecycle_lock_uses_a_single_profile_scoped_file(tmp_path):
    profile = tmp_path / "chromium-profile"
    first = ProfileLifecycleLock(profile)

    first.acquire()
    try:
        assert first.file is not None
        assert first.path == tmp_path / ".chromium-profile.lifecycle.lock"
        assert first.path.is_file()
    finally:
        first.release()

    assert first.file is None


def test_remove_stale_profile_lock_files_removes_only_singleton_artifacts(tmp_path):
    profile = tmp_path / "chromium-profile"
    profile.mkdir()
    (profile / "SingletonLock").symlink_to("old-host-99999")
    (profile / "SingletonCookie").write_text("stale")
    untouched = profile / "Default"
    untouched.mkdir()

    remove_stale_profile_lock_files(profile)

    assert not (profile / "SingletonLock").is_symlink()
    assert not (profile / "SingletonCookie").exists()
    assert untouched.is_dir()


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
