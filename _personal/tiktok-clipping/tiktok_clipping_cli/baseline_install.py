"""Explicit append-only installation of a trusted future style space."""
from .safety import SafetyError, canonical, digest, keys, strict_json, string, validate_strategy


def legacy_baseline_version(db):
    pointer = db.execute("SELECT value FROM settings WHERE key='baseline_pointer'").fetchone()
    if pointer is None:
        row = db.execute('SELECT version FROM strategies WHERE baseline=1 ORDER BY version LIMIT 1').fetchone()
        if row is None:
            raise SafetyError('baseline_missing')
        return row[0]
    try:
        version = int(pointer[0])
    except (ValueError, TypeError):
        raise SafetyError('baseline_pointer_invalid') from None
    row = db.execute('SELECT baseline FROM strategies WHERE version=?', (version,)).fetchone()
    if row is None or row[0] != 1:
        raise SafetyError('baseline_pointer_invalid')
    return version


def _binding(engine, db, version):
    row = db.execute('SELECT proposal FROM strategies WHERE version=?', (version,)).fetchone()
    if row is None:
        raise SafetyError('baseline_strategy_missing')
    proposal = strict_json(row[0], engine.config['limits']['max_payload_bytes'])
    return {'version': version, 'proposal_digest': digest(proposal)}


def state(engine, db):
    """Read configured installed descriptors without creating an objective."""
    from .outcome_learning import objective_key
    if digest(engine.config) != engine.policy_digest:
        raise SafetyError('baseline_config_changed')
    objectives = []
    configured = engine.config['learning'].get('outcome_policy', {}).get('objectives', [])
    for descriptor in configured:
        key = objective_key(descriptor)
        row = db.execute('SELECT * FROM objective_strategies WHERE objective_key=?', (key,)).fetchone()
        if row is None:
            continue
        saved = strict_json(row['descriptor'], engine.config['limits']['max_payload_bytes'])
        if saved != descriptor:
            raise SafetyError('baseline_objective_identity_changed')
        for version in (row['baseline_version'], row['current_version']):
            installed = db.execute('SELECT o.objective_key,o.descriptor,s.baseline FROM strategy_objectives o JOIN strategies s ON s.version=o.version WHERE o.version=?', (version,)).fetchone()
            if installed is None or installed['objective_key'] != key or strict_json(installed['descriptor']) != descriptor or (version == row['baseline_version'] and installed['baseline'] != 1):
                raise SafetyError('baseline_objective_version_binding_changed')
        objectives.append({'objective_key': key, 'descriptor_digest': digest(descriptor),
                           'baseline': _binding(engine, db, row['baseline_version']),
                           'current': _binding(engine, db, row['current_version'])})
    active = db.execute("SELECT value FROM settings WHERE key='active_outcome_objective'").fetchone()
    active_key = active[0] if active else None
    if active_key is not None and active_key not in {row['objective_key'] for row in objectives}:
        raise SafetyError('baseline_active_objective_not_configured')
    current = int(db.execute("SELECT value FROM settings WHERE key='strategy_version'").fetchone()[0])
    return {'schema_version': 1, 'policy_digest': engine.policy_digest,
            'target_baseline_digest': digest(engine.config['baseline']),
            'active_outcome_objective': active_key,
            'active_strategy': _binding(engine, db, current),
            'legacy_baseline': _binding(engine, db, legacy_baseline_version(db)),
            'objectives': sorted(objectives, key=lambda row: row['objective_key'])}


def _quiescent(engine, db):
    if db.execute("SELECT 1 FROM jobs WHERE status IN ('leased','running') OR "
                  "(status NOT IN ('failed','ambiguous','done') AND lease_token IS NOT NULL AND lease_until>?) LIMIT 1",
                  (engine.clock(),)).fetchone():
        raise SafetyError('baseline_active_work')
    for table in ('text_attempts', 'visual_attempts'):
        if db.execute("SELECT 1 FROM " + table + " WHERE state IN ('preparing','pending','recorded') LIMIT 1").fetchone():
            raise SafetyError('baseline_active_native_work')


def install(engine, db, expected, reason):
    try:
        raw = canonical(expected).encode()
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise SafetyError('baseline_snapshot_invalid') from None
    expected = strict_json(raw, engine.config['limits']['max_payload_bytes'])
    keys(expected, {'schema_version', 'policy_digest', 'target_baseline_digest', 'active_outcome_objective',
                    'active_strategy', 'legacy_baseline', 'objectives'})
    string(reason, 1000)
    if not reason.strip():
        raise SafetyError('baseline_reason_required')
    target = engine.config['baseline']
    validate_strategy(target, engine.config)
    from .media import STYLES
    if any(style not in STYLES for style in target['weights']):
        raise SafetyError('baseline_render_style_not_supported')
    if 'outcome_policy' in engine.config['learning']:
        from .outcome_learning import validate_policy
        validate_policy(engine.config['learning']['outcome_policy'], engine.config['learning'])
    _quiescent(engine, db)
    actual = state(engine, db)
    request_digest = digest(expected)
    if canonical(expected) != canonical(actual):
        prior = db.execute("SELECT value FROM settings WHERE key='last_baseline_install'").fetchone()
        saved = strict_json(prior[0], engine.config['limits']['max_payload_bytes']) if prior else None
        if saved is not None and saved['request_digest'] == request_digest and saved['post_snapshot_digest'] == digest(actual):
            return {**saved['result'], 'state': 'unchanged', 'idempotent_replay': True}
        raise SafetyError('baseline_snapshot_conflict')
    bindings = [actual['legacy_baseline'], actual['active_strategy']]
    bindings += [row[key] for row in actual['objectives'] for key in ('baseline', 'current')]
    for binding in bindings:
        old = strict_json(db.execute('SELECT proposal FROM strategies WHERE version=?', (binding['version'],)).fetchone()[0])
        if not set(old['weights']) <= set(target['weights']):
            raise SafetyError('baseline_style_removal_forbidden')
    baseline_bindings = [actual['legacy_baseline']] + [row['baseline'] for row in actual['objectives']]
    if all(row['proposal_digest'] == actual['target_baseline_digest'] for row in baseline_bindings):
        return {'state': 'unchanged', 'snapshot': actual, 'idempotent_replay': False}
    version = db.execute('SELECT max(version)+1 FROM strategies').fetchone()[0]

    def append(descriptor=None):
        nonlocal version
        assigned = version
        version += 1
        db.execute('INSERT INTO strategies VALUES(?,?,?,1)', (assigned, canonical(target), engine.clock()))
        if descriptor is not None:
            from .outcome_learning import objective_key
            db.execute('INSERT INTO strategy_objectives VALUES(?,?,?)', (assigned, objective_key(descriptor), canonical(descriptor)))
        return assigned

    legacy = append()
    db.execute("INSERT INTO settings VALUES('baseline_pointer',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(legacy),))
    active_version = legacy
    for row in actual['objectives']:
        descriptor = strict_json(db.execute('SELECT descriptor FROM objective_strategies WHERE objective_key=?', (row['objective_key'],)).fetchone()[0])
        installed = append(descriptor)
        changed = db.execute('UPDATE objective_strategies SET baseline_version=?,current_version=?,last_evidence=NULL '
                             'WHERE objective_key=? AND baseline_version=? AND current_version=? AND descriptor=?',
                             (installed, installed, row['objective_key'], row['baseline']['version'], row['current']['version'], canonical(descriptor)))
        if changed.rowcount != 1:
            raise SafetyError('baseline_snapshot_conflict')
        if row['objective_key'] == actual['active_outcome_objective']:
            active_version = installed
    changed = db.execute("UPDATE settings SET value=? WHERE key='strategy_version' AND value=?",
                         (str(active_version), str(actual['active_strategy']['version'])))
    if changed.rowcount != 1:
        raise SafetyError('baseline_snapshot_conflict')
    after = state(engine, db)
    result = {'state': 'installed', 'snapshot': after, 'idempotent_replay': False}
    event = {'request_digest': request_digest, 'reason': reason, 'policy_digest': engine.policy_digest,
             'before': actual, 'after': after, 'intentional_style_space_change': True}
    engine.event(db, None, 'baseline_installed', event)
    saved = {'request_digest': request_digest, 'post_snapshot_digest': digest(after), 'result': result}
    raw = canonical(saved)
    if len(raw.encode()) > engine.config['limits']['max_payload_bytes']:
        raise SafetyError('baseline_install_receipt_exceeds_bound')
    db.execute("INSERT INTO settings VALUES('last_baseline_install',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (raw,))
    return result
