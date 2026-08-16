import json
import os
import shutil
import subprocess

from tests.database_fixtures import two_sets_one_part_database

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
    "quantity": 3,
}


def test_installed_set_contents_uses_the_public_launcher_and_local_database(tmp_path):
    launcher = shutil.which("brickstore")
    assert launcher is not None

    database_path = tmp_path / "database-v12"
    database_path.write_bytes(two_sets_one_part_database())
    environment = os.environ.copy()
    environment["BRICKSTORE_DATABASE_PATH"] = str(database_path)
    environment["XDG_DATA_HOME"] = str(tmp_path / "profile")

    result = subprocess.run(
        [launcher, "set-contents", "30670-1", "75313-1"],
        capture_output=True,
        check=False,
        text=True,
        timeout=60,
        env=environment,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout) == [
        {"set_id": "30670-1", "items": [{**SOURCE_ENTRY, "match_no": 0}]},
        {"set_id": "75313-1", "items": [{**SOURCE_ENTRY, "match_no": 0}]},
    ]
