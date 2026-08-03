import json
import os
import shutil
import stat
import subprocess


SOURCE_ENTRY = {
    "item": {
        "category_id": 5,
        "name": "Brick 2 x 4",
        "no": "3001",
        "type": "PART",
    },
    "color_id": 5,
    "extra_quantity": 0,
    "is_alternate": False,
    "is_counterpart": False,
    "quantity": 2,
}


FAKE_BRICKLINK = """#!/usr/bin/env python3
import json
import os
import sys

with open(os.environ["BRICKLINK_ARGS_PATH"], "a", encoding="utf-8") as output:
    output.write(json.dumps(sys.argv[1:]) + "\\n")

print(json.dumps([{"match_no": 7, "entries": [
    {
        "item": {
            "category_id": 5,
            "name": "Brick 2 x 4",
            "no": "3001",
            "type": "PART",
        },
        "color_id": 5,
        "extra_quantity": 0,
        "is_alternate": False,
        "is_counterpart": False,
        "quantity": 2,
    }
]}]))
"""


def test_installed_set_contents_uses_the_public_launcher_and_exact_child_arguments(tmp_path):
    launcher = shutil.which("brickstore")
    assert launcher is not None

    fake_bricklink = tmp_path / "bricklink"
    fake_bricklink.write_text(FAKE_BRICKLINK, encoding="utf-8")
    fake_bricklink.chmod(stat.S_IRWXU)
    child_args_path = tmp_path / "bricklink-args.jsonl"
    environment = os.environ.copy()
    environment["BRICKLINK_ARGS_PATH"] = str(child_args_path)
    environment["PATH"] = "{}:{}".format(tmp_path, environment["PATH"])
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
        {"set_id": "30670-1", "items": [{**SOURCE_ENTRY, "match_no": 7}]},
        {"set_id": "75313-1", "items": [{**SOURCE_ENTRY, "match_no": 7}]},
    ]
    assert [json.loads(line) for line in child_args_path.read_text(encoding="utf-8").splitlines()] == [
        ["catalog", "subsets", "SET", "30670-1"],
        ["catalog", "subsets", "SET", "75313-1"],
    ]
