import json
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import requests
from cli_tools_shared.exceptions import ClientError
from weekly_cli import weeks
from weekly_cli.constants import USER_DOCUMENT_ROOT


class WeekDeleteTests(unittest.TestCase):
    def setUp(self):
        self.http = Mock()
        self.doc = {
            'name': USER_DOCUMENT_ROOT + 'synthetic/weekInstances/selected',
            'updateTime': '2026-01-09T00:00:00Z',
            'fields': {'startDate': {'stringValue': '2026-01-09'}, 'endDate': {'stringValue': '2026-01-15'}, 'allowanceAmount': {'doubleValue': 100}},
        }
        self.response = Mock(status_code=200)
        self.response.json.return_value = self.doc
        self.http.get.side_effect = [self.response, Mock(status_code=404)]
        self.http.delete.return_value = Mock(status_code=200)
        self.context = patch('weekly_cli.weeks.firestore_context', return_value=(self.http, 'https://example.invalid/users/synthetic', {}, {'user_id': 'synthetic'}))
        self.context_mock = self.context.start()
        patch('weekly_cli.weeks.user_preferences', return_value={'timezone': 'UTC'}).start()
        clock = patch('weekly_cli.weeks.datetime', wraps=datetime).start()
        clock.now.return_value = datetime(2026, 1, 9, 12, tzinfo=timezone.utc)
        self.addCleanup(patch.stopall)

    def test_confirmation_is_required_before_any_network_read(self):
        with self.assertRaisesRegex(ClientError, 'without --yes or --dry-run'):
            weeks.delete(object(), 'selected')
        self.context_mock.assert_not_called()
        with self.assertRaisesRegex(ClientError, 'not both'):
            weeks.delete(object(), 'selected', dry_run=True, yes=True)

    def test_preview_identifies_current_week_and_preserves_missing_allowance(self):
        del self.doc['fields']['allowanceAmount']
        result = weeks.delete(object(), 'selected', dry_run=True)
        self.assertTrue(result['dry_run'])
        self.assertTrue(result['is_current'])
        self.assertIn('no current week', result['current_week_effect'])
        self.assertNotIn('allowanceAmount', result)
        self.http.delete.assert_not_called()
        self.assertEqual(self.http.get.call_count, 1)

    def test_execute_deletes_exact_selected_version_and_confirms_absence(self):
        result = weeks.delete(object(), 'selected', yes=True)
        self.assertTrue(result['deleted'])
        self.assertTrue(result['is_current'])
        self.http.delete.assert_called_once_with(
            'https://example.invalid/users/synthetic/weekInstances/selected',
            headers={}, params={'currentDocument.updateTime': self.doc['updateTime']}, timeout=30, allow_redirects=False,
        )
        self.assertEqual(self.http.get.call_count, 2)
        self.http.post.assert_not_called()
        self.http.patch.assert_not_called()

    def test_missing_week_never_deletes(self):
        self.response.status_code = 404
        with self.assertRaisesRegex(ClientError, 'Week not found'):
            weeks.delete(object(), 'selected', yes=True)
        self.http.delete.assert_not_called()

    def test_wrong_identity_missing_version_and_invalid_ids_never_delete(self):
        original = self.doc.copy()
        for change in [{'name': USER_DOCUMENT_ROOT + 'other/weekInstances/selected'}, {'updateTime': None}]:
            self.doc.clear(); self.doc.update(original); self.doc.update(change)
            self.http.get.side_effect = None; self.http.get.return_value = self.response
            with self.subTest(change=change), self.assertRaises(ClientError):
                weeks.delete(object(), 'selected', yes=True)
        for ident in ['', '../other', '..', '.']:
            with self.subTest(ident=ident), self.assertRaisesRegex(ClientError, 'Invalid week ID'):
                weeks.delete(object(), ident, yes=True)
        self.http.delete.assert_not_called()

    def test_stale_version_is_reported_without_retry(self):
        self.http.delete.return_value.status_code = 412
        with self.assertRaisesRegex(ClientError, 'HTTP 412'):
            weeks.delete(object(), 'selected', yes=True)
        self.http.delete.assert_called_once()
        self.assertEqual(self.http.get.call_count, 1)

    def test_timeout_and_unconfirmed_absence_are_explicit_without_retry(self):
        self.http.delete.side_effect = requests.Timeout('secret response')
        with self.assertRaisesRegex(ClientError, 'outcome uncertain; inspect week selected before retrying'):
            weeks.delete(object(), 'selected', yes=True)
        self.http.delete.assert_called_once()
        self.http.delete.reset_mock(side_effect=True)
        self.http.delete.return_value = Mock(status_code=200)
        self.http.get.side_effect = [self.response, Mock(status_code=200)]
        with self.assertRaisesRegex(ClientError, 'outcome uncertain'):
            weeks.delete(object(), 'selected', yes=True)
        self.http.delete.assert_called_once()

    def test_cli_dry_run_uses_requested_id_and_execution_flag(self):
        from typer.testing import CliRunner
        from weekly_cli.main import app
        with patch('weekly_cli.main.get_config', return_value=object()):
            result = CliRunner().invoke(app, ['weeks', 'delete', 'selected', '--dry-run'])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(json.loads(result.stdout)['id'], 'selected')
        self.http.delete.assert_not_called()
