"""Hold real Google Chrome launches while a demo holds the bare desktop.

On the demo host (adam-server) Ronin prepares and records demos on the bare
macOS desktop under a Tether UI lease on the ``remote-bare`` provider. Its prep
scripts drive Chrome by application name ("Google Chrome") through
LaunchServices, System Events and AppleScript. Every Chrome this engine starts
from ``/Applications/Google Chrome.app`` -- headless or not -- registers with
the same bundle id, so those lookups can land on the engine's Chrome instead of
the demo's, and quitting Chrome by name can kill the engine's browser
(agent-issues#1277).

Before launching or attaching to the real Google Chrome app, the engine asks
Warden (Tether's lease ledger) for UI leases on ``remote-bare`` and waits while
one is listed in any state, the same rule Issue Manager's coordinator applies.
A process running inside that lease's own Tether session (``TETHER_SESSION``
equals the lease id) is the demo itself and is not held. A host without
Warden's executable has no lease ledger, so nothing is held there. An
unreadable ledger fails the launch.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from . import BrowserHarnessError

DESKTOP_PROVIDER = "remote-bare"
DEFAULT_WAIT_SECONDS = 600.0
POLL_SECONDS = 10.0


def warden_executable() -> Path:
    """Warden's installed executable in the host's Tether environment."""
    return Path.home() / ".tether" / "venv" / "bin" / "warden"


def is_real_chrome_app(executable: Optional[str]) -> bool:
    return sys.platform == "darwin" and bool(executable) and "/Google Chrome.app/" in executable


def desktop_ui_leases(warden: Path) -> list[dict]:
    """UI leases on the bare desktop held by anyone other than this process's session."""
    command = [str(warden), "status", "--provider", DESKTOP_PROVIDER]
    try:
        result = subprocess.run(
            command, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30
        )
        status = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        raise BrowserHarnessError(
            f"Cannot read the desktop lease ledger with `{' '.join(command)}`: {exc}"
        ) from exc
    if not isinstance(status, dict) or status.get("ok") is not True or not isinstance(
        status.get("leases"), list
    ):
        raise BrowserHarnessError(
            f"Cannot read the desktop lease ledger with `{' '.join(command)}`: "
            f"exit {result.returncode}, output {result.stdout.strip()[:500]!r}"
        )
    own_session = os.environ.get("TETHER_SESSION")
    return [
        lease
        for lease in status["leases"]
        if isinstance(lease, dict)
        and lease.get("type") == "ui"
        and (own_session is None or lease.get("lease") != own_session)
    ]


def _describe(leases: list[dict]) -> str:
    return ", ".join(
        f"lease {lease.get('lease')} owner {lease.get('owner')} ({lease.get('state')})"
        for lease in leases
    )


def wait_for_desktop_lease(
    executable: Optional[str],
    *,
    timeout: float = DEFAULT_WAIT_SECONDS,
    poll: float = POLL_SECONDS,
) -> None:
    """Return once no other UI lease holds the bare desktop, or raise after ``timeout``.

    Only launches of the real Google Chrome app on a host with Warden are held.
    """
    if not is_real_chrome_app(executable):
        return
    warden = warden_executable()
    if not warden.is_file():
        return
    deadline = time.monotonic() + timeout
    announced = False
    while True:
        leases = desktop_ui_leases(warden)
        if not leases:
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BrowserHarnessError(
                f"Google Chrome was not launched: the {DESKTOP_PROVIDER} desktop stayed leased "
                f"for {timeout:g}s ({_describe(leases)}). A demo is using the desktop's Chrome; "
                "run this command again after the lease ends."
            )
        if not announced:
            sys.stderr.write(
                f"Waiting up to {timeout:g}s for the {DESKTOP_PROVIDER} desktop lease to end "
                f"before launching Google Chrome ({_describe(leases)}).\n"
            )
            announced = True
        time.sleep(min(poll, remaining))
