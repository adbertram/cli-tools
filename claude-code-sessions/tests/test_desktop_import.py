import json
from typer.testing import CliRunner
from claude_code_sessions_cli.commands import desktop


def test_import_graph_conflicts_and_idempotency(tmp_path, monkeypatch):
    store = tmp_path / 'store'; projects = tmp_path / 'projects'
    source = store / 'a' / 'o'; dest = store / 'b' / 'p'
    source.mkdir(parents=True); dest.mkdir(parents=True); (projects / 'project').mkdir(parents=True)
    monkeypatch.setattr(desktop, 'STORE', store); monkeypatch.setattr(desktop, 'PROJECTS', projects)
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
    store = tmp_path / 'store'; source = store / 'a' / 'o'
    source.mkdir(parents=True)
    monkeypatch.setattr(desktop, 'STORE', store)
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
        desktop.associated(transcript, 'session', 'local_test')
    except ValueError as exc:
        assert 'Missing referenced subagent transcript' in str(exc)
    else:
        raise AssertionError('missing referenced subagent was accepted')
    folder = tmp_path / 'session' / 'subagents'
    folder.mkdir(parents=True)
    (folder / 'agent-abcdef1234567890.jsonl').write_text('{}\n')
    assert len(desktop.associated(transcript, 'session', 'local_test')) == 1


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
