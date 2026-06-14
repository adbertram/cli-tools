from types import SimpleNamespace

import pytest

from harmony_cli.client import HarmonyClient, probe_network_ports


HUB_CONFIG = {
    "activity": [
        {"id": "-1", "label": "PowerOff"},
        {"id": "100", "label": "Watch TV", "activityTypeDisplayName": "Watch TV"},
    ],
    "device": [
        {
            "id": "200",
            "label": "Living Room TV",
            "manufacturer": "Sony",
            "model": "A80J",
            "deviceTypeDisplayName": "Television",
            "controlGroup": [
                {
                    "name": "Volume",
                    "function": [
                        {
                            "name": "VolumeUp",
                            "label": "Volume Up",
                            "action": '{"command":"VolumeUp","type":"IRCommand"}',
                        },
                        {
                            "name": "VolumeDown",
                            "label": "Volume Down",
                            "action": '{"command":"VolumeDown","type":"IRCommand"}',
                        },
                    ],
                }
            ],
        }
    ],
}


class FakeConfig:
    default_hub = "192.168.1.50"
    default_protocol = "WEBSOCKETS"
    discovery_timeout = 0.01
    config_env_file_path = "/tmp/harmony.env"


class FakeHarmonyApi:
    def __init__(self, ip_address, protocol=None):
        self.ip_address = ip_address
        self.protocol = protocol
        self.name = "Living Room"
        self.hub_id = "hub-1"
        self.fw_version = "4.15.307"
        self.account_id = "acct-1"
        self.email = "owner@example.com"
        self.config = HUB_CONFIG
        self.current_activity = ("100", "Watch TV")
        self.hub_config = SimpleNamespace(info={}, hub_state={}, config=HUB_CONFIG)
        self.sent_commands = []
        self.started = []
        self.closed = False

    async def connect(self):
        return True

    async def close(self):
        self.closed = True

    async def start_activity(self, activity_id):
        self.started.append(activity_id)
        return True, "ok"

    async def power_off(self):
        return True

    async def sync(self):
        return True

    async def send_commands(self, commands):
        self.sent_commands.extend(commands)
        return []

    async def change_channel(self, channel):
        self.channel = channel
        return True


def make_client(api):
    return HarmonyClient(
        config=FakeConfig(),
        api_factory=lambda ip_address, protocol=None: api,
        discovery_factory=lambda timeout: [
            {
                "id": "hub-1",
                "name": "Living Room",
                "host": "harmony.local",
                "ip": "192.168.1.50",
                "port": 8088,
                "protocol": "WEBSOCKETS",
                "service_type": "_logitech-reverse-bonjour._tcp.local.",
                "service_name": "Living Room",
                "properties": {},
            }
        ],
    )


def test_lists_hubs_from_discovery():
    client = make_client(FakeHarmonyApi("192.168.1.50"))

    assert client.list_hubs() == [
        {
            "id": "hub-1",
            "name": "Living Room",
            "host": "harmony.local",
            "ip": "192.168.1.50",
            "port": 8088,
            "protocol": "WEBSOCKETS",
            "service_type": "_logitech-reverse-bonjour._tcp.local.",
            "service_name": "Living Room",
            "properties": {},
        }
    ]


def test_explicit_ip_does_not_wait_for_discovery():
    api = FakeHarmonyApi("192.168.1.50")
    client = HarmonyClient(
        config=FakeConfig(),
        api_factory=lambda ip_address, protocol=None: api,
        discovery_factory=lambda timeout: pytest.fail("IP address should not trigger discovery"),
    )

    assert client.get_hub("192.168.1.50")["ip"] == "192.168.1.50"


def test_low_level_probe_finds_open_harmony_ports_without_mdns():
    class FakeSocket:
        def close(self):
            pass

    def connector(address, timeout=None):
        if address == ("192.168.1.2", 8088):
            return FakeSocket()
        raise OSError("closed")

    rows = probe_network_ports(
        cidr="192.168.1.0/30",
        ports=[8088, 5222],
        timeout=0.01,
        workers=1,
        connector=connector,
        name_resolver=lambda host: "harmonyhub.lan" if host == "192.168.1.2" else "",
    )

    assert rows == [
        {
            "id": "192.168.1.2",
            "name": "harmonyhub.lan",
            "host": "harmonyhub.lan",
            "ip": "192.168.1.2",
            "open_ports": [8088],
            "protocols": ["WEBSOCKETS"],
            "verified": False,
            "probe_method": "tcp",
        }
    ]


def test_probe_hubs_enriches_verified_harmony_hosts():
    api = FakeHarmonyApi("192.168.1.50")
    client = HarmonyClient(
        config=FakeConfig(),
        api_factory=lambda ip_address, protocol=None: api,
        port_probe_factory=lambda **kwargs: [
            {
                "id": "192.168.1.50",
                "name": "harmonyhub.lan",
                "host": "harmonyhub.lan",
                "ip": "192.168.1.50",
                "open_ports": [8088],
                "protocols": ["WEBSOCKETS"],
                "verified": False,
                "probe_method": "tcp",
            }
        ],
    )

    rows = client.probe_hubs(cidr="192.168.1.0/24", verify=True)

    assert rows[0]["id"] == "hub-1"
    assert rows[0]["name"] == "Living Room"
    assert rows[0]["ip"] == "192.168.1.50"
    assert rows[0]["open_ports"] == [8088]
    assert rows[0]["verified"] is True


def test_activity_device_and_command_records_are_normalized():
    client = make_client(FakeHarmonyApi("192.168.1.50"))

    activities = client.list_activities()
    devices = client.list_devices()
    commands = client.list_commands("Living Room TV")

    assert activities[1]["id"] == "100"
    assert activities[1]["name"] == "Watch TV"
    assert activities[1]["status"] == "current"
    assert devices[0]["id"] == "200"
    assert devices[0]["manufacturer"] == "Sony"
    assert devices[0]["command_count"] == 2
    assert commands[1]["id"] == "200:VolumeUp"
    assert commands[1]["device_name"] == "Living Room TV"
    assert commands[1]["action"]["type"] == "IRCommand"


def test_start_activity_resolves_name_and_sends_activity_id():
    api = FakeHarmonyApi("192.168.1.50")
    client = make_client(api)

    result = client.start_activity("Watch TV")

    assert result["success"] is True
    assert result["activity_id"] == "100"
    assert api.started == ["100"]


def test_send_command_resolves_device_and_command():
    api = FakeHarmonyApi("192.168.1.50")
    client = make_client(api)

    result = client.send_command("Living Room TV", "VolumeUp", repeat=2, delay=0.25, hold=0.1)

    assert result["success"] is True
    assert result["device_id"] == "200"
    assert result["command"] == "VolumeUp"
    assert api.sent_commands[0].device == 200
    assert api.sent_commands[0].command == "VolumeUp"
    assert api.sent_commands[1] == 0.25
    assert api.sent_commands[2].command == "VolumeUp"


def test_invalid_protocol_fails_fast():
    client = make_client(FakeHarmonyApi("192.168.1.50"))

    with pytest.raises(Exception, match="Protocol must be WEBSOCKETS or XMPP"):
        client.get_hub("192.168.1.50", protocol="bad")
