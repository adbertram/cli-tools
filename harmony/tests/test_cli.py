import json

from typer.testing import CliRunner

from harmony_cli import main
from harmony_cli.main import app


class FakeClient:
    def list_hubs(self, **kwargs):
        return [
            {"id": "hub-1", "name": "Living Room", "ip": "192.168.1.50", "protocol": "WEBSOCKETS"},
            {"id": "hub-2", "name": "Bedroom", "ip": "192.168.1.51", "protocol": "WEBSOCKETS"},
        ]

    def get_hub(self, hub, **kwargs):
        return {"id": "hub-1", "name": "Living Room", "ip": hub, "activity_count": 2, "device_count": 1}

    def list_activities(self, **kwargs):
        return [
            {"id": "-1", "name": "PowerOff", "status": "available"},
            {"id": "100", "name": "Watch TV", "status": "current"},
        ]

    def get_activity(self, activity, **kwargs):
        return {"id": "100", "name": activity, "status": "current"}

    def get_current_activity(self, **kwargs):
        return {"hub_id": "hub-1", "activity_id": "100", "activity_name": "Watch TV", "status": "active"}

    def start_activity(self, activity, **kwargs):
        return {"activity_id": "100", "activity_name": activity, "success": True}

    def power_off(self, **kwargs):
        return {"success": True, "message": "powered off"}

    def sync(self, **kwargs):
        return {"success": True, "message": "sync complete"}

    def search_hubs(self, query, **kwargs):
        return [row for row in self.list_hubs() if query.lower() in row["name"].lower()]

    def probe_hubs(self, **kwargs):
        return [
            {
                "id": "hub-1",
                "name": "Living Room",
                "host": "harmonyhub.lan",
                "ip": "192.168.1.50",
                "open_ports": [8088],
                "protocols": ["WEBSOCKETS"],
                "verified": True,
                "probe_method": "tcp",
            }
        ]

    def search_activities(self, query, **kwargs):
        return [row for row in self.list_activities() if query.lower() in row["name"].lower()]

    def list_devices(self, **kwargs):
        return [
            {
                "id": "200",
                "name": "Living Room TV",
                "manufacturer": "Sony",
                "model": "A80J",
                "command_count": 2,
            }
        ]

    def get_device(self, device, **kwargs):
        return {"id": "200", "name": device, "manufacturer": "Sony", "command_count": 2}

    def search_devices(self, query, **kwargs):
        return [row for row in self.list_devices() if query.lower() in row["name"].lower()]

    def list_commands(self, device, **kwargs):
        return [
            {"id": "200:VolumeDown", "name": "Volume Down", "command": "VolumeDown", "device_name": device, "group": "Volume"},
            {"id": "200:VolumeUp", "name": "Volume Up", "command": "VolumeUp", "device_name": device, "group": "Volume"},
        ]

    def get_command(self, device, command_name, **kwargs):
        return {"id": f"200:{command_name}", "name": command_name, "command": command_name, "device_name": device}

    def send_command(self, device, command_name, **kwargs):
        return {"device_name": device, "command": command_name, "repeat": kwargs["repeat"], "success": True}

    def change_channel(self, channel, **kwargs):
        return {"channel": channel, "success": True}

    def get_config(self, **kwargs):
        return {"hub": {"id": "hub-1"}, "configuration": {"activity": [], "device": []}}


def test_main_help_includes_harmony_groups():
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "hubs" in result.stdout
    assert "activities" in result.stdout
    assert "devices" in result.stdout
    assert "commands" in result.stdout


def test_list_help_exposes_standard_options():
    runner = CliRunner()

    for group, args in {
        "hubs": ["hubs", "list", "--help"],
        "activities": ["activities", "list", "--help"],
        "devices": ["devices", "list", "--help"],
        "commands": ["commands", "list", "Living Room TV", "--help"],
    }.items():
        result = runner.invoke(app, args)
        assert result.exit_code == 0, group
        assert "--limit" in result.stdout
        assert "--filter" in result.stdout
        assert "--properties" in result.stdout
        assert "--table" in result.stdout


def test_hubs_list_filters_and_projects(monkeypatch):
    monkeypatch.setattr(main, "get_client", lambda: FakeClient())

    result = CliRunner().invoke(
        app,
        ["hubs", "list", "--filter", "name:ilike:%living%", "--properties", "id,name"],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [{"id": "hub-1", "name": "Living Room"}]


def test_hubs_probe_filters_and_projects(monkeypatch):
    monkeypatch.setattr(main, "get_client", lambda: FakeClient())

    result = CliRunner().invoke(
        app,
        [
            "hubs",
            "probe",
            "--cidr",
            "192.168.1.0/24",
            "--no-verify",
            "--filter",
            "verified:eq:true",
            "--properties",
            "ip,protocols",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [
        {"ip": "192.168.1.50", "protocols": ["WEBSOCKETS"]}
    ]


def test_activity_start_outputs_action_result(monkeypatch):
    monkeypatch.setattr(main, "get_client", lambda: FakeClient())

    result = CliRunner().invoke(app, ["activities", "start", "Watch TV", "--hub", "192.168.1.50"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "activity_id": "100",
        "activity_name": "Watch TV",
        "success": True,
    }


def test_commands_send_passes_repeat(monkeypatch):
    monkeypatch.setattr(main, "get_client", lambda: FakeClient())

    result = CliRunner().invoke(
        app,
        ["commands", "send", "Living Room TV", "VolumeUp", "--hub", "192.168.1.50", "--repeat", "3"],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "device_name": "Living Room TV",
        "command": "VolumeUp",
        "repeat": 3,
        "success": True,
    }


def test_config_list_outputs_array(monkeypatch):
    monkeypatch.setattr(main, "get_client", lambda: FakeClient())

    result = CliRunner().invoke(app, ["config", "list", "--hub", "192.168.1.50"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [
        {"hub": {"id": "hub-1"}, "configuration": {"activity": [], "device": []}}
    ]
