import copy
from fractions import Fraction

import pytest

from conftest import iso
from tiktok_clipping_cli.outcome_learning import choose, cohort, from_rational, objective_key, regressed, validate_policy
from tiktok_clipping_cli.safety import SafetyError


def objective(channel='engagement', field='views', horizon=86400, tolerance=3600, currency=None):
    return {'id': field + '-' + str(horizon), 'channel': channel, 'field': field, 'horizon_seconds': horizon,
            'tolerance_seconds': tolerance, 'currency': currency}


def candidate(identifier, source='source', video=None, regime='rate-policy-1', ordinal=0):
    return {'candidate_id': identifier, 'source_id': source, 'media_id': video or identifier,
            'campaign_id': 'campaign', 'regime_digest': regime, 'ordinal': ordinal}


def sample(video, value, source='source', regime='rate-policy-1'):
    return {'source_id': source, 'media_id': video, 'campaign_id': 'campaign', 'regime_digest': regime, 'value': value}


def decide(rows, values, **kwargs):
    obj = objective()
    return choose(rows, [obj], {obj['id']: values}, minimum_samples=2, baseline_share=0, exploration=0, seed=123, **kwargs)


def publication():
    return {'publication_id': 'p', 'published_at': iso(0), 'source_id': 'source', 'media_id': 'video',
            'campaign_id': 'campaign', 'regime_digest': 'policy', 'version': 1}


def observation(identifier, measured, value, channel='engagement', *, observed=None, currency='USD', fresh=True, complete=True):
    data = {'views': value} if channel == 'engagement' else {'received_cents': value, 'currency': currency,
            'readback_fresh': fresh, 'sync': {'complete': complete}}
    return {'id': identifier, 'publication_id': 'p', 'channel': channel, 'measured_at': measured,
            'observed_at': measured if observed is None else observed, 'data': data, 'provenance': 'TEST actual readback'}


def test_actual_video_outcomes_change_selection():
    rows = [candidate('old-low', video='low'), candidate('new-high', video='high', ordinal=1)]
    result = decide(rows, [sample('low', 10), sample('low', 12), sample('high', 100), sample('high', 120)])
    assert result['candidate_id'] == 'new-high' and result['reason'] == 'measured_outcome'
    assert result['scores'][1]['scope'] == 'video'


def test_source_outcomes_change_new_video_selection():
    rows = [candidate('low', source='low', regime='low'), candidate('high', source='high', regime='high', ordinal=1)]
    result = decide(rows, [sample('past-low', 1, 'low', 'low')] * 2 + [sample('past-high', 99, 'high', 'high')] * 2)
    assert result['candidate_id'] == 'high'
    assert all(row['scope'] == 'source' for row in result['scores'])


@pytest.mark.parametrize('difference', ['regime', 'campaign'])
def test_incompatible_source_regime_not_pooled(difference):
    row = candidate('new')
    data = sample('prior', 100)
    data['regime_digest' if difference == 'regime' else 'campaign_id'] = 'different'
    assert decide([row], [data] * 2)['reason'] == 'cold_start'


def test_probability_matches_exact_mixture_and_duplicate_video_collapses():
    obj = objective()
    rows = [candidate('a', video='a'), candidate('a-duplicate', video='a', source='other'), candidate('b', video='b', ordinal=1)]
    result = choose(rows, [obj], {obj['id']: [sample('b', 100)] * 2}, minimum_samples=2,
                    baseline_share=.1, exploration=.2, seed=20)
    assert set(result['distribution']) == {'a', 'b'}
    assert from_rational(result['distribution']['a']) == Fraction(3, 20)
    assert from_rational(result['distribution']['b']) == Fraction(17, 20)
    assert sum(map(from_rational, result['distribution'].values())) == 1
    assert result['propensity'] == result['distribution'][result['candidate_id']]


def test_real_branch_draws_include_all_three_branches():
    obj = objective()
    branches = {choose([candidate('a'), candidate('b')], [obj], {}, minimum_samples=2,
                baseline_share=.1, exploration=.2, seed=seed)['branch'] for seed in range(100)}
    assert branches == {'baseline', 'exploration', 'exploitation'}


def test_sparse_revenue_explicit_engagement_proxy():
    revenue = objective('creator_net', 'received_cents', 1209600, 86400, 'USD')
    engagement = objective()
    result = choose([candidate('a'), candidate('b')], [revenue, engagement],
        {revenue['id']: [sample('a', '9999')], engagement['id']: [sample('b', 100)] * 2},
        minimum_samples=2, baseline_share=0, exploration=0, seed=1)
    assert result['candidate_id'] == 'b'
    assert result['objective'] == engagement and result['reason'] == 'engagement_proxy'
    assert result['skipped_objectives'] == [{'objective_id': revenue['id'], 'known_samples': 1}]


def test_known_revenue_precedes_engagement_no_score_mix():
    revenue = objective('creator_net', 'received_cents', 1209600, 86400, 'USD')
    engagement = objective()
    result = choose([candidate('a', source='a', regime='a'), candidate('b', source='b', regime='b')], [revenue, engagement],
        {revenue['id']: [sample('a', '1', 'a', 'a')] * 2, engagement['id']: [sample('b', 99999, 'b', 'b')] * 2},
        minimum_samples=2, baseline_share=0, exploration=0, seed=1)
    assert result['candidate_id'] == 'a' and result['objective'] == revenue


def test_cold_start_unknown_has_no_fake_score():
    result = decide([candidate('a')], [])
    assert result['reason'] == 'cold_start' and result['scores'] == []


def test_actual_day10_earnings_excluded_day7_can_enter_later_window():
    seven = objective('creator_net', 'received_cents', 604800, 86400, 'USD')
    fourteen = objective('creator_net', 'received_cents', 1209600, 4 * 86400, 'USD')
    rows = [observation(1, 10 * 86400, '500', 'creator_net')]
    assert cohort([publication()], rows, seven) == []
    result = cohort([publication()], rows, fourteen)
    assert result[0]['value'] == '500' and result[0]['age_seconds'] == 10 * 86400
    # Actual deployment tolerance1day needs a real day13-15 observation.
    fourteen['tolerance_seconds'] = 86400
    assert cohort([publication()], rows, fourteen) == []
    rows.append(observation(2, 14 * 86400, '500', 'creator_net'))
    assert cohort([publication()], rows, fourteen)[0]['age_seconds'] == 14 * 86400


def test_exact_huge_signed_cent_values_and_reversal():
    obj = objective('creator_net', 'received_cents', 1209600, 86400, 'USD')
    huge = '769221300334944359700'
    rows = [observation(1, 1209600, huge, 'creator_net')]
    assert cohort([publication()], rows, obj)[0]['value'] == huge
    rows.append(observation(2, 1209600, '-5', 'creator_net', observed=1209601))
    assert cohort([publication()], rows, obj)[0]['value'] == '-5'


def test_new_same_measurement_unknown_invalidates_known():
    rows = [observation(1, 86400, 100), observation(2, 86400, None, observed=86401)]
    assert cohort([publication()], rows, objective()) == []


def test_cached_incomplete_scan_never_becomes_new_measurement():
    obj = objective('creator_net', 'received_cents', 1209600, 86400, 'USD')
    rows = [observation(1, 1209600, '5', 'creator_net'),
            observation(2, 1209600, None, 'creator_net', observed=1209601, fresh=False, complete=False)]
    assert cohort([publication()], rows, obj)[0]['value'] == '5'


def test_currency_and_horizon_do_not_pool():
    obj = objective('creator_net', 'received_cents', 1209600, 86400, 'USD')
    rows = [observation(1, 1209600, '500', 'creator_net', currency='EUR'), observation(2, 604800, '900', 'creator_net')]
    assert cohort([publication()], rows, obj) == []


def test_objective_rename_preserves_descriptor_but_horizon_changes_it():
    obj = objective()
    other = {**obj, 'id': 'new-name'}
    assert objective_key(obj) == objective_key(other)
    other['horizon_seconds'] = 604800
    assert objective_key(obj) != objective_key(other)


@pytest.mark.parametrize('baseline,current,expected', [(['100'], ['70'], True), (['100'], ['90'], False),
    (['-100'], ['-130'], True), (['-100'], ['-110'], False), (['0'], ['-1'], True), ([], ['1'], False)])
def test_exact_regression_with_negative_or_zero_money(baseline, current, expected):
    assert regressed(baseline, current, .2) is expected


def test_policy_validates_currency_horizons_mixture_and_descriptors(config):
    policy = {'objectives': [objective()], 'baseline_share': .1}
    assert validate_policy(policy, config['learning']) == policy
    invalid = []
    value = copy.deepcopy(policy); value['objectives'][0]['currency'] = 'USD'; invalid.append(value)
    value = copy.deepcopy(policy); value['objectives'][0]['horizon_seconds'] = 800; invalid.append(value)
    value = copy.deepcopy(policy); value['baseline_share'] = 1; invalid.append(value)
    value = copy.deepcopy(policy); value['objectives'].append({**objective(), 'id': 'alias'}); invalid.append(value)
    for value in invalid:
        with pytest.raises(SafetyError):
            validate_policy(value, config['learning'])
