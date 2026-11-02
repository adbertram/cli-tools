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


class CategoryUpdateTests(unittest.TestCase):
    def setUp(self):
        from weekly_cli import spending
        self.spending=spending
        self.original={'name':'projects/weekly-6f36c/databases/(default)/documents/users/u/transactions/t','updateTime':'2026-01-01T00:00:00Z','fields':{'target':{'stringValue':'SAFE_TO_SPEND'},'__plaidTx':{'mapValue':{}},'amount':{'doubleValue':5},'title':{'stringValue':'synthetic'},'color':{'stringValue':'warning'},'tagId':{'stringValue':'old'}}}
        self.http=unittest.mock.Mock()
        self.context=patch('weekly_cli.spending.client_context',return_value=(self.http,'https://example.invalid',{}, {'user_id':'u'}))
        self.get=patch('weekly_cli.spending.get_document',return_value=self.original)
        self.tags=patch('weekly_cli.spending.list_documents',return_value=[{'id':'new','name':'Other'}])
        self.context.start();self.get.start();self.tags_mock=self.tags.start()
        self.addCleanup(self.context.stop);self.addCleanup(self.get.stop);self.addCleanup(self.tags.stop)
        self.http.patch.return_value=Response({'name':self.original['name'],'fields':{**self.original['fields'],'tagId':{'stringValue':'new'}}})

    def test_bank_category_only_patches_tag_and_precondition(self):
        out=self.spending.update(object(),'t',category='other')
        self.assertEqual(out['tagId'],'new')
        kw=self.http.patch.call_args.kwargs
        self.assertEqual(kw['json'],{'fields':{'tagId':{'stringValue':'new'}}})
        self.assertEqual(kw['params'],[('currentDocument.updateTime',self.original['updateTime']),('updateMask.fieldPaths','tagId')])
        self.assertEqual(out['amount'],5)
        self.assertEqual(out['color'],'warning')

    def test_manual_category_only_succeeds(self):
        del self.original['fields']['__plaidTx']
        self.original['fields']['isCash']={'booleanValue':True}
        self.spending.update(object(),'t',category='Other')
        self.http.patch.assert_called_once()

    def test_bank_combined_amount_or_title_rejected_before_patch(self):
        for kwargs in ({'amount':'0.01','category':'Other'}, {'title':'changed','category':'Other'}):
            with self.assertRaises(ClientError): self.spending.update(object(),'t',**kwargs)
        self.http.patch.assert_not_called()
        self.tags_mock.assert_not_called()

    def test_unknown_ambiguous_wrong_target_and_transfer_never_patch(self):
        for tags in ([],[{'id':'a','name':'Other'},{'id':'b','name':'OTHER'}]):
            self.tags_mock.return_value=tags
            with self.assertRaises(ClientError): self.spending.update(object(),'t',category='Other')
        self.original['fields']['target']={'stringValue':'FUND'}
        with self.assertRaises(ClientError): self.spending.update(object(),'t',category='Other')
        self.original['fields']['target']={'stringValue':'SAFE_TO_SPEND'}
        self.original['fields']['transferDirection']={'stringValue':'out'}
        with self.assertRaises(ClientError): self.spending.update(object(),'t',category='Other')
        self.http.patch.assert_not_called()

    def test_stale_precondition_failure_is_surfaced(self):
        self.http.patch.return_value.status_code=412
        with self.assertRaises(ClientError): self.spending.update(object(),'t',category='Other')
        self.http.patch.assert_called_once()

class SplitTests(unittest.TestCase):
    def setUp(self):
        from weekly_cli import spending
        self.spending = spending
        self.root = 'projects/weekly-6f36c/databases/(default)/documents/users/u/transactions/'
        self.fields = {'target':{'stringValue':'SAFE_TO_SPEND'}, 'amount':{'doubleValue':0.3}, 'title':{'stringValue':'Synthetic'}, 'date':{'stringValue':'2000-01-02'}, 'color':{'stringValue':'warning'}, '__plaidTx':{'mapValue':{'fields':{'id':{'stringValue':'synthetic-bank'},'extra':{'stringValue':'preserved'}}}}, 'unknown':{'stringValue':'preserved'}}
        self.original = {'name':self.root+'source','updateTime':'2026-01-01T00:00:00Z','fields':self.fields}
        self.http=unittest.mock.Mock()
        self.http.get.return_value=Response(self.original)
        self.http.post.return_value=Response({'writeResults':[{},{}]})
        self.tags=[{'id':'a','name':'Food'}, {'id':'b','name':'Other: stuff'}]
        self.patches=[patch('weekly_cli.firestore.refresh',return_value='token'),patch('weekly_cli.firestore.secret',return_value={'user_id':'u'}),patch('weekly_cli.firestore.requests.Session',return_value=self.http),patch('weekly_cli.spending.list_documents',return_value=self.tags)]
        for p in self.patches: p.start(); self.addCleanup(p.stop)

    def configure_reads(self):
        count=[0]
        def by_url(url,**kwargs):
            count[0]+=1
            if count[0]==1: return Response(self.original)
            ident=url.rsplit('/',1)[-1]
            writes=self.http.post.call_args.kwargs['json']['writes']
            write=next(w for w in writes if w['update']['name'].endswith('/'+ident))
            fields={**self.fields, **write['update']['fields']}
            return Response({'name':self.root+ident,'updateTime':'2026-01-01T00:00:01Z','fields':fields})
        self.http.get.side_effect=by_url

    def test_atomic_split_preserves_fields_and_guards(self):
        import copy
        before=copy.deepcopy(self.original)
        self.configure_reads()
        result=self.spending.split(object(),'source',['0.10: FOOD ','0.20:Other: stuff'])
        self.assertEqual(len(result),2)
        self.assertEqual(self.original,before)
        self.http.post.assert_called_once()
        args,kw=self.http.post.call_args
        self.assertEqual(args[0],'https://firestore.googleapis.com/v1/projects/weekly-6f36c/databases/(default)/documents:commit')
        self.assertEqual(kw['timeout'],30); self.assertFalse(kw['allow_redirects'])
        writes=kw['json']['writes']; self.assertEqual(len(writes),2)
        self.assertEqual(writes[0]['currentDocument'],{'updateTime':self.original['updateTime']})
        self.assertEqual(set(writes[0]['updateMask']['fieldPaths']),{'amount','tagId','isSplit'})
        self.assertEqual(writes[1]['currentDocument'],{'exists':False})
        self.assertEqual(writes[1]['update']['fields']['__plaidTx'],self.fields['__plaidTx'])
        self.assertEqual(writes[1]['update']['fields']['unknown'],self.fields['unknown'])

    def test_invalid_parts_and_sources_do_not_write(self):
        for parts in ([],['0.3:Food'],['0.1:Food','0.19:Food'],['nan:Food','0.2:Food'],['0.001:Food','0.299:Food'],['0.1','0.2:Food'],['0.1:  ','0.2:Food'],['0.1:missing','0.2:Food']):
            with self.subTest(parts=parts),self.assertRaises(ClientError): self.spending.split(object(),'source',parts)
        self.assertEqual(self.http.post.call_count,0)
        for mutate in ({'isSplit':{'booleanValue':True}}, {'target':{'stringValue':'FUND'}}, {'transferDirection':{'stringValue':'out'}}, {'__plaidTx':{'mapValue':{'fields':{}}}}, {'amount':{'doubleValue':-1}}):
            fields=self.original['fields']; old=fields.copy(); fields.update(mutate)
            with self.assertRaises(ClientError): self.spending.split(object(),'source',['0.10:Food','0.20:Food'])
            fields.clear(); fields.update(old)
        for ident in ('','..','a/b'):
            with self.assertRaises(ClientError): self.spending.split(object(),ident,['0.10:Food','0.20:Food'])
        self.http.post.assert_not_called()

    def test_ambiguous_commit_is_not_retried_and_identifies_parts(self):
        self.http.post.return_value=Response({'writeResults':[]})
        with self.assertRaises(ClientError) as e: self.spending.split(object(),'source',['0.10:Food','0.20:Food'])
        names=[w['update']['name'].rsplit('/',1)[-1] for w in self.http.post.call_args.kwargs['json']['writes']]
        self.assertTrue(all(name in str(e.exception) for name in names))
        self.http.post.assert_called_once()

    def test_three_parts_one_tag_fetch_and_decimal_original(self):
        self.original['fields']['amount']={'integerValue':'1'}
        self.http.post.return_value=Response({'writeResults':[{}, {}, {}]})
        self.configure_reads()
        with patch('weekly_cli.spending.list_documents',return_value=self.tags) as tags:
            out=self.spending.split(object(),'source',['0.10:Food','0.20:Food','0.70:Other: stuff'])
        tags.assert_called_once()
        self.assertEqual(len(out),3)
        writes=self.http.post.call_args.kwargs['json']['writes']
        self.assertEqual([w['update']['fields']['amount']['doubleValue'] for w in writes],[0.1,0.2,0.7])
        self.assertNotEqual(writes[1]['update']['name'],writes[2]['update']['name'])

    def test_bad_source_identity_amount_and_categories_are_rejected(self):
        for value in ({},{'stringValue':'0.30'},{'doubleValue':float('nan')},{'doubleValue':0.001}):
            with self.subTest(value=value):
                self.original['fields']['amount']=value
                with self.assertRaises(ClientError): self.spending.split(object(),'source',['0.10:Food','0.20:Food'])
        self.original['fields']['amount']={'doubleValue':0.3}
        self.original['name']=self.root.replace('/u/','/other/')+'source'
        with self.assertRaises(ClientError): self.spending.split(object(),'source',['0.10:Food','0.20:Food'])
        self.original['name']=self.root+'source'
        with patch('weekly_cli.spending.list_documents',return_value=[{'id':'a','name':'Food'},{'id':'b','name':'FOOD'}]):
            with self.assertRaises(ClientError): self.spending.split(object(),'source',['0.10:Food','0.20:Food'])
        self.http.post.assert_not_called()

    def test_failed_and_ambiguous_response_handling(self):
        import requests
        for body in ({},{'writeResults':None},{'writeResults':[{}]},{'writeResults':[{}, {}, {}]},{'writeResults':[{}, None]}):
            self.http.post.return_value=Response(body)
            with self.assertRaises(ClientError) as e: self.spending.split(object(),'source',['0.10:Food','0.20:Food'])
            self.assertIn('source',str(e.exception))
            self.http.post.reset_mock()
        self.http.post.side_effect=requests.Timeout('secret')
        with self.assertRaises(ClientError) as e: self.spending.split(object(),'source',['0.10:Food','0.20:Food'])
        self.assertNotIn('secret',str(e.exception)); self.http.post.assert_called_once()
        self.http.post.side_effect=None; self.http.post.reset_mock()
        self.http.post.return_value=Response({}); self.http.post.return_value.status_code=412
        with self.assertRaises(ClientError) as e: self.spending.split(object(),'source',['0.10:Food','0.20:Food'])
        self.assertIn('412',str(e.exception)); self.http.post.assert_called_once()

    def test_stale_or_incomplete_committed_fields_are_uncertain(self):
        import copy
        for changes in ({}, {'amount':{'doubleValue':9}}, {'tagId':{'stringValue':'wrong'}}, {'isSplit':{'booleanValue':False}}, {'__plaidTx':{'mapValue':{'fields':{}}}}):
            fields=copy.deepcopy(self.fields)
            fields.update({'amount':{'doubleValue':0.1},'tagId':{'stringValue':'a'},'isSplit':{'booleanValue':True}})
            if changes: fields.update(changes)
            else: fields={}
            self.http.get.side_effect=[Response(self.original),Response({'name':self.root+'source','updateTime':'2026-01-01T00:00:01Z','fields':fields})]
            with self.subTest(changes=changes),self.assertRaises(ClientError) as e:
                self.spending.split(object(),'source',['0.10:Food','0.20:Food'])
            self.assertIn('uncertain',str(e.exception))
            self.http.post.reset_mock()

    def test_invalid_version_and_http_timeout_are_uncertain(self):
        self.http.post.return_value=Response({}); self.http.post.return_value.status_code=408
        with self.assertRaises(ClientError) as e: self.spending.split(object(),'source',['0.10:Food','0.20:Food'])
        self.assertIn('uncertain',str(e.exception))
        self.http.post.return_value=Response({'writeResults':[{},{}]})
        self.http.get.side_effect=[Response(self.original),Response({'name':self.root+'source','updateTime':'t','fields':self.fields})]
        with self.assertRaises(ClientError) as e: self.spending.split(object(),'source',['0.10:Food','0.20:Food'])
        self.assertIn('uncertain',str(e.exception))

    def test_bad_post_commit_readback_is_uncertain(self):
        self.http.get.side_effect=[Response(self.original),Response({'name':self.root+'wrong','fields':{},'updateTime':'t'})]
        with self.assertRaises(ClientError) as e: self.spending.split(object(),'source',['0.10:Food','0.20:Food'])
        ids=[w['update']['name'].rsplit('/',1)[-1] for w in self.http.post.call_args.kwargs['json']['writes']]
        self.assertTrue(all(ident in str(e.exception) for ident in ids)); self.http.post.assert_called_once()

    def test_cli_invokes_real_split_and_renders(self):
        from typer.testing import CliRunner
        from weekly_cli.main import app
        self.configure_reads()
        with patch('weekly_cli.main.get_config',return_value=object()):
            result=CliRunner().invoke(app,['transactions','split','source','--part','0.10:Food','--part','0.20:Food','--profile','sample'])
        self.assertEqual(result.exit_code,0,result.output)
        self.assertEqual(len(json.loads(result.stdout)),2)
        self.http.post.assert_called_once()

    def test_cli_table_and_rejected_single_part(self):
        from typer.testing import CliRunner
        from weekly_cli.main import app
        self.configure_reads()
        with patch('weekly_cli.main.get_config',return_value=object()) as config:
            result=CliRunner().invoke(app,['transactions','split','source','--part','0.10:Food','--part','0.20:Food','--table','--profile','sample'])
        self.assertEqual(result.exit_code,0,result.output)
        config.assert_called_once_with('sample')
        self.assertIn('Synthetic',result.stdout)
        self.http.post.reset_mock()
        with patch('weekly_cli.main.get_config',return_value=object()):
            result=CliRunner().invoke(app,['transactions','split','source','--part','0.30:Food'])
        self.assertNotEqual(result.exit_code,0)
        self.assertNotIn('Synthetic',result.stdout)
        self.http.post.assert_not_called()

    def test_bad_part_values_and_readback_version_fail_closed(self):
        for first in ('0:Food','-0.10:Food','Infinity:Food','0.10:',':Food','0.10:Food'):
            second='0.21:Food' if first == '0.10:Food' else '0.20:Food'
            with self.subTest(first=first), self.assertRaises(ClientError):
                self.spending.split(object(),'source',[first,second])
        self.http.post.assert_not_called()
        self.http.get.side_effect=[Response(self.original),Response({'name':self.root+'source','fields':{}})]
        with self.assertRaises(ClientError) as e:
            self.spending.split(object(),'source',['0.10:Food','0.20:Food'])
        self.assertIn('uncertain',str(e.exception))

    def test_split_cli_missing_parts_rejected(self):
        from typer.testing import CliRunner
        from weekly_cli.main import app
        r=CliRunner().invoke(app,['transactions','split','source'])
        self.assertNotEqual(r.exit_code,0)



class UnreviewedTests(unittest.TestCase):
    def setUp(self):
        self.settings = {'rangekey':'all','timezoneoffset':'0','summaryonly':'false','excludefundcontributions':'true','excludeignoredtransactions':'true','excludereportexcludeditems':'true'}
        self.week={'startDate':'2000-01-02T00:00:00Z','endDate':'2000-01-08T00:00:00Z'}
        self.rows=['Id,Title,Date,Target,Amount,Extra']
        self.rows += [f'{i},Match,2000-01-0{2+i%7},INITIAL,-1.00,keep' for i in range(12)]
        self.rows += ['other,Match,2000-01-09,INITIAL,-1.00,keep','reviewed,Match,2000-01-04,SAFE_TO_SPEND,-1.00,keep','different,Other,2000-01-04,INITIAL,-1.00,keep']
        self.response=types.SimpleNamespace(status_code=200,headers={'content-type':'text/csv'},content=('\n'.join(self.rows)+'\n').encode())
        self.patches=[patch('weekly_cli.transactions.refresh',return_value='token'),patch('weekly_cli.transactions.secret',return_value={'user_id':'synthetic','export_settings':self.settings}),patch('weekly_cli.transactions.requests.Session'),patch('weekly_cli.transactions.current_week',return_value=self.week)]
        for p in self.patches: p.start(); self.addCleanup(p.stop)
        self.client=self.patches[2].target.Session.return_value
        self.client.get.return_value=self.response

    def test_all_matches_boundaries_and_local_filter_before_limit(self):
        from weekly_cli.transactions import list_transactions
        all_rows=list_transactions(object(),'all',unreviewed=True)
        self.assertEqual(len(all_rows),13)
        self.assertIn('keep',[r['Extra'] for r in all_rows])
        filtered=list_transactions(object(),'all',limit=1,filters=['Title:eq:Other'],unreviewed=True)
        self.assertEqual([r['Id'] for r in filtered],['different'])
        self.assertEqual(len(list_transactions(object(),'all')),15)

    def test_unreviewed_overrides_saved_range_and_keeps_cross_month_week(self):
        from weekly_cli.transactions import list_transactions
        self.settings['rangekey']='month_to_date'
        self.response.content=(b'Id,Title,Date,Target\n'
            b'a,Before month,1999-12-31,INITIAL\n'
            b'b,This month,2000-01-01,INITIAL\n'
            b'c,Reviewed,not-a-date,SAFE_TO_SPEND\n')
        self.patches[3].target.current_week.return_value={'startDate':'1999-12-29T00:00:00Z','endDate':'2000-01-04T00:00:00Z'}
        result=list_transactions(object(),unreviewed=True)
        self.assertEqual([r['Id'] for r in result],['a','b'])
        self.assertEqual(self.client.get.call_args.kwargs['headers']['rangekey'],'all')

    def test_malformed_dates_missing_columns_and_conflicts_fail(self):
        from weekly_cli.transactions import list_transactions
        for bad in (b'Id,Title,Target,Date\na,Example,INITIAL,not-a-date\n',b'Id,Title\na,Example\n',b'Id,Title\n'):
            self.response.content=bad
            with self.assertRaises(ClientError): list_transactions(object(),'all',unreviewed=True)
        for range_key,offset in [('month_to_date',None),('all',0)]:
            with self.assertRaises(ClientError): list_transactions(object(),range_key,offset,unreviewed=True)

    def test_current_week_timezone_unique_and_invalid(self):
        from weekly_cli.firestore import current_week
        from datetime import datetime, timezone
        fixed=unittest.mock.Mock();fixed.now.return_value=datetime(2000,1,2,1,tzinfo=timezone.utc)
        weeks=[{'startDate':'1999-12-26T00:00:00Z','endDate':'2000-01-01T00:00:00Z'},self.week]
        with patch('weekly_cli.firestore.list_documents',return_value=weeks),patch('weekly_cli.firestore.datetime',wraps=datetime) as dt:
            dt.now.return_value=fixed.now.return_value.astimezone(__import__('zoneinfo').ZoneInfo('America/Chicago'))
            self.assertEqual(current_week(object(),{'timezone':'America/Chicago'}),weeks[0])
        with patch('weekly_cli.firestore.list_documents',return_value=[self.week,self.week]),patch('weekly_cli.firestore.datetime',wraps=datetime) as dt:
            dt.now.return_value=datetime(2000,1,3,tzinfo=timezone.utc)
            with self.assertRaises(ClientError): current_week(object(),{'timezone':'UTC'})
        with patch('weekly_cli.firestore.list_documents',return_value=[{'startDate':'bad','endDate':'bad'}]):
            with self.assertRaises(ClientError): current_week(object(),{'timezone':'UTC'})
            with self.assertRaises(ClientError): current_week(object(),{'timezone':'not/a-zone'})

    def test_budget_current_retains_original_output(self):
        from typer.testing import CliRunner
        from weekly_cli.main import app
        preferences={'timezone':'UTC','savingsAmount':1}
        with patch('weekly_cli.main.get_config',return_value=object()), patch('weekly_cli.main.user_preferences',return_value=preferences), patch('weekly_cli.main.current_week',return_value=self.week) as current, patch('weekly_cli.main.list_documents',side_effect=[[], []]):
            result=CliRunner().invoke(app,['budget','current'])
        self.assertEqual(result.exit_code,0,result.output)
        self.assertEqual(json.loads(result.stdout),{'week':self.week,'recurring_items':[],'funds':[],'preferences':preferences})
        self.assertEqual(current.call_args.args[1],preferences)

    def test_cli_conflicts_and_unreviewed_projection(self):
        from typer.testing import CliRunner
        from weekly_cli.main import app
        with patch('weekly_cli.main.get_config',return_value=object()):
            for opts in (['--range','month_to_date'],['--timezone-offset','0']):
                result=CliRunner().invoke(app,['transactions','list','--unreviewed',*opts])
                self.assertNotEqual(result.exit_code,0)
            result=CliRunner().invoke(app,['transactions','list','--unreviewed','--filter','Title:eq:Other','--limit','1','--properties','Id,Extra'])
        self.assertEqual(result.exit_code,0,result.output)
        self.assertEqual(json.loads(result.stdout),[{'Id':'different','Extra':'keep'}])


if __name__ == '__main__':
    unittest.main()
