#!/usr/bin/env python3
"""Instrument end-to-end `facebook groups get` CLI timing."""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("Value must be greater than zero")
    return parsed


def _read_stream(
    stream: TextIO,
    lines: list[str],
    first_output_times: dict[str, float],
    stream_name: str,
) -> None:
    for line in iter(stream.readline, ""):
        if stream_name not in first_output_times:
            first_output_times[stream_name] = time.perf_counter()
        lines.append(line)


def _parse_group_result(stdout: str) -> dict:
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"facebook groups get did not return valid JSON: {exc}") from exc

    if not isinstance(result, dict):
        raise RuntimeError("facebook groups get returned JSON that is not an object")

    for field in ("group_id", "name"):
        if field not in result:
            raise RuntimeError(f"facebook groups get result is missing required field: {field}")

    return result


def _run_groups_get(facebook_command: str, group_id: str, iteration: int) -> dict:
    command = [facebook_command, "groups", "get", group_id]
    started_at = datetime.now(timezone.utc).isoformat()
    start_time = time.perf_counter()

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    if process.stdout is None:
        raise RuntimeError("Failed to capture stdout from facebook groups get")
    if process.stderr is None:
        raise RuntimeError("Failed to capture stderr from facebook groups get")

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    first_output_times: dict[str, float] = {}
    stdout_thread = threading.Thread(
        target=_read_stream,
        args=(process.stdout, stdout_lines, first_output_times, "stdout"),
    )
    stderr_thread = threading.Thread(
        target=_read_stream,
        args=(process.stderr, stderr_lines, first_output_times, "stderr"),
    )
    stdout_thread.start()
    stderr_thread.start()

    return_code = process.wait()
    stdout_thread.join()
    stderr_thread.join()
    completed_at = datetime.now(timezone.utc).isoformat()
    completed_time = time.perf_counter()

    stdout = "".join(stdout_lines)
    stderr = "".join(stderr_lines)

    duration_seconds = completed_time - start_time
    if return_code != 0:
        raise RuntimeError(
            json.dumps(
                {
                    "error": "facebook groups get failed",
                    "command": command,
                    "return_code": return_code,
                    "duration_seconds": round(duration_seconds, 3),
                    "stderr": stderr,
                    "stdout": stdout,
                },
                indent=2,
            )
        )

    if "stdout" not in first_output_times:
        raise RuntimeError("facebook groups get completed without writing a JSON result to stdout")

    group = _parse_group_result(stdout)

    run = {
        "iteration": iteration,
        "group_id": group_id,
        "command": command,
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_seconds": round(duration_seconds, 3),
        "first_stdout_seconds": round(first_output_times["stdout"] - start_time, 3),
        "return_code": return_code,
        "stderr": stderr,
        "result": group,
    }
    if "stderr" in first_output_times:
        run["first_stderr_seconds"] = round(first_output_times["stderr"] - start_time, 3)
    return run


def _summarize(runs: list[dict]) -> dict:
    durations = [run["duration_seconds"] for run in runs]
    return {
        "count": len(durations),
        "min_seconds": min(durations),
        "max_seconds": max(durations),
        "mean_seconds": round(statistics.mean(durations), 3),
        "median_seconds": round(statistics.median(durations), 3),
    }


def _summarize_by_group(runs: list[dict], group_ids: list[str]) -> dict:
    summary = {}
    for group_id in group_ids:
        group_runs = [run for run in runs if run["group_id"] == group_id]
        summary[group_id] = _summarize(group_runs)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure end-to-end timing for `facebook groups get` CLI invocations."
    )
    parser.add_argument("group_ids", nargs="+", help="Group IDs, slugs, or group URLs to measure.")
    parser.add_argument(
        "--iterations",
        type=_positive_int,
        default=1,
        help="Number of times to run each group get command.",
    )
    parser.add_argument(
        "--facebook-command",
        default="facebook",
        help="Facebook CLI executable to invoke.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON report path. The report is always printed to stdout.",
    )
    args = parser.parse_args()

    runs = []
    for iteration in range(1, args.iterations + 1):
        for group_id in args.group_ids:
            runs.append(_run_groups_get(args.facebook_command, group_id, iteration))

    report = {
        "command_under_test": "facebook groups get",
        "facebook_command": args.facebook_command,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "iterations": args.iterations,
        "group_ids": args.group_ids,
        "summary": _summarize(runs),
        "summary_by_group": _summarize_by_group(runs, args.group_ids),
        "runs": runs,
    }

    serialized = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(f"{serialized}\n", encoding="utf-8")
    print(serialized)


if __name__ == "__main__":
    main()
