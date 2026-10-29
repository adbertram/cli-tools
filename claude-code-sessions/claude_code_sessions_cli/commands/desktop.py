"""Inspect and copy Claude Desktop's account-scoped local session records."""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import typer
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import command, print_json, print_table
from ..parsers import _subagent_identity, iter_session_lines

COMMAND_CREDENTIALS = {"accounts": ["no_auth"], "list": ["no_auth"], "get": ["no_auth"], "import": ["no_auth"]}
app = typer.Typer(help="Inspect and import Claude Desktop local sessions", no_args_is_help=True)
STORE = Path.home() / "Library/Application Support/Claude/claude-code-sessions"
PROJECTS = Path.home() / ".claude/projects"


def pairs():
    if not STORE.is_dir():
        raise ValueError(f"Desktop session store does not exist: {STORE}")
    return sorted(p for a in STORE.iterdir() if a.is_dir() for p in a.iterdir() if p.is_dir() and list(p.glob('local_*.json')))


def records(pair):
    result = {}
    for path in pair.glob('local_*.json'):
        record = json.loads(path.read_text())
        if record.get('sessionId') != path.stem or path.stem in result:
            raise ValueError(f"Invalid or duplicate session ID: {path}")
        result[path.stem] = (path, record)
    return result


def pair_for(account, org):
    matches = [p for p in pairs() if p.parent.name == account and p.name == org]
    if len(matches) != 1:
        raise ValueError(f"Account and organization pair not found: {account}/{org}")
    return matches[0]


def transcript(cli_id):
    if not cli_id:
        raise ValueError('Missing cliSessionId')
    matches = list(PROJECTS.glob(f'*/{cli_id}.jsonl'))
    if len(matches) != 1:
        raise ValueError(f'Expected one transcript for {cli_id}, found {len(matches)}')
    return matches[0]


def closure(all_records, root):
    selected = {root}
    while True:
        found = set(selected)
        for sid, (_, data) in all_records.items():
            parent = data.get('spawnedFrom')
            if isinstance(parent, dict) and parent.get('sessionId') in selected:
                found.add(sid)
        for sid in selected:
            data = all_records[sid][1]
            for field in ('sideSessionNotes', 'peerReceipts'):
                for item in data.get(field, []):
                    target = item.get('targetSessionId') or item.get('sessionId')
                    if target and target not in all_records:
                        raise ValueError(f'Missing linked session {target} referenced by {sid}')
                    if target:
                        found.add(target)
        if found == selected:
            return sorted(selected)
        selected = found


def associated(transcript_path, cli_id, desktop_id):
    session_dir = transcript_path.parent / cli_id
    files = [p for p in session_dir.rglob('*') if p.is_file()] if session_dir.is_dir() else []
    for name in ('tasks', 'session-env', 'file-history', 'todos'):
        path = Path.home() / '.claude' / name / cli_id
        if path.is_file(): files.append(path)
        elif path.is_dir(): files.extend(p for p in path.rglob('*') if p.is_file())
        json_path = path.with_suffix('.json')
        if json_path.is_file(): files.append(json_path)
    notes = STORE.parent / 'side-session-notes' / desktop_id
    if notes.is_file(): files.append(notes)
    elif notes.is_dir(): files.extend(p for p in notes.rglob('*') if p.is_file())
    subagents = session_dir / 'subagents'
    for path in [transcript_path] + [p for p in files if p.parent == subagents and p.suffix == '.jsonl']:
        identities, _, _ = _subagent_identity(path)
        referenced = set(identities)
        for entry in iter_session_lines(path):
            for obj in (entry, entry.get('toolUseResult')):
                if isinstance(obj, dict):
                    referenced.update(obj[k] for k in ('agentId', 'agent_id') if isinstance(obj.get(k), str))
        for agent_id in referenced:
            if not (subagents / f'agent-{agent_id}.jsonl').is_file():
                raise ValueError(f'Missing referenced subagent transcript {agent_id} in {path}')
    return sorted(set(files))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@app.command('accounts')
@command
def accounts(table: bool = typer.Option(False, '--table', '-t'), limit: int = typer.Option(100, '--limit', '-l'), filter: Optional[List[str]] = typer.Option(None, '--filter', '-f', help='Filter: field:op:value (e.g., title:eq:Example)'), properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated fields to include')):
    """List account and organization IDs that have saved Desktop sessions."""
    try:
        config_path = STORE.parent / 'config.json'
        current = json.loads(config_path.read_text()).get('lastKnownAccountUuid') if config_path.exists() else None
        rows = [{'account_id': p.parent.name, 'organization_id': p.name, 'sessions': len(records(p)), 'current_account': p.parent.name == current if current else None} for p in pairs()]
        if filter: rows = apply_filters(rows, filter)
        rows = rows[:limit]
        if properties:
            keys = properties.split(','); rows = [{k: v for k, v in r.items() if k in keys} for r in rows]
        if table: print_table(rows, ['account_id', 'organization_id', 'sessions', 'current_account'], ['Account ID', 'Organization ID', 'Sessions', 'Current'])
        else: print_json(rows)
    except (ValueError, OSError) as e:
        raise typer.BadParameter(str(e))


@app.command('list')
@command
def list_desktop(account: Optional[str] = typer.Option(None, '--account', help='Account ID'), organization: Optional[str] = typer.Option(None, '--organization', help='Organization ID'), table: bool = typer.Option(False, '--table', '-t'), limit: int = typer.Option(100, '--limit', '-l'), filter: Optional[List[str]] = typer.Option(None, '--filter', '-f', help='Filter: field:op:value (e.g., title:eq:Example)'), properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated fields to include')):
    """List Desktop records with their account and organization."""
    try:
        rows = []
        for p in pairs():
            if account and account != p.parent.name or organization and organization != p.name: continue
            for _, d in records(p).values():
                rows.append({'account_id': p.parent.name, 'organization_id': p.name, 'id': d['sessionId'], 'cli_session_id': d.get('cliSessionId'), 'title': d.get('title'), 'cwd': d.get('cwd'), 'last_activity': d.get('lastActivityAt')})
        rows.sort(key=lambda r: r['last_activity'] or 0, reverse=True)
        if filter: rows = apply_filters(rows, filter)
        rows = rows[:limit]
        if properties:
            keys = properties.split(','); rows = [{k: v for k, v in r.items() if k in keys} for r in rows]
        if table: print_table(rows, ['account_id', 'organization_id', 'id', 'title'], ['Account ID', 'Organization ID', 'Session ID', 'Title'])
        else: print_json(rows)
    except (ValueError, OSError) as e:
        raise typer.BadParameter(str(e))


@app.command('get')
@command
def get_desktop(session_id: str = typer.Argument(...), account: str = typer.Option(..., '--account'), organization: str = typer.Option(..., '--organization'), table: bool = typer.Option(False, '--table', '-t')):
    """Get a Desktop session record for a specific account and organization."""
    try:
        found = records(pair_for(account, organization))
        if session_id not in found:
            raise ValueError(f'Session not found: {session_id}')
        data = found[session_id][1]
        if table:
            print_table([{'field': k, 'value': json.dumps(v) if isinstance(v, (dict, list)) else v} for k, v in data.items()], ['field', 'value'], ['Field', 'Value'])
        else:
            print_json(data)
    except (ValueError, OSError) as e:
        raise typer.BadParameter(str(e))


@app.command('import')
@command
def import_desktop(title: str = typer.Argument(..., help='Exact, case-sensitive Desktop session title'), source_account: str = typer.Option(..., '--source-account'), source_organization: str = typer.Option(..., '--source-organization'), destination_account: str = typer.Option(..., '--destination-account'), destination_organization: str = typer.Option(..., '--destination-organization'), dry_run: bool = typer.Option(False, '--dry-run', help='Preview without copying records'), yes: bool = typer.Option(False, '--yes', help='Copy the selected session records')):
    """Copy a session and linked Desktop records into another local account."""
    try:
        source = pair_for(source_account, source_organization)
        destination = pair_for(destination_account, destination_organization)
        if source == destination: raise ValueError('Source and destination must differ')
        all_records = records(source)
        matches = [sid for sid, (_, d) in all_records.items() if d.get('title') == title]
        if len(matches) != 1: raise ValueError(f'Exact title matched {len(matches)} sessions; expected one')
        ids = closure(all_records, matches[0])
        rows = []
        snapshots = {}
        for sid in ids:
            path, d = all_records[sid]; target = destination / path.name; digest = sha(path)
            snapshots[sid] = path.read_bytes()
            if hashlib.sha256(snapshots[sid]).hexdigest() != digest:
                raise ValueError(f'Source changed during scan: {path}')
            status = 'copy' if not target.exists() else 'identical' if sha(target) == digest else 'conflict'
            t = transcript(d.get('cliSessionId'))
            files = associated(t, d['cliSessionId'], sid)
            manifest = {str(p): sha(p) for p in [t] + files}
            rows.append({'id': sid, 'title': d.get('title'), 'cli_session_id': d['cliSessionId'], 'record_sha256': digest, 'status': status, 'transcript': str(t), 'transcript_sha256': sha(t), 'associated_files': manifest, 'bridge_session_ids': d.get('bridgeSessionIds', [])})
        result = {'source': str(source), 'destination': str(destination), 'sessions': rows, 'dry_run': dry_run}
        if any(r['status'] == 'conflict' for r in rows): raise ValueError('Destination has conflicting session records; no files copied')
        if not dry_run:
            if not yes: raise ValueError('Pass --dry-run to inspect or --yes to import')
            backup = destination.parent / 'claude-code-sessions-import-backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            backup.mkdir(parents=True)
            for sid in ids:
                (backup / f'{sid}.json').write_bytes(snapshots[sid])
            (backup / 'manifest.json').write_text(json.dumps(result, indent=2))
            created = []
            try:
                for row in rows:
                    if sha(all_records[row['id']][0]) != row['record_sha256']:
                        raise ValueError(f"Source changed during import: {row['id']}")
                    if row['status'] == 'copy':
                        dst = destination / f"{row['id']}.json"
                        stage = backup / f"{row['id']}.stage"
                        stage.write_bytes(snapshots[row['id']])
                        os.link(stage, dst)
                        created.append((dst, row['record_sha256']))
                        stage.unlink()
                    if sha(destination / f"{row['id']}.json") != row['record_sha256']:
                        raise ValueError(f"Parity verification failed: {row['id']}")
                for row in rows:
                    for path, digest in row['associated_files'].items():
                        if sha(Path(path)) != digest:
                            raise ValueError(f'Shared session data changed during import: {path}')
            except (OSError, ValueError):
                for dst, digest in created:
                    if dst.exists() and sha(dst) == digest: dst.unlink()
                raise
            result['backup'] = str(backup)
        print_json(result)
    except (ValueError, OSError, json.JSONDecodeError) as e:
        raise typer.BadParameter(str(e))
