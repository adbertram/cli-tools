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
