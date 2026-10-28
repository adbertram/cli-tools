"""Summaries that keep shadow field age distinct from successful broker reads."""
import time
import math
from .client import ClientError
from .cloud_mqtt import get_shadow

# These exact partitions returned accepted GETs on the scoped local hardware.
STATUS_PARTITIONS = {"c975020": ("ro-currentstate", "rw-constatus"), "R989020": (None,)}
STATUS_FIELDS = {"battery_percent": "batPct", "mission": "cleanMissionStatus", "connected": "connected", "bin": "bin", "dock": "dock", "tank_level": "tankLvl", "tank_present": "tankPresent"}


def metadata_ages(metadata, now=None):
    timestamps = []
    def visit(node):
        if not isinstance(node, dict):
            return
        if isinstance(node.get("timestamp"), (int, float)) and not isinstance(node["timestamp"], bool) and math.isfinite(node["timestamp"]):
            timestamps.append(node["timestamp"])
        for value in node.values():
            visit(value)
    visit(metadata)
    current = time.time() if now is None else now
    return {"oldest_timestamp": min(timestamps) if timestamps else None,
            "newest_timestamp": max(timestamps) if timestamps else None,
            "oldest_age_seconds": max(0, current - min(timestamps)) if timestamps else None,
            "newest_age_seconds": max(0, current - max(timestamps)) if timestamps else None}



def reported_snapshot(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("state"), dict):
        raise ClientError("Cloud shadow has an invalid state shape")
    reported = payload["state"].get("reported", {})
    metadata_root = payload.get("metadata", {})
    if not isinstance(metadata_root, dict):
        raise ClientError("Cloud shadow has an invalid metadata shape")
    metadata = metadata_root.get("reported", {})
    if not isinstance(reported, dict) or not isinstance(metadata, dict):
        raise ClientError("Cloud shadow has an invalid reported-state shape")
    return reported, metadata

def observed_status(session, credentials, robot_id, timeout=15):
    robot = next((robot for robot in session["robots"] if robot["id"] == robot_id), None)
    partitions = STATUS_PARTITIONS.get(robot.get("sku") if robot else None)
    if partitions is None:
        raise ClientError("Cloud status reads are not verified for this robot model")
    deadline = time.monotonic() + timeout
    fields = {}
    sources = []
    for partition in partitions:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ClientError("Cloud status read deadline expired")
        result = get_shadow(session, credentials, robot_id, remaining, partition)
        payload = result["data"]
        reported, metadata = reported_snapshot(payload)
        if not isinstance(reported, dict) or not isinstance(metadata, dict):
            raise ClientError("Cloud status shadow has an invalid reported-state shape")
        source = partition or "classic"
        sources.append({"partition": source, "shadow_version": payload.get("version"), "shadow_timestamp": payload.get("timestamp")})
        for label, field in STATUS_FIELDS.items():
            if field in reported:
                fields[label] = {"observed": True, "value": reported[field], "partition": source, **metadata_ages(metadata.get(field, {}))}
    for label in STATUS_FIELDS:
        fields.setdefault(label, {"observed": False, "value": None, "partition": None, **metadata_ages({})})
    return {"source": "cloud_shadow", "robot_id": robot_id, "sku": robot["sku"], "device_status": "not_confirmed_live", "fields": fields, "sources": sources}


def robot_schedules(session, credentials, robot_id, timeout=15):
    robot = next((robot for robot in session["robots"] if robot["id"] == robot_id), None)
    if robot is None or robot.get("sku") not in STATUS_PARTITIONS:
        raise ClientError("Cloud schedule reads are not verified for this robot model")
    partition = "rw-schedule" if robot["sku"] == "c975020" else None
    payload = get_shadow(session, credentials, robot_id, timeout, partition)["data"]
    reported, metadata = reported_snapshot(payload)
    if not isinstance(reported, dict) or not isinstance(metadata, dict):
        raise ClientError("Robot schedule shadow has an invalid reported-state shape")
    if partition is None:
        keys = ("cleanSchedule", "cleanSchedule2", "schedHold", "tz", "timezone")
        reported = {key: reported[key] for key in keys if key in reported}
        metadata = {key: metadata[key] for key in keys if key in metadata}
    return {"source": "cloud_shadow", "scope": "robot", "robot_id": robot_id,
            "partition": partition or "classic", "data": reported, "metadata": metadata,
            "metadata_ages": metadata_ages(metadata), "device_status": "not_confirmed_live"}
