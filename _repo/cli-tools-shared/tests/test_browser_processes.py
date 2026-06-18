from cli_tools_shared.browser.processes import (
    ProcessCommand,
    command_user_data_dir,
    profile_process_pids,
    protected_process_ids,
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


def test_command_user_data_dir_supports_equals_space_and_quotes(tmp_path):
    profile = tmp_path / "profile with spaces"
    compact_profile = tmp_path / "profile"

    assert command_user_data_dir(f"chrome --user-data-dir={compact_profile}") == str(compact_profile)
    assert command_user_data_dir(f"chrome --user-data-dir '{profile}'") == str(profile)
    assert command_user_data_dir(f'chrome --user-data-dir="{profile}"') == str(profile)


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
