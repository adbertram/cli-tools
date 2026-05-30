import json
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner


class ProfileOptionTest(unittest.TestCase):
    def setUp(self):
        from cli_tools_shared.data_cache import reset_cache_hit
        from venmo_cli import client as client_module

        reset_cache_hit()
        client_module._clients.clear()

    def tearDown(self):
        from cli_tools_shared.data_cache import reset_cache_hit
        from venmo_cli import client as client_module

        reset_cache_hit()
        client_module._clients.clear()

    def test_get_client_caches_by_auth_profile(self):
        from venmo_cli import client as client_module

        requested_profiles = []

        class FakeConfig:
            def __init__(self, profile):
                self.profile = profile
                self.access_token = f"token-{profile or 'default'}"

            def has_credentials(self):
                return True

            def get_missing_credentials(self):
                return []

        class FakeVenmoApiClient:
            def __init__(self, access_token):
                self.access_token = access_token

            def my_profile(self):
                return SimpleNamespace(id=f"user-for-{self.access_token}")

        fake_venmo_api = types.ModuleType("venmo_api")
        fake_venmo_api.Client = FakeVenmoApiClient

        def fake_get_config(profile=None):
            requested_profiles.append(profile)
            return FakeConfig(profile)

        with patch.dict(sys.modules, {"venmo_api": fake_venmo_api}):
            with patch.object(client_module, "get_config", side_effect=fake_get_config):
                default_client = client_module.get_client()
                personal_client = client_module.get_client(profile="personal")
                personal_client_again = client_module.get_client(profile="personal")
                work_client = client_module.get_client(profile="work")

        self.assertIs(personal_client, personal_client_again)
        self.assertIsNot(default_client, personal_client)
        self.assertIsNot(personal_client, work_client)
        self.assertEqual(requested_profiles, [None, "personal", "work"])

    def test_transactions_list_passes_explicit_profile_to_client(self):
        from venmo_cli import main as main_module

        runner = CliRunner()
        requested_profiles = []
        list_calls = []

        class FakeClient:
            def list_transactions(self, limit=50, before_id=None):
                list_calls.append({"limit": limit, "before_id": before_id})
                return [{"payment_id": "payment-1", "payment": {"amount": 12.34}}]

        def fake_get_client(profile=None):
            requested_profiles.append(profile)
            return FakeClient()

        with patch.object(main_module, "get_client", side_effect=fake_get_client):
            result = runner.invoke(
                main_module.app,
                ["transactions", "list", "--profile", "personal", "--limit", "1"],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(requested_profiles, ["personal"])
        self.assertEqual(list_calls, [{"limit": 1, "before_id": None}])
        self.assertEqual(json.loads(result.output), [{"payment_id": "payment-1", "payment": {"amount": 12.34}}])

    def test_transactions_get_passes_explicit_profile_to_client(self):
        from venmo_cli import main as main_module

        runner = CliRunner()
        requested_profiles = []
        get_calls = []

        class FakeClient:
            def get_transaction(self, transaction_id):
                get_calls.append(transaction_id)
                return {"payment_id": transaction_id, "payment": {"amount": 56.78}}

        def fake_get_client(profile=None):
            requested_profiles.append(profile)
            return FakeClient()

        with patch.object(main_module, "get_client", side_effect=fake_get_client):
            result = runner.invoke(
                main_module.app,
                ["transactions", "get", "payment-2", "--profile", "work"],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(requested_profiles, ["work"])
        self.assertEqual(get_calls, ["payment-2"])
        self.assertEqual(json.loads(result.output), {"payment_id": "payment-2", "payment": {"amount": 56.78}})


if __name__ == "__main__":
    unittest.main()
