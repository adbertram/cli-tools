"""Bounded Classic-shadow MQTT over verified TLS WebSockets.

Transport/auth and Classic shadow topics follow upstream roombapy-prime,
confirmed there for 900-series and SMART-tier robots. No automatic reconnect.
"""
import json
import math
import re
import ssl
import threading
import time
import uuid

import paho.mqtt.client as mqtt

from .client import ClientError, CloudAuthenticationError


def validate_connection_token(token, now=None):
    fields = ("client_id", "iot_token", "iot_signature", "iot_authorizer_name")
    if (not isinstance(token, dict)
            or any(not isinstance(token.get(key), str) or not token[key] or '\r' in token[key] or '\n' in token[key] for key in fields)
            or not isinstance(token.get("devices"), list) or not token["devices"]
            or any(not isinstance(device, str) or not device for device in token["devices"])
            or not isinstance(token.get("expires"), (int, float)) or isinstance(token["expires"], bool)
            or not math.isfinite(token["expires"])):
        raise ClientError("Cloud MQTT session is invalid; import a fresh authorized login capture")
    if token["expires"] <= (time.time() if now is None else now):
        raise ClientError("Cloud MQTT session expired; import a fresh authorized login capture")


def connection_details(session, credentials, robot_id):
    robots = session.get("robots", [])
    matches = [robot for robot in robots if robot.get("id") == robot_id]
    if len(matches) != 1 or not re.fullmatch(r'[A-Za-z0-9_-]+', robot_id):
        raise ClientError("Cloud MQTT target is not an unambiguous imported robot")
    # Deliberate local verification boundary: these two SKUs and this region.
    if matches[0].get("sku") not in ("c975020", "R989020"):
        raise ClientError("Cloud MQTT transport is not verified for this robot model")
    deployment = session.get("deployments", {}).get(matches[0].get("deployment_id"), {})
    endpoint = deployment.get("mqtt")
    if (deployment.get("awsRegion") != "us-east-1" or not isinstance(endpoint, str)
            or not re.fullmatch(r'[A-Za-z0-9-]+\.iot\.us-east-1\.amazonaws\.com', endpoint)):
        raise ClientError("Cloud MQTT deployment routing is missing or unsupported; reimport discovery and login capture")
    tokens = credentials.get("connection_tokens", []) if isinstance(credentials, dict) else []
    candidates = [token for token in tokens if isinstance(token, dict) and isinstance(token.get("devices"), list) and robot_id in token["devices"]]
    if len(candidates) != 1:
        raise ClientError("Cloud MQTT session does not unambiguously authorize this robot")
    validate_connection_token(candidates[0])
    return endpoint, candidates[0]


def reason_failed(code):
    failure = getattr(code, "is_failure", None)
    if isinstance(failure, bool):
        return failure
    value = getattr(code, "value", code)
    return not isinstance(value, int) or value >= 128


class CloudMQTT:
    """One connection, exact topic subscriptions, and one bounded request."""
    def __init__(self, endpoint, token, robot_id, timeout=15, client_factory=None, partition=None):
        self.deadline = time.monotonic() + timeout
        if partition not in (None, "ro-currentstate", "rw-constatus", "rw-schedule", "rw-settings", "ro-configinfo", "ro-stats", "rw-software"):
            raise ClientError("Cloud shadow partition is not in the evidenced probe allowlist")
        self.base = f"$aws/things/{robot_id}/shadow" + (f"/name/{partition}" if partition else "")
        self.connected = threading.Event()
        self.subscribed = threading.Event()
        self.received = threading.Event()
        self.error = None
        self.auth_rejected = False
        self.response = None
        self.allowed_topics = set()
        self.request_token = uuid.uuid4().hex
        factory = client_factory or mqtt.Client
        self.client = factory(mqtt.CallbackAPIVersion.VERSION2, client_id=token["client_id"], protocol=mqtt.MQTTv311, transport="websockets", reconnect_on_failure=False)
        self.client.connect_timeout = min(5, timeout)
        self.client.tls_set_context(ssl.create_default_context())
        self.client.ws_set_options(path="/mqtt", headers={"X-Amz-CustomAuthorizer-Name": token["iot_authorizer_name"], "X-Amz-CustomAuthorizer-Signature": token["iot_signature"], "x-irobot-auth": token["iot_token"]})
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_subscribe = self._on_subscribe
        self.client.on_message = self._on_message
        self.endpoint = endpoint

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ClientError("Cloud MQTT operation timed out")
        return remaining

    def fail(self, message):
        self.error = message
        self.connected.set(); self.subscribed.set(); self.received.set()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if getattr(reason_code, "is_failure", reason_code != 0):
            self.auth_rejected = True
            self.fail("Cloud MQTT authorization or connection rejected")
        self.connected.set()

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.fail("Cloud MQTT disconnected before the operation completed")

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties):
        if not reason_codes or any(reason_failed(code) for code in reason_codes):
            self.fail("Cloud MQTT subscription rejected")
        self.subscribed.set()

    def _on_message(self, client, userdata, message):
        if message.topic not in self.allowed_topics:
            return
        try:
            payload = json.loads(message.payload)
            if not isinstance(payload, dict):
                raise ValueError
        except (ValueError, UnicodeError):
            self.fail("Cloud MQTT returned invalid JSON")
            return
        if payload.get("clientToken") != self.request_token:
            return
        self.response = (message.topic, payload)
        self.received.set()

    def wait(self, event, label):
        if not event.wait(self.remaining()):
            raise ClientError(f"Cloud MQTT {label} timed out")
        if self.error:
            if self.auth_rejected:
                raise CloudAuthenticationError(self.error)
            raise ClientError(self.error)

    def open(self):
        topics = [self.base + "/get/accepted", self.base + "/get/rejected"]
        self.allowed_topics = set(topics)
        self.client.connect(self.endpoint, 443, keepalive=60)
        self.client.loop_start()
        self.wait(self.connected, "connection")
        result, _ = self.client.subscribe([(topic, 1) for topic in topics])
        if result != mqtt.MQTT_ERR_SUCCESS:
            raise ClientError("Cloud MQTT subscription was not sent")
        self.wait(self.subscribed, "subscription")

    def query(self):
        self.request_token = uuid.uuid4().hex
        self.received.clear()
        self.response = None
        published = self.client.publish(self.base + "/get", json.dumps({"clientToken": self.request_token}), qos=1)
        if published.rc != mqtt.MQTT_ERR_SUCCESS:
            raise ClientError("Cloud MQTT shadow request was not sent")
        published.wait_for_publish(timeout=self.remaining())
        self.wait(self.received, "shadow response")
        topic, payload = self.response
        if topic.endswith("/rejected"):
            raise ClientError("Cloud MQTT shadow request rejected")
        return payload

    def close(self):
        try:
            self.client.disconnect()
        except Exception:
            pass
        try:
            self.client.loop_stop()
        except Exception:
            pass

    def get_shadow(self):
        try:
            self.open()
            return self.query()
        except ClientError:
            raise
        except Exception:
            raise ClientError("Cloud MQTT transport failed") from None
        finally:
            self.close()


def get_shadow(session, credentials, robot_id, timeout=15, partition=None):
    endpoint, token = connection_details(session, credentials, robot_id)
    if partition and next(robot for robot in session["robots"] if robot["id"] == robot_id).get("sku") != "c975020":
        raise ClientError("Named shadow probing is only scoped to the Combo j9+")
    payload = CloudMQTT(endpoint, token, robot_id, timeout, partition=partition).get_shadow()
    return {"source": "cloud_shadow", "robot_id": robot_id, "device_status": "not_confirmed_live", "partition": partition or "classic", "data": payload}
