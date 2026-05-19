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


def test_update_article_routes_date_properties_through_properties_json():
    with patch("ata_blog_cli.client.get_config", return_value=_config()):
        client = AtaBlogClient()

    with patch.object(client, "_run_notion", return_value=_result({"id": "page-123"})) as mock_run:
        result = client.update_article(
            "page-123",
            properties={
                "Publish Date": "2026-05-18",
                "Stage Date": "2026-05-17",
            },
        )

    assert result == {"id": "page-123"}
    args = mock_run.call_args.args[0]
    assert args[:4] == ["database", "page", "update", "page-123"]
    assert "--number" not in args
    assert "--text" not in args
    properties_index = args.index("--properties")
    properties_payload = json.loads(args[properties_index + 1])
    assert properties_payload == {
        "Publish Date": {"date": {"start": "2026-05-18"}},
        "Stage Date": {"date": {"start": "2026-05-17"}},
    }


def test_update_article_routes_numeric_properties_through_number_flag():
    with patch("ata_blog_cli.client.get_config", return_value=_config()):
        client = AtaBlogClient()

    with patch.object(client, "_run_notion", return_value=_result({"id": "page-123"})) as mock_run:
        result = client.update_article(
            "page-123",
            properties={"Dev Review Iterations": "2"},
        )

    assert result == {"id": "page-123"}
    mock_run.assert_called_once_with(
        [
            "database",
            "page",
            "update",
            "page-123",
            "--number",
            "Dev Review Iterations:2",
        ]
    )


def test_update_article_routes_intro_archetype_through_select_flag():
    with patch("ata_blog_cli.client.get_config", return_value=_config()):
        client = AtaBlogClient()

    with patch.object(client, "_run_notion", return_value=_result({"id": "page-123"})) as mock_run:
        result = client.update_article(
            "page-123",
            properties={"Intro Archetype": "Warning"},
        )

    assert result == {"id": "page-123"}
    mock_run.assert_called_once_with(
        [
            "database",
            "page",
            "update",
            "page-123",
            "--select",
            "Intro Archetype:Warning",
        ]
    )
