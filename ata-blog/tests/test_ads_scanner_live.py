"""Live e2e tests for the ads scanner.

Gated by ATA_BLOG_LIVE_TESTS=1 so CI skips by default.
Run manually before shipping:

    ATA_BLOG_LIVE_TESTS=1 pytest tests/test_ads_scanner_live.py -v
"""
import os

import pytest

from ata_blog_cli.ads_scanner import scan_page

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("ATA_BLOG_LIVE_TESTS") != "1",
        reason="set ATA_BLOG_LIVE_TESTS=1 to run live ad-server tests",
    ),
    pytest.mark.exercises_live_browser,
]

LIVE_URL = "https://adamtheautomator.com/how-to-sign-powershell-script"


def test_live_scan_known_good_page_has_ads():
    result = scan_page(LIVE_URL, checks=2, interval=2, per_check_timeout=30)
    assert result["gpt_detected"] is True, (
        f"Expected GPT on {LIVE_URL} but got gpt_detected=false; "
        f"check whether site still serves Google ads or Playwright is blocked. "
        f"Full result: {result}"
    )
    assert len(result["unique_advertisers"]) >= 1, (
        f"Expected >=1 advertiser on {LIVE_URL}; got 0. Full result: {result}"
    )
    assert result["total_impressions"] >= 1
