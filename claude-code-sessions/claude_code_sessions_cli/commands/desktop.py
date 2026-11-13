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
APP_SUPPORT = Path.home() / "Library/Application Support"
PROJECTS = Path.home() / ".claude/projects"


def stores():
    found = sorted(p.parent for p in APP_SUPPORT.glob('*/claude-code-sessions') if p.is_dir())
    if not found:
        raise ValueError(f"No Desktop session store found under {APP_SUPPORT}")
    return found


def app_of(pair):
    return pair.parents[2]


def pairs(store=None):
    apps = [a for a in stores() if store is None or a.name == store]
    if not apps:
        raise ValueError(f"Desktop store not found: {store}")
    return [p for a in apps for acct in sorted((a / 'claude-code-sessions').iterdir()) if acct.is_dir() for p in sorted(acct.iterdir()) if p.is_dir() and any(p.glob('local_*.json'))]


def records(pair):
    result = {}
    for path in pair.glob('local_*.json'):
        record = json.loads(path.read_text())
        if record.get('sessionId') != path.stem or path.stem in result:
            raise ValueError(f"Invalid or duplicate session ID: {path}")
        result[path.stem] = (path, record)
    return result


def pair_for(account, org, store=None):
    matches = [p for p in pairs(store) if p.parent.name == account and p.name == org]
    if not matches:
        raise ValueError(f"Account and organization pair not found: {account}/{org}")
    if len(matches) > 1:
        raise ValueError(f"Account and organization pair {account}/{org} exists in stores {', '.join(app_of(p).name for p in matches)}; select one with the store option")
    return matches[0]


def transcript(cli_id):
    if not cli_id:
        raise ValueError('Missing cliSessionId')
    matches = sorted(PROJECTS.glob(f'*/{cli_id}.jsonl'))
    if not matches:
        raise ValueError(f'No transcript found for {cli_id}')
    if len({sha(path) for path in matches}) != 1:
        raise ValueError(f'Conflicting transcripts for {cli_id}')
    return matches


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


def associated(transcript_path, cli_id):
    session_dir = transcript_path.parent / cli_id
    files = [p for p in session_dir.rglob('*') if p.is_file()] if session_dir.is_dir() else []
    for name in ('tasks', 'session-env', 'file-history', 'todos'):
        path = Path.home() / '.claude' / name / cli_id
        if path.is_file(): files.append(path)
        elif path.is_dir(): files.extend(p for p in path.rglob('*') if p.is_file())
        json_path = path.with_suffix('.json')
        if json_path.is_file(): files.append(json_path)
    subagents = session_dir / 'subagents'
    queue, scanned = [transcript_path] + [p for p in files if p.parent == subagents and p.suffix == '.jsonl'], set()
    while queue:
        path = queue.pop()
        if path in scanned: continue
        scanned.add(path)
        identities, _, _ = _subagent_identity(path)
        referenced, sources = set(identities), set()
        for entry in iter_session_lines(path):
            if isinstance(entry.get('sessionId'), str): sources.add(entry['sessionId'])
            for obj in (entry, entry.get('toolUseResult')):
                if isinstance(obj, dict):
                    referenced.update(obj[k] for k in ('agentId', 'agent_id') if isinstance(obj.get(k), str))
        # A forked session keeps its source's sessionId on copied lines; nested subagents may live only there.
        folders = [subagents] + [transcript_path.parent / s / 'subagents' for s in sorted(sources - {cli_id})]
        for agent_id in referenced:
            found = next((f / f'agent-{agent_id}.jsonl' for f in folders if (f / f'agent-{agent_id}.jsonl').is_file()), None)
            if found is None:
                raise ValueError(f'Missing referenced subagent transcript {agent_id} in {path}')
            if found.parent != subagents:
                files.append(found); queue.append(found)
    return sorted(set(files))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def note_copies(source_app, destination_app, sid):
    """Side-session notes live beside the store in each app's data directory."""
    root = source_app / 'side-session-notes'
    notes = root / sid
    if source_app == destination_app or not notes.exists():
        return []
    found = [notes] if notes.is_file() else sorted(p for p in notes.rglob('*') if p.is_file())
    return [(p, destination_app / 'side-session-notes' / p.relative_to(root)) for p in found]


STORE_OPTION = typer.Option(None, '--store', help='Desktop app data directory name, e.g. Claude or Claude-3p')


@app.command('accounts')
@command
def accounts(store: Optional[str] = STORE_OPTION, table: bool = typer.Option(False, '--table', '-t'), limit: int = typer.Option(100, '--limit', '-l'), filter: Optional[List[str]] = typer.Option(None, '--filter', '-f', help='Filter: field:op:value (e.g., title:eq:Example)'), properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated fields to include')):
    """List account and organization IDs that have saved Desktop sessions in every Desktop app store."""
    try:
        def current(app):
            config_path = app / 'config.json'
            return json.loads(config_path.read_text()).get('lastKnownAccountUuid') if config_path.exists() else None
        rows = []
        for p in pairs(store):
            last = current(app_of(p))
            rows.append({'store': app_of(p).name, 'account_id': p.parent.name, 'organization_id': p.name, 'sessions': len(records(p)), 'current_account': p.parent.name == last if last else None})
        if filter: rows = apply_filters(rows, filter)
        rows = rows[:limit]
        if properties:
            keys = properties.split(','); rows = [{k: v for k, v in r.items() if k in keys} for r in rows]
        if table: print_table(rows, ['store', 'account_id', 'organization_id', 'sessions', 'current_account'], ['Store', 'Account ID', 'Organization ID', 'Sessions', 'Current'])
        else: print_json(rows)
    except (ValueError, OSError) as e:
        raise typer.BadParameter(str(e))


@app.command('list')
@command
def list_desktop(store: Optional[str] = STORE_OPTION, account: Optional[str] = typer.Option(None, '--account', help='Account ID'), organization: Optional[str] = typer.Option(None, '--organization', help='Organization ID'), table: bool = typer.Option(False, '--table', '-t'), limit: int = typer.Option(100, '--limit', '-l'), filter: Optional[List[str]] = typer.Option(None, '--filter', '-f', help='Filter: field:op:value (e.g., title:eq:Example)'), properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated fields to include')):
    """List Desktop records with their store, account, and organization."""
    try:
        rows = []
        for p in pairs(store):
            if account and account != p.parent.name or organization and organization != p.name: continue
            for _, d in records(p).values():
                parent = d.get('spawnedFrom')
                parent_id = parent.get('sessionId') if isinstance(parent, dict) else None
                rows.append({'parent_session_id': parent_id, 'is_child': bool(parent_id), 'store': app_of(p).name, 'account_id': p.parent.name, 'organization_id': p.name, 'id': d['sessionId'], 'cli_session_id': d.get('cliSessionId'), 'title': d.get('title'), 'is_archived': d.get('isArchived'), 'cwd': d.get('cwd'), 'last_activity': d.get('lastActivityAt')})
        rows.sort(key=lambda r: r['last_activity'] or 0, reverse=True)
        if filter: rows = apply_filters(rows, filter)
        rows = rows[:limit]
        if properties:
            keys = properties.split(','); rows = [{k: v for k, v in r.items() if k in keys} for r in rows]
        if table: print_table(rows, ['store', 'account_id', 'organization_id', 'id', 'title'], ['Store', 'Account ID', 'Organization ID', 'Session ID', 'Title'])
        else: print_json(rows)
    except (ValueError, OSError) as e:
        raise typer.BadParameter(str(e))


@app.command('get')
@command
def get_desktop(session_id: str = typer.Argument(...), store: Optional[str] = STORE_OPTION, account: str = typer.Option(..., '--account'), organization: str = typer.Option(..., '--organization'), table: bool = typer.Option(False, '--table', '-t')):
    """Get a Desktop session record for a specific store, account, and organization."""
    try:
        found = records(pair_for(account, organization, store))
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
def import_desktop(title: str = typer.Argument(..., help='Exact, case-sensitive Desktop session title'), source_account: str = typer.Option(..., '--source-account'), source_organization: str = typer.Option(..., '--source-organization'), destination_account: str = typer.Option(..., '--destination-account'), destination_organization: str = typer.Option(..., '--destination-organization'), source_store: Optional[str] = typer.Option(None, '--source-store', help='Source Desktop app data directory name, e.g. Claude-3p'), destination_store: Optional[str] = typer.Option(None, '--destination-store', help='Destination Desktop app data directory name, e.g. Claude'), session_id: Optional[str] = typer.Option(None, '--session-id', help='Exact Desktop session ID to disambiguate the title'), dry_run: bool = typer.Option(False, '--dry-run', help='Preview without copying records'), yes: bool = typer.Option(False, '--yes', help='Copy the selected session records')):
    """Copy a session and linked Desktop records into another local account or Desktop app store."""
    try:
        source = pair_for(source_account, source_organization, source_store)
        destination = pair_for(destination_account, destination_organization, destination_store)
        if source == destination: raise ValueError('Source and destination must differ')
        all_records = records(source)
        matches = [sid for sid, (_, d) in all_records.items() if d.get('title') == title and (session_id is None or sid == session_id)]
        if len(matches) != 1: raise ValueError(f'Exact title matched {len(matches)} sessions; expected one')
        ids = closure(all_records, matches[0])
        rows = []
        copies = []
        for sid in ids:
            path, d = all_records[sid]
            planned = []
            for src, dst in [(path, destination / path.name)] + note_copies(app_of(source), app_of(destination), sid):
                data = src.read_bytes(); digest = hashlib.sha256(data).hexdigest()
                status = 'copy' if not dst.exists() else 'identical' if sha(dst) == digest else 'conflict'
                planned.append({'source': src, 'destination': dst, 'data': data, 'sha256': digest, 'status': status})
            copies += planned
            transcripts = transcript(d.get('cliSessionId'))
            t = transcripts[0]
            files = set(transcripts)
            for transcript_path in transcripts:
                files.update(associated(transcript_path, d['cliSessionId']))
            manifest = {str(p): sha(p) for p in sorted(files)}
            notes = {str(c['destination']): c['status'] for c in planned[1:]}
            rows.append({'id': sid, 'title': d.get('title'), 'cli_session_id': d['cliSessionId'], 'record_sha256': planned[0]['sha256'], 'status': planned[0]['status'], 'side_session_notes': notes, 'transcript': str(t), 'transcript_sha256': sha(t), 'associated_files': manifest, 'bridge_session_ids': d.get('bridgeSessionIds', [])})
        result = {'source_store': app_of(source).name, 'source': str(source), 'destination_store': app_of(destination).name, 'destination': str(destination), 'sessions': rows, 'dry_run': dry_run}
        if any(c['status'] == 'conflict' for c in copies): raise ValueError('Destination has conflicting session records or side-session notes; no files copied')
        if not dry_run:
            if not yes: raise ValueError('Pass --dry-run to inspect or --yes to import')
            backup = destination.parent / 'claude-code-sessions-import-backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            backup.mkdir(parents=True)
            for c in copies:
                if c['source'].parent == source:
                    (backup / c['source'].name).write_bytes(c['data'])
            (backup / 'manifest.json').write_text(json.dumps(result, indent=2))
            created = []
            made_dirs = []
            try:
                for i, c in enumerate(copies):
                    if sha(c['source']) != c['sha256']:
                        raise ValueError(f"Source changed during import: {c['source']}")
                    if c['status'] == 'copy':
                        missing = [d for d in reversed(c['destination'].parents) if not d.exists()]
                        c['destination'].parent.mkdir(parents=True, exist_ok=True)
                        made_dirs += missing
                        stage = backup / f'{i}.stage'
                        stage.write_bytes(c['data'])
                        os.link(stage, c['destination'])
                        created.append((c['destination'], c['sha256']))
                        stage.unlink()
                    if sha(c['destination']) != c['sha256']:
                        raise ValueError(f"Parity verification failed: {c['destination']}")
                for row in rows:
                    for path, digest in row['associated_files'].items():
                        if sha(Path(path)) != digest:
                            raise ValueError(f'Shared session data changed during import: {path}')
            except (OSError, ValueError):
                for dst, digest in created:
                    if dst.exists() and sha(dst) == digest: dst.unlink()
                for d in reversed(made_dirs):
                    if d.is_dir() and not any(d.iterdir()): d.rmdir()
                raise
            result['backup'] = str(backup)
        print_json(result)
    except (ValueError, OSError, json.JSONDecodeError) as e:
        raise typer.BadParameter(str(e))
