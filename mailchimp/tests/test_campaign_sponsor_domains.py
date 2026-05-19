import json
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from mailchimp_cli.commands.campaigns import extract_sponsor_domains_from_html
from mailchimp_cli.main import app


class FakeCampaignClient:
    def get_campaign(self, campaign_id):
        return {"id": campaign_id, "type": "regular"}

    def get_campaign_report(self, campaign_id):
        return {
            "id": campaign_id,
            "emails_sent": 100,
            "opens": {"unique_opens": 40, "open_rate": 0.4},
            "clicks": {"unique_clicks": 8, "click_rate": 0.08},
            "bounces": {"hard_bounces": 1, "soft_bounces": 1},
            "unsubscribed": 1,
            "send_time": "2026-04-20T09:00:00+00:00",
        }

    def get_campaign_content(self, campaign_id):
        return {
            "html": """
<h2>Messages from our Sponsors</h2>
<a href="https://www.specopssoft.com/key-recovery">Specops</a>
"""
        }


class CampaignSponsorDomainTests(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()

    def test_extract_sponsor_domains_from_html_returns_matching_domains_only(self):
        html = """
<h2>Messages from our Sponsors</h2>
<a href="https://www.specopssoft.com/key-recovery">Specops</a>
<a href="https://example.com/nope">Other</a>
"""

        self.assertEqual(
            extract_sponsor_domains_from_html(html, ["specopssoft.com", "scriptrunner.com"]),
            ["specopssoft.com"],
        )

    def test_report_accepts_sponsor_domains_without_sponsor_names(self):
        fake_client = FakeCampaignClient()

        with patch("mailchimp_cli.commands.campaigns.get_client", return_value=fake_client):
            result = self.runner.invoke(
                app,
                ["campaigns", "report", "abc123", "--sponsor-domain", "specopssoft.com"],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["sponsor_domains"], ["specopssoft.com"])
        self.assertNotIn("sponsor", payload)


if __name__ == "__main__":
    unittest.main()
