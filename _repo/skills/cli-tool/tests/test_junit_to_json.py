"""Regression coverage for auth-status precheck injection in junit_to_json.py."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]


def test_junit_to_json_injects_precheck_failure_and_exits_nonzero(tmp_path):
    junit_path = tmp_path / "results.xml"
    junit_path.write_text(
        "<testsuite tests='1' failures='0' errors='0' skipped='0'>"
        "<testcase classname='tests.example' name='test_example'/>"
        "</testsuite>",
        encoding="utf-8",
    )
    raw_output_path = tmp_path / "raw.log"
    raw_output_path.write_text("", encoding="utf-8")

    env = os.environ.copy()
    env.update({
        "CLI_NAME": "google",
        "JUNIT": str(junit_path),
        "EXIT_CODE": "0",
        "RAW_OUTPUT_FILE": str(raw_output_path),
        "PRECHECK_STATUS": "failed",
        "PRECHECK_MESSAGE": "profiles must be array",
    })

    result = subprocess.run(
        ["python3", str(SKILL_ROOT / "scripts/junit_to_json.py")],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert payload["summary"] == {"passed": 1, "failed": 1, "skipped": 0, "errors": 0}
    assert payload["failures"][0]["test_name"] == "test_auth_status_schema_preflight"
    assert payload["failures"][0]["message"] == "profiles must be array"


def test_junit_to_json_marks_auth_readiness_precheck_as_auth_required(tmp_path):
    junit_path = tmp_path / "results.xml"
    junit_path.write_text(
        "<testsuite tests='0' failures='0' errors='0' skipped='0'></testsuite>",
        encoding="utf-8",
    )
    raw_output_path = tmp_path / "raw.log"
    raw_output_path.write_text("", encoding="utf-8")

    env = os.environ.copy()
    env.update({
        "CLI_NAME": "brickowl",
        "JUNIT": str(junit_path),
        "EXIT_CODE": "0",
        "RAW_OUTPUT_FILE": str(raw_output_path),
        "PRECHECK_STATUS": "failed",
        "PRECHECK_MESSAGE": (
            "profile default credential_types[browser_session].authenticated "
            "must be true in auth status output"
        ),
    })

    result = subprocess.run(
        ["python3", str(SKILL_ROOT / "scripts/junit_to_json.py")],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["auth_required"] is True
    assert payload["auth_command"] == "brickowl auth login"


def test_junit_to_json_exits_zero_when_successful(tmp_path):
    junit_path = tmp_path / "results.xml"
    junit_path.write_text(
        "<testsuite tests='1' failures='0' errors='0' skipped='0'>"
        "<testcase classname='tests.example' name='test_example'/>"
        "</testsuite>",
        encoding="utf-8",
    )
    raw_output_path = tmp_path / "raw.log"
    raw_output_path.write_text("", encoding="utf-8")

    env = os.environ.copy()
    env.update({
        "CLI_NAME": "google",
        "JUNIT": str(junit_path),
        "EXIT_CODE": "0",
        "RAW_OUTPUT_FILE": str(raw_output_path),
        "PRECHECK_STATUS": "passed",
        "PRECHECK_MESSAGE": "ok",
    })

    result = subprocess.run(
        ["python3", str(SKILL_ROOT / "scripts/junit_to_json.py")],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
