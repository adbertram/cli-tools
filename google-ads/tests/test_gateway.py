"""Offline contract tests use official descriptors and fake transports, never Ads accounts."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from google.protobuf import json_format, empty_pb2
from google.longrunning import operations_pb2
from google.ads.googleads.v25.services.types.google_ads_service import SearchGoogleAdsResponse, SearchGoogleAdsStreamResponse
from google.ads.googleads.v25.services.types.campaign_service import MutateCampaignsResponse
from google.rpc.status_pb2 import Status
from typer.testing import CliRunner
from cli_tools_shared.exceptions import ClientError

from google_ads_cli.client import GoogleAdsClient, READ_RETRY
from google_ads_cli.main import app
from google_ads_cli.schema import catalog, coverage, method_info, protobuf_class, request_message, to_dict

RPCS = [(service, method, info) for service, entry in catalog().items() for method, info in entry['methods'].items()]


@pytest.mark.parametrize('service,method,info', RPCS, ids=[f'{s}.{m}' for s,m,_ in RPCS])
def test_every_discovered_rpc_reachable_with_strict_request_and_response(service, method, info):
    request = request_message(service, method, {})
    assert to_dict(request) == {}
    response = protobuf_class(info['response_class'])()
    if info['paged'] and not info.get('operations'):
        response = SimpleNamespace(_response=response, pages=[response])
    elif info['stream']:
        response = iter([response])
    rpc = Mock(return_value=response)
    transport = SimpleNamespace(operations_client=SimpleNamespace(**{'_'+method: rpc})) if info.get('operations') else None
    service_client = SimpleNamespace(transport=transport, **{method: rpc})
    sdk = Mock()
    sdk.get_service.return_value = service_client
    result = GoogleAdsClient(sdk=sdk).call(service, method, {}, yes=True)
    assert (list(result) if info['stream'] else result) == ([{}] if info['stream'] else {})
    kwargs = rpc.call_args.kwargs
    assert kwargs['timeout'] == 60.0
    assert kwargs['retry'] is (READ_RETRY if info['read_only'] else None)


def test_coverage_has_all_generated_public_rpc_methods():
    manifest = coverage()
    assert manifest['service_count'] == 111
    assert manifest['rpc_count'] == 174
    # Descriptors, not a hand-written short command list, define the reachable API.
    assert manifest['rpcs'] == json.loads(__import__('pathlib').Path(__file__).parents[1].joinpath('docs/coverage.json').read_text())['rpcs']
    assert {'search','search_stream','mutate'} <= set(catalog()['GoogleAdsService']['methods'])
    assert 'upload_click_conversions' in catalog()['ConversionUploadService']['methods']
    assert 'add_batch_job_operations' in catalog()['BatchJobService']['methods']


def test_offline_preview_never_constructs_authenticated_sdk(monkeypatch):
    client = GoogleAdsClient()
    monkeypatch.setattr(client, '_client', Mock(side_effect=AssertionError('must not access credentials')))
    result = client.call('CampaignService','mutate_campaigns',{'customer_id':'123'},dry_run=True)
    assert result['request']['customer_id'] == '123'
    client._client.assert_not_called()


def test_mutation_refused_without_explicit_yes_and_invalid_validation_refused():
    client = GoogleAdsClient()
    with pytest.raises(ClientError, match='Refusing to change'):
        client.call('CampaignService','mutate_campaigns',{'customer_id':'123'})
    with pytest.raises(ClientError, match='does not support'):
        client.call('CustomerService','list_accessible_customers',{},validate_only=True)


def test_validate_only_rpc_uses_validation_without_mutation():
    rpc = Mock(return_value=MutateCampaignsResponse())
    sdk = Mock(); sdk.get_service.return_value = SimpleNamespace(mutate_campaigns=rpc)
    GoogleAdsClient(sdk=sdk).call('CampaignService','mutate_campaigns',{'customer_id':'123'},validate_only=True)
    assert rpc.call_args.kwargs['request'].validate_only is True
    assert rpc.call_args.kwargs['retry'] is READ_RETRY


@pytest.mark.parametrize('body', [{'unknown_field':1}, {'customer_id':'1','operations':[{'create':{'status':'NONEXISTENT'}}]}, ['invalid']])
def test_invalid_proto_json_rejected_before_api_access(body):
    with pytest.raises(ClientError):
        GoogleAdsClient().call('CampaignService','mutate_campaigns',body,dry_run=True)


def test_complete_pages_preserve_envelope_fields_and_large_ints():
    first = SearchGoogleAdsResponse(next_page_token='second', total_results_count=9007199254740993)
    second = SearchGoogleAdsResponse(field_mask='customer.id')
    rpc = Mock(return_value=SimpleNamespace(_response=first,pages=iter([first,second])))
    sdk = Mock(); sdk.get_service.return_value = SimpleNamespace(search=rpc)
    client = GoogleAdsClient(sdk=sdk)
    assert client.call('GoogleAdsService','search',{},all_pages=True) == {'pages': [to_dict(first),to_dict(second)]}
    assert to_dict(first)['total_results_count'] == '9007199254740993'


def test_stream_is_lazy_and_preserves_whole_batches():
    batches = [SearchGoogleAdsStreamResponse(request_id='first'),SearchGoogleAdsStreamResponse(request_id='second')]
    sdk = Mock(); sdk.get_service.return_value = SimpleNamespace(search_stream=Mock(return_value=iter(batches)))
    result = GoogleAdsClient(sdk=sdk).call('GoogleAdsService','search_stream',{})
    assert list(result) == [{'request_id':'first'},{'request_id':'second'}]


def test_partial_failure_preserves_whole_response_and_fails_explicitly():
    response = MutateCampaignsResponse(partial_failure_error=Status(code=3,message='invalid item'))
    with pytest.raises(ClientError) as exc:
        GoogleAdsClient._checked_dict(response)
    result = json.loads(str(exc.value))
    assert result['response']['partial_failure_error'] == {'code':3,'message':'invalid item'}


def test_void_and_long_running_operation_serialization():
    assert to_dict(None) == {}
    assert to_dict(operations_pb2.Operation(name='customers/123/operations/456',done=False)) == {'name':'customers/123/operations/456'}


def test_cli_stdin_request_preview(monkeypatch):
    result = CliRunner().invoke(app,['api','call','CampaignService','mutate_campaigns','--body-file','-','--dry-run'],input='{"customer_id":"123"}')
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)['request']['customer_id'] == '123'


def test_cli_stream_outputs_one_json_document_per_batch(monkeypatch):
    fake = Mock(); fake.call.return_value = iter([{'request_id':'one'},{'request_id':'two'}])
    monkeypatch.setattr('google_ads_cli.commands.api.get_client',lambda version='v25':fake)
    result = CliRunner().invoke(app,['api','call','GoogleAdsService','search_stream','--body','{"customer_id":"123","query":"SELECT customer.id FROM customer"}'])
    assert result.exit_code == 0
    assert [json.loads(line) for line in result.stdout.splitlines()] == [{'request_id':'one'},{'request_id':'two'}]


def test_explicit_client_import_never_displays_or_copies_tokens(monkeypatch):
    import google_ads_cli.commands.auth as auth
    secrets = {'chosen-id':'private-id','chosen-secret':'private-secret'}
    monkeypatch.setattr(auth,'read_cli_tool_secret',secrets.get)
    config = Mock(); monkeypatch.setattr(auth,'get_config',lambda profile:config)
    result = CliRunner().invoke(app,['auth','client','import','--client-id-secret','chosen-id','--client-secret-secret','chosen-secret'])
    assert result.exit_code == 0, result.output
    config.save_credentials.assert_called_once_with(CLIENT_ID='private-id',CLIENT_SECRET='private-secret')
    config.clear_ephemeral.assert_called_once()
    assert 'private-id' not in result.output and 'private-secret' not in result.output


@pytest.mark.parametrize('timeout', ['nan','inf','-inf'])
def test_cli_nonfinite_timeout_rejected_before_offline_preview(timeout):
    result = CliRunner().invoke(app,['api','call','CustomerService','list_accessible_customers','--body','{}','--timeout',timeout,'--dry-run'])
    assert result.exit_code != 0
    assert result.stdout == ''
    assert ('finite' in result.stderr or 'range' in result.stderr), result.output


@pytest.mark.parametrize('timeout', [float('nan'),float('inf'),-float('inf'),0,-1])
def test_nonpositive_or_nonfinite_timeout_never_constructs_client(timeout,monkeypatch):
    client = GoogleAdsClient()
    monkeypatch.setattr(client,'_client',Mock(side_effect=AssertionError('must not access API')))
    with pytest.raises(ClientError,match='finite and greater than zero'):
        client.call('CustomerService','list_accessible_customers',{},timeout=timeout,dry_run=True)
    client._client.assert_not_called()


def test_reporting_sdk_version_uses_installed_metadata():
    from importlib.metadata import version
    from google_ads_cli.schema import SDK_VERSION
    assert SDK_VERSION == version('google-ads')


def test_query_command_uses_same_lazy_full_batch_output(monkeypatch,capsys):
    from google_ads_cli.commands.query import search
    fake = Mock(); fake.call.return_value = iter([{'request_id':'one','results':[]},{'request_id':'two'}])
    monkeypatch.setattr('google_ads_cli.commands.query.get_client',lambda version='v25':fake)
    search(query='SELECT customer.id FROM customer',customer_id='123',stream=True,all_pages=False,page_token=None,api_version='v25',timeout=60.0)
    assert [json.loads(line) for line in capsys.readouterr().out.splitlines()] == [{'request_id':'one','results':[]},{'request_id':'two'}]


@pytest.mark.parametrize('initial_token,tokens,expected_calls', [
    ('',['same','same'],2),
    ('same',['same'],1),
    ('',['first','second','first'],3),
])
def test_real_generated_sdk_pager_stops_before_repeated_token_fetch(initial_token,tokens,expected_calls):
    from google.auth.credentials import AnonymousCredentials
    from google.ads.googleads.v25.services.services.google_ads_service import GoogleAdsServiceClient
    generated = GoogleAdsServiceClient(credentials=AnonymousCredentials())
    sent = []
    def transport_rpc(request,**kwargs):
        sent.append(request.page_token)
        if len(sent)>expected_calls:
            raise AssertionError('Pager fetched repeated token after cycle should have stopped')
        return SearchGoogleAdsResponse(next_page_token=tokens[len(sent)-1],query_resource_consumption=len(sent))
    transport = generated.transport
    transport._wrapped_methods[transport.search] = transport_rpc
    client = GoogleAdsClient(sdk=SimpleNamespace(get_service=lambda *a,**kw:generated))
    with pytest.raises(ClientError,match='repeated page token'):
        client.call('GoogleAdsService','search',{'customer_id':'123','query':'SELECT campaign.id FROM campaign','page_token':initial_token},all_pages=True)
    assert len(sent) == expected_calls
    assert len(sent) == len(set(sent))
    transport.close()


def test_real_generated_sdk_pager_preserves_all_envelope_fields():
    from google.auth.credentials import AnonymousCredentials
    from google.ads.googleads.v25.services.services.google_ads_service import GoogleAdsServiceClient
    generated = GoogleAdsServiceClient(credentials=AnonymousCredentials())
    responses = [SearchGoogleAdsResponse(next_page_token='next',query_resource_consumption=13),SearchGoogleAdsResponse(total_results_count=2,query_resource_consumption=17)]
    sent = []
    def transport_rpc(request,**kwargs):
        sent.append(request.page_token)
        return responses[len(sent)-1]
    generated.transport._wrapped_methods[generated.transport.search] = transport_rpc
    client = GoogleAdsClient(sdk=SimpleNamespace(get_service=lambda *a,**kw:generated))
    assert client.call('GoogleAdsService','search',{'customer_id':'123','query':'SELECT campaign.id FROM campaign'},all_pages=True) == {'pages':[to_dict(value) for value in responses]}
    assert sent == ['','next']
    generated.transport.close()


@pytest.mark.parametrize('value',['NaN','Infinity','-Infinity'])
def test_cli_rejects_bare_nonfinite_json_numbers_in_double_fields(value):
    body = '{"customer_id":"123","conversions":[{"conversion_value":'+value+'}]}'
    result = CliRunner().invoke(app,['api','call','ConversionUploadService','upload_click_conversions','--body',body,'--dry-run'])
    assert result.exit_code != 0
    assert result.stdout == ''
    assert 'not valid JSON' in result.stderr


@pytest.mark.parametrize('value',['NaN','Infinity','-Infinity'])
def test_cli_accepts_quoted_protobuf_special_float_values(value):
    body = json.dumps({'customer_id':'123','conversions':[{'conversion_value':value}]})
    result = CliRunner().invoke(app,['api','call','ConversionUploadService','upload_click_conversions','--body',body,'--dry-run'])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)['request']['conversions'][0]['conversion_value'] == value
