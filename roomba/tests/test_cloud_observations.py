"""Cloud snapshot age, missing telemetry and stored schedule source tests."""
from unittest.mock import patch
import pytest
from roomba_cli.client import ClientError
from roomba_cli.cloud_observations import metadata_ages, observed_status, robot_schedules

SESSION = {"robots": [{"id": "older", "sku": "R989020"}, {"id": "combo", "sku": "c975020"}]}


def snapshot(reported, metadata=None):
    return {"data": {"state": {"reported": reported}, "metadata": {"reported": metadata or {}}}}


def test_metadata_age_ignores_invalid_bool_and_nonfinite_timestamps():
    result = metadata_ages({"a": {"timestamp": True}, "b": {"timestamp": float("nan")}, "c": {"timestamp": float("inf")}, "d": {"timestamp": 20}}, 100)
    assert result["oldest_timestamp"] == 20 and result["oldest_age_seconds"] == 80


def test_old_connected_true_does_not_become_live_and_missing_battery_is_unknown():
    with patch("roomba_cli.cloud_observations.get_shadow", return_value=snapshot({"connected": True}, {"connected": {"timestamp": 1}})):
        result = observed_status(SESSION, {}, "older")
    assert result["device_status"] == "not_confirmed_live"
    assert result["fields"]["connected"]["value"] is True
    assert result["fields"]["connected"]["oldest_age_seconds"] > 100 * 86400
    assert result["fields"]["battery_percent"]["observed"] is False
    assert result["fields"]["battery_percent"]["value"] is None


def test_combo_reads_exact_two_verified_status_partitions():
    with patch("roomba_cli.cloud_observations.get_shadow", side_effect=[snapshot({"batPct": 17}), snapshot({"connected": True})]) as read:
        result = observed_status(SESSION, {}, "combo")
    assert [call.args[4] for call in read.call_args_list] == ["ro-currentstate", "rw-constatus"]
    assert result["fields"]["battery_percent"]["value"] == 17


@pytest.mark.parametrize("payload", [{}, {"state": None}, {"state": []}, {"state": {"reported": []}}, {"state": {"reported": {}}, "metadata": None}])
def test_malformed_remote_shadow_fails_explicitly(payload):
    with patch("roomba_cli.cloud_observations.get_shadow", return_value={"data": payload}):
        with pytest.raises(ClientError): observed_status(SESSION, {}, "older")


def test_older_schedules_preserve_raw_legacy_schedule_and_age():
    reported = {"cleanSchedule": {"days": [0] * 7, "hrs": [0] * 7, "mins": [0] * 7}, "schedHold": True, "batPct": 90}
    with patch("roomba_cli.cloud_observations.get_shadow", return_value=snapshot(reported, {"cleanSchedule": {"timestamp": 1}})):
        result = robot_schedules(SESSION, {}, "older")
    assert result["data"]["cleanSchedule"] == reported["cleanSchedule"]
    assert "batPct" not in result["data"]
    assert result["metadata_ages"]["oldest_age_seconds"] > 100 * 86400
