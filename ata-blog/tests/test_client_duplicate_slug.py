import json
from unittest.mock import MagicMock, patch

from ata_blog_cli.client import AtaBlogClient


def _result(payload):
    result = MagicMock()
    result.stdout = json.dumps(payload)
    result.stderr = ""
    result.returncode = 0
    return result


def _config():
    config = MagicMock()
    config.is_notion_available.return_value = True
    config.is_wordpress_available.return_value = True
    return config


def test_check_duplicate_post_uses_eq_filter():
    with patch("ata_blog_cli.client.get_config", return_value=_config()):
        client = AtaBlogClient()

    with patch.object(client, "_run_wordpress", return_value=_result([])) as mock_run:
        assert client.check_duplicate_post("microsoft-purview-dlp-policies") is False

    mock_run.assert_called_once_with(
        [
            "posts",
            "list",
            "--filter",
            "slug:eq:microsoft-purview-dlp-policies",
        ]
    )
