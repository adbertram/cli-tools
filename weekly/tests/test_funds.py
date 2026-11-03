from copy import deepcopy
import unittest
import json
from typer.testing import CliRunner
from weekly_cli.main import app
from unittest.mock import Mock,patch
import requests
from cli_tools_shared.exceptions import ClientError
from weekly_cli.funds import create
from weekly_cli.constants import USER_DOCUMENT_ROOT


class FundTests(unittest.TestCase):
    def setUp(self):
        self.http=Mock();self.http.post.return_value=Mock(status_code=200)
        self.http.post.return_value.json.return_value={'writeResults':[{}, {}, {}]}
        self.version='2026-11-03T12:00:00Z'
        def doc(col,ident,fields):return {'name':USER_DOCUMENT_ROOT+'u/'+col+'/'+ident,'updateTime':self.version,'fields':fields}
        self.bill=doc('items','b',{'title':{'stringValue':'Example'},'color':{'stringValue':'warning'},'nextTransactionDateOverride':{'stringValue':'2026-11-03'}})
        self.tx=doc('transactions','t',{'title':{'stringValue':'Paid'},'date':{'stringValue':'2026-11-03'},'target':{'stringValue':'INITIAL'},'color':{'stringValue':'warning'},'amount':{'doubleValue':125},'__plaidTx':{'mapValue':{'fields':{'id':{'stringValue':'bank'},'amount':{'doubleValue':125}}}}})
        self.args=dict(name='Example fund',contribution='40.00',starting_balance='0',emoji='💰',color='gray',goal='120',replace_bill='b',settled_transaction='t')
        self.ps=[patch('weekly_cli.funds.list_documents',return_value=[]),patch('weekly_cli.funds.firestore_context',return_value=(self.http,'https://example.invalid/u',{}, {'user_id':'u'})),patch('weekly_cli.funds.uuid4',return_value=Mock(hex='f'))]
        for p in self.ps:p.start();self.addCleanup(p.stop)

    def test_preview_creates_no_credit_and_writes_nothing(self):
        with patch('weekly_cli.funds.read_document',side_effect=[self.bill,self.tx]):r=create(object(),**self.args,dry_run=True)
        self.assertTrue(r['dry_run']);self.assertFalse(r['current_week_credits_created']);self.assertEqual(r['fund']['contributionInterval'],'weekly');self.assertEqual(len(r['changes']),3);self.http.post.assert_not_called()

    def test_atomic_three_document_commit_preserves_override_and_bank_fields(self):
        after_bill=deepcopy(self.bill);after_bill['fields'].update(archived={'booleanValue':True},latestTransactionDate={'stringValue':'2026-11-03'},latestTransactionMerchant={'stringValue':'Paid'})
        after_tx=deepcopy(self.tx);after_tx['fields'].update(target={'stringValue':'RECURRING'},itemId={'stringValue':'b'})
        def read(h,u,headers,uid,col,ident):
            if self.http.post.called:
                if col=='funds':return {'fields':self.http.post.call_args.kwargs['json']['writes'][0]['update']['fields']}
                return after_bill if col=='items' else after_tx
            return self.bill if col=='items' else self.tx
        with patch('weekly_cli.funds.read_document',side_effect=read):r=create(object(),**self.args)
        self.assertTrue(r['created']);writes=self.http.post.call_args.kwargs['json']['writes'];self.assertEqual(len(writes),3)
        self.assertEqual(writes[0]['currentDocument'],{'exists':False})
        self.assertEqual(writes[1]['currentDocument'],{'updateTime':self.version})
        self.assertEqual(set(writes[1]['updateMask']['fieldPaths']),{'archived','latestTransactionDate','latestTransactionMerchant'})
        self.assertEqual(writes[2]['updateMask']['fieldPaths'],['target','itemId'])

    def test_standalone_future_fund_has_one_create_and_no_week_writes(self):
        self.http.post.return_value.json.return_value = {'writeResults': [{}]}
        args = {**self.args, 'replace_bill': None, 'settled_transaction': None}
        def read(*args):
            return {'fields': self.http.post.call_args.kwargs['json']['writes'][0]['update']['fields']}
        with patch('weekly_cli.funds.read_document', side_effect=read):
            result = create(object(), **args)
        writes = self.http.post.call_args.kwargs['json']['writes']
        self.assertEqual(len(writes), 1)
        self.assertFalse(result['current_week_credits_created'])
        self.assertTrue(writes[0]['update']['name'].endswith('/funds/f'))

    def test_cli_create_preview_and_read_contract(self):
        runner = CliRunner()
        with patch('weekly_cli.main.get_config', return_value=object()), patch('weekly_cli.funds.read_document', side_effect=[self.bill, self.tx]):
            result = runner.invoke(app, ['funds', 'create', '--name', 'Example', '--contribution', '40', '--starting-balance', '0', '--emoji', '💰', '--color', 'gray', '--replace-bill', 'b', '--settled-transaction', 't', '--dry-run'])
        self.assertEqual(result.exit_code, 0, result.stdout)
        self.assertTrue(json.loads(result.stdout)['dry_run'])
        self.http.post.assert_not_called()
        with patch('weekly_cli.main.get_config', return_value=object()), patch('weekly_cli.main.list_documents', return_value=[{'id': 'f', 'name': 'Example'}]):
            result = runner.invoke(app, ['funds', 'get', 'f'])
            self.assertEqual(result.exit_code, 0, result.stdout)
            self.assertEqual(json.loads(result.stdout)['id'], 'f')
            result = runner.invoke(app, ['funds', 'list', '--properties', 'id,name'])
            self.assertEqual(result.exit_code, 0, result.stdout)
            self.assertEqual(json.loads(result.stdout), [{'id': 'f', 'name': 'Example'}])

    def test_invalid_and_duplicate_inputs_do_not_commit(self):
        for change in ({'name':''},{'contribution':'-1'},{'contribution':'1.001'},{'starting_balance':'-1'},{'color':'invented'},{'goal':'0'},{'settled_transaction':None},{'starting_balance':'1'},{'replace_bill':'a/b'}):
            with self.subTest(change=change),self.assertRaises(ClientError):create(object(),**{**self.args,**change})
        with patch('weekly_cli.funds.list_documents',return_value=[{'name':'EXAMPLE FUND'}]),self.assertRaises(ClientError):create(object(),**self.args)
        self.http.post.assert_not_called()

    def test_conflict_timeout_and_bad_readback_never_retry(self):
        for status in (412,408,500):
            self.http.post.reset_mock();self.http.post.return_value.status_code=status
            with patch('weekly_cli.funds.read_document',side_effect=[self.bill,self.tx]),self.assertRaises(ClientError):create(object(),**self.args)
            self.assertEqual(self.http.post.call_count,1)
        self.http.post.return_value.status_code=200;self.http.post.side_effect=requests.Timeout()
        with patch('weekly_cli.funds.read_document',side_effect=[self.bill,self.tx]),self.assertRaisesRegex(ClientError,'uncertain'):create(object(),**self.args)
        self.http.post.side_effect=None
        with patch('weekly_cli.funds.read_document',side_effect=[self.bill,self.tx,{'fields':{}}]),self.assertRaisesRegex(ClientError,'uncertain'):create(object(),**self.args)

    def test_missing_bank_id_credit_and_manual_rejected_before_commit(self):
        original = deepcopy(self.tx)
        variants = []
        for value in ({}, {'stringValue': ''}):
            doc = deepcopy(original)
            doc['fields']['__plaidTx']['mapValue']['fields']['id'] = value
            variants.append(doc)
        for value in (-125, 0):
            doc = deepcopy(original)
            doc['fields']['__plaidTx']['mapValue']['fields']['amount'] = {'doubleValue': value}
            variants.append(doc)
        doc = deepcopy(original)
        doc['fields']['isCash'] = {'booleanValue': True}
        variants.append(doc)
        for tx in variants:
            with self.subTest(tx=tx), patch('weekly_cli.funds.read_document', side_effect=[self.bill, tx]), self.assertRaises(ClientError):
                create(object(), **self.args)
        self.http.post.assert_not_called()

    def test_missing_update_time_rejected_by_shared_reader(self):
        from weekly_cli.funds import read_document
        response = Mock(status_code=200)
        response.json.return_value = {k: v for k, v in self.bill.items() if k != 'updateTime'}
        self.http.get.return_value = response
        with self.assertRaisesRegex(ClientError, 'unexpected identity or shape'):
            read_document(self.http, 'https://example.invalid/u', {}, 'u', 'items', 'b')
        self.http.post.assert_not_called()

    def test_unsupported_settlement_does_not_commit(self):
        for doc,key,value in [(self.bill,'archived',{'booleanValue':True}),(self.tx,'target',{'stringValue':'SAFE_TO_SPEND'})]:
            original=deepcopy(doc);doc['fields'][key]=value
            with patch('weekly_cli.funds.read_document',side_effect=[self.bill,self.tx]),self.assertRaises(ClientError):create(object(),**self.args)
            doc.clear();doc.update(original)
        self.http.post.assert_not_called()
