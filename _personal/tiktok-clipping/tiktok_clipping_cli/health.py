"""Durable, secret-free operational evidence; reporting never fences recovery."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS capability_health(
 capability TEXT PRIMARY KEY,last_success REAL,last_failure REAL,
 category TEXT,code TEXT,failures INTEGER NOT NULL DEFAULT 0,provider TEXT);
CREATE INDEX IF NOT EXISTS health_event_lookup ON events(event,at DESC,id DESC);
CREATE INDEX IF NOT EXISTS health_job_event_lookup ON events(job_id,event,at);
CREATE INDEX IF NOT EXISTS health_job_lookup ON jobs(status,updated_at);
CREATE INDEX IF NOT EXISTS health_snapshot_lookup ON snapshots(observed_at DESC);
CREATE INDEX IF NOT EXISTS health_text_lookup ON text_attempts(completed_at DESC);
CREATE INDEX IF NOT EXISTS health_visual_lookup ON visual_attempts(completed_at DESC);
"""


def initialize(db):
    db.executescript(SCHEMA)
    if 'provider' not in {r[1] for r in db.execute('PRAGMA table_info(capability_health)')}:
        db.execute('ALTER TABLE capability_health ADD COLUMN provider TEXT')


def observe(db, capability, now, *, category=None, code=None, provider=None):
    # Error text/diagnostics, cookies, request bodies and model strings never
    # enter this projection. Only the adapter's typed, bounded code is retained.
    code = code if isinstance(code, str) and code.isascii() and all(c.isalnum() or c in '._:-' for c in code) and len(code) <= 128 else None
    if category is None:
        db.execute('INSERT INTO capability_health(capability,last_success) VALUES(?,?) ON CONFLICT(capability) DO UPDATE SET last_success=excluded.last_success,category=NULL,code=NULL,failures=0', (capability, now))
    else:
        provider = provider if provider in {'whop','tiktok','youtube','google','model'} else None
        db.execute('INSERT INTO capability_health(capability,last_failure,category,code,failures,provider) VALUES(?,?,?,?,1,?) ON CONFLICT(capability) DO UPDATE SET last_failure=excluded.last_failure,category=excluded.category,code=excluded.code,provider=excluded.provider,failures=capability_health.failures+1', (capability, now, category, code, provider))


def model_event(db, event, data, now):
    table = {'text_usage_observed':'text_attempts','visual_usage_observed':'visual_attempts'}.get(event)
    if table is None:
        return
    row = db.execute('SELECT result FROM '+table+' WHERE id=?', (data['attempt_id'],)).fetchone()
    receipt = json.loads(row[0])
    failure = receipt.get('failure')
    category = failure['category'] if failure else None
    if category in {'provider_unavailable','model_failed','timeout','malformed_output'}:
        category = 'transient'
    if not failure and (receipt['outcome']!='completed' or not receipt['usage_observed']):
        category = 'transient'
    observe(db,'model',now,category=category,code=failure['code'] if failure else None,provider='model')


def project(engine, db, state, discovery=None):
    now = engine.clock()
    policy = engine.config.get('monitoring')
    enabled = bool(policy and policy['enabled'])
    day = engine._day()
    budget = db.execute('SELECT * FROM budgets WHERE day=?',(day,)).fetchone()
    remaining = {field:engine.config['limits']['daily_'+field]-(budget[field] if budget else 0) for field in ('posts','model_calls','runtime_seconds')}
    exhausted = [field for field,value in remaining.items() if value<=0 or (field=='runtime_seconds' and value<engine.config['limits']['work_timeout_seconds'])]
    reset_at = (datetime.fromtimestamp(now,timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)).timestamp()
    issues, capabilities = [], []
    for row in db.execute('SELECT h.*,coalesce(c.until,0) AS retry_at FROM capability_health h LEFT JOIN circuits c ON c.capability=h.capability ORDER BY h.capability'):
        item = dict(row)
        # Known single-provider operations may have legacy failure rows without
        # provider metadata. Mixed discovery/preflight operations do not guess.
        provider = item['provider'] or {'publish':'tiktok','reconcile':'tiktok','metrics':'tiktok','metrics_batch':'tiktok','submit_rewards':'whop','reconcile_rewards':'whop','reward_status':'whop','sync_reward_revenue':'whop'}.get(item['capability'])
        if provider:
            circuit = db.execute('SELECT until FROM circuits WHERE capability=?', ('provider:'+provider,)).fetchone()
            if circuit:
                item['retry_at'] = max(item['retry_at'], circuit[0])
        category = item['category']
        if category is None:
            item['state'] = 'healthy'
        elif category == 'auth':
            item['state'] = 'action_required'
        elif category == 'permanent':
            item['state'] = 'source_failure' if item['capability']=='discover' and item['code'] in {'source_access_denied','source_unsupported'} else 'action_required'
        elif category == 'ambiguous':
            item['state'] = 'reconciliation_pending'
        elif item['retry_at'] > now:
            item['state'] = 'cooldown'
        elif category in {'transient', 'rate_limit'} and item['failures'] < engine.config['limits']['max_attempts']:
            item['state'] = 'retry_pending'
        else:
            item['state'] = 'action_required'
        if item['state'] == 'action_required':
            issues.append({'reason': 'capability_failure', 'capability': item['capability'], 'category': category, 'code': item['code']})
        capabilities.append(item)
    model_rows = [db.execute('SELECT completed_at,result FROM '+table+' WHERE result IS NOT NULL ORDER BY completed_at DESC LIMIT 1').fetchone() for table in ('text_attempts','visual_attempts')]
    latest = max((r for r in model_rows if r is not None), key=lambda r:r['completed_at'], default=None)
    if latest is not None and not any(c['capability']=='model' for c in capabilities):
        receipt = json.loads(latest['result'])
        failure = receipt.get('failure')
        circuit = db.execute("SELECT failures,until FROM circuits WHERE capability='model'").fetchone()
        until = circuit['until'] if circuit else 0
        failures = circuit['failures'] if circuit else 0
        model_state = ('healthy' if failure is None and receipt['outcome']=='completed' else
                       'action_required' if failure and failure['category']=='auth' else
                       'cooldown' if until>now else
                       'action_required' if failures>=engine.config['limits']['max_attempts'] else 'retry_pending')
        capabilities.append({'capability':'model','state':model_state,'last_observed':latest['completed_at'],
                             'category':failure['category'] if failure else None,'retry_at':until,'failures':failures})
        if model_state=='action_required':
            issues.append({'reason':'capability_failure','capability':'model','category':failure['category'] if failure else None})
    present = {c['capability'] for c in capabilities}
    for row in db.execute("SELECT capability,until,failures FROM circuits WHERE until>? AND (capability='model' OR capability LIKE 'provider:%') ORDER BY capability", (now,)):
        if row['capability'] not in present:
            capabilities.append({'capability':row['capability'],'state':'cooldown','retry_at':row['until'],'failures':row['failures']})
    if discovery is not None:
        refresh = discovery.get('last_refresh')
        for failure in discovery['unit_failures']:
            if failure['category']=='auth':
                issues.append({'reason':'discovery_auth_failure','capability':failure['provider'],'category':'auth','scope':'unresolved_dependency'})
        if refresh:
            for failure in refresh['failures']:
                if failure['category']=='auth':
                    issues.append({'reason':'discovery_auth_failure','capability':failure['provider'],'category':'auth'})
        progress = discovery['scan'].get('last_progress')
        since = progress['recorded_at'] if progress else discovery['scan'].get('first_refresh_started')
        excluded_units = sum(f['count'] for f in discovery['unit_failures'] if f['category'] in {'permanent','access_denied','unsupported'})
        pending_recovery = discovery['pending_dependency_count'] > excluded_units
        barrier = discovery['refresh_interrupted_or_in_progress'] or (discovery['eligible_count']==0 and
                  (pending_recovery or (not discovery['scan']['current_pass_provider_end'] and bool((refresh or {}).get('failures')))))
        cooling = any(t>now for t in discovery['cooldowns'].values())
        if policy and barrier and not cooling and since is not None and now-since >= policy['stalled_job_age_seconds']:
            issues.append({'reason':'discovery_progress_stalled','age_seconds':now-since,'last_progress_kind':progress['kind'] if progress else None})
    if policy:
        for row in db.execute("SELECT j.id,p.idempotency_key,coalesce((SELECT min(at) FROM events e WHERE e.job_id=j.id AND e.event='upload_started'),j.created_at) AS started_at FROM jobs j LEFT JOIN publications p ON p.job_id=j.id WHERE j.status IN ('ambiguous','reconciling') AND started_at<=? ORDER BY started_at LIMIT 20", (now-policy['ambiguity_age_seconds'],)):
            issues.append({'reason': 'publication_outcome_unknown', 'job_id': row['id'], 'request_id': row['idempotency_key'], 'age_seconds': now-row['started_at']})
        for row in db.execute("SELECT job_id,request_id,deadline,state FROM rewards WHERE state IN ('pending_submission','ambiguous','submitting','dispatch_pending','reconciling') AND deadline<=? ORDER BY deadline LIMIT 20", (now,)):
            issues.append({'reason': 'reward_submission_overdue' if row['state']=='pending_submission' else 'reward_outcome_unknown', 'job_id': row['job_id'], 'request_id': row['request_id'], 'overdue_seconds': now-row['deadline']})
        for row in db.execute("SELECT id,updated_at FROM jobs WHERE status='blocked' AND updated_at<=? ORDER BY updated_at LIMIT 20", (now-policy['stalled_job_age_seconds'],)):
            issues.append({'reason': 'blocked_job', 'job_id': row['id'], 'age_seconds': now-row['updated_at']})
    last = {}
    for label,event in [('publication','published_verified'),('submission','reward_submitted')]:
        row = db.execute('SELECT at FROM events WHERE event=? ORDER BY at DESC,id DESC LIMIT 1', (event,)).fetchone()
        last[label] = row[0] if row else None
    row = db.execute('SELECT observed_at FROM snapshots ORDER BY observed_at DESC LIMIT 1').fetchone()
    last['measurement'] = row[0] if row else None
    row = db.execute("SELECT last_success FROM capability_health WHERE capability='discover'").fetchone()
    last['discovery_call'] = row[0] if row else None
    last['discovery_page'] = discovery['scan']['last_successful_page'] if discovery else None
    # User-issued pause/stop is deliberate. Fresh installs have no control event.
    control_event = db.execute("SELECT data FROM events WHERE event='control' ORDER BY at DESC,id DESC LIMIT 1").fetchone()
    explicit_control = control_event is not None and json.loads(control_event[0]).get('state')==state['control']
    if enabled and (state['state'] == 'unconfigured' or not state['adapter_configured'] or (state['control'] != 'running' and not explicit_control)):
        issues.append({'reason': 'operational_configuration_missing' if state['state']=='unconfigured' else 'operational_service_not_started'})
    active_issues = issues if enabled and state['control'] == 'running' else []
    if enabled and any(i['reason'].startswith('operational_') for i in issues):
        active_issues = issues
    health_state = 'action_required' if active_issues else ('staged' if not enabled else state['state'])
    if health_state == 'running':
        if any(c['state']=='cooldown' for c in capabilities) or (discovery and any(t>now for t in discovery['cooldowns'].values())):
            health_state = 'cooldown'
        elif discovery and discovery['eligible_count']==0:
            incomplete = discovery['refresh_interrupted_or_in_progress'] or discovery['pending_dependency_count'] or not discovery['scan']['current_pass_provider_end'] or bool((discovery.get('last_refresh') or {}).get('failures'))
            health_state = 'discovery_incomplete' if incomplete else 'idle_observed_catalog'
        else:
            health_state = 'budget_waiting' if exhausted else 'healthy'
    terminal_failures = db.execute("SELECT count(*) FROM jobs WHERE status='failed'").fetchone()[0]
    return {'state': health_state, 'monitoring_enabled': enabled, 'actionable': bool(active_issues),
            'issues': active_issues, 'observed_issues': issues, 'capabilities': capabilities,
            'last_success': last, 'discovery': discovery, 'terminal_failed_jobs':terminal_failures,
            'budget_window':{'day':day,'timezone':'UTC','reset_at':reset_at,'remaining':remaining,'exhausted':exhausted},'observed_at': now}
