import unittest
from unittest.mock import Mock

from gemini_cli.client import (
    GeminiClient,
    _FILES_LIST_TIMEOUT_MS,
    _MODELS_LIST_TIMEOUT_MS,
)


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
