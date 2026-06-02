from typer.testing import CliRunner

from impact_cli.main import app
from impact_cli.models import create_resource
from impact_cli.commands import ads, jobs


runner = CliRunner()


class FakeAdsClient:
    def __init__(self):
        self.calls = []

    def list_ads(self, limit=100, filters=None):
        self.calls.append(("list_ads", limit, filters))
        return [
            create_resource({"Id": "A1", "Name": "Banner", "CampaignId": "C1"}),
            create_resource({"Id": "A2", "Name": "Text", "CampaignId": "C1"}),
        ]

    def get_ad(self, ad_id):
        self.calls.append(("get_ad", ad_id))
        return create_resource({"Id": ad_id, "Name": "Banner"})


class FakeJobsClient:
    def __init__(self):
        self.calls = []

    def replay_job(self, job_id):
        self.calls.append(("replay_job", job_id))
        return create_resource({"Id": job_id, "Status": "QUEUED"})


def test_ads_list_supports_limit_filter_properties(monkeypatch):
    fake = FakeAdsClient()
    monkeypatch.setattr(ads, "get_client", lambda: fake)

    result = runner.invoke(
        app,
        [
            "ads",
            "list",
            "--limit",
            "2",
            "--filter",
            "CampaignId:eq:C1",
            "--properties",
            "Id,Name",
        ],
    )

    assert result.exit_code == 0, result.output
    assert fake.calls == [("list_ads", 2, ["CampaignId:eq:C1"])]
    assert '"Id": "A1"' in result.output
    assert '"Name": "Banner"' in result.output
    assert "CampaignId" not in result.output


def test_ads_get_is_task_named(monkeypatch):
    fake = FakeAdsClient()
    monkeypatch.setattr(ads, "get_client", lambda: fake)

    result = runner.invoke(app, ["ads", "get", "A1"])

    assert result.exit_code == 0, result.output
    assert fake.calls == [("get_ad", "A1")]
    assert '"Id": "A1"' in result.output


def test_jobs_replay_requires_force(monkeypatch):
    fake = FakeJobsClient()
    monkeypatch.setattr(jobs, "get_client", lambda: fake)

    blocked = runner.invoke(app, ["jobs", "replay", "J1"])

    assert blocked.exit_code == 1
    assert fake.calls == []
    assert "--force" in blocked.output

    allowed = runner.invoke(app, ["jobs", "replay", "J1", "--force"])

    assert allowed.exit_code == 0, allowed.output
    assert fake.calls == [("replay_job", "J1")]
