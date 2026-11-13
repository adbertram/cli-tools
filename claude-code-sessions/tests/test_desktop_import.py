import json
from typer.testing import CliRunner
from claude_code_sessions_cli.commands import desktop


def test_import_graph_conflicts_and_idempotency(tmp_path, monkeypatch):
    store = tmp_path / 'Claude' / 'claude-code-sessions'; projects = tmp_path / 'projects'
    source = store / 'a' / 'o'; dest = store / 'b' / 'p'
    source.mkdir(parents=True); dest.mkdir(parents=True); (projects / 'project').mkdir(parents=True)
    monkeypatch.setattr(desktop, 'APP_SUPPORT', tmp_path); monkeypatch.setattr(desktop, 'PROJECTS', projects)
    def record(directory, sid, cli, title, **kwargs):
        (directory / f'{sid}.json').write_text(json.dumps({'sessionId': sid, 'cliSessionId': cli, 'title': title, **kwargs}))
        (projects / 'project' / f'{cli}.jsonl').write_text('{}\n')
    record(source, 'local_root', 'root', 'Target', peerReceipts=[{'targetSessionId': 'local_peer'}])
    record(source, 'local_peer', 'peer', 'Peer')
    record(source, 'local_child', 'child', 'Child', spawnedFrom={'sessionId': 'local_peer'})
    record(dest, 'local_existing', 'existing', 'Existing')
    args = ['import', 'Target', '--source-account', 'a', '--source-organization', 'o', '--destination-account', 'b', '--destination-organization', 'p']
    runner = CliRunner()
    preview = runner.invoke(desktop.app, args + ['--dry-run'])
    assert preview.exit_code == 0, preview.output
    assert len(json.loads(preview.stdout)['sessions']) == 3
    assert len(list(dest.glob('*.json'))) == 1
    conflict = dest / 'local_peer.json'; conflict.write_text('{}')
    assert runner.invoke(desktop.app, args + ['--yes']).exit_code != 0
    assert not (dest / 'local_root.json').exists()
    conflict.unlink()
    result = runner.invoke(desktop.app, args + ['--yes'])
    assert result.exit_code == 0, result.output
    for name in ('local_root', 'local_peer', 'local_child'):
        assert (source / f'{name}.json').read_bytes() == (dest / f'{name}.json').read_bytes()
    repeat = runner.invoke(desktop.app, args + ['--dry-run'])
    assert all(r['status'] == 'identical' for r in json.loads(repeat.stdout)['sessions'])
    record(source, 'local_duplicate', 'duplicate', 'Target')
    assert runner.invoke(desktop.app, args + ['--dry-run']).exit_code != 0
    selected = runner.invoke(desktop.app, args + ['--session-id', 'local_duplicate', '--yes'])
    assert selected.exit_code == 0, selected.output
    assert (dest / 'local_duplicate.json').exists()
    assert runner.invoke(desktop.app, args + ['--session-id', 'local_existing', '--dry-run']).exit_code != 0
    wrong_title = args.copy(); wrong_title[1] = 'Wrong title'
    assert runner.invoke(desktop.app, wrong_title + ['--session-id', 'local_duplicate', '--dry-run']).exit_code != 0


def test_desktop_archive_filter(tmp_path, monkeypatch):
    source = tmp_path / 'Claude' / 'claude-code-sessions' / 'a' / 'o'
    source.mkdir(parents=True)
    monkeypatch.setattr(desktop, 'APP_SUPPORT', tmp_path)
    for sid, archived in [('local_active', False), ('local_archive', True), ('local_unknown', None)]:
        record = {'sessionId': sid, 'title': sid}
        if archived is not None: record['isArchived'] = archived
        (source / f'{sid}.json').write_text(json.dumps(record))
    (source / 'local_child.json').write_text(json.dumps({'sessionId': 'local_child', 'isArchived': False, 'spawnedFrom': {'sessionId': 'local_active'}}))
    runner = CliRunner()
    all_rows = runner.invoke(desktop.app, ['list'])
    assert next(row for row in json.loads(all_rows.stdout) if row['id'] == 'local_unknown')['is_archived'] is None
    filtered = runner.invoke(desktop.app, ['list', '--filter', 'is_archived:eq:false'])
    assert filtered.exit_code == 0, filtered.output
    assert {r['id'] for r in json.loads(filtered.stdout)} == {'local_active', 'local_child'}
    top = runner.invoke(desktop.app, ['list', '--filter', 'is_archived:eq:false,is_child:eq:false'])
    assert [r['id'] for r in json.loads(top.stdout)] == ['local_active']
    child = next(r for r in json.loads(all_rows.stdout) if r['id'] == 'local_child')
    assert child['is_child'] is True and child['parent_session_id'] == 'local_active'


def test_referenced_subagent_must_exist(tmp_path):
    transcript = tmp_path / 'session.jsonl'
    transcript.write_text('{"agentId":"abcdef1234567890"}\n')
    try:
        desktop.associated(transcript, 'session')
    except ValueError as exc:
        assert 'Missing referenced subagent transcript' in str(exc)
    else:
        raise AssertionError('missing referenced subagent was accepted')
    folder = tmp_path / 'session' / 'subagents'
    folder.mkdir(parents=True)
    (folder / 'agent-abcdef1234567890.jsonl').write_text('{}\n')
    assert len(desktop.associated(transcript, 'session')) == 1


def test_forked_session_finds_nested_subagent_in_source_session(tmp_path):
    transcript = tmp_path / 'fork.jsonl'
    transcript.write_text('{"sessionId":"source","agentId":"aaaa000000000001"}\n')
    folder = tmp_path / 'fork' / 'subagents'
    folder.mkdir(parents=True)
    (folder / 'agent-aaaa000000000001.jsonl').write_text('{"sessionId":"source","agentId":"bbbb000000000002"}\n')
    try:
        desktop.associated(transcript, 'fork')
    except ValueError as exc:
        assert 'Missing referenced subagent transcript bbbb000000000002' in str(exc)
    else:
        raise AssertionError('nested subagent missing everywhere was accepted')
    (tmp_path / 'unrelated' / 'subagents').mkdir(parents=True)
    (tmp_path / 'unrelated' / 'subagents' / 'agent-bbbb000000000002.jsonl').write_text('{}\n')
    try:
        desktop.associated(transcript, 'fork')
    except ValueError as exc:
        assert 'bbbb000000000002' in str(exc)
    else:
        raise AssertionError('nested subagent from an unrelated session was accepted')
    nested = tmp_path / 'source' / 'subagents' / 'agent-bbbb000000000002.jsonl'
    nested.parent.mkdir(parents=True)
    nested.write_text('{"sessionId":"source"}\n')
    assert nested in desktop.associated(transcript, 'fork')


def test_duplicate_transcripts_are_inventoried_and_conflicts_rejected(tmp_path, monkeypatch):
    projects = tmp_path / 'projects'
    first = projects / 'one' / 'session.jsonl'; second = projects / 'two' / 'session.jsonl'
    first.parent.mkdir(parents=True); second.parent.mkdir(parents=True)
    first.write_text('{}\n'); second.write_text('{}\n')
    monkeypatch.setattr(desktop, 'PROJECTS', projects)
    assert desktop.transcript('session') == [first, second]
    second.write_text('{"changed":true}\n')
    try:
        desktop.transcript('session')
    except ValueError as exc:
        assert 'Conflicting transcripts' in str(exc)
    else:
        raise AssertionError('divergent transcripts were accepted')


def make_store(root, app, account, org, *records, current=None):
    pair = root / app / 'claude-code-sessions' / account / org
    pair.mkdir(parents=True)
    for record in records:
        (pair / f"{record['sessionId']}.json").write_text(json.dumps(record))
    if current:
        (root / app / 'config.json').write_text(json.dumps({'lastKnownAccountUuid': current}))
    return pair


def test_every_desktop_store_is_listed_and_pairs_are_store_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop, 'APP_SUPPORT', tmp_path)
    (tmp_path / 'Unrelated App').mkdir()
    make_store(tmp_path, 'Claude', 'a', 'o', {'sessionId': 'local_old', 'title': 'Old'}, current='b')
    make_store(tmp_path, 'Claude-3p', 'a', 'o', {'sessionId': 'local_new', 'title': 'New'}, current='a')
    runner = CliRunner()
    rows = json.loads(runner.invoke(desktop.app, ['accounts']).stdout)
    assert [(r['store'], r['account_id'], r['current_account']) for r in rows] == [('Claude', 'a', False), ('Claude-3p', 'a', True)]
    listed = json.loads(runner.invoke(desktop.app, ['list', '--account', 'a', '--organization', 'o', '--filter', 'title:eq:New']).stdout)
    assert [(r['store'], r['id']) for r in listed] == [('Claude-3p', 'local_new')]
    assert [r['id'] for r in json.loads(runner.invoke(desktop.app, ['list', '--store', 'Claude']).stdout)] == ['local_old']
    ambiguous = runner.invoke(desktop.app, ['get', 'local_new', '--account', 'a', '--organization', 'o'])
    assert ambiguous.exit_code != 0 and 'exists in stores Claude, Claude-3p' in ambiguous.output
    got = runner.invoke(desktop.app, ['get', 'local_new', '--store', 'Claude-3p', '--account', 'a', '--organization', 'o'])
    assert got.exit_code == 0 and json.loads(got.stdout)['title'] == 'New'
    missing = runner.invoke(desktop.app, ['list', '--store', 'Nope'])
    assert missing.exit_code != 0 and 'Desktop store not found: Nope' in missing.output


def test_cross_store_import_copies_side_session_notes(tmp_path, monkeypatch):
    projects = tmp_path / 'projects'; (projects / 'p').mkdir(parents=True)
    monkeypatch.setattr(desktop, 'APP_SUPPORT', tmp_path); monkeypatch.setattr(desktop, 'PROJECTS', projects)
    for cli in ('root', 'side'):
        (projects / 'p' / f'{cli}.jsonl').write_text('{}\n')
    make_store(tmp_path, 'Claude', 'a', 'o', {'sessionId': 'local_stale', 'cliSessionId': 'root', 'title': 'Target'})
    source = make_store(tmp_path, 'Claude-3p', 'a', 'o',
        {'sessionId': 'local_root', 'cliSessionId': 'root', 'title': 'Target', 'sideSessionNotes': [{'sessionId': 'local_side'}]},
        {'sessionId': 'local_side', 'cliSessionId': 'side', 'title': 'Side', 'spawnedFrom': {'sessionId': 'local_root'}})
    dest = make_store(tmp_path, 'Claude', 'b', 'p', {'sessionId': 'local_existing', 'cliSessionId': 'root', 'title': 'Existing'})
    note = tmp_path / 'Claude-3p' / 'side-session-notes' / 'local_root' / 'note.md'
    note.parent.mkdir(parents=True); note.write_text('side note')
    copied_note = tmp_path / 'Claude' / 'side-session-notes' / 'local_root' / 'note.md'
    base = ['import', 'Target', '--source-account', 'a', '--source-organization', 'o', '--destination-account', 'b', '--destination-organization', 'p']
    runner = CliRunner()
    ambiguous = runner.invoke(desktop.app, base + ['--dry-run'])
    assert ambiguous.exit_code != 0 and 'select one with the store option' in ambiguous.output
    args = base + ['--source-store', 'Claude-3p', '--destination-store', 'Claude']
    preview = json.loads(runner.invoke(desktop.app, args + ['--dry-run']).stdout)
    assert (preview['source_store'], preview['destination_store']) == ('Claude-3p', 'Claude')
    assert {r['id']: r['side_session_notes'] for r in preview['sessions']} == {'local_root': {str(copied_note): 'copy'}, 'local_side': {}}
    assert not copied_note.exists()
    copied_note.parent.mkdir(parents=True); copied_note.write_text('different')
    conflict = runner.invoke(desktop.app, args + ['--yes'])
    assert conflict.exit_code != 0 and not (dest / 'local_root.json').exists()
    copied_note.unlink(); copied_note.parent.rmdir()
    result = runner.invoke(desktop.app, args + ['--yes'])
    assert result.exit_code == 0, result.output
    assert copied_note.read_text() == 'side note'
    for name in ('local_root', 'local_side'):
        assert (source / f'{name}.json').read_bytes() == (dest / f'{name}.json').read_bytes()
    repeat = json.loads(runner.invoke(desktop.app, args + ['--dry-run']).stdout)
    assert all(r['status'] == 'identical' for r in repeat['sessions'])
    assert repeat['sessions'][0]['side_session_notes'] == {str(copied_note): 'identical'}


def test_failed_cross_store_import_rolls_back_records_and_note_folders(tmp_path, monkeypatch):
    projects = tmp_path / 'projects'; (projects / 'p').mkdir(parents=True)
    monkeypatch.setattr(desktop, 'APP_SUPPORT', tmp_path); monkeypatch.setattr(desktop, 'PROJECTS', projects)
    for cli in ('root', 'side'):
        (projects / 'p' / f'{cli}.jsonl').write_text('{}\n')
    make_store(tmp_path, 'Claude-3p', 'a', 'o',
        {'sessionId': 'local_root', 'cliSessionId': 'root', 'title': 'Target'},
        {'sessionId': 'local_side', 'cliSessionId': 'side', 'title': 'Side', 'spawnedFrom': {'sessionId': 'local_root'}})
    dest = make_store(tmp_path, 'Claude', 'b', 'p', {'sessionId': 'local_existing', 'cliSessionId': 'root', 'title': 'Existing'})
    note = tmp_path / 'Claude-3p' / 'side-session-notes' / 'local_root' / 'note.md'
    note.parent.mkdir(parents=True); note.write_text('side note')
    real_link = desktop.os.link; calls = []
    def flaky_link(src, dst):
        calls.append(dst)
        if len(calls) == 3: raise OSError('disk full')
        real_link(src, dst)
    monkeypatch.setattr(desktop.os, 'link', flaky_link)
    result = CliRunner().invoke(desktop.app, ['import', 'Target', '--source-store', 'Claude-3p', '--source-account', 'a', '--source-organization', 'o', '--destination-store', 'Claude', '--destination-account', 'b', '--destination-organization', 'p', '--yes'])
    assert result.exit_code != 0 and 'disk full' in result.output
    assert len(calls) == 3
    assert sorted(p.name for p in dest.glob('*.json')) == ['local_existing.json']
    assert not (tmp_path / 'Claude' / 'side-session-notes').exists()
