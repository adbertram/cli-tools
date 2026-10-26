"""Synthetic capture import, secret scoping, and target binding checks."""
import json
from unittest.mock import Mock, patch

import pytest

from roomba_cli.client import ClientError
from roomba_cli.commands.cloud import import_capture, run_read
from test_cloud import CREDS, template


class Config:
    def __init__(self, path): self.path = path
    def get_default_robot(self): return "synthetic"
    def get_robot(self, name): return {"blid": "synthetic-robot"} if name == "synthetic" else None
    def get_profile_data_dir(self): return self.path


def captured():
    return {"credentials": CREDS, "robots": [{"id": "synthetic-robot", "name": "synthetic", "sku": "synthetic-sku"}], "requests": [dict(template(), region="us-east-1")]}


def test_import_stores_only_credentials_and_supported_bound_templates(tmp_path):
    config = Config(tmp_path)
    data = captured()
    wrong = dict(template(), url="https://auth3.prod.iot.irobotapi.com/v1/robots/unrelated/setupinfo", region="us-east-1")
    data["requests"].append(wrong)
    result = Mock(returncode=0, stdout=json.dumps(data))
    with patch("roomba_cli.commands.cloud.subprocess.run", return_value=result) as decoder, patch("roomba_cli.commands.cloud.secret") as secret:
        imported = import_capture(config, tmp_path / "synthetic.flows")
    assert imported["resources"] == ["setup"]
    secret.assert_called_once_with(config, "set", CREDS)
    saved = tmp_path / "cloud-session.json"
    assert saved.stat().st_mode & 0o777 == 0o600
    raw = saved.read_text()
    assert "synthetic-secret" not in raw and "unrelated" not in raw
    assert decoder.call_args.kwargs["timeout"] == 120


@pytest.mark.parametrize("data", [[], None, {}, {"requests": "bad"}, dict(captured(), credentials={}), dict(captured(), robots=[]), dict(captured(), requests=[])])
def test_invalid_import_does_not_store_credentials(tmp_path, data):
    with patch("roomba_cli.commands.cloud.subprocess.run", return_value=Mock(returncode=0, stdout=json.dumps(data))), patch("roomba_cli.commands.cloud.secret") as secret:
        with pytest.raises(ClientError): import_capture(Config(tmp_path), tmp_path / "synthetic.flows")
        secret.assert_not_called()
    assert not (tmp_path / "cloud-session.json").exists()


def test_wrong_cloud_robot_refuses_before_secret_or_http(tmp_path):
    (tmp_path / "cloud-session.json").write_text(json.dumps({"robots": captured()["robots"], "templates": {"synthetic-robot": {"setup": template()}}}))
    with patch("roomba_cli.commands.cloud.secret") as secret, patch("roomba_cli.commands.cloud.read_resource") as read:
        with pytest.raises(ClientError, match="selection is missing"): run_read(Config(tmp_path), "setup", 15, "wrong")
        secret.assert_not_called(); read.assert_not_called()


def test_multiple_cloud_robots_keep_histories_isolated_and_allow_selection(tmp_path):
    from roomba_cli.commands.cloud import resolve_robot
    data = {"robots": [{"id": "a", "name": "same"}, {"id": "b", "name": "same"}]}
    config = Config(tmp_path)
    with pytest.raises(ClientError, match="Multiple cloud robots"): resolve_robot(config, data)
    with pytest.raises(ClientError, match="ambiguous"): resolve_robot(config, data, "same")
    assert resolve_robot(config, data, "b") == "b"
    data["default_robot_id"] = "b"
    assert resolve_robot(config, data) == "b"


def test_uncaptured_second_robot_resource_does_not_fall_back_to_first(tmp_path):
    data = {"robots": [{"id": "a"}, {"id": "b"}], "templates": {"a": {"setup": template()}}, "default_robot_id": "a"}
    (tmp_path / "cloud-session.json").write_text(json.dumps(data))
    with patch("roomba_cli.commands.cloud.secret") as secret, patch("roomba_cli.commands.cloud.read_resource") as read:
        with pytest.raises(ClientError, match="not captured"): run_read(Config(tmp_path), "setup", 15, "b")
        secret.assert_not_called(); read.assert_not_called()


def test_decoder_excludes_previous_accounts_templates_and_passwords(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path
    from types import ModuleType, SimpleNamespace
    import sys
    class Query:
        def items(self, multi=False): return []
    def login(key, robot):
        body = {"credentials": dict(CREDS, AccessKeyId=key), "robots": {robot: {"name": "synthetic", "sku": "synthetic", "password": "never-export-this"}}}
        return SimpleNamespace(request=SimpleNamespace(method="POST", scheme="https", port=443, host="unauth3.prod.iot.irobotapi.com", path="/v2/login"), response=SimpleNamespace(status_code=200, content=json.dumps(body).encode()))
    def read(key, household):
        headers = {"authorization": f"AWS4-HMAC-SHA256 Credential={key}/20260101/us-east-1/execute-api/aws4_request, SignedHeaders=x", "accept": "application/json", "content-type": "application/json", "user-agent": "synthetic"}
        return SimpleNamespace(request=SimpleNamespace(method="GET", scheme="https", port=443, host="auth3.prod.iot.irobotapi.com", path=f"/v1/households/{household}/settings/schedule", headers=headers, query=Query()), response=SimpleNamespace(status_code=200))
    flows = [login("key-a", "robot-a"), read("key-a", "household-a"), login("key-b", "robot-b"), read("key-b", "household-b")]
    fake = ModuleType("mitmproxy.io"); fake.FlowReader = lambda handle: SimpleNamespace(stream=lambda: iter(flows))
    monkeypatch.setitem(sys.modules, "mitmproxy", ModuleType("mitmproxy"))
    monkeypatch.setitem(sys.modules, "mitmproxy.io", fake)
    source = Path(__file__).parents[1] / "roomba_cli" / "capture_session.py"
    spec = importlib.util.spec_from_file_location("synthetic_capture_decoder", source)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    path = tmp_path / "synthetic.flows"; path.touch()
    result = module.decode(path)
    raw = json.dumps(result)
    assert "household-a" not in raw and "robot-a" not in raw
    assert "household-b" in raw and "robot-b" in raw
    assert "never-export-this" not in raw and "password" not in raw
    assert result["credentials"]["AccessKeyId"] == "key-b"


def test_cloud_select_changes_only_private_local_default(tmp_path):
    from typer.testing import CliRunner
    from roomba_cli.commands.cloud import app
    data = {"robots": [{"id": "a", "name": "one"}, {"id": "b", "name": "two"}], "templates": {}}
    (tmp_path / "cloud-session.json").write_text(json.dumps(data))
    with patch("roomba_cli.commands.cloud.get_config", return_value=Config(tmp_path)), patch("roomba_cli.commands.cloud.secret") as secret:
        result = CliRunner().invoke(app, ["select", "two"])
    assert result.exit_code == 0
    assert json.loads((tmp_path / "cloud-session.json").read_text())["default_robot_id"] == "b"
    assert (tmp_path / "cloud-session.json").stat().st_mode & 0o777 == 0o600
    secret.assert_not_called()


def test_cloud_import_and_inventory_work_without_any_lan_robots(tmp_path):
    from typer.testing import CliRunner
    from roomba_cli.commands.cloud import app
    class EmptyLAN(Config):
        def get_default_robot(self): return None
        def get_robot(self, name): return None
        def has_credentials(self): return False
    config = EmptyLAN(tmp_path)
    result = Mock(returncode=0, stdout=json.dumps(captured()))
    with patch("roomba_cli.commands.cloud.subprocess.run", return_value=result), patch("roomba_cli.commands.cloud.secret"):
        assert import_capture(config, tmp_path / "synthetic.flows")["imported"]
    with patch("roomba_cli.commands.cloud.get_config", return_value=config):
        result = CliRunner().invoke(app, ["robots", "list"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)[0]["id"] == "synthetic-robot"


def test_two_household_schedules_are_stored_only_for_their_member_robots(tmp_path):
    from test_cloud import template as setup_template
    first = setup_template()
    household = {"method": "GET", "url": "https://auth3.prod.iot.irobotapi.com/v1/households/household-a/settings/schedule", "headers": first["headers"], "query": [], "region": "us-east-1", "household_robot_ids": ["robot-a"]}
    other = dict(household, url="https://auth3.prod.iot.irobotapi.com/v1/households/household-b/settings/schedule", household_robot_ids=["robot-b"])
    data = {"credentials": CREDS, "robots": [{"id": "robot-a"}, {"id": "robot-b"}], "requests": [household, other]}
    with patch("roomba_cli.commands.cloud.subprocess.run", return_value=Mock(returncode=0, stdout=json.dumps(data))), patch("roomba_cli.commands.cloud.secret"):
        import_capture(Config(tmp_path), tmp_path / "synthetic.flows")
    saved = json.loads((tmp_path / "cloud-session.json").read_text())
    assert saved["templates"]["robot-a"]["schedule"]["url"] == household["url"]
    assert saved["templates"]["robot-b"]["schedule"]["url"] == other["url"]
    assert "schedule" not in saved["shared"]


@pytest.mark.parametrize("identity,old_deployment,admitted", [("same", "v011", True), ("other", "v011", False), ("same", "v005", False)])
def test_prior_key_requires_same_cognito_and_exact_robot_deployment(tmp_path, monkeypatch, identity, old_deployment, admitted):
    import importlib.util
    from pathlib import Path
    from types import ModuleType, SimpleNamespace
    import sys
    def login(key, account, deployment):
        body = {"credentials": dict(CREDS, AccessKeyId=key, CognitoId=account), "robots": {"robot-a": {"sku": "c975020", "svcDeplId": deployment}}}
        return SimpleNamespace(request=SimpleNamespace(method="POST", scheme="https", port=443, host="unauth3.prod.iot.irobotapi.com", path="/v2/login"), response=SimpleNamespace(status_code=200, content=json.dumps(body).encode()))
    class Query:
        def items(self, multi=False): return []
    headers = {"authorization": "AWS4-HMAC-SHA256 Credential=old/20260101/us-east-1/execute-api/aws4_request, SignedHeaders=x"}
    request = SimpleNamespace(method="GET", scheme="https", port=443, host="auth3.prod.iot.irobotapi.com", path="/v1/user/settings", headers=headers, query=Query())
    flows = [login("old", identity, old_deployment), SimpleNamespace(request=request, response=SimpleNamespace(status_code=200)), login("new", "same", "v011")]
    fake = ModuleType("mitmproxy.io"); fake.FlowReader = lambda handle: SimpleNamespace(stream=lambda: iter(flows))
    monkeypatch.setitem(sys.modules, "mitmproxy", ModuleType("mitmproxy")); monkeypatch.setitem(sys.modules, "mitmproxy.io", fake)
    spec = importlib.util.spec_from_file_location("synthetic_decoder_identity", Path(__file__).parents[1] / "roomba_cli" / "capture_session.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    path = tmp_path / "synthetic.flows"; path.touch()
    result = module.decode(path)
    assert bool(result["requests"]) is admitted
    assert "CognitoId" not in result["credentials"]


def test_shared_household_schedule_is_available_to_every_member_robot(tmp_path):
    household = {"method": "GET", "url": "https://auth3.prod.iot.irobotapi.com/v1/households/household/settings/schedule", "headers": template()["headers"], "query": [], "region": "us-east-1", "household_robot_ids": ["robot-a", "robot-b"]}
    data = {"credentials": CREDS, "robots": [{"id": "robot-a"}, {"id": "robot-b"}], "requests": [household]}
    with patch("roomba_cli.commands.cloud.subprocess.run", return_value=Mock(returncode=0, stdout=json.dumps(data))), patch("roomba_cli.commands.cloud.secret"):
        import_capture(Config(tmp_path), tmp_path / "synthetic.flows")
    saved = json.loads((tmp_path / "cloud-session.json").read_text())
    assert saved["templates"]["robot-a"]["schedule"] == saved["templates"]["robot-b"]["schedule"]
