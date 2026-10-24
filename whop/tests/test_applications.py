"""Application contracts measured from live Content Rewards frontend assets."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from cli_tools_shared.exceptions import ClientError
from whop_cli.application_operations import application_form, apply_campaign, validate_answers

CID = 'campaign-1'
FORM = {'id': 'form-1', 'status': 'active', 'fields': [
    {'name': 'insights', 'label': 'Audience insights', 'type': 'input', 'required': True},
]}
ROW = {'id': 'application-1', 'campaignId': CID, 'status': 'pending'}


@pytest.fixture(autouse=True)
def profile(tmp_path):
    global TEST_PROFILE
    TEST_PROFILE = tmp_path.resolve() / 'profile'
    TEST_PROFILE.mkdir(mode=0o700)


def client():
    instance = Mock()
    instance.config = SimpleNamespace(get_profile_data_dir=lambda: TEST_PROFILE)
    instance.account.return_value = {'id': 'user_TEST'}
    instance.applications.side_effect = [
        {'applications': [], 'partialFailure': False},
        {'applications': [ROW], 'partialFailure': False},
    ]
    instance._rest.side_effect = [
        {'data': {'id': CID, 'requiresApplication': True, 'configuration': {'application': {'id': 'form-1'}}}},
        {'data': FORM},
    ]
    instance.linked_accounts.return_value = [{'id': 'social-1'}]
    instance._discover_action.return_value = 'a' * 40
    instance._location.return_value = ('https://example.apps.whop.com', '/c/exp_TEST')
    instance._action_document.return_value.evaluate.return_value = {
        'status': 200, 'text': '0:{"a":"$@1"}\n1:{"success":true,"data":{}}',
    }
    return instance


def apply(instance, **kwargs):
    return apply_campaign(instance, CID, answers={'insights': 'https://example.com/insights'},
                          social_account_ids=['social-1'], expected_account_id='user_TEST', confirm=True, **kwargs)


def test_form_uses_measured_native_routes():
    instance = client()
    assert application_form(instance, CID) == {'campaign_id': CID, 'application_id': 'form-1', 'form': FORM}
    assert instance._rest.call_args_list[1].args == ('/api/application/application-forms/form-1', {'campaignId': CID})


def test_apply_sends_once_then_returns_native_readback():
    instance = client()
    assert apply(instance) == {'status': 'applied', 'campaign_id': CID, 'application': ROW}
    assert instance._action_document.return_value.evaluate.call_count == 1
    payload = instance._action_document.return_value.evaluate.call_args.args[1]
    assert payload == {'path': '/c/exp_TEST/campaigns/' + CID, 'action': 'a' * 40, 'body': [{
        'applicationId': 'form-1', 'campaignId': CID,
        'response': {'insights': 'https://example.com/insights'}, 'socialAccountIds': ['social-1'],
    }]}


@pytest.mark.parametrize('status', ['pending', 'approved', 'rejected', 'withdrawn'])
def test_existing_never_resends(status):
    instance = client()
    row = {**ROW, 'status': status}
    instance.applications.side_effect = [{'applications': [row], 'partialFailure': False}]
    assert apply(instance)['status'] == 'existing'
    instance._action_document.assert_not_called()


def test_transport_failure_reads_back_without_retry():
    instance = client()
    instance._action_document.return_value.evaluate.side_effect = TimeoutError()
    assert apply(instance)['application'] == ROW
    assert instance._action_document.return_value.evaluate.call_count == 1


def test_missing_readback_is_unknown_never_success():
    instance = client()
    instance.applications.side_effect = [{'applications': [], 'partialFailure': False}] * 2
    with pytest.raises(ClientError, match='campaign_application_outcome_unknown'):
        apply(instance)
    assert instance._action_document.return_value.evaluate.call_count == 1


@pytest.mark.parametrize('payload', [
    {'applications': [], 'partialFailure': True},
    {'applications': [{'campaignId': CID, 'status': 'new-status'}], 'partialFailure': False},
    {'applications': [ROW, ROW], 'partialFailure': False},
])
def test_bad_existing_read_stops_before_send(payload):
    instance = client()
    instance.applications.side_effect = [payload]
    with pytest.raises(ClientError):
        apply(instance)
    instance._action_document.assert_not_called()


def test_actor_mismatch_stops_before_send():
    instance = client()
    instance.account.return_value = {'id': 'user_OTHER'}
    with pytest.raises(ClientError, match='actor_changed'):
        apply(instance)
    instance.applications.assert_not_called()


@pytest.mark.parametrize('answers', [{}, {'insights': ''}, {'insights': 2}, {'insights': 'x' * 256}, {'unknown': 'x'}])
def test_invalid_answers(answers):
    with pytest.raises(ClientError):
        validate_answers(FORM, answers)


@pytest.mark.parametrize('field,value', [
    ({'type': 'checkbox'}, True),
    ({'type': 'select', 'options': ['a', 'b']}, 'a'),
    ({'type': 'select', 'options': ['a', 'b'], 'multiple': True}, ['a', 'b']),
    ({'type': 'textarea', 'minLength': 3}, 'abc'),
    ({'type': 'input', 'format': 'url'}, 'https://example.com'),
])
def test_measured_field_types(field, value):
    validate_answers({'fields': [{'name': 'question', 'required': True, **field}]}, {'question': value})


def test_file_upload_fails_explicitly():
    with pytest.raises(ClientError, match='file_upload_unsupported'):
        validate_answers({'fields': [{'name': 'upload', 'required': True, 'type': 'file'}]}, {'upload': ['https://example.com/file']})


def test_uncertain_dispatch_blocks_later_invocations_even_when_readback_empty():
    instance = client()
    instance.applications.side_effect = [{'applications': [], 'partialFailure': False}] * 3
    with pytest.raises(ClientError, match='outcome_unknown'):
        apply(instance)
    with pytest.raises(ClientError, match='outcome_unknown'):
        apply(instance)
    assert instance._action_document.return_value.evaluate.call_count == 1


def test_existing_after_uncertain_dispatch_reconciles_without_second_send():
    instance = client()
    instance.applications.side_effect = [
        {'applications': [], 'partialFailure': False},
        {'applications': [], 'partialFailure': False},
        {'applications': [ROW], 'partialFailure': False},
    ]
    with pytest.raises(ClientError, match='outcome_unknown'):
        apply(instance)
    assert apply(instance)['status'] == 'existing'
    assert instance._action_document.return_value.evaluate.call_count == 1
