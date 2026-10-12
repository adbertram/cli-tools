"""Watch analytics contracts validated against the 2026-10-12 Studio response."""
import json
from pathlib import Path

import pytest

from tiktok_cli.studio import StudioContractError
from tiktok_cli.studio_watch import normalize, read

ID = '7695809227801087246'
OWNER = {'account_id': '7692213003349443597', 'username': 'ata_clipper', 'profile': 'clipper'}


def payload():
    return json.loads((Path(__file__).parent / 'fixtures/studio_watch.json').read_text())


def test_live_observed_units_and_secret_allowlist():
    result = normalize(payload(), OWNER, ID)
    metrics = result['metrics']
    assert metrics['average_watch_time_seconds'] == 3.33
    assert metrics['total_watch_time_seconds'] == 340
    assert metrics['completion_rate'] == .0098
    assert metrics['retention'][1] == {'time_seconds': 1, 'retention_rate': .57}
    assert len(metrics['retention']) == 57
    assert result['watch_metrics_error'] is None
    assert 'video_info' not in result and 'log_pb' not in result


@pytest.mark.parametrize('path,value', [('aweme_id', '1'), ('author', {'uid': '1'}), ('aweme_id', int(ID))])
def test_wrong_post_or_owner_fails(path, value):
    data = payload(); data['video_info'][path] = value
    with pytest.raises(StudioContractError): normalize(data, OWNER, ID)


def test_processing_is_unknown_not_zero():
    data = payload(); del data['video_retention_rate_realtime']
    data['video_per_duration_realtime']['value'] = {'status': 2, 'value': 0}
    result = normalize(data, OWNER, ID)
    assert result['metrics']['retention'] is None
    assert result['metrics']['average_watch_time_seconds'] is None
    assert result['metrics']['total_watch_time_seconds'] == 340
    assert result['watch_metrics_error']


@pytest.mark.parametrize('value', [True, -1, float('nan'), float('inf'), '3.33', 10**1000])
def test_malformed_scalar_is_unknown(value):
    data = payload(); data['video_per_duration_realtime']['value']['value'] = value
    assert normalize(data, OWNER, ID)['metrics']['average_watch_time_seconds'] is None


@pytest.mark.parametrize('mutation', ['duplicate_time', 'negative_time', 'numeric_time', 'rate_above_one', 'no_points', 'delayed'])
def test_curve_boundaries(mutation):
    data = payload(); wrapper = data['video_retention_rate_realtime']; points = wrapper['value']['list']
    if mutation == 'duplicate_time': points[1]['timestamp'] = '0'
    if mutation == 'negative_time': points[1]['timestamp'] = '-1000'
    if mutation == 'numeric_time': points[1]['timestamp'] = 1000
    if mutation == 'rate_above_one': points[1]['value'] = 1.1
    if mutation == 'no_points': wrapper['value']['list'] = []
    if mutation == 'delayed': wrapper['is_data_delay'] = True
    assert normalize(data, OWNER, ID)['metrics']['retention'] is None


def test_rise_in_retention_is_preserved():
    data = payload(); data['video_retention_rate_realtime']['value']['list'][2]['value'] = .6
    assert normalize(data, OWNER, ID)['metrics']['retention'][2]['retention_rate'] == .6


def test_owner_verified_before_and_after_one_bounded_read():
    class Client:
        count = 0
        def get_account(self, **kwargs): self.count += 1; return OWNER
        def _get_browser(self): return self
        def get_page(self, url): assert ID in url; return self
        def evaluate(self, js, query):
            assert 'AbortController' in js and '2097152' in js
            assert 'video_vv_history_7d' in query
            return {'status': 200, 'body': json.dumps(payload())}
    client = Client()
    assert read(client, OWNER['username'], ID, OWNER['account_id'])['id'] == ID
    assert client.count == 2


def test_invalid_id_fails_before_browser():
    with pytest.raises(StudioContractError): read(None, OWNER['username'], 'x', OWNER['account_id'])
