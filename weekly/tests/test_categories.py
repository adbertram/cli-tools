import json
import unittest
from unittest.mock import Mock, patch

import requests
from cli_tools_shared.exceptions import ClientError
from weekly_cli import firestore


class CategoryCreateTests(unittest.TestCase):
    def setUp(self):
        self.http = Mock()
        self.fields = {key: {'stringValue': value} for key, value in {'name': 'Christmas', 'color': 'red', 'emoji': '🎄'}.items()}
        self.doc = {'name': firestore.USER_DOCUMENT_ROOT + 'u/tags/new', 'fields': self.fields}
        self.response = Mock(status_code=200)
        self.response.json.return_value = self.doc
        self.http.post.return_value = self.response
        self.context = patch('weekly_cli.firestore.firestore_context', return_value=(self.http, 'https://example.invalid/users/u', {}, {'user_id': 'u'}))
        self.listing = patch('weekly_cli.firestore.list_documents', return_value=[{'id': 'other', 'name': 'Other'}])
        self.context.start()
        self.listing.start()
        self.addCleanup(patch.stopall)

    def test_create_preserves_explicit_metadata_and_returns_record(self):
        self.assertEqual(firestore.create_category(object(), ' Christmas ', 'red', '🎄'), {'id': 'new', 'name': 'Christmas', 'color': 'red', 'emoji': '🎄'})
        args, kwargs = self.http.post.call_args
        self.assertEqual(args, ('https://example.invalid/users/u/tags',))
        self.assertEqual(kwargs['json'], {'fields': self.fields})
        self.assertFalse(kwargs['allow_redirects'])

    def test_duplicate_name_is_rejected_even_if_archived_or_case_differs(self):
        with patch('weekly_cli.firestore.list_documents', return_value=[{'name': 'CHRISTMAS', 'archived': True}]):
            with self.assertRaisesRegex(ClientError, 'already exists'):
                firestore.create_category(object(), 'Christmas', 'red', '🎄')
        self.http.post.assert_not_called()

    def test_empty_metadata_is_rejected_without_writing(self):
        for values in [(' ', 'red', '🎄'), ('Christmas', '', '🎄'), ('Christmas', 'red', ' ')]:
            with self.subTest(values=values), self.assertRaises(ClientError):
                firestore.create_category(object(), *values)
        self.http.post.assert_not_called()

    def test_failed_or_uncertain_creation_does_not_expose_response(self):
        self.response.status_code = 403
        with self.assertRaisesRegex(ClientError, 'HTTP 403'):
            firestore.create_category(object(), 'Christmas', 'red', '🎄')
        self.response.json.assert_not_called()
        self.http.post.side_effect = requests.Timeout('private')
        with self.assertRaisesRegex(ClientError, 'outcome uncertain; check categories before retrying'):
            firestore.create_category(object(), 'Christmas', 'red', '🎄')

    def test_wrong_user_or_returned_metadata_is_rejected(self):
        for doc in [{'name': firestore.USER_DOCUMENT_ROOT + 'other/tags/new', 'fields': self.fields}, {'name': self.doc['name'], 'fields': {}}]:
            self.response.json.return_value = doc
            with self.subTest(doc=doc), self.assertRaisesRegex(ClientError, 'unexpected identity or fields'):
                firestore.create_category(object(), 'Christmas', 'red', '🎄')

    def test_cli_requires_metadata_and_prints_category_record(self):
        from typer.testing import CliRunner
        from weekly_cli.main import app
        runner = CliRunner()
        self.assertEqual(runner.invoke(app, ['categories', 'create', '--name', 'Christmas']).exit_code, 2)
        with patch('weekly_cli.main.get_config', return_value=object()):
            result = runner.invoke(app, ['categories', 'create', '--name', 'Christmas', '--color', 'red', '--emoji', '🎄'])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(json.loads(result.stdout), {'id': 'new', 'name': 'Christmas', 'color': 'red', 'emoji': '🎄'})
