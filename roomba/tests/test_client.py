"""Regression coverage for the public synchronous Roombapy API and telemetry."""
import unittest
from unittest.mock import patch

from roomba_cli.client import ClientError, RoombaClient


class FakeConfig:
    def get_robot(self, name):
        return {"name": "test", "ip": "127.0.0.1", "blid": "test", "password": "test"}


class FakeRobot:
    def __init__(self, message=None, error=None):
        self.message = message
        self.error = error
        self.disconnected = False
        self.client_error = None
        self.roomba_connected = True

    def register_on_message_callback(self, callback):
        self.callback = callback

    def connect(self):
        if self.error:
            raise self.error
        if self.message is not None:
            self.callback(self.message)

    def disconnect(self):
        self.disconnected = True


class ClientTests(unittest.TestCase):
    def setUp(self):
        with patch("roomba_cli.client.get_config", return_value=FakeConfig()):
            self.client = RoombaClient()

    def test_public_factory_api(self):
        robot = self.client._make_roomba("127.0.0.1", "test", "test")
        self.assertTrue(callable(robot.connect))
        self.assertTrue(callable(robot.disconnect))

    def test_live_status_and_disconnect(self):
        robot = FakeRobot({"state": {"reported": {"batPct": 83, "cleanMissionStatus": {"phase": "charge", "error": 0}, "bin": {"present": True, "full": False}}}})
        with patch.object(self.client, "_make_roomba", return_value=robot):
            status = self.client.get_status("test", timeout=0)
        self.assertEqual(status.battery_percent, 83)
        self.assertEqual(status.phase.value, "charge")
        self.assertFalse(status.bin_full)
        self.assertTrue(robot.disconnected)

    def test_partial_status_keeps_missing_values_unknown(self):
        robot = FakeRobot({"state": {"reported": {"cleanMissionStatus": {"phase": "future-phase"}}}})
        with patch.object(self.client, "_make_roomba", return_value=robot):
            status = self.client.get_status("test", timeout=0)
        self.assertIsNone(status.battery_percent)
        self.assertIsNone(status.bin_present)
        self.assertIsNone(status.bin_full)
        self.assertEqual(status.phase.value, "unknown")

    def test_no_telemetry_is_failure_and_disconnects(self):
        for message in (None, {"state": {"reported": {"irrelevant": 1}}}):
            robot = FakeRobot(message)
            with patch.object(self.client, "_make_roomba", return_value=robot):
                with self.assertRaisesRegex(ClientError, "No reported telemetry"):
                    self.client.get_status("test", timeout=0)
            self.assertTrue(robot.disconnected)

    def test_mqtt_rejection_is_not_reported_as_missing_telemetry(self):
        robot = FakeRobot()
        robot.client_error = "rejected"
        robot.roomba_connected = False
        with patch.object(self.client, "_make_roomba", return_value=robot):
            with self.assertRaisesRegex(ClientError, "MQTT connection rejected"):
                self.client.get_status("test", timeout=0)
        self.assertTrue(robot.disconnected)

    def test_connection_failure_disconnects(self):
        from roombapy.roomba import RoombaConnectionError
        robot = FakeRobot(error=RoombaConnectionError("test"))
        with patch.object(self.client, "_make_roomba", return_value=robot):
            with self.assertRaisesRegex(ClientError, "Failed to connect"):
                self.client.get_status("test", timeout=0)
        self.assertTrue(robot.disconnected)


if __name__ == "__main__":
    unittest.main()
