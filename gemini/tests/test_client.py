import unittest
from unittest.mock import Mock, patch

from google.genai import errors as genai_errors

from gemini_cli.client import (
    GeminiClient,
    _FILES_LIST_TIMEOUT_MS,
    _MODELS_LIST_TIMEOUT_MS,
    _RETRY_DELAYS,
    _retry_on_transient_api_error,
)


def api_error(code: int) -> genai_errors.APIError:
    return genai_errors.APIError(
        code,
        {"error": {"code": code, "message": "test error", "status": "UNAVAILABLE"}},
    )


class RetryTransientAPIErrorTests(unittest.TestCase):
    @patch("gemini_cli.client.time.sleep")
    def test_recovers_after_503(self, sleep: Mock) -> None:
        operation = Mock(side_effect=[api_error(503), "success"])

        result = _retry_on_transient_api_error(operation)

        self.assertEqual(result, "success")
        self.assertEqual(operation.call_count, 2)
        sleep.assert_called_once_with(_RETRY_DELAYS[0])

    @patch("gemini_cli.client.time.sleep")
    def test_raises_503_after_retries_are_exhausted(self, sleep: Mock) -> None:
        error = api_error(503)
        operation = Mock(side_effect=error)

        with self.assertRaises(genai_errors.APIError) as raised:
            _retry_on_transient_api_error(operation)

        self.assertIs(raised.exception, error)
        self.assertEqual(operation.call_count, len(_RETRY_DELAYS) + 1)
        self.assertEqual(
            [call.args[0] for call in sleep.call_args_list],
            _RETRY_DELAYS,
        )

    @patch("gemini_cli.client.time.sleep")
    def test_does_not_retry_nonretryable_api_error(self, sleep: Mock) -> None:
        error = api_error(400)
        operation = Mock(side_effect=error)

        with self.assertRaises(genai_errors.APIError) as raised:
            _retry_on_transient_api_error(operation)

        self.assertIs(raised.exception, error)
        operation.assert_called_once_with()
        sleep.assert_not_called()


class ListFilesTests(unittest.TestCase):
    def test_list_files_passes_sdk_timeout(self) -> None:
        client = GeminiClient.__new__(GeminiClient)
        client.client = Mock()

        pager = Mock()
        pager.page = []
        pager.next_page.side_effect = IndexError()
        client.client.files.list.return_value = pager

        files = client.list_files(limit=1)

        self.assertEqual(files, [])
        client.client.files.list.assert_called_once_with(
            config={
                "page_size": 1,
                "http_options": {"timeout": _FILES_LIST_TIMEOUT_MS},
            }
        )


class ListModelsTests(unittest.TestCase):
    def test_list_models_passes_sdk_timeout(self) -> None:
        client = GeminiClient.__new__(GeminiClient)
        client.client = Mock()

        pager = Mock()
        pager.page = []
        pager.next_page.side_effect = IndexError()
        client.client.models.list.return_value = pager

        models = client.list_models(limit=1)

        self.assertEqual(models, [])
        client.client.models.list.assert_called_once_with(
            config={
                "page_size": 1,
                "http_options": {"timeout": _MODELS_LIST_TIMEOUT_MS},
            }
        )


if __name__ == "__main__":
    unittest.main()
