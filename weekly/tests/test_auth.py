import base64
import json
import sys
import types
import unittest
from unittest.mock import patch

stub = types.ModuleType('mitmproxy')
io = types.ModuleType('mitmproxy.io')
io.FlowReader = object
sys.modules.setdefault('mitmproxy', stub)
sys.modules.setdefault('mitmproxy.io', io)
from weekly_cli import capture, session
from cli_tools_shared.exceptions import ClientError


def jwt(uid='user', aud='weekly-6f36c'):
    payload = base64.urlsafe_b64encode(json.dumps({'sub': uid, 'aud': aud}).encode()).decode().rstrip('=')
    return 'header.' + payload + '.signature'


class Response:
    status_code = 200
    def __init__(self, body): self.body = body
    def get_text(self): return json.dumps(self.body)
    def json(self): return self.body


class Request:
    method = 'POST'
    headers = {'x-ios-bundle-identifier': 'test.bundle'}
    def __init__(self, url, body): self.url, self.body = url, body
    def get_text(self): return json.dumps(self.body)


def flows(uid='user'):
    def flow(url, req, res): return types.SimpleNamespace(request=Request(url, req), response=Response(res))
    return [flow('https://www.googleapis.com/identitytoolkit/v3/relyingparty/verifyAssertion?key=fake', {}, {'idToken': jwt(), 'localId': 'user', 'refreshToken': 'old'}), flow('https://securetoken.googleapis.com/v1/token?key=fake', {'refreshToken': 'old'}, {'id_token': jwt(uid), 'user_id': uid, 'refresh_token': 'new'})]


class CaptureTests(unittest.TestCase):
    def decode(self, items):
        with patch('weekly_cli.capture._flows', return_value=iter(items)):
            return capture.decode('unused')

    def test_import_binds_identity_and_project(self):
        self.assertEqual(self.decode(flows())['refresh_token'], 'new')
        with self.assertRaises(ValueError): self.decode(flows('other'))
        bad = flows(); bad[1].request.body['refreshToken'] = 'wrong'
        with self.assertRaises(ValueError): self.decode(bad)


class RenewalTests(unittest.TestCase):
    def test_success_and_identity_mismatch(self):
        data = {'api_key': 'fake', 'refresh_token': 'old', 'user_id': 'user', 'headers': {}}
        response = Response({'refresh_token':'new', 'id_token':jwt(), 'user_id':'user', 'expires_in':'3600'})
        with patch('weekly_cli.session.requests.Session') as cls:
            cls.return_value.post.return_value = response
            self.assertEqual(session.renew(data)['refresh_token'], 'new')
            response.body['id_token'] = jwt('other')
            with self.assertRaises(ClientError): session.renew(data)
        self.assertEqual(data['refresh_token'], 'old')

    def test_error_does_not_expose_response_or_overwrite_saved_session(self):
        data = {'api_key': 'fake', 'refresh_token': 'old', 'user_id': 'user', 'headers': {}}
        response = Response({'secret': 'do-not-print'}); response.status_code = 401
        with patch('weekly_cli.session.requests.Session') as cls, patch('weekly_cli.session.secret', return_value=data) as store:
            cls.return_value.post.return_value = response
            with self.assertRaises(ClientError) as exc: session.refresh(object())
            self.assertNotIn('do-not-print', str(exc.exception))
            self.assertEqual(store.call_count, 1)

class ExportTests(unittest.TestCase):
    def test_export_returns_all_columns_and_uses_captured_settings(self):
        from weekly_cli import transactions
        settings = {'rangekey':'all','timezoneoffset':'0','summaryonly':'false','excludefundcontributions':'true','excludeignoredtransactions':'true','excludereportexcludeditems':'true'}
        data = {'user_id':'synthetic-user','export_settings':settings}
        response = types.SimpleNamespace(status_code=200, headers={'content-type':'text/csv; charset=utf-8'}, content=b'Id,Title,Amount,Extra\nsynthetic-id,Example,1.00,preserved\n')
        with patch('weekly_cli.transactions.refresh',return_value='fake-token'), patch('weekly_cli.transactions.secret',return_value=data), patch('weekly_cli.transactions.requests.Session') as client:
            client.return_value.get.return_value=response
            rows=transactions.list_transactions(object(), 'all')
            self.assertEqual(rows, [{'Id':'synthetic-id','Title':'Example','Amount':'1.00','Extra':'preserved'}])
            request=client.return_value.get.call_args
            self.assertEqual(request.kwargs['headers']['requesteduserid'],'synthetic-user')
            self.assertFalse(request.kwargs['allow_redirects'])
            response.headers['content-type']='text/html'
            with self.assertRaises(ClientError): transactions.list_transactions(object())


class FirestoreTests(unittest.TestCase):
    def test_document_value_decoding_and_identity_bound_listing(self):
        from weekly_cli import firestore
        data = {'user_id':'synthetic-user'}
        name = 'projects/weekly-6f36c/databases/(default)/documents/users/synthetic-user/accounts/synthetic-account'
        response = Response({'documents':[{'name':name, 'fields':{'current_balance':{'doubleValue':12.5}, 'enabled':{'booleanValue':True}, 'nested':{'mapValue':{'fields':{'count':{'integerValue':'2'}}}}}}]})
        with patch('weekly_cli.firestore.refresh',return_value='fake-token'), patch('weekly_cli.firestore.secret',return_value=data), patch('weekly_cli.firestore.requests.Session') as client:
            client.return_value.get.return_value=response
            rows=firestore.list_documents(object(),'accounts')
            self.assertEqual(rows,[{'id':'synthetic-account','current_balance':12.5,'enabled':True,'nested':{'count':2}}])
            response.body['documents'][0]['name']=name.replace('synthetic-user','another-user')
            with self.assertRaises(ClientError): firestore.list_documents(object(),'accounts')
        with self.assertRaises(ClientError): firestore.list_documents(object(),'unverified')


class OutputContractTests(unittest.TestCase):
    def test_list_properties_and_limits_use_client_contract(self):
        from typer.testing import CliRunner
        from weekly_cli.main import app
        rows = [{'Id':'a', 'Title':'one', 'extra':1}, {'Id':'b', 'Title':'two', 'extra':2}]
        with patch('weekly_cli.main.get_config', return_value=object()), patch('weekly_cli.main.list_transactions', return_value=rows) as fetch:
            result = CliRunner().invoke(app, ['transactions','list','--properties','Id,Title'])
            self.assertEqual(result.exit_code, 0)
            self.assertEqual(json.loads(result.stdout), [{'Id':'a','Title':'one'}, {'Id':'b','Title':'two'}])
            self.assertIsNone(fetch.call_args.args[3])

    def test_explicit_csv_filter_and_limit_apply_before_output(self):
        from weekly_cli import transactions
        settings = {'rangekey':'all','timezoneoffset':'0','summaryonly':'false','excludefundcontributions':'true','excludeignoredtransactions':'true','excludereportexcludeditems':'true'}
        response = types.SimpleNamespace(status_code=200, headers={'content-type':'text/csv'}, content=b'Id,Title\na,one\nb,two\nc,two\n')
        with patch('weekly_cli.transactions.refresh',return_value='fake-token'), patch('weekly_cli.transactions.secret',return_value={'user_id':'synthetic','export_settings':settings}), patch('weekly_cli.transactions.requests.Session') as client:
            client.return_value.get.return_value=response
            self.assertEqual(transactions.list_transactions(object(), limit=1, filters=['Title:eq:two']), [{'Id':'b','Title':'two'}])


class SpendingTests(unittest.TestCase):
    def test_update_only_manual_fields_with_precondition(self):
        from weekly_cli import spending
        uid='synthetic-user'; ident='synthetic-id'
        original={'name':'projects/weekly-6f36c/databases/(default)/documents/users/'+uid+'/transactions/'+ident,'updateTime':'2026-01-01T00:00:00Z','fields':{'target':{'stringValue':'SAFE_TO_SPEND'},'isCash':{'booleanValue':True},'title':{'stringValue':'before'}}}
        updated={'name':original['name'],'fields':{'title':{'stringValue':'after'},'amount':{'doubleValue':0.02}}}
        http=unittest.mock.Mock(); http.patch.return_value=Response(updated)
        with patch('weekly_cli.spending.client_context',return_value=(http,'https://example.invalid',{}, {'user_id':uid})), patch('weekly_cli.spending.get_document',return_value=original):
            out=spending.update(object(),ident,'0.02','after')
            self.assertEqual(out['amount'],0.02)
            kwargs=http.patch.call_args.kwargs
            self.assertIn(('currentDocument.updateTime', original['updateTime']),kwargs['params'])
            self.assertEqual(set(kwargs['json']['fields']), {'amount','title'})
            original['fields']['__plaidTx']={'mapValue':{}}
            with self.assertRaises(ClientError): spending.update(object(),ident,'0.03')
        with self.assertRaises(ClientError): spending.amount_value('0.001')


class SpendingCreateTests(unittest.TestCase):
    def test_create_uses_observed_native_shape_and_requested_category(self):
        from weekly_cli import spending
        uid='synthetic-user'
        http=unittest.mock.Mock()
        http.post.return_value=Response({'name':'projects/weekly-6f36c/databases/(default)/documents/users/'+uid+'/transactions/synthetic-id','fields':{'amount':{'doubleValue':0.01}}})
        with patch('weekly_cli.spending.user_preferences',return_value={'timezone':'UTC'}), patch('weekly_cli.spending.client_context',return_value=(http,'https://example.invalid',{}, {'user_id':uid})), patch('weekly_cli.spending.list_documents',return_value=[{'id':'synthetic-tag','name':'Other'}]):
            item=spending.create(object(),'Synthetic test','0.01','2026-01-02','Other')
        fields=http.post.call_args.kwargs['json']['fields']
        self.assertEqual(set(fields),{'isCash','amount','title','target','date','tagId','color','created','createdTime'})
        self.assertEqual(fields['target']['stringValue'],'SAFE_TO_SPEND')
        self.assertEqual(fields['tagId']['stringValue'],'synthetic-tag')
        self.assertEqual(fields['color']['stringValue'],'warning')
        self.assertEqual(item['id'],'synthetic-id')


class ProfileLifecycleTests(unittest.TestCase):
    def test_profile_delete_cleans_only_after_success(self):
        from weekly_cli.main import with_secret_cleanup
        config=types.SimpleNamespace(env_file_path='synthetic-profile')
        with patch('weekly_cli.main.get_config',return_value=config), patch('weekly_cli.main.profile_secret_field_map',return_value={'SESSION_DATA':'synthetic-secret'}), patch('weekly_cli.main.delete_profile_secret') as remove:
            with_secret_cleanup(lambda name,force: None)(name='sample',force=True)
            remove.assert_called_once_with('synthetic-secret')
            remove.reset_mock()
            def failure(name,force): raise ClientError('not deleted')
            with self.assertRaises(ClientError): with_secret_cleanup(failure)(name='sample',force=True)
            remove.assert_not_called()


class ExportImportTests(unittest.TestCase):
    def test_selected_segment_and_traversal_rejection(self):
        import tempfile
        from pathlib import Path
        from weekly_cli import session
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root/'venv/bin').mkdir(parents=True)
            (root/'venv/bin/python').touch(); (root/'wireguard-1.flows').touch()
            result=types.SimpleNamespace(returncode=0,stdout=json.dumps({'user_id':'synthetic','export_settings':{'rangekey':'all'}}))
            with patch('weekly_cli.session.subprocess.run',return_value=result) as run, patch('weekly_cli.session.secret',return_value={'user_id':'synthetic'}) as store:
                session.import_export(object(),root,'wireguard-1.flows')
                self.assertEqual(Path(run.call_args.args[0][-1]), (root/'wireguard-1.flows').resolve())
                self.assertEqual(store.call_args_list[-1].args[1], 'set')
                with self.assertRaises(ClientError): session.import_export(object(),root,'../outside.flows')
                with self.assertRaises(ClientError): session.import_export(object(),root,'missing.flows')


class ReimportTests(unittest.TestCase):
    def test_same_user_retains_export_settings_only(self):
        import tempfile
        from pathlib import Path
        from weekly_cli import session
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'venv/bin').mkdir(parents=True);(root/'venv/bin/python').touch();(root/'app.flows').touch()
            config=types.SimpleNamespace(env_file_path='synthetic',save_credentials=unittest.mock.Mock())
            result=types.SimpleNamespace(returncode=0,stdout=json.dumps({'user_id':'same'}))
            with patch('weekly_cli.session.subprocess.run',return_value=result), patch('weekly_cli.session.profile_secret_field_map',return_value={'SESSION_DATA':'synthetic'}), patch('weekly_cli.session.renew',side_effect=lambda x:x), patch('weekly_cli.session.secret',return_value={'user_id':'same','export_settings':{'rangekey':'all'}}) as store:
                session.import_capture(config,root)
                self.assertIn('export_settings',store.call_args.args[2])
                result.stdout=json.dumps({'user_id':'different'})
                session.import_capture(config,root)
                self.assertNotIn('export_settings',store.call_args.args[2])


class MalformedServiceTests(unittest.TestCase):
    def test_csv_truncated_row_rejected(self):
        from weekly_cli import transactions
        settings = {'rangekey':'all','timezoneoffset':'0','summaryonly':'false','excludefundcontributions':'true','excludeignoredtransactions':'true','excludereportexcludeditems':'true'}
        response = types.SimpleNamespace(status_code=200, headers={'content-type':'text/csv'}, content=b'Id,Title,Amount\na,Example\n')
        with patch('weekly_cli.transactions.refresh',return_value='fake'), patch('weekly_cli.transactions.secret',return_value={'user_id':'u','export_settings':settings}), patch('weekly_cli.transactions.requests.Session') as client:
            client.return_value.get.return_value=response
            with self.assertRaises(ClientError): transactions.list_transactions(object())

    def test_firestore_pagination_cycle_rejected(self):
        from weekly_cli import firestore
        pages=[Response({'nextPageToken':'a'}),Response({'nextPageToken':'b'}),Response({'nextPageToken':'a'})]
        with patch('weekly_cli.firestore.refresh',return_value='fake'), patch('weekly_cli.firestore.secret',return_value={'user_id':'u'}), patch('weekly_cli.firestore.requests.Session') as client:
            client.return_value.get.side_effect=pages
            with self.assertRaises(ClientError): firestore.list_documents(object(),'accounts')
            self.assertEqual(client.return_value.get.call_count,3)


class ConsolidationTests(unittest.TestCase):
    def test_shared_render_keeps_projection_and_single_shape(self):
        from weekly_cli.main import render_rows
        rows=[{'id':'one','nested':{'value':4},'extra':'preserved'}]
        with patch('weekly_cli.main.print_json') as output:
            render_rows(rows,'id,nested.value',False,single=True)
            output.assert_called_once_with({'id':'one','nested.value':4})
        with patch('weekly_cli.main.print_json') as output:
            render_rows(rows,None,False)
            output.assert_called_once_with(rows)
        with patch('weekly_cli.main.print_table') as output:
            render_rows(rows,'nested.value,id',True,single=True)
            self.assertEqual(output.call_args.args[1], ['nested.value','id'])

    def test_decoder_failure_is_sanitized(self):
        from weekly_cli.session import decode_capture
        failure=types.SimpleNamespace(returncode=1,stdout='',stderr='sensitive capture data')
        with patch('weekly_cli.session.subprocess.run',return_value=failure) as run:
            with self.assertRaises(ClientError) as err:
                decode_capture('/synthetic/python','/synthetic/file','safe message',mode='export')
            self.assertEqual(str(err.exception),'safe message')
            self.assertEqual(run.call_args.kwargs['timeout'],60)


if __name__ == '__main__':
    unittest.main()
