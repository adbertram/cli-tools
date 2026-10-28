"""Experimental, single-publish cloud start/pause with separate receipt evidence."""
import json
import math
import re
import time

import paho.mqtt.client as mqtt

from .client import ClientError
from .cloud_mqtt import CloudMQTT, connection_details
from .cloud_observations import reported_snapshot, metadata_ages


def confirmation(baseline, payload, envelope):
    before, _ = reported_snapshot(baseline)
    reported, metadata = reported_snapshot(payload)
    sent = envelope["time"]
    last = reported.get("lastCommand")
    last_age = metadata_ages(metadata.get("lastCommand", {}))
    last_confirmed = (isinstance(last, dict) and last != before.get("lastCommand")
                      and all(last.get(key) == value for key, value in envelope.items())
                      and last_age["oldest_timestamp"] is not None and last_age["oldest_timestamp"] >= sent)
    mission = reported.get("cleanMissionStatus")
    mission_age = metadata_ages(metadata.get("cleanMissionStatus", {}))
    phase = mission.get("phase") if isinstance(mission, dict) else None
    matching_phase = phase == ("run" if envelope["command"] == "start" else "stop")
    prior_mission = before.get("cleanMissionStatus")
    prior_phase = prior_mission.get("phase") if isinstance(prior_mission, dict) else None
    phase_metadata = metadata.get("cleanMissionStatus", {})
    if isinstance(phase_metadata, dict) and "phase" in phase_metadata:
        phase_metadata = phase_metadata["phase"]
    phase_age = metadata_ages(phase_metadata)
    mission_confirmed = (isinstance(mission, dict) and prior_phase != phase
                         and matching_phase and mission.get("cycle") not in (None, "none")
                         and phase_age["oldest_timestamp"] is not None and phase_age["oldest_timestamp"] >= sent)
    return {"matching_last_command": bool(last_confirmed), "matching_mission_transition": bool(mission_confirmed),
            "mission_phase": phase, "mission_metadata_ages": mission_age}


def send_control(session, credentials, robot_id, action, timeout=30, transport_factory=CloudMQTT):
    if action not in ("start", "pause"):
        raise ClientError("Only cloud start and pause are supported")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or not 1 <= timeout <= 60:
        raise ClientError("Cloud control timeout must be between 1 and 60 seconds")
    endpoint, token = connection_details(session, credentials, robot_id)
    robot = next(robot for robot in session["robots"] if robot["id"] == robot_id)
    prefix = session.get("deployments", {}).get(robot["deployment_id"], {}).get("irbtTopics")
    if not isinstance(prefix, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', prefix):
        raise ClientError("Captured command topic prefix is missing or invalid; reimport discovery capture")
    partition = "ro-currentstate" if robot["sku"] == "c975020" else None
    transport = transport_factory(endpoint, token, robot_id, timeout, partition=partition)
    result = {"robot_id": robot_id, "command": action, "compatibility": "experimental",
              "publish_attempted": False, "broker_received": False, "robot_confirmed": False,
              "confirmation": None, "completion": "not_sent"}
    try:
        transport.open()
        baseline = transport.query()
        # Validate before the only mutation publish. Cached baseline is not proof
        # of online presence, and existing matching state cannot confirm a change.
        reported_snapshot(baseline)
        transport.remaining()
        envelope = {"command": action, "time": int(time.time()), "initiator": "rmtApp"}
        result["publish_attempted"] = True
        result["completion"] = "unknown"
        published = transport.client.publish(f"{prefix}/things/{robot_id}/cmd", json.dumps(envelope), qos=1, retain=False)
        if published.rc != mqtt.MQTT_ERR_SUCCESS:
            result["error"] = "Command publish was not accepted by the client; do not assume execution"
            return result
        published.wait_for_publish(timeout=transport.remaining())
        result["broker_received"] = bool(published.is_published())
        if not result["broker_received"]:
            result["error"] = "Broker receipt and robot execution are unconfirmed; do not retry automatically"
            return result
        while True:
            payload = transport.query()
            evidence = confirmation(baseline, payload, envelope)
            result["confirmation"] = evidence
            if evidence["matching_last_command"] or evidence["matching_mission_transition"]:
                result["robot_confirmed"] = True
                result["completion"] = "robot_reported"
                return result
            time.sleep(min(0.5, transport.remaining()))
    except ClientError:
        if not result["publish_attempted"]:
            raise
        result["error"] = "Command completion could not be confirmed before disconnect or deadline; do not retry automatically"
        return result
    except Exception:
        if not result["publish_attempted"]:
            raise ClientError("Cloud control transport failed before command publish") from None
        result["error"] = "Command transport failed after publish attempt; completion unknown, do not retry automatically"
        return result
    finally:
        transport.close()


def run_control(config, selector, action, timeout=30):
    from .commands.cloud import resolve_robot
    from .cloud_session import load_session, secret
    from .cloud_auth import profile_lock, credentials_due, refresh_auth
    # Whole operation lock prevents the shared server MQTT client ID colliding.
    # Auth can renew before publish, never by replaying an attempted mutation.
    with profile_lock(config, "mqtt"):
        session = load_session(config)
        target = resolve_robot(config, session, selector)
        credentials = secret(config, "get")
        if credentials_due(credentials, session):
            credentials, _ = refresh_auth(config)
        return send_control(session, credentials, target, action, timeout)
