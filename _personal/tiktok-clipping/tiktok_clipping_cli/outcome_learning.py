"""Comparable observed outcomes and the implemented selection distribution."""
from fractions import Fraction
import json
import math
import random
import re

from .revenue import NET_FIELDS
from .safety import SafetyError, canonical, digest, keys, number, string, timestamp

ENGAGEMENT_FIELDS = {'views', 'likes', 'comments', 'shares', 'watch_seconds'}
HORIZONS = {'engagement': {21600, 86400, 604800},
            'creator_net': {604800, 1209600, 2592000, 5184000, 7776000}}
HISTORY_SCHEMA = '''
CREATE TABLE IF NOT EXISTS revenue_history(
 id INTEGER PRIMARY KEY,job_id TEXT NOT NULL,publication_id TEXT NOT NULL,
 submission_id TEXT NOT NULL,campaign_id TEXT NOT NULL,measured_at REAL,
 recorded_at REAL NOT NULL,digest TEXT NOT NULL UNIQUE,data TEXT NOT NULL,proof TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS revenue_history_cohort ON revenue_history(publication_id,measured_at,recorded_at DESC,id DESC);
CREATE TABLE IF NOT EXISTS strategy_objectives(version INTEGER PRIMARY KEY,objective_key TEXT NOT NULL,descriptor TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS strategy_objective_versions ON strategy_objectives(objective_key,version);
CREATE TABLE IF NOT EXISTS objective_strategies(objective_key TEXT PRIMARY KEY,descriptor TEXT NOT NULL,baseline_version INTEGER NOT NULL,current_version INTEGER NOT NULL,last_evidence TEXT);
CREATE TABLE IF NOT EXISTS selection_windows(id TEXT PRIMARY KEY,digest TEXT NOT NULL,candidates TEXT NOT NULL,decision TEXT NOT NULL,created_at REAL NOT NULL);
'''


def append_revenue(db, record, *, job_id, reward_request_id, polling_lease_token, recorded_at):
    """Persist the already validated actual record inside the successful CAS."""
    measured = timestamp(record['observed_at']) if record['observed_at'] is not None else None
    proof = {'reward_request_id': reward_request_id, 'polling_lease_token': polling_lease_token,
             'binding': record['sync'].get('binding'), 'sync': record['sync'], 'recorded_at': recorded_at}
    db.execute('INSERT OR IGNORE INTO revenue_history(job_id,publication_id,submission_id,campaign_id,measured_at,recorded_at,digest,data,proof) VALUES(?,?,?,?,?,?,?,?,?)',
               (job_id, record['publication_id'], record['submission_id'], record['campaign_id'], measured,
                recorded_at, digest(record), canonical(record), canonical(proof)))


def revenue_observations(db, publication_id, objective):
    # The caller bounds the exact publication-age interval in SQL.
    start, end = objective
    return [{'id': row['id'], 'publication_id': row['publication_id'], 'channel': 'creator_net',
             'measured_at': row['measured_at'], 'observed_at': row['measured_at'],
             'recorded_at': row['recorded_at'], 'data': json.loads(row['data']),
             'provenance': {'revenue_digest': row['digest'], 'history_id': row['id']}}
            for row in db.execute('SELECT * FROM revenue_history WHERE publication_id=? AND measured_at BETWEEN ? AND ? ORDER BY recorded_at DESC,id DESC', (publication_id, start, end))]


def validate_policy(policy, learning):
    keys(policy, {'objectives', 'baseline_share'})
    number(policy['baseline_share'], 0, 1)
    if policy['baseline_share'] == 0:
        raise SafetyError('outcome_baseline_share_required')
    if policy['baseline_share'] + learning['max_exploration'] > 1:
        raise SafetyError('outcome_mixture_exceeds_one')
    objectives = policy['objectives']
    if not isinstance(objectives, list) or not 1 <= len(objectives) <= 16:
        raise SafetyError('invalid_outcome_objectives')
    ids, descriptors = set(), set()
    for objective in objectives:
        keys(objective, {'id', 'channel', 'field', 'horizon_seconds', 'tolerance_seconds', 'currency'})
        string(objective['id'], 64)
        channel = objective['channel']
        if channel not in HORIZONS or objective['horizon_seconds'] not in HORIZONS[channel]:
            raise SafetyError('unsupported_outcome_horizon')
        number(objective['horizon_seconds'], 1, integer=True)
        number(objective['tolerance_seconds'], 0, objective['horizon_seconds'], integer=True)
        if channel == 'engagement':
            if objective['field'] not in ENGAGEMENT_FIELDS or objective['currency'] is not None:
                raise SafetyError('invalid_engagement_objective')
        elif objective['field'] not in NET_FIELDS or not isinstance(objective['currency'], str) or not re.fullmatch('[A-Z]{3}', objective['currency']):
            raise SafetyError('invalid_creator_net_objective')
        descriptor = objective_key(objective)
        if objective['id'] in ids or descriptor in descriptors:
            raise SafetyError('duplicate_outcome_objective')
        ids.add(objective['id'])
        descriptors.add(descriptor)
    return policy


def objective_key(objective):
    """Renaming a label cannot conflate measurement descriptors."""
    return digest({key: value for key, value in objective.items() if key != 'id'})


def exact(value):
    # Decimal representations of validated floats are rational, money is int.
    return Fraction(str(value))


def rational(value):
    value = exact(value)
    return {'numerator': str(value.numerator), 'denominator': str(value.denominator)}


def from_rational(value):
    keys(value, {'numerator', 'denominator'})
    try:
        result = Fraction(int(value['numerator']), int(value['denominator']))
    except (ValueError, TypeError, ZeroDivisionError):
        raise SafetyError('invalid_outcome_rational') from None
    return result


def cohort(publications, observations, objective):
    """Nearest actual-age measurement, with latest same-time revision winning.

    Caller supplies validated observations, not retained last-known amounts.
    Incomplete/cached payout scans are audit records, not measurements.
    """
    latest = {}
    for observation in observations:
        if observation['channel'] != objective['channel']:
            continue
        if objective['channel'] == 'creator_net':
            record = observation['data']
            if record['readback_fresh'] is not True or record['sync']['complete'] is not True:
                continue
        measured = observation['measured_at']
        if measured is None:
            continue
        key = (observation['publication_id'], measured)
        previous = latest.get(key)
        if previous is None or (observation.get('recorded_at', observation['observed_at']), observation['id']) > (previous.get('recorded_at', previous['observed_at']), previous['id']):
            latest[key] = observation
    grouped = {}
    for (publication_id, _), row in latest.items():
        grouped.setdefault(publication_id, []).append(row)
    samples = []
    for publication in publications:
        published = timestamp(publication['published_at'])
        matching = [row for row in grouped.get(publication['publication_id'], [])
                    if abs(row['measured_at'] - published - objective['horizon_seconds']) <= objective['tolerance_seconds']]
        if not matching:
            continue
        row = min(matching, key=lambda item: (abs(item['measured_at'] - published - objective['horizon_seconds']), -item['observed_at'], -item['id']))
        value = row['data'].get(objective['field'])
        if value is None:
            continue
        if objective['channel'] == 'creator_net':
            if row['data']['currency'] != objective['currency']:
                continue
            value = int(value)
        else:
            number(value, 0)
        samples.append({**publication, 'objective_id': objective['id'], 'objective_key': objective_key(objective),
                        'value': str(value) if objective['channel'] == 'creator_net' else value,
                        'value_basis': objective['channel'], 'currency': objective['currency'],
                        'age_seconds': row['measured_at'] - published, 'measured_at': row['measured_at'],
                        'observed_at': row['observed_at'], 'provenance': row['provenance']})
    return sorted(samples, key=lambda row: row['publication_id'])


def scores(candidates, samples, minimum):
    """Prefer a mature exact video, then a compatible source stratum."""
    regimes, videos = {}, {}
    for row in samples:
        regime = (row['campaign_id'], row['regime_digest'])
        value = exact(row['value'])
        for target, key in ((regimes, regime), (videos, (*regime, row['media_id']))):
            count, total = target.get(key, (0, Fraction()))
            target[key] = count + 1, total + value
    result = []
    for candidate in candidates:
        regime = (candidate['campaign_id'], candidate['regime_digest'])
        compatible = regimes.get(regime, (0, Fraction()))
        video = videos.get((*regime, candidate['media_id']), (0, Fraction()))
        (count, total), scope = (video, 'video') if video[0] >= minimum else (compatible, 'source')
        result.append({'candidate_id': candidate['candidate_id'], 'scope': scope,
                       'known_samples': count, 'mean': rational(total / count) if count >= minimum else None})
    return result


def choose(candidates, objectives, samples_by_objective, *, minimum_samples, baseline_share, exploration, seed):
    """Exact rational draws implement the recorded mixture, not model confidence."""
    if not candidates:
        raise SafetyError('empty_selection_window')
    candidates = sorted(candidates, key=lambda row: (row['ordinal'], row['candidate_id']))
    units = {}
    for candidate in candidates:
        # Catalog IDs may represent the same video under distinct campaigns.
        unit = candidate['media_id']
        units.setdefault(unit, candidate)
    candidates = list(units.values())
    if len({row['candidate_id'] for row in candidates}) != len(candidates):
        raise SafetyError('duplicate_selection_candidate_id')
    b, e = exact(baseline_share), exact(exploration)
    if min(b, e) < 0 or b + e > 1:
        raise SafetyError('outcome_mixture_exceeds_one')
    selected_objective, summaries, skipped = None, [], []
    for objective in objectives:
        current = scores(candidates, samples_by_objective.get(objective['id'], []), minimum_samples)
        if any(row['mean'] is not None for row in current):
            selected_objective, summaries = objective, current
            break
        skipped.append({'objective_id': objective['id'], 'known_samples': len(samples_by_objective.get(objective['id'], []))})
    known = [row for row in summaries if row['mean'] is not None]
    winner = max(known, key=lambda row: (from_rational(row['mean']), row['candidate_id']))['candidate_id'] if known else candidates[0]['candidate_id']
    rng = random.Random(seed)
    # Common denominator gives a draw matching exact B/E fractions.
    denominator = (b + e).denominator * b.denominator
    draw = Fraction(rng.randrange(denominator), denominator)
    branch = 'baseline' if draw < b else 'exploration' if draw < b + e else 'exploitation'
    selected = rng.choice(candidates)['candidate_id'] if branch != 'exploitation' else winner
    distribution = {row['candidate_id']: rational((b + e) / len(candidates) + (1 - b - e if row['candidate_id'] == winner else 0)) for row in candidates}
    objective = selected_objective or objectives[0]
    return {'candidate_id': selected, 'branch': branch, 'propensity': distribution[selected],
            'distribution': distribution, 'objective': objective, 'objective_key': objective_key(objective),
            'reason': ('cold_start' if not known else 'engagement_proxy' if skipped and objective['channel'] == 'engagement' else 'measured_outcome'),
            'skipped_objectives': skipped, 'scores': summaries, 'baseline_share': baseline_share,
            'exploration': exploration, 'seed': str(seed), 'candidate_ids': [row['candidate_id'] for row in candidates]}


def select_candidates(candidates, observations, *, decision_context):
    """Catalog seam: observations are already validated per-objective cohorts."""
    keys(decision_context, {'objectives', 'minimum_samples', 'baseline_share', 'exploration', 'seed'})
    return choose(candidates, decision_context['objectives'], observations,
                  **{key: decision_context[key] for key in ('minimum_samples', 'baseline_share', 'exploration', 'seed')})


def assign_style(strategy, baseline, branch, seed, allowed=None):
    """Branch-specific style assignment; probabilities match the actual draw."""
    weights = baseline['weights'] if branch == 'baseline' else strategy['weights']
    styles = sorted(allowed if allowed is not None else weights)
    if not styles or any(style not in weights for style in styles):
        raise SafetyError('invalid_selection_style_set')
    values = [Fraction(1, len(styles)) if branch == 'exploration' else exact(weights[style]) for style in styles]
    total = sum(values, Fraction())
    if not total:
        raise SafetyError('empty_selection_style_distribution')
    values = [value / total for value in values]
    denominator = 1
    for value in values:
        denominator = math.lcm(denominator, value.denominator)
    draw = Fraction(random.Random(seed).randrange(denominator), denominator)
    cumulative = Fraction()
    for style, value in zip(styles, values):
        cumulative += value
        if draw < cumulative:
            return {'style': style, 'propensity': rational(value),
                    'distribution': {key: rational(item) for key, item in zip(styles, values)}}
    raise SafetyError('selection_style_draw_invalid')


def regressed(baseline, current, fraction):
    if not baseline or not current:
        return False
    base = sum((exact(value) for value in baseline), Fraction()) / len(baseline)
    active = sum((exact(value) for value in current), Fraction()) / len(current)
    return active < base - abs(base) * exact(fraction)


def learning_summary(samples, current_version, baseline_version, allowed_styles):
    """All-data sufficient statistics for only the two compared policies."""
    groups = {}
    for sample in samples:
        if sample['version'] not in {current_version, baseline_version}:
            continue
        if sample['style'] not in allowed_styles or sample['branch'] not in {'baseline', 'exploration', 'exploitation', 'legacy'}:
            raise SafetyError('outcome_assignment_not_allowlisted')
        key = sample['version'], sample['style'], sample['branch']
        count, total = groups.get(key, (0, Fraction()))
        groups[key] = count + 1, total + exact(sample['value'])
    return [{'version': version, 'style': style, 'branch': branch, 'count': count,
             'total': rational(total), 'mean': rational(total / count)}
            for (version, style, branch), (count, total) in sorted(groups.items())]
