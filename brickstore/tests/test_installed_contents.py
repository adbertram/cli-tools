import json
import os
import shutil
import subprocess

import pytest

from tests.database_fixtures import minifig_database, two_sets_one_part_database

SOURCE_ENTRY = {
    "item": {
        "category_id": 5,
        "name": "Brick 2 x 4",
        "no": "3001",
        "type": "PART",
    },
    "color_id": 5,
    "extra_quantity": 1,
    "is_alternate": False,
    "is_counterpart": False,
    "match_no": 0,
    "quantity": 3,
}


@pytest.mark.parametrize(
    ("database_bytes", "command_name", "id_key", "item_numbers"),
    [
        (two_sets_one_part_database(), "set-contents", "set_id", ["30670-1", "75313-1"]),
        (minifig_database(["sw0001a", "sw0036"]), "minifig-contents", "minifig_id", ["sw0001a", "sw0036"]),
    ],
)
def test_installed_contents_uses_the_public_launcher_and_local_database(
    tmp_path, database_bytes, command_name, id_key, item_numbers
):
    launcher = shutil.which("brickstore")
    assert launcher is not None

    database_path = tmp_path / "database-v12"
    database_path.write_bytes(database_bytes)
    environment = os.environ.copy()
    environment["BRICKSTORE_DATABASE_PATH"] = str(database_path)
    environment["XDG_DATA_HOME"] = str(tmp_path / "profile")

    result = subprocess.run(
        [launcher, command_name, *item_numbers],
        capture_output=True,
        check=False,
        text=True,
        timeout=60,
        env=environment,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout) == [
        {id_key: item_number, "items": [SOURCE_ENTRY]} for item_number in item_numbers
    ]
