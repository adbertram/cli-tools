"""Exact SDK revenue observations. Cent strings never become float earnings."""
import re

from .safety import SafetyError, canonical, digest, strict_json, timestamp


NET_FIELDS = ('pending_cents', 'received_cents', 'total_earned_cents')


def validate_revenue(record, ledger, maximum):
    strict_json(canonical(record), maximum)
    required = {'submission_id', 'campaign_id', 'publication_id', 'amount_basis', 'amounts_verified', 'currency', 'sync', 'provenance', 'readback_fresh', 'observed_at', 'status', *NET_FIELDS}
    if not isinstance(record, dict) or not required <= record.keys() or any(record.get(k) != ledger[k] for k in
            ('submission_id', 'campaign_id', 'publication_id')):
        raise SafetyError('revenue_submission_binding_changed')
    if record.get('amount_basis') != 'creator_net' or type(record.get('amounts_verified')) is not bool:
        raise SafetyError('revenue_amount_basis_invalid')
    currency = record.get('currency')
    if currency is not None and (not isinstance(currency, str) or not re.fullmatch('[A-Z]{3}', currency)):
        raise SafetyError('revenue_currency_invalid')
    sync = record.get('sync')
    provenance = record.get('provenance')
    if (not isinstance(sync, dict) or type(sync.get('complete')) is not bool
            or not isinstance(provenance, dict) or type(provenance.get('moderation_readback_fresh')) is not bool
            or type(record.get('readback_fresh')) is not bool):
        raise SafetyError('revenue_freshness_contract_invalid')
    if record['readback_fresh'] is not (sync['complete'] and provenance['moderation_readback_fresh']):
        raise SafetyError('revenue_freshness_contract_invalid')
    if sync['complete']:
        start, end = timestamp(sync.get('started_at')), timestamp(sync.get('completed_at'))
        if end < start or record.get('observed_at') != sync['completed_at']:
            raise SafetyError('revenue_scan_interval_invalid')
    for field in NET_FIELDS:
        value = record.get(field)
        if value is not None:
            if not isinstance(value, str) or not re.fullmatch(r'-?(0|[1-9][0-9]{0,37})', value):
                raise SafetyError('revenue_cent_string_invalid')
            if currency is None or not sync['complete'] or record['readback_fresh'] is not True or provenance['moderation_readback_fresh'] is not True:
                raise SafetyError('revenue_known_amount_without_fresh_complete_proof')
    if record['amounts_verified'] and any(record.get(field) is None for field in NET_FIELDS):
        raise SafetyError('revenue_verified_amount_missing')
    if record.get('total_earned_cents') is not None and (any(record.get(k) is None for k in NET_FIELDS[:2]) or
            int(record['total_earned_cents']) != int(record['pending_cents']) + int(record['received_cents'])):
        raise SafetyError('revenue_total_mismatch')
    return record


def retain_known(previous, record):
    """Unknown fields preserve prior proof; a newer real decrease replaces it."""
    result = dict(previous or {})
    if record.get('observed_at') is None:
        return result
    measured = timestamp(record['observed_at'])
    for field in NET_FIELDS:
        if record.get(field) is None:
            continue
        old = result.get(field)
        if old is not None and timestamp(old['observed_at']) >= measured:
            if timestamp(old['observed_at']) == measured and (old['cents'], old['currency']) != (record[field], record['currency']):
                raise SafetyError('revenue_same_observation_changed')
            continue
        result[field] = {'cents': record[field], 'currency': record['currency'],
            'observed_at': record['observed_at'], 'amount_basis': 'creator_net',
            'scan_started_at': record['sync']['started_at'], 'scan_completed_at': record['sync']['completed_at'],
            'evidence_digest': digest(record), 'provenance': record['provenance']}
    return result


def normalize_revenue(record, ledger, actor, experience, maximum):
    bound = {k: ledger[k] for k in ('campaign_id', 'publication_id')}
    bound['submission_id'] = ledger['submission']['submission_id']
    record = validate_revenue(record, bound, maximum)
    binding = record['sync'].get('binding', {})
    if any(binding.get(k) != v for k, v in {'account_id': actor['account_id'], 'profile': actor['profile'], 'experience': experience}.items()):
        raise SafetyError('revenue_provider_actor_changed')
    fresh = record['provenance']['moderation_readback_fresh']
    observed = record['provenance'].get('moderation_observed_at')
    if fresh:
        timestamp(observed)
    # Match the owning SDK's observed creatorStatusOf expression. Missing flags
    # cannot establish moderation from a raw status alone.
    flags = (record.get('flagged'), record.get('is_deleted'))
    if any(value is not None and type(value) is not bool for value in flags):
        raise SafetyError('revenue_moderation_flags_invalid')
    creator_status = ('rejected' if flags == (True, False) else record.get('status')) if all(type(value) is bool for value in flags) and fresh else None
    if record.get('creator_status') != creator_status:
        raise SafetyError('revenue_creator_status_changed')
    status = {'approved': 'accepted', 'pending': 'pending', 'rejected': 'rejected'}.get(creator_status, 'unknown')
    return {'status': status, **{k: bound[k] for k in ('campaign_id', 'publication_id')},
        'observed_at': observed, 'readback_fresh': fresh, 'earnings': None,
        'revenue': record, 'provenance': canonical({'kind': 'whop_individual_creator_net', 'evidence_digest': digest(record), 'moderation': record['provenance']})}
