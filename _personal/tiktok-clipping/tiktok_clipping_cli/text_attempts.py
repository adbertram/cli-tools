"""Original-lease model attempts. Usage ingestion never grants action authority."""
from __future__ import annotations

import hashlib
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from .safety import SafetyError, canonical, digest, keys, number, strict_json, string, timestamp, write_allowance
from .visual import USAGE_FIELDS, owned_bytes

ENVELOPE_FIELDS = {'schema_version', 'job_id', 'attempt_id', 'kind', 'lease_token', 'nonce', 'input_digest', 'policy_digest', 'prompt_digest', 'manifest_path', 'manifest_sha256', 'overlay_path', 'overlay_sha256', 'native_execution', 'model_deadline', 'expires_at'}


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS text_attempts(
        id TEXT PRIMARY KEY,job_id TEXT NOT NULL,kind TEXT NOT NULL,state TEXT NOT NULL,
        envelope TEXT NOT NULL,settings TEXT NOT NULL,reservation TEXT NOT NULL,
        created_at REAL NOT NULL,artifacts_ready INTEGER NOT NULL DEFAULT 0,
        preparation_process TEXT NOT NULL,result TEXT,result_digest TEXT,completed_at REAL,
        native_completed_at REAL,native_termination_proof TEXT,action_error TEXT,
        artifacts_cleaned INTEGER NOT NULL DEFAULT 0,cleanup_issue TEXT,cleanup_inventory TEXT,
        UNIQUE(job_id,envelope))''')
    if 'cleanup_inventory' not in {row[1] for row in db.execute('PRAGMA table_info(text_attempts)')}:
        db.execute('ALTER TABLE text_attempts ADD COLUMN cleanup_inventory TEXT')
    db.execute('CREATE INDEX IF NOT EXISTS text_attempt_lookup ON text_attempts(job_id,state,native_completed_at)')


def _fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write(path, raw):
    with path.open('xb') as stream:
        os.chmod(path, 0o600)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_directory(path.parent)


def validate_receipt(receipt, attempt, now):
    saved = strict_json(attempt['settings'])
    if len(canonical(receipt).encode()) > saved['max_receipt_bytes']:
        raise SafetyError('text_receipt_too_large')
    keys(receipt, {'envelope', 'outcome', 'raw_result', 'usage_observed', 'usage', 'usage_provenance', 'model', 'observed_at', 'failure'})
    envelope = receipt['envelope']
    keys(envelope, ENVELOPE_FIELDS)
    if envelope != strict_json(attempt['envelope']):
        raise SafetyError('text_attempt_binding_changed')
    if receipt['model'] != saved['model']:
        raise SafetyError('text_model_binding_changed')
    if receipt['outcome'] not in {'completed', 'failed', 'timeout'} or type(receipt['usage_observed']) is not bool:
        raise SafetyError('invalid_text_outcome')
    observed = timestamp(receipt['observed_at'])
    if not attempt['created_at'] - 5 <= observed <= now + 5:
        raise SafetyError('text_observation_time_invalid')
    if receipt['usage_observed']:
        keys(receipt['usage'], USAGE_FIELDS)
        for value in receipt['usage'].values():
            number(value, 0, 2**53 - 1, integer=True)
    elif receipt['usage'] is not None:
        raise SafetyError('unobserved_text_usage_must_be_unknown')
    provenance = receipt['usage_provenance']
    keys(provenance, {'session_id', 'as_of_seq'})
    if receipt['usage_observed'] or provenance['session_id'] is not None:
        if not re.fullmatch(r'session-[A-Za-z0-9_-]{1,128}', string(provenance['session_id'], 136)):
            raise SafetyError('invalid_text_usage_session')
        number(provenance['as_of_seq'], 0, 2**53 - 1, integer=True)
    elif (provenance['session_id'] is None) != (provenance['as_of_seq'] is None):
        raise SafetyError('invalid_text_usage_provenance')
    raw = receipt['raw_result']
    if raw is not None and (not isinstance(raw, str) or len(raw.encode()) > saved['max_result_bytes']):
        raise SafetyError('invalid_text_raw_result')
    if receipt['outcome'] == 'completed':
        if receipt['failure'] is not None or not receipt['usage_observed'] or raw is None:
            raise SafetyError('incomplete_text_success')
    else:
        failure = receipt['failure']
        keys(failure, {'category', 'code', 'status', 'retry_after_ms'})
        if failure['category'] not in {'rate_limit', 'auth', 'provider_unavailable', 'malformed_output', 'timeout', 'model_failed'}:
            raise SafetyError('invalid_text_failure_category')
        string(failure['code'], 128)
        if failure['status'] is not None:
            number(failure['status'], 100, 599, integer=True)
        if failure['retry_after_ms'] is not None:
            number(failure['retry_after_ms'], 0)
    return receipt


class TextAttempts:
    def __init__(self, engine):
        self.engine = engine
        self.workspace = engine.workspace

    def begin(self, db, job, prompt):
        engine = self.engine
        settings = dict(engine.config['native_text'])
        if engine.native_execution is None or engine.native_execution['workflow_id'] != settings['workflow_ids'][job['kind']]:
            raise SafetyError('text_native_workflow_identity_changed')
        active = db.execute("SELECT 1 FROM text_attempts WHERE job_id=? AND native_completed_at IS NULL", (job['id'],)).fetchone()
        if active:
            raise SafetyError('text_native_termination_unknown')
        from .visual import current_process_identity
        preparation = current_process_identity()
        attempt_id = secrets.token_hex(16)
        reservation = engine._reserve_model_attempt(db, attempt_id, job['kind'], settings['timeout_seconds'])
        root = self.workspace / 'model' / job['id'] / attempt_id
        prompt_digest = hashlib.sha256(prompt.encode()).hexdigest()
        manifest = {'schema_version': 1, 'job_id': job['id'], 'attempt_id': attempt_id, 'kind': job['kind'], 'prompt': prompt, 'prompt_digest': prompt_digest}
        manifest_raw = canonical(manifest).encode()
        if len(prompt.encode()) > 1048576 or len(manifest_raw) > 2 * 1048576:
            raise SafetyError('text_prompt_too_large')
        settings['max_receipt_bytes'] = engine.config['limits']['max_payload_bytes']
        tool = Path(__file__).resolve().parents[1]
        template = (tool / 'deploy' / 'deepseek-analysis.yml').read_text()
        config = {'workspace': str(self.workspace), 'sdkPackage': settings['sdk_package'], 'pythonExecutable': settings['python_executable'],
                  'model': settings['model'], 'maxTokens': settings['max_output_tokens'], 'maxResultBytes': settings['max_result_bytes'], 'maxReceiptBytes': settings['max_receipt_bytes']}
        overlay = template + '\n- id: llm-deepseek\n  config:\n    maxTokens: ' + str(settings['max_output_tokens']) + '\n    models:\n      - id: ' + canonical(settings['model']['model']) + '\n        name: ' + canonical(settings['model']['model']) + '\n        maxTokens: ' + str(settings['max_output_tokens']) + '\n        inputModalities: [text]\n- id: headless-runner\n  disabled: true\n- insert:\n    - id: clipping-text-runner\n      name: ' + canonical(str(tool / 'deploy' / 'text-runner.mjs')) + '\n      inject: [headlessStartup]\n      config:\n        task: !!js ctx.headlessStartup.task\n'
        overlay += ''.join('        ' + key + ': ' + canonical(value) + '\n' for key, value in config.items())
        overlay += '\n- id: session-persistence-jsonl\n  config:\n    root: ' + canonical(str(root / 'sessions')) + '\n- id: attachment-local\n  config:\n    dshHome: ' + canonical(str(root / 'artifacts')) + '\n- id: session-query-sqlite\n  config:\n    path: \':memory:\'\n    openAt: never\n'
        overlay_raw = overlay.encode()
        if len(overlay_raw) > 16384:
            raise SafetyError('text_overlay_too_large')
        now = engine.clock()
        deadline = now + settings['timeout_seconds']
        expires = deadline + settings['continuation_seconds']
        if expires > job['lease_until']:
            raise SafetyError('text_lease_headroom_missing')
        envelope = {'schema_version': 1, 'job_id': job['id'], 'attempt_id': attempt_id, 'kind': job['kind'], 'lease_token': job['lease_token'],
                    'nonce': secrets.token_urlsafe(32), 'input_digest': job['input_digest'], 'policy_digest': job['policy_digest'],
                    'prompt_digest': prompt_digest, 'manifest_path': str(root / 'manifest.json'), 'manifest_sha256': hashlib.sha256(manifest_raw).hexdigest(),
                    'overlay_path': str(root / 'deepseek-text.yml'), 'overlay_sha256': hashlib.sha256(overlay_raw).hexdigest(),
                    'native_execution': engine.native_execution, 'model_deadline': deadline, 'expires_at': expires}
        if len(canonical({'envelope': envelope, 'receipt_json': None, 'native_failure': {'timed_out': False, 'exit_code': None}}).encode()) > settings['max_receipt_bytes']:
            raise SafetyError('text_transport_headroom_missing')
        db.execute("INSERT INTO text_attempts(id,job_id,kind,state,envelope,settings,reservation,created_at,preparation_process) VALUES(?,?,?,'preparing',?,?,?,?,?)",
                   (attempt_id, job['id'], job['kind'], canonical(envelope), canonical(settings), canonical(reservation), now, canonical(preparation)))
        db.execute('UPDATE jobs SET lease_until=? WHERE id=?', (expires, job['id']))
        engine.event(db, job['id'], 'text_attempt_reserved', {'attempt_id': attempt_id, **reservation})
        return {'envelope': envelope, 'root': root, 'manifest': manifest_raw, 'overlay': overlay_raw}

    def finish(self, plan):
        root, engine, envelope = plan['root'], self.engine, plan['envelope']
        try:
            root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if root.parent.resolve() != root.parent or self.workspace.resolve() != self.workspace:
                raise SafetyError('text_artifact_parent_symlink')
            root.mkdir(mode=0o700)
            _fsync_directory(root.parent)
            for name in ('manifest', 'overlay'):
                raw = plan[name]
                if len(raw) > write_allowance(self.workspace, engine.config['limits']['max_disk_bytes']):
                    raise SafetyError('text_artifact_disk_budget_exhausted')
                _write(Path(envelope[name + '_path']), raw)
            with engine.transaction() as db:
                engine._active(db)
                job = engine._job(db, envelope['job_id'])
                if job['status'] != 'leased' or job['lease_token'] != envelope['lease_token'] or job['lease_until'] <= engine.clock():
                    raise SafetyError('text_worker_lease_changed')
                changed = db.execute("UPDATE text_attempts SET state='pending',artifacts_ready=1 WHERE id=? AND state='preparing'", (envelope['attempt_id'],))
                if changed.rowcount != 1:
                    raise SafetyError('text_preparation_reclaimed')
            return envelope
        except BaseException:
            with engine.transaction() as db:
                db.execute("UPDATE text_attempts SET state='preparation_failed',action_error='text_preparation_failed' WHERE id=? AND state='preparing'", (envelope['attempt_id'],))
            raise

    def verify_artifacts(self, attempt):
        envelope = strict_json(attempt['envelope'])
        root = self.workspace / 'model' / envelope['job_id'] / envelope['attempt_id']
        if envelope['manifest_path'] != str(root / 'manifest.json') or envelope['overlay_path'] != str(root / 'deepseek-text.yml'):
            raise SafetyError('text_artifact_binding_changed')
        owned_bytes(envelope['overlay_path'], self.workspace, 16384, envelope['overlay_sha256'])
        manifest = strict_json(owned_bytes(envelope['manifest_path'], self.workspace, 2*1048576, envelope['manifest_sha256']), 2*1048576)
        keys(manifest, {'schema_version', 'job_id', 'attempt_id', 'kind', 'prompt', 'prompt_digest'})
        if manifest['schema_version'] != 1 or any(manifest[key] != envelope[key] for key in ('job_id', 'attempt_id', 'kind', 'prompt_digest')) or hashlib.sha256(string(manifest['prompt'], 1048576).encode()).hexdigest() != envelope['prompt_digest']:
            raise SafetyError('text_prompt_binding_changed')
        return root

    def record(self, receipt):
        if not isinstance(receipt, dict):
            raise SafetyError('invalid_text_receipt')
        engine, envelope = self.engine, receipt.get('envelope', {})
        if not isinstance(envelope, dict):
            raise SafetyError('invalid_text_envelope')
        with engine.transaction() as db:
            attempt = db.execute('SELECT * FROM text_attempts WHERE id=? AND job_id=?', (envelope.get('attempt_id'), envelope.get('job_id'))).fetchone()
            if attempt is None:
                raise SafetyError('text_attempt_unknown')
            validate_receipt(receipt, attempt, engine.clock())
            result_digest = digest(receipt)
            if attempt['result_digest'] is not None and attempt['result_digest'] != result_digest:
                raise SafetyError('text_duplicate_result_changed')
            if engine.native_completion:
                if engine.native_execution != envelope['native_execution']:
                    raise SafetyError('text_native_completion_owner_changed')
                db.execute('UPDATE text_attempts SET native_completed_at=coalesce(native_completed_at,?) WHERE id=?', (engine.clock(), attempt['id']))
            if attempt['result_digest'] is None:
                db.execute("UPDATE text_attempts SET state='recorded',result=?,result_digest=?,completed_at=? WHERE id=?", (canonical(receipt), result_digest, engine.clock(), attempt['id']))
                engine.event(db, envelope['job_id'], 'text_usage_observed', {'attempt_id': attempt['id'], 'usage_observed': receipt['usage_observed'], 'usage': receipt['usage'], 'outcome': receipt['outcome'], 'reservation': strict_json(attempt['reservation'])})
                failure = receipt['failure']
                if failure is not None:
                    delay = failure['retry_after_ms'] / 1000 if failure['retry_after_ms'] is not None else (engine.config['limits']['retry_base_seconds'] if failure['category'] == 'rate_limit' else None)
                    engine._circuit_failure('model', delay, db=db)
            from .native_runtime import settle_native
            settle_native(engine,db,envelope,attempt['kind'],strict_json(attempt['reservation'])['reservation_id'],receipt)
            current = db.execute('SELECT * FROM text_attempts WHERE id=?', (attempt['id'],)).fetchone()
            return dict(current), attempt['result_digest'] is not None

    def fence_expired(self, db):
        engine = self.engine
        rows = db.execute("SELECT a.id,a.envelope,j.lease_token,j.id job_id FROM text_attempts a JOIN jobs j ON j.id=a.job_id WHERE a.native_completed_at IS NULL AND j.status='leased' AND j.lease_until<=?", (engine.clock(),)).fetchall()
        for row in rows:
            if row['lease_token'] != strict_json(row['envelope'])['lease_token']:
                continue
            db.execute("UPDATE jobs SET status='blocked',error='text_native_termination_unknown',updated_at=? WHERE id=?", (engine.clock(), row['job_id']))
            engine.event(db, row['job_id'], 'text_native_termination_pending', {'attempt_id': row['id']})

    def native_state(self, attempt):
        envelope = strict_json(attempt['envelope'])
        if attempt['native_termination_proof'] is not None:
            return strict_json(attempt['native_termination_proof'])
        root = self.workspace / 'model' / envelope['job_id'] / envelope['attempt_id']
        marker_path = root / 'process-start.json'
        native_return = False
        if attempt['artifacts_ready'] and marker_path.exists():
            marker = strict_json(owned_bytes(marker_path, self.workspace, 2048), 2048)
            keys(marker, {'schema_version', 'job_id', 'attempt_id', 'nonce', 'pid', 'start_identity'})
            if marker['schema_version'] != 1 or any(marker[k] != envelope[k] for k in ('job_id', 'attempt_id', 'nonce')):
                raise SafetyError('text_process_marker_binding_changed')
            process = {'pid': marker['pid'], 'start_identity': marker['start_identity']}
        elif not attempt['artifacts_ready']:
            process = strict_json(attempt['preparation_process'])
        elif attempt['native_completed_at'] is not None:
            # Persisted trusted native node return is independent proof: the
            # installed helper returns only on spawn error or child close.
            # Also require exact terminal workflow and preparation PID absence.
            process = strict_json(attempt['preparation_process'])
            native_return = True
        else:
            raise SafetyError('text_native_launch_proof_missing')
        result = self.engine._call('visual_execution_state', {**envelope, 'preparation_process': process})
        keys(result, {'execution_id', 'workflow_id', 'terminal', 'process_absent', 'stopped_at', 'provenance'})
        if any(result[k] != envelope['native_execution'][k] for k in ('execution_id', 'workflow_id')) or result['terminal'] is not True or result['process_absent'] is not True:
            raise SafetyError('text_native_termination_unknown')
        timestamp(result['stopped_at'])
        if native_return:
            result = {**result, 'provenance': canonical({'native_node_return_observed_at': attempt['native_completed_at'], 'original_preparation_process': process, 'terminal_execution_proof': result['provenance']})}
        return result

    def unknown_timeout(self, attempt, proof):
        envelope = strict_json(attempt['envelope'])
        return {'envelope': envelope, 'outcome': 'timeout', 'raw_result': None, 'usage_observed': False, 'usage': None,
                'usage_provenance': {'session_id': None, 'as_of_seq': None}, 'model': strict_json(attempt['settings'])['model'],
                'observed_at': proof['stopped_at'], 'failure': {'category': 'timeout', 'code': 'native_terminal_without_receipt', 'status': None, 'retry_after_ms': None}}

    def inventory(self, root):
        records, total = [], 0
        if root.resolve() != root:
            raise SafetyError('text_cleanup_path_changed')
        for path in sorted(root.rglob('*')):
            if path.is_symlink():
                raise SafetyError('text_cleanup_unowned_object')
            relative = path.relative_to(root).as_posix()
            directories = relative in {'sessions', 'artifacts', 'artifacts/attachments', 'artifacts/attachments/v1', 'artifacts/attachments/v1/objects'} or re.fullmatch(r'sessions/[^/]+(?:/session-[a-f0-9-]{36})?', relative) or re.fullmatch(r'artifacts/attachments/v1/objects/[a-f0-9]{2}', relative)
            if path.is_dir():
                if not directories:
                    raise SafetyError('text_cleanup_unknown_directory')
                continue
            top = {'manifest.json', 'deepseek-text.yml', 'result.json', 'process-start.json', 'runtime.json', '.runtime.pending.json'}
            attachment = re.fullmatch(r'artifacts/attachments/v1/objects/([a-f0-9]{2})/([a-f0-9]{64})', relative)
            session = re.fullmatch(r'sessions/[^/]+/session-[a-f0-9-]{36}/session\.jsonl(?:\.zstd)?', relative)
            if relative not in top and not attachment and not session:
                raise SafetyError('text_cleanup_unknown_file')
            raw = owned_bytes(path, self.workspace, 8 << 20, minimum=0 if relative == '.runtime.pending.json' else 1)
            measured = hashlib.sha256(raw).hexdigest()
            if attachment and (attachment[1] != measured[:2] or attachment[2] != measured):
                raise SafetyError('text_cleanup_object_changed')
            total += len(raw)
            if len(records) >= 1000 or total > 32 << 20:
                raise SafetyError('text_cleanup_inventory_limit')
            records.append({'path': relative, 'bytes': len(raw), 'sha256': measured})
        return records

    def prune(self, attempt_id):
        """Only known original sinks, persisted inventory, retention and process proof."""
        engine = self.engine
        with engine.transaction() as db:
            row = db.execute('SELECT * FROM text_attempts WHERE id=?', (attempt_id,)).fetchone()
            if row['artifacts_cleaned']:
                return True
            if row['result'] is None or row['native_termination_proof'] is None or row['state'] not in {'applied', 'failed', 'stale', 'blocked'}:
                return False
            saved = strict_json(row['settings'])
            if engine.clock() < max(row['completed_at'], row['native_completed_at']) + saved['retention_seconds']:
                return False
            root = self.workspace / 'model' / row['job_id'] / row['id']
            if root.resolve() != root or not root.is_relative_to(self.workspace.resolve()):
                raise SafetyError('text_cleanup_path_changed')
            if row['result'] is not None:
                from .native_runtime import settle_native
                settle_native(engine,db,strict_json(row['envelope']),row['kind'],strict_json(row['reservation'])['reservation_id'],strict_json(row['result']))
            current = self.inventory(root)
            if row['cleanup_inventory'] is None:
                inventory = current
                db.execute('UPDATE text_attempts SET cleanup_inventory=? WHERE id=?', (canonical(inventory), attempt_id))
                engine.event(db, row['job_id'], 'text_artifact_cleanup_inventory', {'attempt_id': row['id'], 'files': inventory})
            else:
                inventory = strict_json(row['cleanup_inventory'], 1 << 20)
        # Inventory commits before the first unlink. Missing files are permitted
        # after interruption; new or changed files are never swept away.
        expected = {item['path']: item for item in inventory}
        current = self.inventory(root)
        if any(expected.get(item['path']) != item for item in current):
            raise SafetyError('text_cleanup_inventory_changed')
        for item in current:
            path = root / item['path']
            owned_bytes(path, self.workspace, 8 << 20, item['sha256'], minimum=0 if item['path'] == '.runtime.pending.json' else 1)
            path.unlink()
            _fsync_directory(path.parent)
        for path in sorted((p for p in root.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            if path.is_symlink():
                raise SafetyError('text_cleanup_unowned_object')
            path.rmdir()
            _fsync_directory(path.parent)
        if root.exists():
            root.rmdir()
            _fsync_directory(root.parent)
        with engine.transaction() as db:
            db.execute('UPDATE text_attempts SET artifacts_cleaned=1,cleanup_issue=NULL WHERE id=?', (attempt_id,))
        return True
