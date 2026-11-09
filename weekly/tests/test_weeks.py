import json
import unittest
from datetime import date, datetime, timezone
from unittest.mock import Mock, patch

from cli_tools_shared.exceptions import ClientError
from weekly_cli.weeks import historical_week, money, week_dates


class WeekValidationTests(unittest.TestCase):
    def test_dates_are_inclusive_without_an_invented_duration(self):
        self.assertEqual(week_dates('2026-01-02', '2026-01-02', []), (date(2026, 1, 2), date(2026, 1, 2)))
        self.assertEqual(week_dates('2026-01-02', '2026-01-12', []), (date(2026, 1, 2), date(2026, 1, 12)))
        for start, end in [('20260102', '2026-01-03'), ('2026-02-30', '2026-03-01'), ('2026-01-03', '2026-01-02')]:
            with self.subTest(start=start, end=end), self.assertRaises(ClientError):
                week_dates(start, end, [])

    def test_overlap_includes_shared_boundary_but_not_adjacent_day(self):
        saved = [{'startDate': '2026-01-02', 'endDate': '2026-01-08'}]
        for start, end in [('2026-01-01', '2026-01-02'), ('2026-01-08', '2026-01-10'), ('2026-01-03', '2026-01-04')]:
            with self.subTest(start=start), self.assertRaisesRegex(ClientError, 'overlap'):
                week_dates(start, end, saved)
        week_dates('2026-01-09', '2026-01-15', saved)

    def test_money_rejects_fractions_of_cents_and_nonfinite_values(self):
        self.assertEqual(str(money('0')), '0')
        self.assertEqual(str(money('123.45')), '123.45')
        for value in ('NaN', 'Infinity', '1.001', 'not-money', '12345678901234567890.12'):
            with self.subTest(value=value), self.assertRaises(ClientError):
                money(value)

    def test_historical_builder_matches_observed_expenses_only_summary(self):
        transactions = [
            {'date': '2026-01-02', 'target': 'INITIAL', 'amount': 6.20, '__plaidTx': {'amount': 6.20}},
            {'date': '2026-01-08', 'target': 'INITIAL', 'amount': 4.10, '__plaidTx': {'amount': 4.10}},
            {'date': '2026-01-04', 'target': 'INITIAL', 'amount': 50, '__plaidTx': {'amount': -50}},
            {'date': '2026-01-09', 'target': 'INITIAL', 'amount': 99, '__plaidTx': {'amount': 99}},
        ]
        result = historical_week('2026-01-02', '2026-01-08', '100.00', 'PRO', [], transactions, date(2026, 1, 9))
        self.assertEqual(result, {
            'startDate': '2026-01-02', 'endDate': '2026-01-08',
            'allowanceAmount': 100.0, 'spentAmount': 0, 'endingBalance': 100.0,
            'spendingSummary': {'INITIAL': 10.3}, 'rolloverAmount': 0,
            'rolloverEnabled': False, 'rolloverOption': 'ignore', 'currentPlan': 'PRO',
            'showPastWeekTxsForReview': False, 'weekCreationType': 'historical',
        })

    def test_unestablished_historical_shapes_and_future_flow_are_explicit(self):
        for transaction in [
            {'date': '2026-01-02', 'target': 'SAFE_TO_SPEND', '__plaidTx': {'amount': 1}},
            {'date': '2026-01-02', 'target': 'INITIAL', 'amount': 1},
            {'date': '2026-01-02', 'target': 'INITIAL', '__plaidTx': {'amount': 1}, 'transferDirection': 'in'},
            {'date': '2026-01-02', 'target': 'INITIAL', '__plaidTx': {}},
        ]:
            with self.subTest(transaction=transaction), self.assertRaises(ClientError):
                historical_week('2026-01-02', '2026-01-08', '100', 'PRO', [], [transaction], date(2026, 1, 9))
        with self.assertRaisesRegex(ClientError, 'completed past'):
            historical_week('2026-01-02', '2026-01-08', '100', 'PRO', [], [], date(2026, 1, 8))

    def test_zero_limit_is_preserved_and_missing_plan_is_not_guessed(self):
        result = historical_week('2026-01-02', '2026-01-08', '0', 'PRO', [], [], date(2026, 1, 9))
        self.assertEqual(result['allowanceAmount'], 0)
        self.assertEqual(result['endingBalance'], 0)
        with self.assertRaisesRegex(ClientError, 'explicit Weekly plan'):
            historical_week('2026-01-02', '2026-01-08', '100', None, [], [], date(2026, 1, 9))


class WeekCreateTests(unittest.TestCase):
    def setUp(self):
        self.current = {'id': 'current', 'currentPlan': 'PRO'}
        self.transaction = {'date': '2026-01-02', 'target': 'INITIAL', 'amount': 4, '__plaidTx': {'amount': 4}}
        self.patches = [
            patch('weekly_cli.weeks.user_preferences', return_value={'timezone': 'UTC'}),
            patch('weekly_cli.weeks.current_week', return_value=self.current),
            patch('weekly_cli.weeks.list_documents', side_effect=[[], [self.transaction]]),
            patch('weekly_cli.weeks.create_document', return_value={'id': 'new'}),
            patch('weekly_cli.weeks.datetime', wraps=datetime),
        ]
        self.mocks = [item.start() for item in self.patches]
        self.mocks[4].now.return_value = datetime(2026, 1, 9, 12, tzinfo=timezone.utc)
        self.addCleanup(patch.stopall)

    def test_dry_run_builds_record_and_never_writes(self):
        from weekly_cli.weeks import create
        result = create(object(), '2026-01-02', '2026-01-08', '100.00', dry_run=True)
        self.assertEqual(result['dry_run'], True)
        self.assertEqual(result['fields']['spendingSummary'], {'INITIAL': 4.0})
        self.assertEqual(result['fields']['currentPlan'], 'PRO')
        self.mocks[3].assert_not_called()

    def test_real_create_writes_only_one_week_document(self):
        from weekly_cli.weeks import create
        result = create(object(), '2026-01-02', '2026-01-08', '100.00')
        self.assertEqual(result, {'id': 'new'})
        self.assertEqual(self.mocks[3].call_args.args[1], 'weekInstances')
        self.assertEqual(self.mocks[3].call_args.args[2]['weekCreationType'], 'historical')
        self.mocks[3].assert_called_once()

    def test_current_upcoming_and_duplicate_ranges_never_write(self):
        from weekly_cli.weeks import create
        for start, end in [('2026-01-09', '2026-01-15'), ('2026-01-02', '2026-01-09')]:
            with self.subTest(start=start), self.assertRaisesRegex(ClientError, 'Current and upcoming'):
                create(object(), start, end, '100')
        self.mocks[3].assert_not_called()
        self.mocks[2].side_effect = [[{'startDate': '2026-01-02', 'endDate': '2026-01-08'}], []]
        with self.assertRaisesRegex(ClientError, 'overlap'):
            create(object(), '2026-01-02', '2026-01-08', '100')
        self.mocks[3].assert_not_called()

    def test_encoded_creation_request_matches_observed_nested_fields(self):
        from weekly_cli import firestore
        values = historical_week('2026-01-02', '2026-01-08', '100', 'PRO', [], [self.transaction], date(2026, 1, 9))
        fields = {key: firestore.encode_value(value) for key, value in values.items()}
        http = Mock()
        response = Mock(status_code=200)
        response.json.return_value = {'name': firestore.USER_DOCUMENT_ROOT + 'synthetic/weekInstances/new', 'fields': fields}
        http.post.return_value = response
        with patch('weekly_cli.firestore.firestore_context', return_value=(http, 'https://example.invalid/users/synthetic', {}, {'user_id': 'synthetic'})):
            result = firestore.create_document(object(), 'weekInstances', values)
        self.assertEqual(result, {'id': 'new', **values})
        self.assertEqual(http.post.call_args.args[0], 'https://example.invalid/users/synthetic/weekInstances')
        self.assertEqual(http.post.call_args.kwargs['json']['fields']['spendingSummary'], {'mapValue': {'fields': {'INITIAL': {'doubleValue': 4.0}}}})


class WeekReadCommandTests(unittest.TestCase):
    def test_list_preserves_dates_limits_and_query_options(self):
        from typer.testing import CliRunner
        from weekly_cli.main import app
        rows = [{'id': 'one', 'startDate': '2026-01-02', 'endDate': '2026-01-08', 'allowanceAmount': 100}]
        with patch('weekly_cli.main.get_config', return_value=object()), patch('weekly_cli.main.list_documents', return_value=rows) as read:
            result = CliRunner().invoke(app, ['weeks', 'list', '--limit', '1', '--filter', 'startDate:eq:2026-01-02', '--properties', 'id,startDate,endDate,allowanceAmount'])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(json.loads(result.stdout), rows)
        self.assertEqual(read.call_args.args[1], 'weekInstances')
        self.assertEqual(read.call_args.kwargs, {'limit': 1, 'filters': ['startDate:eq:2026-01-02']})

    def test_get_returns_one_week_without_synthesizing_missing_limit(self):
        from typer.testing import CliRunner
        from weekly_cli.main import app
        row = {'id': 'current', 'startDate': '2026-01-02', 'endDate': '2026-01-08'}
        with patch('weekly_cli.main.get_config', return_value=object()), patch('weekly_cli.main.list_documents', return_value=[row]):
            result = CliRunner().invoke(app, ['weeks', 'get', 'current'])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(json.loads(result.stdout), row)
