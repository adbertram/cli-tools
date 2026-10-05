"""Durable ownership for rendered files, never discovered by directory scanning."""
import hashlib
import os
import re
import sqlite3
import stat
import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .safety import SafetyError, canonical, digest, strict_json
from .visual import current_process_identity, owned_bytes

SCHEMA = """
CREATE TABLE IF NOT EXISTS rendered_assets(
 id TEXT PRIMARY KEY,job_id TEXT NOT NULL,owner TEXT NOT NULL,asset TEXT NOT NULL,
 receipt TEXT NOT NULL,receipt_digest TEXT NOT NULL,created_at REAL NOT NULL,
 inventory TEXT,cleaned_at REAL,cleanup_issue TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS rendered_asset_live ON rendered_assets(job_id,receipt_digest) WHERE cleaned_at IS NULL;
CREATE TABLE IF NOT EXISTS render_temporaries(
 id TEXT PRIMARY KEY,job_id TEXT NOT NULL,owner TEXT NOT NULL,path TEXT NOT NULL UNIQUE,
 kind TEXT NOT NULL,process TEXT NOT NULL,descendants_unproven INTEGER NOT NULL DEFAULT 0,
 created_at REAL NOT NULL,directory_identity TEXT,child_groups TEXT NOT NULL DEFAULT '[]',inventory TEXT,cleaned_at REAL,cleanup_issue TEXT);
"""
OWNER_FIELDS = ('job_id', 'input_digest', 'proposal_digest', 'policy_digest')


def render_owner(job):
    return {'job_id': job['id'], **{field: job[field] for field in OWNER_FIELDS[1:]}}


def process_absent(identity):
    observed = subprocess.run(['/bin/ps', '-p', str(identity['pid']), '-o', 'lstart='],
        capture_output=True, text=True, timeout=2, env={**os.environ, 'LC_ALL': 'C'})
    return ((observed.returncode == 1 and not observed.stdout.strip()) or
        (observed.returncode == 0 and bool(observed.stdout.strip()) and observed.stdout.strip() != identity['start_identity']))


def child_groups_absent(groups):
    """The owning Whisper CLI and its subprocess.run children share one PGID.

    Never signal a surviving group. Reused or unregistered groups stay held.
    """
    for group in groups:
        identity=group['process']
        if identity is None:return False
        try:os.killpg(identity['pid'],0)
        except ProcessLookupError:continue
        except PermissionError:return False
        return False
    return True


def file_identity(value):
    return (value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns)


def check_deadline(deadline):
    if deadline is not None and time.monotonic()>=deadline:
        raise TimeoutError('render_cleanup_time_budget_exhausted')


def exact_file(path, root, maximum, expected=None, *, minimum=0, deadline=None, with_identity=False):
    """Read a stable owned descriptor without following links or blocking on FIFOs."""
    path = Path(path)
    check_deadline(deadline)
    if not path.is_absolute() or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise SafetyError('render_cleanup_path_changed')
    current = path.parent
    while current != root:
        if current.is_symlink():
            raise SafetyError('render_cleanup_parent_changed')
        current = current.parent
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not minimum <= before.st_size <= maximum:
            raise SafetyError('render_cleanup_file_invalid')
        hasher = hashlib.sha256()
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            for chunk in iter(lambda: stream.read(1 << 20), b''):
                check_deadline(deadline)
                hasher.update(chunk)
        after, current = os.fstat(fd), path.lstat()
        result = {'path': str(path), 'bytes': before.st_size, 'sha256': hasher.hexdigest()}
        if file_identity(before) != file_identity(after) or file_identity(after) != file_identity(current) or (expected is not None and result != expected):
            raise SafetyError('render_cleanup_file_changed')
        return (result,file_identity(after)) if with_identity else result
    finally:
        os.close(fd)


class RenderOwnership:
    """Only the original leased render can reserve a path before creating it."""
    def __init__(self, config, job, proposal, *, clock=time.time, deadline=None):
        self.config, self.job, self.clock = config, job, clock
        self.deadline=deadline if deadline is not None else time.monotonic()+config['limits']['work_timeout_seconds']
        self.owner = render_owner(job)
        if digest(proposal) != self.owner['proposal_digest']:
            raise SafetyError('render_owner_proposal_changed')
        self.root = Path(config['workspace']) / 'media'
        self.active_temporaries = []
        self.process = current_process_identity()

    @contextmanager
    def transaction(self, *, validate=True):
        with sqlite3.connect(self.config['database'], timeout=5) as db:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT * FROM jobs WHERE id=?', (self.job['id'],)).fetchone()
            if validate and (current is None or current['status'] != 'running' or current['lease_until'] is None
                    or current['lease_until'] <= self.clock() or current['lease_token'] != self.job['lease_token']
                    or any(current[field] != self.owner[field] for field in OWNER_FIELDS[1:])):
                raise SafetyError('render_owner_lease_changed')
            if validate and db.execute("SELECT value FROM settings WHERE key='control'").fetchone()[0] != 'running':
                raise SafetyError('render_owner_control_changed')
            yield db

    def intent(self, asset, receipt):
        if receipt.get('render_owner') != self.owner or receipt.get('asset') != asset:
            raise SafetyError('render_intent_binding_changed')
        if digest(receipt.get('proposal')) != self.owner['proposal_digest']:
            raise SafetyError('render_intent_proposal_changed')
        raw = canonical(receipt)
        strict_json(raw, self.config['limits']['max_payload_bytes'])
        path = Path(asset['path'])
        if path.parent != self.root or len(path.stem) != 64 or any(c not in '0123456789abcdef' for c in path.stem) or path.suffix != '.mp4':
            raise SafetyError('render_intent_path_changed')
        with self.transaction() as db:
            existing = db.execute('SELECT asset,receipt FROM rendered_assets WHERE job_id=? AND receipt_digest=? AND cleaned_at IS NULL', (self.job['id'],digest(receipt))).fetchone()
            if existing is not None and (existing['asset'] != canonical(asset) or existing['receipt'] != raw):
                raise SafetyError('render_intent_conflict')
            db.execute('INSERT OR IGNORE INTO rendered_assets(id,job_id,owner,asset,receipt,receipt_digest,created_at) VALUES(?,?,?,?,?,?,?)',
                (uuid.uuid4().hex,self.job['id'],canonical(self.owner),canonical(asset),raw,digest(receipt),self.clock()))

    @contextmanager
    def temporary(self, kind):
        if kind not in {'render', 'refinement', 'process'}:
            raise SafetyError('render_temporary_kind_invalid')
        identifier = uuid.uuid4().hex
        path = self.root / (kind + '-' + identifier)
        # Reservation becomes durable before mkdir or any media write.
        with self.transaction() as db:
            db.execute('INSERT INTO render_temporaries(id,job_id,owner,path,kind,process,created_at) VALUES(?,?,?,?,?,?,?)',
                (identifier,self.job['id'],canonical(self.owner),str(path),kind,canonical(self.process),self.clock()))
        path.mkdir(mode=0o700)
        fsync_directory(path.parent)
        directory_identity=list(directory_owner(path))
        with self.transaction() as db:
            db.execute('UPDATE render_temporaries SET directory_identity=? WHERE id=?',(canonical(directory_identity),identifier))
        self.active_temporaries.append(identifier)
        primary=None
        try:
            yield str(path)
        except BaseException as exc:
            primary=exc
            raise
        finally:
            self.active_temporaries.remove(identifier)
            # All synchronous child calls returned before the normal context exit.
            # An abrupt death leaves the durable row for stricter recovery.
            try:
                directory_owner(path,directory_identity)
                with self.transaction(validate=False) as db:
                    groups=strict_json(db.execute('SELECT child_groups FROM render_temporaries WHERE id=?',(identifier,)).fetchone()[0])
                if not child_groups_absent(groups):raise SafetyError('render_temporary_child_group_unproven')
                inventory = temporary_inventory(path,kind,self.config['limits']['max_disk_bytes'],deadline=self.deadline,groups=groups)
                with self.transaction(validate=False) as db:
                    db.execute('UPDATE render_temporaries SET inventory=? WHERE id=?', (canonical(inventory),identifier))
                remove_inventory(path,inventory,self.root,self.config['limits']['max_disk_bytes'],deadline=self.deadline,directory_identity=directory_identity)
                with self.transaction(validate=False) as db:
                    db.execute('UPDATE render_temporaries SET cleaned_at=? WHERE id=?', (self.clock(),identifier))
            except (SafetyError,OSError,TimeoutError,sqlite3.Error) as exc:
                try:
                    with self.transaction(validate=False) as db:
                        db.execute('UPDATE render_temporaries SET cleanup_issue=? WHERE id=?',(type(exc).__name__,identifier))
                except sqlite3.Error:pass
                if primary is not None:primary.add_note('Owned render temporary cleanup held; durable ownership remains.')

    def unproven_descendants(self):
        if self.active_temporaries:
            with self.transaction() as db:
                for identifier in self.active_temporaries:
                    db.execute('UPDATE render_temporaries SET descendants_unproven=1 WHERE id=?',(identifier,))

    def child_intent(self, command):
        # Observed owning whisper/client.py create_transcript uses exactly
        # whisper-cpp-*/<input stem>.16k.wav and <input stem>.json. It never
        # detaches _run subprocesses from this start_new_session CLI group.
        if command[:3]!=['whisper','transcripts','create']:
            self.unproven_descendants();return None
        stem=Path(command[3]).stem
        if re.fullmatch(r'[A-Za-z0-9_-]{1,120}',stem) is None:
            self.unproven_descendants();return None
        ticket=uuid.uuid4().hex
        with self.transaction() as db:
            for identifier in self.active_temporaries:
                groups=strict_json(db.execute('SELECT child_groups FROM render_temporaries WHERE id=?',(identifier,)).fetchone()[0])
                if len(groups)>=16:raise SafetyError('render_child_group_budget_exhausted')
                groups.append({'ticket':ticket,'stem':stem,'process':None})
                db.execute('UPDATE render_temporaries SET child_groups=? WHERE id=?',(canonical(groups),identifier))
        return ticket

    def child_started(self,ticket,process):
        if ticket is None:return
        check_deadline(self.deadline)
        observed=subprocess.run(['/bin/ps','-p',str(process.pid),'-o','lstart='],capture_output=True,text=True,
            timeout=min(2,max(0.001,self.deadline-time.monotonic())),env={**os.environ,'LC_ALL':'C'})
        start=observed.stdout.strip() if observed.returncode==0 else None
        if start is None and not child_groups_absent([{'process':{'pid':process.pid}}]):
            raise SafetyError('render_child_identity_unproven')
        identity={'pid':process.pid,'start_identity':start}
        with self.transaction() as db:
            for identifier in self.active_temporaries:
                groups=strict_json(db.execute('SELECT child_groups FROM render_temporaries WHERE id=?',(identifier,)).fetchone()[0])
                matches=[group for group in groups if group['ticket']==ticket and group['process'] is None]
                if len(matches)!=1:raise SafetyError('render_child_intent_changed')
                matches[0]['process']=identity
                db.execute('UPDATE render_temporaries SET child_groups=? WHERE id=?',(canonical(groups),identifier))

    def child_not_started(self,ticket):
        if ticket is None:return
        with self.transaction(validate=False) as db:
            for identifier in self.active_temporaries:
                groups=strict_json(db.execute('SELECT child_groups FROM render_temporaries WHERE id=?',(identifier,)).fetchone()[0])
                db.execute('UPDATE render_temporaries SET child_groups=? WHERE id=?',
                    (canonical([group for group in groups if group['ticket']!=ticket]),identifier))


def fsync_directory(path):
    descriptor=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)


def directory_owner(path,expected=None):
    info=path.lstat()
    if not stat.S_ISDIR(info.st_mode) or (expected is not None and list((info.st_dev,info.st_ino))!=expected):
        raise SafetyError('render_temporary_directory_changed')
    return info.st_dev,info.st_ino


def temporary_inventory(path,kind,maximum,*,deadline=None,groups=()):
    if path.is_symlink() or not path.is_dir():
        raise SafetyError('render_temporary_path_changed')
    # Rights schema permits eight source labels plus eight labels for each
    # of eight clip rules. Actual unexpected files remain untouched.
    allowed = ({'clip.mp4','receipt.json','captions.ass',*(f'overlay-{i}.txt'for i in range(72))} if kind=='render'
        else {f'cut-{i}.wav'for i in range(4)} if kind=='refinement' else set())
    # stdout/stderr TemporaryFiles are anonymous on supported POSIX hosts.
    # Only source-backed Whisper names are recognized inside its own TMPDIR.
    if kind=='process' and groups:
        if len(groups)!=1:raise SafetyError('render_temporary_child_contract_changed')
        entries=list_bounded(path,1,deadline)
        result=[]
        for directory in entries:
            if re.fullmatch(r'whisper-cpp-[a-z0-9_]{8}',directory.name) is None:
                raise SafetyError('render_temporary_unknown_file')
            identity=directory_owner(directory)
            names={groups[0]['stem']+'.16k.wav',groups[0]['stem']+'.json'}
            for child in list_bounded(directory,len(names),deadline):
                if child.name not in names:raise SafetyError('render_temporary_unknown_file')
                result.append(exact_file(child,path,maximum,deadline=deadline))
            result.append({'path':str(directory),'directory_identity':list(identity)})
        return result
    entries=[]
    for p in path.iterdir():
        check_deadline(deadline)
        if p.name not in allowed or len(entries)>=len(allowed):raise SafetyError('render_temporary_unknown_file')
        entries.append(p)
    return [exact_file(p,path,maximum,deadline=deadline)for p in entries]


def list_bounded(path,maximum,deadline):
    result=[]
    for entry in path.iterdir():
        check_deadline(deadline)
        if len(result)>=maximum:raise SafetyError('render_temporary_unknown_file')
        result.append(entry)
    return result


def checked_inventory(path,inventory,root,maximum,*,deadline=None):
    """A durable inventory permits resuming only its exact remaining files."""
    path=Path(path)
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise SafetyError('render_cleanup_path_changed')
    if not path.exists():return {}
    expected={entry['path']:entry for entry in inventory}
    checked={}
    def visit(directory,depth=0):
        for p in list_bounded(directory,len(expected),deadline):
            entry=expected.get(str(p))
            if entry is None:raise SafetyError('render_temporary_unknown_file')
            if 'directory_identity' in entry:
                if depth:raise SafetyError('render_temporary_unknown_file')
                identity=directory_owner(p,entry['directory_identity'])
                visit(p,depth+1);checked[str(p)]=identity
            else:checked[str(p)]=exact_file(p,root,maximum,entry,deadline=deadline,with_identity=True)[1]
    visit(path)
    return checked


def unlink_checked(path,identity):
    if len(identity)==2:
        directory_owner(path,list(identity));path.rmdir();return
    current=path.lstat()
    if not stat.S_ISREG(current.st_mode) or file_identity(current)!=identity:
        raise SafetyError('render_cleanup_file_changed')
    path.unlink()


def remove_inventory(path,inventory,root,maximum,*,deadline=None,directory_identity=None):
    path=Path(path)
    checked=checked_inventory(path,inventory,root,maximum,deadline=deadline)
    if path.exists() and directory_identity is not None:directory_owner(path,directory_identity)
    removed=0
    for filename,identity in checked.items():
        check_deadline(deadline);unlink_checked(Path(filename),identity);removed+=identity[2] if len(identity)>2 else 0
    if path.exists():path.rmdir();fsync_directory(path.parent)
    return removed


def eligible(db,row,now,limits):
    job=db.execute('SELECT * FROM jobs WHERE id=?',(row['job_id'],)).fetchone()
    if job is None or (job['lease_until'] is not None and job['lease_until']>now):return False
    if 'asset' not in row.keys():
        return job['status'] not in {'leased','running','visual_pending','ambiguous','reconciling'}
    asset=strict_json(row['asset']);owner=strict_json(row['owner'])
    if db.execute("SELECT 1 FROM publications WHERE asset_digest=? AND state IN ('uploading','dispatch_pending','ambiguous','published')",(asset['sha256'],)).fetchone():return False
    current=strict_json(job['asset']) if job['asset'] is not None else None
    if current is not None and current['sha256']==asset['sha256']:
        if job['status']!='failed':return False
        if job['stage']=='visual' and job['attempts']<limits['max_attempts'] and job['revisions']<=limits['max_revisions']:return False
    return job['status']=='failed' or job['proposal_digest']!=owner['proposal_digest']


def prune_owned(engine):
    """Bounded, fair cleanup only from previously durable ownership records."""
    from .media import MediaRenderer
    renderer=MediaRenderer(engine.config)
    removed=0
    for table in ('rendered_assets','render_temporaries'):
        with engine.transaction() as db:
            engine._active(db)
            rows=db.execute('SELECT a.* FROM '+table+' a LEFT JOIN inspections i ON i.key=a.id||\':media\' WHERE a.cleaned_at IS NULL ORDER BY coalesce(i.sequence,0),a.created_at LIMIT 20').fetchall()
        for row in rows:
            if engine._deadline is not None and engine.clock()>=engine._deadline:return removed
            with engine.transaction() as db:
                sequence=db.execute('SELECT coalesce(max(sequence),0)+1 FROM inspections').fetchone()[0]
                db.execute("INSERT INTO inspections VALUES(?,?) ON CONFLICT(key) DO UPDATE SET sequence=excluded.sequence",(row['id']+':media',sequence))
                if not eligible(db,row,engine.clock(),engine.config['limits']):continue
            try:
                deadline=min(engine._deadline or engine.clock()+2,engine.clock()+2)
                hash_deadline=time.monotonic()+max(0,deadline-engine.clock())
                # Existing media flock also fences inherited direct encoder work.
                with renderer._lock(hash_deadline):
                    if table=='render_temporaries':
                        groups=strict_json(row['child_groups'])
                        if row['descendants_unproven'] or not process_absent(strict_json(row['process'])) or not child_groups_absent(groups):
                            raise SafetyError('render_temporary_process_unproven')
                        path=Path(row['path'])
                        if path.exists():
                            if row['directory_identity'] is None:raise SafetyError('render_temporary_directory_ownership_unproven')
                            directory_owner(path,strict_json(row['directory_identity']))
                        inventory=(strict_json(row['inventory']) if row['inventory'] is not None else
                            temporary_inventory(path,row['kind'],engine.config['limits']['max_disk_bytes'],deadline=hash_deadline,groups=groups) if path.exists() else [])
                    else:
                        maximum=engine.config['limits']['max_payload_bytes']
                        asset,receipt=strict_json(row['asset']),strict_json(row['receipt'],maximum)
                        if receipt.get('asset')!=asset or receipt.get('render_owner')!=strict_json(row['owner']) or digest(receipt)!=row['receipt_digest']:
                            raise SafetyError('render_cleanup_receipt_binding_changed')
                        path=Path(asset['path'])
                        if path.is_symlink():raise SafetyError('render_cleanup_path_changed')
                        receipt_path=path.with_suffix('.json')
                        check_deadline(hash_deadline)
                        if receipt_path.exists() and strict_json(owned_bytes(receipt_path,engine.workspace,maximum),maximum)!=receipt:
                            raise SafetyError('render_cleanup_receipt_changed')
                        inventory=strict_json(row['inventory']) if row['inventory'] is not None else [
                            exact_file(path,engine.workspace,engine.config['limits']['max_disk_bytes'],{'path':str(path),'bytes':asset['bytes'],'sha256':asset['sha256']},minimum=1,deadline=hash_deadline)] if path.exists() else []
                    # Persist exact inventory before deletion, including empty intent.
                    with engine.transaction() as db:
                        engine._active(db)
                        current=db.execute('SELECT * FROM '+table+' WHERE id=?',(row['id'],)).fetchone()
                        if current['cleaned_at'] is not None or current['owner']!=row['owner'] or not eligible(db,current,engine.clock(),engine.config['limits']):continue
                        db.execute('UPDATE '+table+' SET inventory=? WHERE id=?',(canonical(inventory),row['id']))
                    # Hashing stays outside SQLite. Keep only stable descriptor
                    # identities for the short claim-fenced unlink transaction.
                    if table=='render_temporaries':
                        checked=checked_inventory(path,inventory,renderer.root,engine.config['limits']['max_disk_bytes'],deadline=hash_deadline)
                    else:
                        checked={entry['path']:exact_file(Path(entry['path']),engine.workspace,engine.config['limits']['max_disk_bytes'],entry,minimum=1,deadline=hash_deadline,with_identity=True)[1]
                            for entry in inventory if Path(entry['path']).exists()}
                    with engine.transaction() as db:
                        engine._active(db)
                        current=db.execute('SELECT * FROM '+table+' WHERE id=?',(row['id'],)).fetchone()
                        if current['cleaned_at'] is not None or current['owner']!=row['owner'] or current['inventory']!=canonical(inventory) or not eligible(db,current,engine.clock(),engine.config['limits']):continue
                        check_deadline(hash_deadline)
                        if table=='render_temporaries' and path.exists():directory_owner(path,strict_json(current['directory_identity']))
                        size=0
                        # Claims/retries cannot interleave between this final
                        # eligibility check and the exact, non-hashing unlink.
                        for filename,identity in checked.items():
                            check_deadline(hash_deadline)
                            unlink_checked(Path(filename),identity);size+=identity[2] if len(identity)>2 else 0
                        if table=='render_temporaries' and path.exists():path.rmdir()
                        fsync_directory(path.parent)
                        db.execute('UPDATE '+table+' SET cleaned_at=?,cleanup_issue=NULL WHERE id=?',(engine.clock(),row['id']))
                        engine.event(db,row['job_id'],'owned_render_artifact_pruned',{'artifact_id':row['id'],'kind':table,'bytes':size})
                    removed+=size
            except (SafetyError,OSError,TimeoutError,subprocess.SubprocessError) as exc:
                reason=str(exc) if isinstance(exc,SafetyError) else type(exc).__name__
                with engine.transaction() as db:
                    current=db.execute('SELECT cleanup_issue FROM '+table+' WHERE id=?',(row['id'],)).fetchone()
                    if current['cleanup_issue']!=reason:
                        db.execute('UPDATE '+table+' SET cleanup_issue=? WHERE id=?',(reason,row['id']))
                        engine.event(db,row['job_id'],'owned_render_cleanup_held',{'artifact_id':row['id'],'reason':reason})
    return removed
