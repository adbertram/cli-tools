"""Unit coverage for command fixture argument construction."""

from cli_test_utils import get_fixture_args


def test_get_fixture_args_supports_valueless_boolean_flags():
    test_config = {
        "cli_specific": {
            "notion": {
                "param_fixtures": {
                    "comments list": {
                        "--page-id": "page_id",
                        "--open-only": True,
                    }
                }
            }
        }
    }

    args = get_fixture_args(
        "notion",
        "comments list",
        {"page_id": "page-123"},
        test_config,
    )

    assert args == ["--page-id", "page-123", "--open-only"]
