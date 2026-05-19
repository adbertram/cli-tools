"""Integration tests for `ata-blog wordpress-post get/list --include-ads`.

Mocks subprocess.run (wordpress CLI) and ads_scanner.scan_pages.
"""
import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from ata_blog_cli.commands.wordpress_post import app


@pytest.fixture
def runner():
    return CliRunner()


def _mock_subprocess_json(stdout_obj, returncode=0, stderr=""):
    """Return a MagicMock that mimics subprocess.run result."""
    result = MagicMock()
    result.stdout = json.dumps(stdout_obj) if not isinstance(stdout_obj, str) else stdout_obj
    result.stderr = stderr
    result.returncode = returncode
    return result


def _canned_scan(url, **_):
    """Default canned scan result for a given URL."""
    return {
        "url": url,
        "scanned_at": "2026-04-21T14:30:00Z",
        "checks_completed": 3,
        "duration_seconds": 1.0,
        "gpt_detected": True,
        "unique_advertisers": [
            {"domain": "digicert.com", "advertiser_id": "4532817",
             "creative_ids": ["100"], "slot": "div-gpt-ad-h", "appearances": 1, "share": 1.0},
        ],
        "total_impressions": 1,
    }


# ========== Passthrough regression tests ==========

def test_get_without_include_ads_is_pure_passthrough(runner, sample_wp_post):
    """Without --include-ads, posts_get must invoke wordpress CLI unchanged."""
    with patch("ata_blog_cli.commands.wordpress_post.subprocess.run") as mock_run, \
         patch("ata_blog_cli.commands._ads_helpers.scan_pages") as mock_scan:
        mock_run.return_value = MagicMock(returncode=0)
        result = runner.invoke(app, ["get", "26786"])
        assert result.exit_code == 0
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[:3] == ["wordpress", "posts", "get"]
        assert "26786" in cmd
        mock_scan.assert_not_called()


def test_get_without_include_ads_preserves_extra_args(runner):
    """Extra flags should reach subprocess unchanged (positional first, extras after)."""
    with patch("ata_blog_cli.commands.wordpress_post.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = runner.invoke(app, ["get", "26786", "-p", "id,title"])
        assert result.exit_code == 0
        cmd = mock_run.call_args[0][0]
        assert "-p" in cmd
        assert "id,title" in cmd


def test_list_without_include_ads_is_pure_passthrough(runner):
    with patch("ata_blog_cli.commands.wordpress_post.subprocess.run") as mock_run, \
         patch("ata_blog_cli.commands._ads_helpers.scan_pages") as mock_scan:
        mock_run.return_value = MagicMock(returncode=0)
        result = runner.invoke(app, ["list", "--limit", "5"])
        assert result.exit_code == 0
        mock_run.assert_called_once()
        mock_scan.assert_not_called()


# ========== Merge shape ==========

def test_get_with_include_ads_merges_top_level_ads_key(runner, sample_wp_post):
    scan_result = _canned_scan(sample_wp_post["link"])
    with patch("ata_blog_cli.commands._ads_helpers.subprocess.run") as mock_run, \
         patch("ata_blog_cli.commands._ads_helpers.scan_pages", return_value=[scan_result]):
        mock_run.return_value = _mock_subprocess_json(sample_wp_post)
        result = runner.invoke(app, ["get", "--include-ads", "26786"])
        assert result.exit_code == 0, result.stderr
        out = json.loads(result.stdout)
        # Original keys preserved
        assert out["id"] == sample_wp_post["id"]
        assert out["slug"] == sample_wp_post["slug"]
        assert out["link"] == sample_wp_post["link"]
        # New top-level `ads` key
        assert "ads" in out
        assert out["ads"]["url"] == sample_wp_post["link"]
        assert len(out["ads"]["unique_advertisers"]) == 1


def test_get_with_include_ads_uses_link_field_as_url(runner, sample_wp_post):
    with patch("ata_blog_cli.commands._ads_helpers.subprocess.run") as mock_run, \
         patch("ata_blog_cli.commands._ads_helpers.scan_pages") as mock_scan:
        mock_scan.return_value = [_canned_scan(sample_wp_post["link"])]
        mock_run.return_value = _mock_subprocess_json(sample_wp_post)
        runner.invoke(app, ["get", "--include-ads", "26786"])
        mock_scan.assert_called_once()
        args, kwargs = mock_scan.call_args
        urls = args[0] if args else kwargs.get("urls")
        assert urls == [sample_wp_post["link"]]


def test_get_with_include_ads_passes_tuning_flags(runner, sample_wp_post):
    with patch("ata_blog_cli.commands._ads_helpers.subprocess.run") as mock_run, \
         patch("ata_blog_cli.commands._ads_helpers.scan_pages") as mock_scan:
        mock_scan.return_value = [_canned_scan(sample_wp_post["link"])]
        mock_run.return_value = _mock_subprocess_json(sample_wp_post)
        runner.invoke(app, [
            "get",
            "--include-ads", "--ad-checks", "1", "--ad-interval", "2", "--ad-timeout", "10",
            "26786",
        ])
        _, kwargs = mock_scan.call_args
        assert kwargs.get("checks") == 1
        assert kwargs.get("interval") == 2
        assert kwargs.get("per_check_timeout") == 10


def test_get_with_include_ads_auto_injects_link_into_properties(runner, sample_wp_post):
    """When --properties is set but excludes 'link', 'link' must be injected."""
    with patch("ata_blog_cli.commands._ads_helpers.subprocess.run") as mock_run, \
         patch("ata_blog_cli.commands._ads_helpers.scan_pages") as mock_scan:
        mock_scan.return_value = [_canned_scan(sample_wp_post["link"])]
        mock_run.return_value = _mock_subprocess_json(sample_wp_post)
        runner.invoke(app, [
            "get", "--include-ads", "26786", "-p", "title",
        ])
        cmd = mock_run.call_args[0][0]
        # Find properties arg
        assert "-p" in cmd or "--properties" in cmd or any(a.startswith("--properties=") for a in cmd)
        # Join and check 'link' is included
        joined = " ".join(cmd)
        assert "link" in joined


# ========== Error paths ==========

def test_get_with_include_ads_missing_link_exits_nonzero(runner):
    """Post without 'link' field must fail fast; scan NOT called."""
    bad_post = {"id": 26786, "slug": "x", "title": "X"}  # no link
    with patch("ata_blog_cli.commands._ads_helpers.subprocess.run") as mock_run, \
         patch("ata_blog_cli.commands._ads_helpers.scan_pages") as mock_scan:
        mock_run.return_value = _mock_subprocess_json(bad_post)
        result = runner.invoke(app, ["get", "--include-ads", "26786"])
        assert result.exit_code != 0
        mock_scan.assert_not_called()


def test_get_with_include_ads_malformed_json_propagates(runner):
    with patch("ata_blog_cli.commands._ads_helpers.subprocess.run") as mock_run, \
         patch("ata_blog_cli.commands._ads_helpers.scan_pages") as mock_scan:
        mock_run.return_value = MagicMock(returncode=0, stdout="not json at all", stderr="")
        result = runner.invoke(app, ["get", "--include-ads", "26786"])
        assert result.exit_code != 0
        mock_scan.assert_not_called()


def test_get_table_and_include_ads_rejected(runner):
    result = runner.invoke(app, ["get", "--table", "--include-ads", "26786"])
    assert result.exit_code != 0
    # Typer surfaces BadParameter to stderr
    combined = (result.stderr or "") + (result.stdout or "")
    assert "cannot combine --table" in combined.lower() or "table" in combined.lower()


def test_list_table_and_include_ads_rejected(runner):
    result = runner.invoke(app, ["list", "--table", "--include-ads"])
    assert result.exit_code != 0


def test_get_with_include_ads_scanner_raises_propagates(runner, sample_wp_post):
    from cli_tools_shared.browser import PlaywrightServiceError
    with patch("ata_blog_cli.commands._ads_helpers.subprocess.run") as mock_run, \
         patch("ata_blog_cli.commands._ads_helpers.scan_pages",
               side_effect=PlaywrightServiceError("nope")):
        mock_run.return_value = _mock_subprocess_json(sample_wp_post)
        result = runner.invoke(app, ["get", "--include-ads", "26786"])
        assert result.exit_code != 0
        assert result.exit_code == 1 or isinstance(result.exception, PlaywrightServiceError)


def test_get_with_include_ads_scanner_value_error_propagates(runner, sample_wp_post):
    with patch("ata_blog_cli.commands._ads_helpers.subprocess.run") as mock_run, \
         patch("ata_blog_cli.commands._ads_helpers.scan_pages",
               side_effect=ValueError("bad params")):
        mock_run.return_value = _mock_subprocess_json(sample_wp_post)
        result = runner.invoke(app, ["get", "--include-ads", "26786"])
        assert result.exit_code != 0


def test_get_invalid_post_id_no_scan(runner):
    with patch("ata_blog_cli.commands._ads_helpers.subprocess.run") as mock_run, \
         patch("ata_blog_cli.commands._ads_helpers.scan_pages") as mock_scan:
        mock_run.return_value = MagicMock(returncode=1, stderr="post not found", stdout="")
        result = runner.invoke(app, ["get", "--include-ads", "99999999"])
        assert result.exit_code != 0
        mock_scan.assert_not_called()


# ========== List behavior ==========

def test_list_with_include_ads_uses_scan_pages(runner, sample_wp_list):
    """List should call scan_pages ONCE with all links, not scan_page per item."""
    scans = [_canned_scan(p["link"]) for p in sample_wp_list[:2]]
    with patch("ata_blog_cli.commands._ads_helpers.subprocess.run") as mock_run, \
         patch("ata_blog_cli.commands._ads_helpers.scan_pages", return_value=scans) as mock_scan:
        mock_run.return_value = _mock_subprocess_json(sample_wp_list[:2])
        result = runner.invoke(app, ["list", "--limit", "2", "--include-ads"])
        assert result.exit_code == 0, result.stderr
        mock_scan.assert_called_once()
        args, _kwargs = mock_scan.call_args
        assert args[0] == [sample_wp_list[0]["link"], sample_wp_list[1]["link"]]


def test_list_with_include_ads_merges_per_item_ads_key(runner, sample_wp_list):
    scans = [_canned_scan(p["link"]) for p in sample_wp_list]
    with patch("ata_blog_cli.commands._ads_helpers.subprocess.run") as mock_run, \
         patch("ata_blog_cli.commands._ads_helpers.scan_pages", return_value=scans):
        mock_run.return_value = _mock_subprocess_json(sample_wp_list)
        result = runner.invoke(app, ["list", "--include-ads"])
        assert result.exit_code == 0, result.stderr
        out = json.loads(result.stdout)
        assert isinstance(out, list)
        assert len(out) == 3
        for item in out:
            assert "ads" in item


def test_list_with_include_ads_warns_when_3_or_more(runner, sample_wp_list):
    scans = [_canned_scan(p["link"]) for p in sample_wp_list]
    with patch("ata_blog_cli.commands._ads_helpers.subprocess.run") as mock_run, \
         patch("ata_blog_cli.commands._ads_helpers.scan_pages", return_value=scans):
        mock_run.return_value = _mock_subprocess_json(sample_wp_list)
        result = runner.invoke(app, ["list", "--include-ads"])
        assert result.exit_code == 0
        # Warning on stderr
        assert "Scanning" in (result.stderr or "") or "3 posts" in (result.stderr or "")


def test_list_with_include_ads_no_warning_below_3(runner, sample_wp_list):
    two = sample_wp_list[:2]
    scans = [_canned_scan(p["link"]) for p in two]
    with patch("ata_blog_cli.commands._ads_helpers.subprocess.run") as mock_run, \
         patch("ata_blog_cli.commands._ads_helpers.scan_pages", return_value=scans):
        mock_run.return_value = _mock_subprocess_json(two)
        result = runner.invoke(app, ["list", "--limit", "2", "--include-ads"])
        assert result.exit_code == 0
        assert "Scanning" not in (result.stderr or "")


def test_list_with_include_ads_first_item_fails_stops_batch(runner, sample_wp_list):
    """When scan_pages raises, the whole batch fails (fail-fast)."""
    from cli_tools_shared.browser import PlaywrightServiceError
    with patch("ata_blog_cli.commands._ads_helpers.subprocess.run") as mock_run, \
         patch("ata_blog_cli.commands._ads_helpers.scan_pages",
               side_effect=PlaywrightServiceError("boom")):
        mock_run.return_value = _mock_subprocess_json(sample_wp_list)
        result = runner.invoke(app, ["list", "--include-ads"])
        assert result.exit_code != 0


def test_list_sponsored_and_include_ads_warns(runner, sample_wp_list):
    """--sponsored + --include-ads should warn that ads are disabled on sponsored posts."""
    two = sample_wp_list[:2]
    scans = [_canned_scan(p["link"]) for p in two]
    with patch("ata_blog_cli.commands._ads_helpers.subprocess.run") as mock_run, \
         patch("ata_blog_cli.commands._ads_helpers.scan_pages", return_value=scans):
        mock_run.return_value = _mock_subprocess_json(two)
        result = runner.invoke(app, ["list", "--limit", "2", "--sponsored", "--include-ads"])
        assert result.exit_code == 0
        stderr = result.stderr or ""
        assert "sponsored" in stderr.lower() and "ads" in stderr.lower()
