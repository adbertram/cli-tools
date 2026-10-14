"""Native clip metrics, owner binding, pagination and freshness."""
from types import SimpleNamespace
from unittest.mock import Mock
from datetime import datetime
import pytest
from cli_tools_shared.exceptions import ClientError
from vyro_cli.client import VyroClient


def client():
    return VyroClient(SimpleNamespace(get_active_profile_name=lambda: 'adam'), Mock())


def test_native_metrics_pagination_requery_and_unknowns():
    c = client()
    def page(path):
        index = 2 if 'page=2' in path else 1
        return {'data':[{'id':str(index),'metrics':{'totalViews':index,'totalLikes':0,'lastMetricsUpdatedAt':'provider-time','extraMetric':9},'earnings':{'totalEarnings':0,'cpm':2}}],
                'meta':{'page':{'next':2 if index == 1 else None}}}
    c._get = Mock(side_effect=page)
    first = c.analytics(limit=2)
    second = c.analytics(limit=2)
    assert c._get.call_count == 4
    assert [r['views'] for r in first] == [1,2]
    assert first[0]['likes'] == 0 and first[0]['comments'] is None and first[0]['shares'] is None
    assert first[0]['native']['metrics']['extraMetric'] == 9
    assert first[0]['earnings']['totalEarnings'] == 0
    assert first[0]['metrics_updated_at'] == 'provider-time'
    assert datetime.fromisoformat(second[0]['observed_at']).tzinfo is not None


def test_detail_is_owned():
    c = client()
    c.account = Mock(return_value={'id':'actor'})
    c.submission = Mock(return_value={'id':'one','owner':{'id':'other'},'metrics':{'totalViews':1}})
    with pytest.raises(ClientError, match='owner_mismatch'):
        c.analytics_submission('one')
    c.submission.return_value['owner']['id'] = 'actor'
    assert c.analytics_submission('one')['views'] == 1


@pytest.mark.parametrize('metrics',[[], 'bad', 1])
def test_bad_metrics_are_explicit_failure(metrics):
    with pytest.raises(ClientError, match='invalid_clip_analytics'):
        client()._analytics_record({'id':'one','metrics':metrics})
