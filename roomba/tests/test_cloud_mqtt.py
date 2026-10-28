"""Synthetic Classic cloud transport authorization, scoping, deadline and GET checks."""
import json
from types import SimpleNamespace
from unittest.mock import patch
import pytest

from roomba_cli.client import ClientError
from roomba_cli.cloud_mqtt import CloudMQTT, connection_details, get_shadow, validate_connection_token

TOKEN = {"client_id": "synthetic-client", "expires": 9999999999, "devices": ["robot-a", "robot-b"], "iot_token": "synthetic-secret", "iot_signature": "synthetic-signature", "iot_authorizer_name": "synthetic-authorizer"}
HOST = "synthetic.iot.us-east-1.amazonaws.com"
SESSION = {"robots": [{"id": "robot-a", "sku": "c975020", "deployment_id": "new"}, {"id": "robot-b", "sku": "R989020", "deployment_id": "old"}], "deployments": {"new": {"mqtt": HOST, "awsRegion": "us-east-1"}, "old": {"mqtt": "older.iot.us-east-1.amazonaws.com", "awsRegion": "us-east-1"}}}


class Client:
    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs; self.publishes = []; self.subscriptions = []; self.stopped = False; self.disconnected = False
    def tls_set_context(self, context): self.tls = context
    def ws_set_options(self, **kwargs): self.ws = kwargs
    def connect(self, host, port, keepalive): self.endpoint = (host, port)
    def loop_start(self): self.on_connect(self, None, None, 0, None)
    def subscribe(self, topics):
        self.subscriptions = topics
        self.on_subscribe(self, None, 1, [0] * len(topics), None)
        return 0, 1
    def publish(self, topic, payload, qos):
        self.publishes.append((topic, payload, qos))
        token = json.loads(payload)["clientToken"]
        # An unrelated accepted message must not satisfy this operation.
        wrong = json.dumps({"clientToken": "other-request", "state": {"reported": {"unrelated": True}}})
        self.on_message(self, None, SimpleNamespace(topic=topic + "/accepted", payload=wrong))
        response = json.dumps({"clientToken": token, "state": {"reported": {"connected": True}}, "metadata": {"reported": {"connected": {"timestamp": 1}}}})
        self.on_message(self, None, SimpleNamespace(topic=topic + "/accepted", payload=response))
        return SimpleNamespace(rc=0, wait_for_publish=lambda timeout: None)
    def disconnect(self): self.disconnected = True
    def loop_stop(self): self.stopped = True


def test_bounded_authenticated_get_is_correlated_and_never_publishes_mutation():
    client = Client()
    transport = CloudMQTT(HOST, TOKEN, "robot-a", 1, client_factory=lambda *a, **kw: client)
    result = transport.get_shadow()
    assert result["state"]["reported"] == {"connected": True}
    assert client.endpoint == (HOST, 443)
    assert client.tls.check_hostname is True
    assert set(client.ws["headers"]) == {"X-Amz-CustomAuthorizer-Name", "X-Amz-CustomAuthorizer-Signature", "x-irobot-auth"}
    assert client.ws["path"] == "/mqtt"
    assert client.subscriptions == [("$aws/things/robot-a/shadow/get/accepted", 1), ("$aws/things/robot-a/shadow/get/rejected", 1)]
    assert len(client.publishes) == 1 and client.publishes[0][0] == "$aws/things/robot-a/shadow/get"
    assert client.disconnected and client.stopped


def test_factory_disables_reconnect_and_uses_server_client_id():
    with patch("roomba_cli.cloud_mqtt.mqtt.Client", side_effect=Client) as factory:
        transport = CloudMQTT(HOST, TOKEN, "robot-a", 1)
        transport.get_shadow()
    assert factory.call_args.kwargs["reconnect_on_failure"] is False
    assert factory.call_args.kwargs["client_id"] == TOKEN["client_id"]
    assert factory.call_args.kwargs["transport"] == "websockets"


@pytest.mark.parametrize("expires", [True, None, "later", float("nan"), float("inf"), 1])
def test_expired_or_nonfinite_token_never_connects(expires):
    with pytest.raises(ClientError): validate_connection_token(dict(TOKEN, expires=expires))


def test_endpoint_and_token_are_exactly_selected_robot_bound():
    endpoint, token = connection_details(SESSION, {"connection_tokens": [TOKEN]}, "robot-b")
    assert endpoint == "older.iot.us-east-1.amazonaws.com" and token is TOKEN
    with pytest.raises(ClientError): connection_details(SESSION, {"connection_tokens": [dict(TOKEN, devices=["robot-a"])]}, "robot-b")
    with pytest.raises(ClientError): connection_details(SESSION, {"connection_tokens": [TOKEN]}, "robot-c")


def test_broker_rejection_does_not_publish_and_cleans_up():
    class Rejected(Client):
        def subscribe(self, topics):
            self.on_subscribe(self, None, 1, [SimpleNamespace(is_failure=True, value=128)], None)
            return 0, 1
    client = Rejected()
    with pytest.raises(ClientError, match="subscription rejected"):
        CloudMQTT(HOST, TOKEN, "robot-a", 1, client_factory=lambda *a, **kw: client).get_shadow()
    assert not client.publishes and client.disconnected and client.stopped


def test_connection_failure_is_redacted_and_never_retried():
    class Broken(Client):
        def connect(self, *a, **kw): raise OSError("synthetic-secret")
    client = Broken()
    with pytest.raises(ClientError) as error:
        CloudMQTT(HOST, TOKEN, "robot-a", 1, client_factory=lambda *a, **kw: client).get_shadow()
    assert "synthetic-secret" not in str(error.value)
    assert client.disconnected and client.stopped


def test_shadow_snapshot_never_claims_live_robot_status():
    with patch("roomba_cli.cloud_mqtt.CloudMQTT") as transport:
        transport.return_value.get_shadow.return_value = {"state": {"reported": {"connected": True}}}
        result = get_shadow(SESSION, {"connection_tokens": [TOKEN]}, "robot-a")
    assert result["device_status"] == "not_confirmed_live"
