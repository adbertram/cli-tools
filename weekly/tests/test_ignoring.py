from copy import deepcopy
import json
import unittest
from unittest.mock import Mock, patch
import requests
from typer.testing import CliRunner
from cli_tools_shared.exceptions import ClientError
from weekly_cli.ignoring import ignore
from weekly_cli.main import app
from weekly_cli.constants import USER_DOCUMENT_ROOT


class IgnoreTests(unittest.TestCase):
    def setUp(self):
        self.original = {'name': USER_DOCUMENT_ROOT+'u/transactions/t', 'updateTime': '2026-11-03T12:00:00Z', 'fields': {
            'title': {'stringValue':'Example'}, 'amount': {'doubleValue':125},
            'target': {'stringValue':'INITIAL'}, 'color': {'stringValue':'success'},
            '__plaidTx': {'mapValue': {'fields': {'id': {'stringValue':'bank'}, 'other': {'nullValue':None}}}}}}
        self.expected = deepcopy(self.original)
        self.expected['fields']['target'] = {'stringValue':'IGNORED'}
        self.http = Mock()
        self.http.patch.return_value = Mock(status_code=200)
        self.http.patch.return_value.json.return_value = self.expected
        self.context = patch('weekly_cli.ignoring.client_context', return_value=(self.http,'https://example.invalid/transactions',{}, {'user_id':'u'}))
        self.context.start(); self.addCleanup(self.context.stop)

    def test_mask_version_and_fresh_read_preserve_every_other_field(self):
        with patch('weekly_cli.ignoring.get_document', side_effect=[self.original,self.expected]) as read:
            result=ignore(object(),'t')
        self.assertTrue(result['changed']); self.assertEqual(read.call_count,2)
        self.assertEqual(result['transaction']['target'],'IGNORED')
        call=self.http.patch.call_args
        self.assertEqual(call.kwargs['params'], [('currentDocument.updateTime',self.original['updateTime']),('updateMask.fieldPaths','target')])
        self.assertEqual(call.kwargs['json'],{'fields':{'target':{'stringValue':'IGNORED'}}})
        self.assertFalse(call.kwargs['allow_redirects'])

    def test_preview_and_idempotence_never_write(self):
        for doc,dry in [(self.original,True),(self.expected,False),(self.expected,True)]:
            with self.subTest(dry=dry),patch('weekly_cli.ignoring.get_document',return_value=doc):
                result=ignore(object(),'t',dry)
                self.assertEqual(result['changed'],doc==self.original)
        self.http.patch.assert_not_called()

    def test_reject_unsupported_states_and_invalid_versions_before_write(self):
        variants=[]
        for target in ('SAFE_TO_SPEND','FUND','RECURRING','unknown'):
            doc=deepcopy(self.original);doc['fields']['target']={'stringValue':target};variants.append(doc)
        for key in ('isCash','transferDirection'):
            doc=deepcopy(self.original);doc['fields'][key]={'booleanValue':True};variants.append(doc)
        doc=deepcopy(self.original);del doc['fields']['__plaidTx'];variants.append(doc)
        doc=deepcopy(self.original);doc['updateTime']='2026-11-03';variants.append(doc)
        for doc in variants:
            with self.subTest(doc=doc),patch('weekly_cli.ignoring.get_document',return_value=doc),self.assertRaises(ClientError):ignore(object(),'t')
        for ident in ('','../x','a/b','.'):
            with self.assertRaises(ClientError):ignore(object(),ident)
        self.http.patch.assert_not_called()

    def test_conflict_and_uncertain_results_are_never_retried(self):
        for status in (409,412,408,500,503):
            self.http.patch.reset_mock();self.http.patch.return_value.status_code=status
            with self.subTest(status=status),patch('weekly_cli.ignoring.get_document',return_value=self.original),self.assertRaises(ClientError):ignore(object(),'t')
            self.assertEqual(self.http.patch.call_count,1)
        self.http.patch.return_value.status_code=200
        for result in ({}, {'name':self.original['name'],'fields':self.original['fields']}):
            self.http.patch.return_value.json.return_value=result
            with patch('weekly_cli.ignoring.get_document',return_value=self.original),self.assertRaisesRegex(ClientError,'outcome uncertain'):ignore(object(),'t')
        self.http.patch.side_effect=requests.Timeout()
        with patch('weekly_cli.ignoring.get_document',return_value=self.original),self.assertRaisesRegex(ClientError,'outcome uncertain'):ignore(object(),'t')

    def test_failed_or_changed_readback_is_uncertain(self):
        for after in (self.original, ClientError('read failed'), requests.Timeout()):
            with self.subTest(after=after),patch('weekly_cli.ignoring.get_document',side_effect=[self.original,after]),self.assertRaisesRegex(ClientError,'outcome uncertain'):ignore(object(),'t')

    def test_cli_json_preview(self):
        with patch('weekly_cli.main.get_config',return_value=object()),patch('weekly_cli.ignoring.get_document',return_value=self.original):
            result=CliRunner().invoke(app,['transactions','ignore','t','--dry-run'])
        self.assertEqual(result.exit_code,0,result.stdout)
        self.assertTrue(json.loads(result.stdout)['dry_run']);self.http.patch.assert_not_called()
