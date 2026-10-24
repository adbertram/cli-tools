"""Provider analytics retain reported values and query each invocation."""
from types import SimpleNamespace
from unittest.mock import Mock
from datetime import datetime
import pytest
from cli_tools_shared.exceptions import ClientError
from whop_cli.client import WhopClient


def client():
    return WhopClient(SimpleNamespace(get_active_profile_name=lambda: 'rewards'), Mock())


def test_live_pagination_and_requery():
    c = client()
    def page(args):
        request = args[1][0]
        index = 2 if 'cursor' in request else 1
        return {'data': [{'id': str(index), 'socialMediaPost': {'views': str(index), 'shares': '0'}}],
                'nextCursor': 'next' if index == 1 else None}
    c._action = Mock(side_effect=lambda *args: page(args))
    first = c.analytics(2, 'pending')
    second = c.analytics(2, 'pending')
    assert c._action.call_count == 4
    assert [r['views'] for r in first] == ['1', '2']
    assert first[0]['shares'] == '0' and first[0]['likes'] is None
    assert first[0]['native']['socialMediaPost']['views'] == '1'
    assert first[0]['metrics_updated_at'] is None
    assert datetime.fromisoformat(second[0]['observed_at']).tzinfo is not None
    assert first[0]['profile'] == 'rewards'


def test_all_statuses_share_total_bound():
    c = client()
    c.submissions = Mock(side_effect=[[{'id':'a'}], [{'id':'b'}]])
    assert [r['id'] for r in c.analytics(2)] == ['a','b']
    assert c.submissions.call_args_list[0].args == (2, 'pending', False)
    assert c.submissions.call_args_list[1].args == (1, 'approved', False)


def test_get_retains_all_native_metrics():
    c = client()
    row = {'id':'one','campaignId':'campaign','socialMediaPost':{'views':'0','updatedAt':'timestamp','newMetric':4},'cpmTerms':{'rateCents':'50'}}
    c.submission = Mock(return_value=row)
    result = c.analytics_submission('one')
    assert result['native'] == row and result['provider_updated_at'] == 'timestamp'
    assert result['views'] == '0' and result['comments'] is None


@pytest.mark.parametrize('post',[[], 'bad', 1])
def test_bad_metrics_are_explicit_failure(post):
    with pytest.raises(ClientError, match='invalid_clip_analytics'):
        client()._analytics_record({'id':'one','socialMediaPost':post})


def test_retainer_uses_provider_contract():
    c = client()
    c.submissions = Mock(return_value=[{'id':'retainer'}])
    assert c.analytics(2, 'pending', True)[0]['views'] is None
    c.submissions.assert_called_once_with(2, 'pending', True)
