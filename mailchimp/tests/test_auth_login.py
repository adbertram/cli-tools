from contextlib import contextmanager
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from mailchimp_cli.config import Config
from mailchimp_cli.main import app
import mailchimp_cli.config as mailchimp_config


def _fake_secret_manager(store):
    def _run(command: str, secret_name: str, *, secret_value=None):
        if command == "get":
            value = store.get(secret_name)
            return subprocess.CompletedProcess(
                args=[command, secret_name],
                returncode=0 if value is not None else 1,
                stdout="" if value is None else f"{value}\n",
                stderr="",
            )
        if command == "set":
            store[secret_name] = secret_value
            return subprocess.CompletedProcess(
                args=[command, secret_name],
                returncode=0,
                stdout="",
                stderr="",
            )
        if command == "delete":
            existed = secret_name in store
            store.pop(secret_name, None)
            return subprocess.CompletedProcess(
                args=[command, secret_name],
                returncode=0 if existed else 1,
                stdout="",
                stderr="",
            )
        if command == "has":
            return subprocess.CompletedProcess(
                args=[command, secret_name],
                returncode=0 if secret_name in store else 1,
                stdout="",
                stderr="",
            )
        raise AssertionError(f"Unexpected secret-manager command: {command}")

    return _run


class AuthLoginTests(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()

    def tearDown(self):
        mailchimp_config._configs.clear()

    def _clear_mailchimp_env(self):
        for field_name in Config.CUSTOM_ALL_FIELDS:
            os.environ.pop(field_name, None)
        os.environ.pop("ACTIVE", None)

    @contextmanager
    def _temp_profile_session(self, store=None):
        if store is None:
            store = {}
        with tempfile.TemporaryDirectory() as tmpdir:
            self._clear_mailchimp_env()
            mailchimp_config._configs.clear()
            with patch.dict(os.environ, {"XDG_DATA_HOME": tmpdir}, clear=False):
                with patch("cli_tools_shared.config._run_secret_manager", side_effect=_fake_secret_manager(store)):
                    yield store
            mailchimp_config._configs.clear()
            self._clear_mailchimp_env()

    def _invoke(self, args, *, input_text=None):
        result = self.runner.invoke(app, args, input=input_text)
        config = mailchimp_config.get_config()
        env_path = config.env_file_path
        env_text = env_path.read_text() if env_path.exists() else ""
        return result, env_text

    def test_auth_login_help_shows_supported_flags(self):
        result = self.runner.invoke(app, ["auth", "login", "--help"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("--api-key", result.output)
        self.assertIn("-k", result.output)
        self.assertIn("--force", result.output)
        self.assertIn("-F", result.output)

    def test_auth_login_accepts_api_key_option(self):
        with self._temp_profile_session() as store:
            result, env_text = self._invoke(["auth", "login", "--api-key", "test-key-us6"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(store["mailchimp-api-key"], "test-key-us6")
        self.assertIn("MAILCHIMP_API_KEY='secret://mailchimp-api-key'", env_text)

    def test_auth_login_reads_api_key_from_stdin_when_option_omitted(self):
        with self._temp_profile_session() as store:
            result, env_text = self._invoke(
                ["auth", "login"],
                input_text="stdin-key-us7\n",
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(store["mailchimp-api-key"], "stdin-key-us7")
        self.assertIn("MAILCHIMP_API_KEY='secret://mailchimp-api-key'", env_text)

    def test_auth_login_force_preserves_existing_secret_when_prompt_aborts(self):
        with self._temp_profile_session() as store:
            result, _env_text = self._invoke(["auth", "login", "--api-key", "original-key-us6"])
            self.assertEqual(result.exit_code, 0, result.output)

            result, env_text = self._invoke(
                ["auth", "login", "--force"],
                input_text="\n",
            )

        self.assertEqual(result.exit_code, 1, result.output)
        self.assertEqual(store["mailchimp-api-key"], "original-key-us6")
        self.assertIn("MAILCHIMP_API_KEY='secret://mailchimp-api-key'", env_text)

    def test_auth_login_force_flags_accept_stdin_replacement(self):
        for force_flag in ("--force", "-F"):
            with self.subTest(force_flag=force_flag):
                with self._temp_profile_session() as store:
                    result, _env_text = self._invoke(
                        ["auth", "login", "--api-key", "original-key-us6"]
                    )
                    self.assertEqual(result.exit_code, 0, result.output)

                    result, env_text = self._invoke(
                        ["auth", "login", force_flag],
                        input_text="replacement-key-us7\n",
                    )

                self.assertEqual(result.exit_code, 0, result.output)
                self.assertEqual(store["mailchimp-api-key"], "replacement-key-us7")
                self.assertIn("MAILCHIMP_API_KEY='secret://mailchimp-api-key'", env_text)


if __name__ == "__main__":
    unittest.main()
