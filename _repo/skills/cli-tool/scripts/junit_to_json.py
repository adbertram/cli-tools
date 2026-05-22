#!/usr/bin/env python3
"""Convert JUnit XML produced by pytest into the JSON contract test-cli-tool.sh emits.

Replaces ~200 lines of fragile awk/sed regex parsing of pytest's stdout. Reads
environment variables passed from the shell wrapper:

    CLI_NAME   – CLI tool name
    COMMAND    – optional command filter
    JUNIT      – path to the pytest --junitxml file
    EXIT_CODE  – pytest exit code (string)
    RAW_OUTPUT_FILE – path to pytest stdout/stderr captured by the wrapper

Emits a single JSON document on stdout.
"""

from __future__ import annotations

import json
import os
import re
import sys
import xml.etree.ElementTree as ET


def main() -> int:
    cli_name = os.environ.get("CLI_NAME", "")
    command = os.environ.get("COMMAND") or None
    junit_path = os.environ.get("JUNIT", "")
    exit_code = int(os.environ.get("EXIT_CODE", "1"))
    raw_output_file = os.environ.get("RAW_OUTPUT_FILE", "")
    precheck_status = os.environ.get("PRECHECK_STATUS", "")
    precheck_message = os.environ.get("PRECHECK_MESSAGE", "")
    raw_output = ""
    if raw_output_file:
        try:
            raw_output = open(raw_output_file, encoding="utf-8").read()
        except OSError:
            raw_output = ""
    else:
        raw_output = os.environ.get("RAW_OUTPUT", "")

    summary = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    failures: list[dict] = []

    try:
        root = ET.parse(junit_path).getroot()
    except (FileNotFoundError, ET.ParseError):
        root = None

    if root is not None:
        suites = root.iter("testsuite") if root.tag != "testsuite" else [root]
        for suite in suites:
            summary["failed"] += int(suite.get("failures", "0"))
            summary["errors"] += int(suite.get("errors", "0"))
            summary["skipped"] += int(suite.get("skipped", "0"))
            total = int(suite.get("tests", "0"))
            summary["passed"] += max(0, total - summary["failed"] - summary["errors"] - summary["skipped"])
            for case in suite.iter("testcase"):
                problem = case.find("failure")
                if problem is None:
                    problem = case.find("error")
                if problem is None:
                    continue
                message = (problem.get("message") or "").splitlines()[0][:300] or "Test failed"
                test_name = case.get("name", "")
                test_file = (case.get("classname") or "").replace(".", "/").split("/")[-1] or "tests"
                failures.append({
                    "test_name": test_name,
                    "file": test_file,
                    "message": message,
                    "todo": {
                        "content": f"Fix: {message}"[:150],
                        "activeForm": f"Fixing {test_name}"[:100],
                        "status": "pending",
                    },
                })

    if precheck_status == "passed":
        summary["passed"] += 1
    elif precheck_status == "skipped":
        summary["skipped"] += 1
    elif precheck_status == "failed":
        summary["failed"] += 1
        failures.insert(0, {
            "test_name": "test_auth_status_schema_preflight",
            "file": "test-cli-tool.sh",
            "message": precheck_message[:300] or "auth status schema preflight failed",
            "todo": {
                "content": f"Fix: {precheck_message[:145] or 'auth status schema preflight failed'}",
                "activeForm": "Fixing auth status schema preflight",
                "status": "pending",
            },
        })

    auth_text = "\n".join([raw_output, precheck_message])
    auth_required = bool(re.search(
        r"not authenticated|not fully authenticated|authentication required|"
        r"complete live list-command testing|missing authenticated credential types|"
        r"authenticated must be true in auth status output|"
        r"Run '.*auth login'|auth login.*first",
        auth_text, re.IGNORECASE,
    ))
    auth_cmd_match = re.search(r"Run '([^']+)'", raw_output)
    auth_command = auth_cmd_match.group(1) if auth_cmd_match else (f"{cli_name} auth login" if auth_required else None)

    success = exit_code == 0 and precheck_status != "failed"

    json.dump({
        "success": success,
        "cli_name": cli_name,
        "command_filter": command,
        "summary": summary,
        "auth_required": auth_required,
        "auth_command": auth_command,
        "failures": failures,
        "raw_output": raw_output,
    }, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
