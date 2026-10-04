"""Process-isolated trusted adapters with hard wall time and JSON boundaries."""
from __future__ import annotations

import subprocess
import os
import signal
import sys
import tempfile
from pathlib import Path

from .safety import SafetyError, canonical, strict_json


class ExternalAdapter:
    def __init__(self, config):
        self.config = config
        self.timeout = config["limits"]["work_timeout_seconds"]

    def __getattr__(self, method):
        if method not in {"discover", "render", "quality", "publish", "reconcile", "metrics", "submit_rewards", "reconcile_rewards", "reward_status", "verify_ready", "visual_execution_state"}:
            raise AttributeError(method)
        return lambda *args: self.call(method, args)

    def call(self, method, args):
        from .engine import AdapterFailure
        message = canonical({"config": self.config, "method": method, "args": args}).encode()
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as error:
            try:
                process = subprocess.Popen([sys.executable, "-m", "tiktok_clipping_cli.adapter_worker"],
                    stdin=subprocess.PIPE, stdout=output, stderr=error, start_new_session=True)
                try:
                    process.communicate(message, timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    # Freeze the worker's process group before bounded inspection.
                    # Killing/reaping that group must happen even if ps itself fails.
                    try:
                        os.killpg(process.pid, signal.SIGSTOP)
                    except ProcessLookupError:
                        pass
                    try:
                        listing = subprocess.run(["ps", "-axo", "pid=,ppid="], capture_output=True, text=True, timeout=2, check=False)
                        parent_map = {}
                        for row in listing.stdout.splitlines():
                            columns = row.split()
                            if len(columns) == 2 and all(c.isdigit() for c in columns):
                                parent_map.setdefault(int(columns[1]), []).append(int(columns[0]))
                        descendants = []
                        pending = [process.pid]
                        while pending:
                            parent = pending.pop()
                            children = parent_map.get(parent, [])
                            descendants.extend(children)
                            pending.extend(children)
                        for child in reversed(descendants):
                            try:
                                os.kill(child, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                    except (OSError, subprocess.TimeoutExpired):
                        # Inspection failure cannot bypass mandatory worker termination.
                        pass
                    finally:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.communicate()
                    raise
            except subprocess.TimeoutExpired as exc:
                raise AdapterFailure("ambiguous" if method in {"publish", "submit_rewards"} else "transient", "adapter_work_timeout") from exc
            output.seek(0)
            raw = output.read(self.config["limits"]["max_payload_bytes"] + 1)
            if process.returncode != 0:
                raise AdapterFailure("ambiguous" if method in {"publish", "submit_rewards"} else "permanent", "adapter_process_failed")
            try:
                record = strict_json(raw, self.config["limits"]["max_payload_bytes"])
                if not isinstance(record, dict) or set(record) not in ({"result"}, {"error", "category", "retry_after"}, {"error", "category", "retry_after", "provider", "code", "status"}):
                    raise SafetyError("invalid_adapter_envelope")
            except SafetyError as exc:
                raise AdapterFailure("ambiguous" if method in {"publish", "submit_rewards"} else "permanent", str(exc)) from exc
            if "error" in record:
                raise AdapterFailure(record["category"], record["error"], record["retry_after"], provider=record.get("provider"), code=record.get("code"), status=record.get("status"))
            return record["result"]
