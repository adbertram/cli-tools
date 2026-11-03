import json
import unittest
from unittest.mock import Mock, patch

import requests
from cli_tools_shared.exceptions import ClientError
from typer.testing import CliRunner
from weekly_cli import bills, firestore
from weekly_cli.main import app


class BillTests(unittest.TestCase):
    def setUp(self):
        self.values = dict(title='Electricity', amount='35.75', interval='monthly',
                           category='utilities', emoji='💡', emoji_color='blue')

    def test_native_expense_shape_with_optional_next_date(self):
        fields = bills.bill_fields(**self.values, next_date='2026-11-15')
        self.assertEqual(fields, {
            'title': 'Electricity', 'amount': 35.75, 'interval': 'monthly',
            'category': 'utilities', 'emoji': '💡', 'emojiColor': 'blue',
            'color': 'warning', 'nextTransactionDateOverride': '2026-11-15',
            'nextTransactionDateStored': '2026-11-15',
        })

    def test_income_keeps_positive_amount_and_uses_success_color(self):
        values = {**self.values, 'category': 'income', 'kind': 'income'}
        fields = bills.bill_fields(**values)
        self.assertEqual(fields['amount'], 35.75)
        self.assertEqual(fields['color'], 'success')
        self.assertNotIn('kind', fields)
        self.assertNotIn('nextTransactionDateOverride', fields)
        self.assertNotIn('nextTransactionDateStored', fields)

    def test_all_native_choices_and_independent_kind_category(self):
        self.assertEqual(len(bills.INTERVALS), 19)
        self.assertEqual(len(bills.CATEGORIES), 15)
        self.assertEqual(len(bills.EMOJI_COLORS), 7)
        for key, choices in [('interval', bills.INTERVALS), ('category', bills.CATEGORIES),
                             ('emoji_color', bills.EMOJI_COLORS)]:
            for value in choices:
                with self.subTest(setting=key, value=value):
                    bills.bill_fields(**{**self.values, key: value})
        self.assertEqual(bills.bill_fields(**self.values, kind='income')['color'], 'success')
        self.assertEqual(bills.bill_fields(**{**self.values, 'category': 'income'})['color'], 'warning')
        fields = bills.bill_fields(**self.values, hide_from_reports=True, archived=True)
        self.assertTrue(fields['excludeFromReports'])
        self.assertTrue(fields['archived'])
        self.assertNotIn('archived', bills.bill_fields(**self.values))

    def test_native_four_week_education_record_with_red_background(self):
        fields = bills.bill_fields('clibilltest', '1.00', 'every4weeks',
                                    'education', '💰', 'red')
        self.assertEqual(fields, {
            'title': 'clibilltest', 'amount': 1.0, 'interval': 'every4weeks',
            'category': 'education', 'emoji': '💰', 'emojiColor': 'red',
            'color': 'warning',
        })

    def test_invalid_inputs_never_reach_creation(self):
        changes = [
            {'amount': x} for x in ['0', '-1', '1.001', 'NaN', 'Infinity', '1e1000', 'not money']
        ] + [
            {'title': ' '}, {'emoji': ''}, {'interval': 'every999weeks'},
            {'category': 'not-a-native-category'}, {'emoji_color': 'unverified-color'},
            {'kind': 'refund'},
            {'next_date': '20261103'}, {'next_date': '2026-02-29'},
            {'next_date': ''},
        ]
        with patch('weekly_cli.bills.create_document') as write:
            for change in changes:
                with self.subTest(change=change), self.assertRaises(ClientError):
                    bills.create(object(), **{**self.values, **change})
            write.assert_not_called()

    def test_dry_run_does_not_contact_account(self):
        with patch('weekly_cli.bills.create_document') as write:
            result = bills.create(object(), **self.values, dry_run=True)
        write.assert_not_called()
        self.assertTrue(result['dry_run'])
        self.assertEqual(result['collection'], 'items')
        self.assertEqual(result['fields']['amount'], 35.75)

    def test_create_posts_only_verified_fields_and_validates_identity(self):
        fields = bills.bill_fields(**self.values)
        encoded = {key: firestore.encode_value(value) for key, value in fields.items()}
        response = Mock(status_code=200)
        response.json.return_value = {'name': firestore.USER_DOCUMENT_ROOT + 'u/items/new', 'fields': encoded}
        http = Mock()
        http.post.return_value = response
        with patch('weekly_cli.firestore.firestore_context', return_value=(http, 'https://example.invalid/users/u', {}, {'user_id': 'u'})):
            result = bills.create(object(), **self.values)
            self.assertEqual(result, {'id': 'new', **fields})
            args, kwargs = http.post.call_args
            self.assertEqual(args, ('https://example.invalid/users/u/items',))
            self.assertEqual(kwargs['json'], {'fields': encoded})
            self.assertFalse(kwargs['allow_redirects'])
            response.json.return_value['name'] = firestore.USER_DOCUMENT_ROOT + 'someone-else/items/new'
            with self.assertRaisesRegex(ClientError, 'unexpected identity'):
                bills.create(object(), **self.values)
            for status in (408, 500, 503):
                response.status_code = status
                with self.subTest(status=status), self.assertRaisesRegex(ClientError, 'outcome uncertain; check bills before retrying'):
                    bills.create(object(), **self.values)
            http.post.side_effect = requests.Timeout('private')
            with self.assertRaisesRegex(ClientError, 'outcome uncertain; check bills before retrying'):
                bills.create(object(), **self.values)

    def test_cli_preview_and_reads_preserve_json_contract(self):
        runner = CliRunner()
        args = ['bills', 'create', '--title', 'Electricity', '--amount', '35.75',
                '--interval', 'monthly', '--category', 'utilities', '--emoji', '💡',
                '--emoji-color', 'blue', '--hide-from-reports', '--archived', '--dry-run']
        with patch('weekly_cli.main.get_config', return_value=object()), patch('weekly_cli.bills.create_document') as write:
            result = runner.invoke(app, args)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(json.loads(result.stdout)['fields']['color'], 'warning')
        self.assertTrue(json.loads(result.stdout)['fields']['archived'])
        self.assertTrue(json.loads(result.stdout)['fields']['excludeFromReports'])
        write.assert_not_called()
        rows = [{'id': 'a', 'title': 'Electricity', 'amount': 35.75, 'interval': 'monthly', 'category': 'utilities'}]
        with patch('weekly_cli.main.get_config', return_value=object()), patch('weekly_cli.main.list_documents', return_value=rows) as listing:
            result = runner.invoke(app, ['bills', 'list', '-l', '2', '-f', 'title:eq:Electricity', '-p', 'id,title'])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(json.loads(result.stdout), [{'id': 'a', 'title': 'Electricity'}])
            self.assertEqual(listing.call_args.kwargs, {'limit': 2, 'filters': ['title:eq:Electricity']})
            result = runner.invoke(app, ['bills', 'get', 'a'])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(json.loads(result.stdout), rows[0])
            result = runner.invoke(app, ['bills', 'get', 'missing'])
            self.assertNotEqual(result.exit_code, 0)


if __name__ == '__main__':
    unittest.main()
