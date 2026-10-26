"""Synthetic favorites lookup and robot-binding coverage."""
from unittest.mock import patch
import pytest
from roomba_cli.client import ClientError
from roomba_cli.commands.cloud import find_favorite, robot_favorites


def favorite(identifier, robot):
    return {"favorite_id": identifier, "name": "synthetic", "cloud_capable": True, "commanddefs": [{"robot_id": robot, "command": "start", "regions": [{"rid": "synthetic-region"}]}]}


def test_favorites_only_include_exact_selected_robot_and_keep_payload():
    mine = favorite("mine", "robot-a")
    other = favorite("other", "robot-b")
    with patch("roomba_cli.commands.cloud.load_session", return_value={}), patch("roomba_cli.commands.cloud.resolve_robot", return_value="robot-a"), patch("roomba_cli.commands.cloud.run_read", return_value={"data": [mine, other]}) as read:
        robot, result = robot_favorites(object(), "robot-a")
    assert robot == "robot-a" and result == [mine]
    assert result[0]["commanddefs"][0]["regions"] == [{"rid": "synthetic-region"}]
    assert read.call_count == 1


def test_wrong_robot_favorite_fails_instead_of_retargeting():
    with patch("roomba_cli.commands.cloud.robot_favorites", return_value=("robot-a", [favorite("mine", "robot-a")])):
        with pytest.raises(ClientError, match="selected cloud robot"): find_favorite(object(), "other", "robot-a")


@pytest.mark.parametrize("payload", [None, {}, [None], [{"favorite_id": "a"}], [{"favorite_id": "a", "commanddefs": [None]}], [{"commanddefs": [{"robot_id": "robot-a"}]}]])
def test_invalid_favorite_shape_fails_explicitly(payload):
    with patch("roomba_cli.commands.cloud.load_session", return_value={}), patch("roomba_cli.commands.cloud.resolve_robot", return_value="robot-a"), patch("roomba_cli.commands.cloud.run_read", return_value={"data": payload}):
        with pytest.raises(ClientError): robot_favorites(object(), "robot-a")
