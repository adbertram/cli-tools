"""Concurrent Agent/Task identity, terminal evidence, and bounded query regressions."""
import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from claude_code_sessions_cli.client import ClaudeCodeSessionsClient
from claude_code_sessions_cli.commands import subagent_activity, tool_calls
from claude_code_sessions_cli.parsers import (
    _build_agent_to_task_mapping,
    extract_subagents_from_session,
    extract_timeline_from_session,
    extract_tool_calls_with_subagents,
)


def write(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(json.dumps(entry) for entry in entries) + '\n')


def entry(kind, content, timestamp='2026-10-20T10:00:00Z', **extra):
    return dict(type=kind, timestamp=timestamp, message={'content': content}, **extra)


def launch(task, prompt, name='Agent'):
    return entry('assistant', [{'type': 'tool_use', 'id': task, 'name': name,
                               'input': {'prompt': prompt, 'subagent_type': task, 'run_in_background': True}}], uuid=task)


def result(task, agent):
    return entry('user', [{'type': 'tool_result', 'tool_use_id': task,
                           'content': f'Async agent launched in background. agentId: {agent}'}])


def notify(task, agent, status='failed'):
    return entry('user', f'<task-notification><task-id>{agent}</task-id>'
                 f'<tool-use-id>{task}</tool-use-id><status>{status}</status>'
                 '<summary>Interrupted by HTTP 429/session limit</summary></task-notification>')


def child(path, agent, prompt):
    write(path.parent / path.stem / 'subagents' / f'agent-{agent}.jsonl', [
        entry('user', prompt, uuid=f'{agent}-user'),
        entry('assistant', [{'type': 'tool_use', 'id': f'{agent}-call', 'name': 'Bash',
                             'input': {'command': agent}}], uuid=f'{agent}-assistant'),
        entry('user', [{'type': 'tool_result', 'tool_use_id': f'{agent}-call', 'content': 'report saved'}]),
    ])


def test_concurrent_shared_prefix_results_authoritative_and_status_failed(tmp_path):
    path = tmp_path / 'session.jsonl'
    prefix = 'Shared reviewer instructions. ' * 8
    write(path, [launch('launch-a', prefix+'a'), launch('launch-b', prefix+'b', 'Task'),
                 result('launch-b', 'child-b'), result('launch-a', 'child-a'),
                 notify('launch-a', 'child-a'), notify('launch-b', 'child-b', 'completed')])
    # Deliberately give children the other launch prompt. Exact result wins.
    child(path, 'child-b', prefix+'a')
    child(path, 'child-a', prefix+'b')
    records = {row['id']: row for row in extract_subagents_from_session(path, 'Project')}
    assert records['launch-a']['agent_id'] == 'child-a'
    assert records['launch-b']['agent_id'] == 'child-b'
    assert records['launch-a']['status'] == 'failed'
    assert 'HTTP 429' in records['launch-a']['errors'][0]['content']
    assert records['launch-b']['status'] == 'completed'
    assert records['launch-a']['tool_calls'][0]['input']['command'] == 'child-a'
    calls = extract_tool_calls_with_subagents(path, 'Project')
    assert {row['agent_id']: row['parent_tool_call_id'] for row in calls if row['is_sidechain']} == {
        'child-a': 'launch-a', 'child-b': 'launch-b'}
    timeline = extract_timeline_from_session(path, 'Project')
    assert {row.agent_id: row.agent_name for row in timeline if row.agent_id} == {
        'child-a': 'launch-a', 'child-b': 'launch-b'}


def test_duplicate_full_prompts_stay_unmatched_without_identity(tmp_path):
    path = tmp_path / 'session.jsonl'
    write(path, [launch('launch-a', 'identical'), launch('launch-b', 'identical')])
    child(path, 'child-a', 'identical')
    child(path, 'child-b', 'identical')
    assert _build_agent_to_task_mapping(path) == {}
    records = extract_subagents_from_session(path, 'Project')
    assert len(records) == 4
    assert {row['status'] for row in records} == {'unknown'}


def test_unique_full_prompt_legacy_fallback_and_unfinished_unknown(tmp_path):
    path = tmp_path / 'session.jsonl'
    write(path, [launch('legacy', 'complete prompt', 'Task')])
    child(path, 'child', 'complete prompt')
    record, = extract_subagents_from_session(path, 'Project')
    assert record['agent_id'] == 'child'
    assert record['status'] == 'unknown'  # A saved report is not terminal evidence.


@pytest.fixture
def client(tmp_path, monkeypatch):
    project = tmp_path / 'projects' / '-Users-adam-GitRepos-Project'
    older = project / 'older.jsonl'
    write(older, [launch('older-task', 'old'), result('older-task', 'old-agent'), notify('older-task', 'old-agent')])
    child(older, 'old-agent', 'old')
    newer = launch('newer-task', 'new')
    newer['timestamp'] = '2026-10-21T10:00:00Z'
    write(project / 'newer.jsonl', [newer])
    client = ClaudeCodeSessionsClient.__new__(ClaudeCodeSessionsClient)
    client.projects_dir = tmp_path / 'projects'
    client.claude_dir = tmp_path
    monkeypatch.setattr(client, 'get_session', lambda value: SimpleNamespace(subagents={}))
    monkeypatch.setattr(client, 'resolve_session_id', lambda value, **kwargs: value)
    monkeypatch.setattr(subagent_activity, 'get_client', lambda: client)
    monkeypatch.setattr(tool_calls, 'get_client', lambda: client)
    return client


def test_session_subagent_and_generic_filters_precede_limit(client):
    rows = client.list_subagent_activity('Project', limit=1, session_id='older')
    assert rows[0].id == 'older-task'
    rows = client.list_subagent_activity('Project', limit=1, filters=['id:eq:older-task'])
    assert rows[0].id == 'older-task'
    rows = client.list_tool_calls('Project', limit=1, session_id='older', subagent_id='older-task', filters=['tool:eq:Bash'])
    assert rows[0].agent_id == 'old-agent'
    assert client.get_subagent('older-task', 'Project')['status'] == 'failed'
    assert client.get_subagent('old-agent', 'Project')['id'] == 'older-task'
    runner = CliRunner()
    for app, args in [(subagent_activity.app, ['--filter', 'id:eq:older-task']),
                      (tool_calls.app, ['--subagent-id', 'older-task', '--filter', 'tool:eq:Bash'])]:
        response = runner.invoke(app, ['list', '--project', 'Project', '--session-id', 'older', '--limit', '1', *args])
        assert response.exit_code == 0, response.output
        assert len(json.loads(response.stdout)) == 1


def test_sync_terminal_result_and_async_ack_use_launch_contract(tmp_path):
    path = tmp_path / 'session.jsonl'
    sync = launch('sync', 'sync prompt')
    sync['message']['content'][0]['input']['run_in_background'] = False
    write(path, [sync, launch('async', 'async prompt'),
                 entry('user', [{'type': 'tool_result', 'tool_use_id': 'sync', 'content': 'Reviewed background workers'}]),
                 entry('user', [{'type': 'tool_result', 'tool_use_id': 'async', 'content': 'Accepted'}])])
    records = {row['id']: row for row in extract_subagents_from_session(path, 'Project')}
    assert records['sync']['status'] == 'completed'
    assert records['async']['status'] == 'unknown'


def test_parallel_results_do_not_reuse_entry_metadata_for_every_block(tmp_path):
    path = tmp_path / 'session.jsonl'
    write(path, [launch('a', 'a'), launch('b', 'b'),
                 entry('user', [{'type': 'tool_result', 'tool_use_id': 'a', 'content': 'Accepted'},
                                {'type': 'tool_result', 'tool_use_id': 'b', 'content': 'Accepted'}],
                       toolUseResult={'agentId': 'wrong-agent'})])
    assert _build_agent_to_task_mapping(path) == {}


def test_structured_completion_status_and_failed_launch(tmp_path):
    path = tmp_path / 'session.jsonl'
    write(path, [launch('a', 'a'), launch('b', 'b'),
                 entry('user', [{'type': 'tool_result', 'tool_use_id': 'a', 'content': 'Result'}],
                       toolUseResult={'agentId': 'agent-a', 'status': 'completed'}),
                 entry('user', [{'type': 'tool_result', 'tool_use_id': 'b', 'content': 'API error', 'is_error': True}])])
    records = {row['id']: row for row in extract_subagents_from_session(path, 'Project')}
    assert records['a']['status'] == 'completed'
    assert records['b']['status'] == 'failed'
    assert records['b']['errors'][0]['content'] == 'API error'


def test_get_preserves_embedded_messages_with_canonical_status(client, monkeypatch):
    embedded = SimpleNamespace(model_dump=lambda: {'messages': [{'text': 'legacy message'}], 'status': 'completed'})
    monkeypatch.setattr(client, 'get_session', lambda value: SimpleNamespace(subagents={'older-task': embedded}))
    record = client.get_subagent('older-task', 'Project')
    assert record['messages'] == [{'text': 'legacy message'}]
    assert record['status'] == 'failed'


def test_structured_async_status_never_means_completed(tmp_path):
    path = tmp_path / 'session.jsonl'
    spawn = launch('a', 'a')
    spawn['message']['content'][0]['input'].pop('run_in_background')
    write(path, [spawn, entry('user', [{'type': 'tool_result', 'tool_use_id': 'a', 'content': 'Accepted'}],
                              toolUseResult={'agentId': 'agent-a', 'status': 'async_launched'})])
    record, = extract_subagents_from_session(path, 'Project')
    assert record['agent_id'] == 'agent-a'
    assert record['status'] == 'unknown'
