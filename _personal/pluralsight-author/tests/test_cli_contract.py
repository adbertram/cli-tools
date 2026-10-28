import json
import tempfile
from pathlib import Path

from cli_tools_shared.data_cache import reset_cache_hit
from typer.testing import CliRunner

from pluralsight_author_cli.client import PluralsightAuthorClient
from pluralsight_author_cli.commands.icons import COMMAND_CREDENTIALS as ICON_COMMAND_CREDENTIALS
from pluralsight_author_cli.config import (
    AUTH_METHOD_AUTHOR_KIT,
    AUTH_METHOD_OPPORTUNITIES,
    Config,
    get_config,
)
from pluralsight_author_cli.main import ICON_CREDENTIALS, app

TOOL_DIR = Path(__file__).resolve().parents[1]

ITEMS = [
    {
        "id": "security-course-may-11-2026",
        "title": "Security Course",
        "opportunity_type": "Video Course",
        "category": "Security",
        "posted_date": "May 11, 2026",
        "is_new": True,
        "page_number": 1,
    },
    {
        "id": "ux-course-may-10-2026",
        "title": "UX Course",
        "opportunity_type": "Video Course",
        "category": "Product & UX",
        "posted_date": "May 10, 2026",
        "is_new": False,
        "page_number": 1,
    },
]
ICONS = [
    {
        "id": "azure-cloud_Blue",
        "name": "Azure Cloud",
        "category": "Cloud",
        "color": "Blue",
        "tags": ["azure", "cloud"],
        "download_url": "zip://Blue/azure-cloud_Blue.png",
        "thumbnail_url": "",
        "source_url": "https://authors.pluralsight.com/icon-library/",
        "file_type": "png",
    },
    {
        "id": "security-shield_Pink",
        "name": "Security Shield",
        "category": "Security",
        "color": "Pink",
        "tags": ["security", "shield"],
        "download_url": "zip://Pink/security-shield_Pink.png",
        "thumbnail_url": "",
        "source_url": "https://authors.pluralsight.com/icon-library/",
        "file_type": "png",
    },
]


def test_icon_commands_do_not_require_browser_credentials():
    assert set(ICON_CREDENTIALS) == {"import", "list", "search", "get", "download"}
    assert ICON_CREDENTIALS == ICON_COMMAND_CREDENTIALS
    assert all(
        credential_types == [AUTH_METHOD_AUTHOR_KIT, "no_auth"]
        for credential_types in ICON_CREDENTIALS.values()
    )


def install_profiles(monkeypatch, auth_types=(AUTH_METHOD_OPPORTUNITIES, AUTH_METHOD_AUTHOR_KIT)):
    data_home = Path(tempfile.mkdtemp(prefix="pluralsight-author-cli-test-"))
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setenv("CLI_TOOL_DIR_PLURALSIGHT_AUTHOR_CLI", str(TOOL_DIR))
    profiles_dir = data_home / "cli-tools" / "pluralsight-author" / "authentication_profiles"
    for auth_type in auth_types:
        profile_dir = profiles_dir / auth_type
        profile_dir.mkdir(parents=True)
        (profile_dir / ".env").write_text(f"ACTIVE=true\nAUTH_METHOD={auth_type}\n")
    monkeypatch.setattr(Config, "has_saved_session", lambda self: True)
    get_config.cache_clear()


def install_client(monkeypatch, auth_types=(AUTH_METHOD_OPPORTUNITIES, AUTH_METHOD_AUTHOR_KIT)):
    install_profiles(monkeypatch, auth_types)
    monkeypatch.setattr(PluralsightAuthorClient, "list_opportunities", lambda self, limit=1000: ITEMS[:limit])
    monkeypatch.setattr(
        PluralsightAuthorClient,
        "search",
        lambda self, query, limit=100: [
            item for item in ITEMS if query.casefold() in f"{item['title']} {item['category']}".casefold()
        ][:limit],
    )
    monkeypatch.setattr(
        PluralsightAuthorClient,
        "get_item",
        lambda self, item_id: {
            **next(item for item in ITEMS if item["id"] == item_id),
            "learning_objectives": [
                "1. Evaluate a strategic decision against a chain of evidence",
                "2. Distinguish signal from noise in product data",
            ],
        },
    )
    monkeypatch.setattr(
        PluralsightAuthorClient,
        "list_icons",
        lambda self, limit=0: ICONS[:limit] if limit > 0 else ICONS,
    )
    def fake_search_icons(self, query, limit=0):
        matches = [
            item
            for item in ICONS
            if query.casefold()
            in f"{item['name']} {item['category']} {item['color']} {' '.join(item['tags'])}".casefold()
        ]
        return matches[:limit] if limit > 0 else matches

    monkeypatch.setattr(PluralsightAuthorClient, "search_icons", fake_search_icons)

    def icon_by_id(item_id, color=None):
        target_color = "Pink" if color and color.casefold() == "pink" else color
        rows = [item for item in ICONS if not target_color or item["color"] == target_color]
        return next(
            item
            for item in rows
            if item["id"] == item_id or item["id"].rsplit("_", 1)[0] == item_id
        )

    monkeypatch.setattr(
        PluralsightAuthorClient,
        "get_icon",
        lambda self, item_id, color=None: icon_by_id(item_id, color),
    )

    def fake_download_icon(self, item_id, output, color=None):
        target = Path(output)
        target.write_bytes(b"\x89PNG\r\n\x1a\nicon")
        item = icon_by_id(item_id, color)
        return {**item, "output": str(target), "bytes": target.stat().st_size, "content_type": "image/png"}

    monkeypatch.setattr(PluralsightAuthorClient, "download_icon", fake_download_icon)
    monkeypatch.setattr(
        PluralsightAuthorClient,
        "import_icon_archive",
        lambda self, source: {
            "cache_path": str(Path(self.config.storage_dir) / "icon-library.zip"),
            "bytes": Path(source).stat().st_size,
            "sha256": "test-sha256",
            "icon_count": 1,
            "asset_count": 8,
            "colors": ["Blue", "Green", "Inky Blue", "Orange", "Pink", "Purple", "White", "Yellow"],
            "file_type": "png",
        },
    )
    monkeypatch.setattr(
        PluralsightAuthorClient,
        "apply",
        lambda self, item_id, params: {
            "id": item_id,
            "title": next(item for item in ITEMS if item["id"] == item_id)["title"],
            "detail_url": "https://app.pluralsight.com/author-home/opportunity/detail-id-2",
            "submitted_param_keys": sorted(params.keys()),
            "form_markers": [
                "Application for:",
                "Tell us about your availability and domain expertise.",
                "Send application",
            ],
            "post_submit_state": "application_form_closed",
        },
    )


def invoke(monkeypatch, args):
    install_client(monkeypatch)
    reset_cache_hit()
    result = CliRunner().invoke(app, args)
    reset_cache_hit()
    get_config.cache_clear()
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_opportunities_list_filters_and_selects_properties(monkeypatch):
    assert invoke(
        monkeypatch,
        ["opportunities", "list", "--filter", "category:eq:Security", "--properties", "id,title"],
    ) == [{"id": "security-course-may-11-2026", "title": "Security Course"}]


def test_opportunities_get_returns_single_opportunity(monkeypatch):
    assert invoke(monkeypatch, ["opportunities", "get", "ux-course-may-10-2026"]) == {
        **ITEMS[1],
        "learning_objectives": [
            "1. Evaluate a strategic decision against a chain of evidence",
            "2. Distinguish signal from noise in product data",
        ],
    }


def test_opportunities_get_with_properties_returns_single_object(monkeypatch):
    assert invoke(
        monkeypatch,
        ["opportunities", "get", "ux-course-may-10-2026", "--properties", "id,title"],
    ) == {"id": "ux-course-may-10-2026", "title": "UX Course"}


def test_opportunities_apply_returns_verified_submission_state(monkeypatch):
    assert invoke(
        monkeypatch,
        [
            "opportunities",
            "apply",
            "ux-course-may-10-2026",
            "--start_date",
            "06/01/2026",
            "--estimated_completion_weeks",
            "8",
            "--experience",
            "Built several accessibility-focused UX courses.",
        ],
    ) == {
        "id": "ux-course-may-10-2026",
        "title": "UX Course",
        "detail_url": "https://app.pluralsight.com/author-home/opportunity/detail-id-2",
        "submitted_param_keys": ["estimated_completion_weeks", "experience", "start_date"],
        "form_markers": [
            "Application for:",
            "Tell us about your availability and domain expertise.",
            "Send application",
        ],
        "post_submit_state": "application_form_closed",
    }


def test_opportunities_apply_accepts_explicit_options_and_passes_dict(monkeypatch):
    captured = {}

    def fake_apply(self, item_id, params):
        captured["item_id"] = item_id
        captured["params"] = params
        return {
            "id": item_id,
            "title": "Security Course",
            "detail_url": "https://app.pluralsight.com/author-home/opportunity/detail-id-1",
            "submitted_param_keys": sorted(params.keys()),
            "form_markers": [
                "Application for:",
                "Tell us about your availability and domain expertise.",
                "Send application",
            ],
            "post_submit_state": "application_form_closed",
        }

    install_profiles(monkeypatch)
    monkeypatch.setattr(PluralsightAuthorClient, "list_opportunities", lambda self, limit=1000: ITEMS[:limit])
    monkeypatch.setattr(PluralsightAuthorClient, "apply", fake_apply)
    reset_cache_hit()
    result = CliRunner().invoke(
        app,
        [
            "opportunities",
            "apply",
            "security-course-may-11-2026",
            "--start_date",
            "06/01/2026",
            "--estimated_completion_weeks",
            "8",
            "--experience",
            "Hands-on security course delivery.",
        ],
    )
    reset_cache_hit()
    get_config.cache_clear()

    assert result.exit_code == 0, result.output
    assert captured == {
        "item_id": "security-course-may-11-2026",
        "params": {
            "start_date": "06/01/2026",
            "estimated_completion_weeks": "8",
            "experience": "Hands-on security course delivery.",
        },
    }


def test_opportunities_apply_fails_when_required_option_is_missing_before_client_invocation(monkeypatch):
    invoked = {"apply_called": False}

    def fail_if_called(self, item_id, params):
        del self, item_id, params
        invoked["apply_called"] = True
        raise AssertionError("apply should not be called when required options are missing")

    monkeypatch.setattr(PluralsightAuthorClient, "apply", fail_if_called)
    reset_cache_hit()
    result = CliRunner().invoke(
        app,
        [
            "opportunities",
            "apply",
            "security-course-may-11-2026",
            "--start_date",
            "06/01/2026",
            "--estimated_completion_weeks",
            "8",
        ],
    )
    reset_cache_hit()

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "Missing option '--experience'" in result.stderr
    assert invoked["apply_called"] is False


def test_opportunities_apply_fails_when_start_date_option_is_missing_before_client_invocation(monkeypatch):
    invoked = {"apply_called": False}

    def fail_if_called(self, item_id, params):
        del self, item_id, params
        invoked["apply_called"] = True
        raise AssertionError("apply should not be called when required options are missing")

    monkeypatch.setattr(PluralsightAuthorClient, "apply", fail_if_called)
    reset_cache_hit()
    result = CliRunner().invoke(
        app,
        [
            "opportunities",
            "apply",
            "security-course-may-11-2026",
            "--estimated_completion_weeks",
            "8",
            "--experience",
            "Hands-on security course delivery.",
        ],
    )
    reset_cache_hit()

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "Missing option '--start_date'" in result.stderr
    assert invoked["apply_called"] is False


def test_search_query_selects_properties(monkeypatch):
    assert invoke(monkeypatch, ["search", "query", "security", "--properties", "id,category"]) == [
        {"id": "security-course-may-11-2026", "category": "Security"}
    ]


def test_icons_list_filters_and_selects_properties(monkeypatch):
    assert invoke(
        monkeypatch,
        ["icons", "list", "--filter", "category:eq:Security", "--properties", "id,name,color"],
    ) == [{"id": "security-shield_Pink", "name": "Security Shield", "color": "Pink"}]


def test_icons_list_filters_by_tag(monkeypatch):
    assert invoke(monkeypatch, ["icons", "list", "--filter", "tag:contains:azure", "--properties", "id"]) == [
        {"id": "azure-cloud_Blue"}
    ]


def test_icons_list_filters_by_color_option(monkeypatch):
    assert invoke(monkeypatch, ["icons", "list", "--color", "pink", "--properties", "id,color"]) == [
        {"id": "security-shield_Pink", "color": "Pink"}
    ]


def test_icons_list_applies_multiple_filter_flags_as_constraints(monkeypatch):
    assert invoke(
        monkeypatch,
        [
            "icons",
            "list",
            "--filter",
            "category:eq:Cloud",
            "--filter",
            "color:eq:Blue",
            "--filter",
            "tag:contains:azure",
            "--properties",
            "id,name,category,color",
        ],
    ) == [{"id": "azure-cloud_Blue", "name": "Azure Cloud", "category": "Cloud", "color": "Blue"}]


def test_icons_search_selects_properties(monkeypatch):
    assert invoke(monkeypatch, ["icons", "search", "cloud", "--properties", "id,name"]) == [
        {"id": "azure-cloud_Blue", "name": "Azure Cloud"}
    ]


def test_icons_search_filters_by_color_option(monkeypatch):
    assert invoke(monkeypatch, ["icons", "search", "shield", "--color", "pink", "--properties", "id,color"]) == [
        {"id": "security-shield_Pink", "color": "Pink"}
    ]


def test_icons_get_returns_single_icon(monkeypatch):
    assert invoke(monkeypatch, ["icons", "get", "azure-cloud_Blue"]) == ICONS[0]


def test_icons_get_returns_requested_color_variant(monkeypatch):
    assert invoke(monkeypatch, ["icons", "get", "security-shield", "--color", "pink"]) == ICONS[1]


def test_icons_get_with_properties_returns_single_object(monkeypatch):
    assert invoke(
        monkeypatch,
        ["icons", "get", "azure-cloud_Blue", "--properties", "id,name,color"],
    ) == {"id": "azure-cloud_Blue", "name": "Azure Cloud", "color": "Blue"}


def test_icons_get_supports_table_output(monkeypatch):
    install_client(monkeypatch)
    reset_cache_hit()
    result = CliRunner().invoke(app, ["icons", "get", "azure-cloud_Blue", "--table"])
    reset_cache_hit()
    get_config.cache_clear()

    assert result.exit_code == 0, result.output
    assert "name" in result.stdout
    assert "Azure Cloud" in result.stdout


def test_icons_download_writes_non_empty_file(monkeypatch, tmp_path):
    output = tmp_path / "icon.png"

    result = invoke(monkeypatch, ["icons", "download", "azure-cloud_Blue", "--output", str(output)])

    assert output.read_bytes() == b"\x89PNG\r\n\x1a\nicon"
    assert result["output"] == str(output)
    assert result["bytes"] > 0


def test_icons_download_writes_requested_color_variant(monkeypatch, tmp_path):
    output = tmp_path / "icon.png"

    result = invoke(
        monkeypatch,
        ["icons", "download", "security-shield", "--color", "pink", "--output", str(output)],
    )

    assert output.read_bytes() == b"\x89PNG\r\n\x1a\nicon"
    assert result["id"] == "security-shield_Pink"
    assert result["color"] == "Pink"


def test_icons_import_returns_cache_metadata(monkeypatch, tmp_path):
    archive = tmp_path / "legacy-icons.zip"
    archive.write_bytes(b"legacy archive")

    result = invoke(monkeypatch, ["icons", "import", str(archive)])

    assert result["bytes"] == archive.stat().st_size
    assert result["asset_count"] == 8
    assert result["file_type"] == "png"


def test_icons_cache_command_is_not_registered(monkeypatch):
    install_client(monkeypatch)
    reset_cache_hit()
    result = CliRunner().invoke(app, ["icons", "cache"])
    reset_cache_hit()
    get_config.cache_clear()

    assert result.exit_code == 2
    assert "No such command" in result.stderr
    assert "cache" in result.stderr


def test_opportunities_reject_author_kit_profile(monkeypatch):
    install_client(monkeypatch)
    reset_cache_hit()
    result = CliRunner().invoke(app, ["opportunities", "list", "--profile", AUTH_METHOD_AUTHOR_KIT])
    reset_cache_hit()
    get_config.cache_clear()

    assert result.exit_code != 0
    assert "requires auth type 'opportunities'" in result.output


def test_icons_reject_opportunities_profile(monkeypatch):
    install_client(monkeypatch)
    reset_cache_hit()
    result = CliRunner().invoke(app, ["icons", "list", "--profile", AUTH_METHOD_OPPORTUNITIES])
    reset_cache_hit()
    get_config.cache_clear()

    assert result.exit_code != 0
    assert "requires auth type 'author_kit'" in result.output
