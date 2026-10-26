"""Private per-profile cloud metadata and CLI secret-manager access."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from .client import ClientError

def secret_helper():
    return Path(__file__).resolve().parents[2] / "_repo" / "_secret-manager" / "secrets.sh"


def secret_name(config):
    digest = hashlib.sha256(str(config.get_profile_data_dir()).encode()).hexdigest()[:16]
    return "cloud-session-" + digest


def secret(config, operation, value=None):
    helper = secret_helper()
    args = [str(helper), operation]
    args += ["--tool", "roomba", "--type", secret_name(config)] if operation == "set" else ["roomba-" + secret_name(config)]
    try:
        if operation == "set":
            checked = subprocess.run([str(helper), "has", "roomba-" + secret_name(config)], capture_output=True, text=True, timeout=30)
            if checked.returncode not in (0, 1):
                raise ClientError("Cloud credential store unavailable")
        result = subprocess.run(args, input=json.dumps(value) if value is not None else None, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        raise ClientError("Cloud credential store unavailable") from None
    if result.returncode:
        raise ClientError("Cloud credentials unavailable in CLI secret manager; import an authorized login capture")
    if operation == "get":
        try:
            return json.loads(result.stdout)
        except ValueError:
            raise ClientError("Cloud credential store returned invalid session data") from None


def session_path(config):
    return config.get_profile_data_dir() / "cloud-session.json"


def save_session(config, data):
    destination = session_path(config)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(data, handle)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_session(config):
    try:
        data = json.loads(session_path(config).read_text())
    except (OSError, ValueError):
        raise ClientError("Cloud session missing; import an authorized login capture") from None
    if not isinstance(data, dict) or not isinstance(data.get("robots"), list):
        raise ClientError("Cloud session invalid; reimport an authorized login capture")
    return data


