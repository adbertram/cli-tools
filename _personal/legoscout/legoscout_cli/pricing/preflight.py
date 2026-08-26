#!/usr/bin/env python3
"""Mandatory FULL pre-run gate for a LEGO Scout deal run.

A deal run touches far more than the two comps credentials: a dozen source
CLIs (some needing live authenticated sessions), a runtime headless browser,
the adam-server deployment the `pull-db`/`push` bookends depend on, the
source registry's own structural health and researched fee configs, the
ledger working copy, five custom-agent definitions plus their hard-rules
parity contract, ten project skills, the global agent standards file the
worker prompts reference verbatim, and the per-run workspace directories.
This command verifies every one of those BEFORE any worker spawns, because
each of them has already silently cost a run something when skipped:

- A session-wide eBay auth lapse looks identical to a per-candidate miss
  from inside any single comps call; on 2026-08-20 eleven set candidates
  got zero eBay comps before anyone noticed. `pricing comps` keeps its
  deliberate PER-CANDIDATE resilience (`ebay.available: false` on one set);
  this gate catches the SESSION-WIDE lapse instead.
- The expired-listing sweep used to abort mid-run on a missing source CLI
  (2026-08-22): every CLI-first namespace's binary must resolve up front.
- A registry row whose `fees` block was never researched makes landed-cost
  synthesis RAISE for that source's candidates mid-run; surfaced here as a
  warning naming every such active source.
- Stale agent definitions or hard-rules drift break the spawn step itself;
  the parity checker runs here, not just after edits.

Gate vs warning: anything a run cannot complete without (credentials,
binaries, auth sessions, browser, adam-server/pm2, registry soundness,
ledger writability, agent files, parity, skills, standards) FAILS the run
at the door. Missing outreach (Gmail) auth only degrades the optional
prospect half, so it warns. Unresearched fee configs warn because the run
still completes for every OTHER source while naming the gap.

Execution model (2026-08-23 chaos-hardened):

- INDEPENDENT CHECKS RUN CONCURRENTLY in a thread pool -- every expensive
  check is a subprocess wait (auth round-trips 5-7s each, ssh ~0.3s), so
  wall time collapses from the SUM of waits to roughly the SLOWEST one.
  Results are assembled deterministically after all futures resolve.
- NOTHING HANGS UNBOUNDED. Every subprocess carries a timeout; the checks
  run in parallel, so the worst-case wall time is max(auth 30s, ssh 45s,
  parity 60s), not their sum.
- NOTHING ESCAPES AS A TRACEBACK. Every external input is untrusted: an
  unreadable/locked/corrupt registry database, a binary emitting invalid
  UTF-8 or non-JSON noise before its payload, an unwritable workspace
  parent -- all resolve to labeled FAIL lines in the structured report,
  never an unhandled exception past `main()`.

Read-only except for creating the standard run workspace directories when
missing (idempotent setup, no data touched). Auth checks shell out to each
tool's own `auth status` -- same pattern the rest of the pricing modules
use -- never a Python API client.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import (
    ThreadPoolExecutor,
    TimeoutError as FuturesTimeoutError,
)
from pathlib import Path
from typing import Any

import requests

from .. import paths
from ..deploy import config as deploy_config
from . import brickognize, minifig_detector

BRICKLINK_COMMAND = "bricklink"
EBAY_COMMAND = "ebay"

# Every active registry namespace reached "CLI first" and the binary that
# serves it. Auth requirements are NOT duplicated here: they are read from
# the live registry entry (`access.auth_required`), so a registry change
# flows through automatically. An active CLI-first namespace missing from
# this map is a FAILURE, not a silent skip.
SOURCE_CLI_BINARIES = {
    "americasthriftsupply": "americasthriftsupply",
    "auctionzip": "auctionzip",
    "depop": "depop",
    "ebay": "ebay",
    "facebook": "facebook",
    "fbgroup-bricklinkww": "facebook",
    "fbgroup-retiredsets": "facebook",
    "fbgroup-usabst": "facebook",
    "mercari": "mercari",
    "nextdoor": "nextdoor",
    "poshmark": "poshmark",
    "shopgoodwill": "shopgoodwill",
    "shopsalvationarmy": "shopsalvationarmy",
    "stockx": "stockx",
}

PLAYWRIGHT_CLI = "playwright-cli"
GOOGLE_CLI = "google"
BRICKOGNIZE_HEALTH_URL = "https://api.brickognize.com/health/"
BRICKOGNIZE_TIMEOUT_SECONDS = 10
DETECTOR_CHECK_TIMEOUT_SECONDS = 120
MINIFIG_DETECTOR = "grounding-dino-tiny"
REQUIRED_MINIFIG_LEAVES = ("detect", "eval", "identify", "price")
USAGE_PROBE_TIMEOUT_SECONDS = 30

PROJECT_SKILLS = (
    "legoscout-orchestrator",
    "legoscout-sources",
    "legoscout-pricing",
    "legoscout-comps",
    "legoscout-deal-scoring",
    "legoscout-ledger",
    "legoscout-deal-invalidate",
    "legoscout-display",
    "start-legoscout-run",
    "legoscout-minifig-identifier",
)

AGENT_NAMES = (
    "legoscout-source-worker",
    "legoscout-classifier",
    "legoscout-appraiser",
    "legoscout-prospect-scout",
    "legoscout-minifig-identifier",
)

GLOBAL_STANDARDS_PATH = (Path("~/.agents/skills/agent-expert/references/"
                              "global-standards.md")).expanduser()

AUTH_TIMEOUT_SECONDS = 30
SSH_TIMEOUT_SECONDS = 45
PARITY_TIMEOUT_SECONDS = 60
POOL_WORKERS = 10         # top-level independent checks
INNER_AUTH_WORKERS = 4    # concurrent auth round-trips inside the source scan


def _shorten(text: str, limit: int = 1200) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit] + "...[truncated]"


def _loads_tolerant(*texts: str | None) -> tuple[Any, str | None]:
    """Parse the first JSON value found in any candidate text (tried in
    order, stdout before stderr).

    Tolerates two real-world quirks without weakening the verdict: a wrapper
    script printing a warning/banner BEFORE the JSON payload, and a tool
    that prints its status document to stderr instead of stdout. Anything
    else comes back as (None, evidence) and the caller reports not-
    authenticated / unreachable with that evidence.
    """
    for text in texts:
        if not text:
            continue
        try:
            return json.loads(text), None
        except Exception:  # noqa: BLE001 -- fall through to prefix strip
            pass
        # Strip leading non-JSON noise and retry from the first brace.
        for opener in ("{", "["):
            idx = text.find(opener)
            if idx > 0:
                try:
                    return json.loads(text[idx:]), None
                except Exception:  # noqa: BLE001
                    continue
    evidence = _shorten(" | ".join(
        "%s:%s" % (name, (text or "").strip()[:200])
        for name, text in (("stdout", texts[0] if texts else None),
                           ("stderr", texts[1] if len(texts) > 1 else None))
        if text))
    return None, (evidence or "empty output")


def _select_profile(binary_name: str, profiles: list) -> dict[str, Any]:
    """The one profile this check evaluates, or an error describing why none
    can be chosen. Never guesses among ambiguous candidates."""
    if not profiles:
        return {"error": "%s auth status returned zero profiles" % binary_name}
    active = [p for p in profiles if isinstance(p, dict) and p.get("active") is True]
    if len(active) == 1:
        return {"profile": active[0]}
    if not active and len(profiles) == 1 and isinstance(profiles[0], dict):
        return {"profile": profiles[0]}
    return {"error": "%s auth status returned %d profile(s) with none "
                     "unambiguously active -- refusing to guess which one to check"
                     % (binary_name, len(profiles))}


def _check(binary_name: str, profile: str | None) -> dict[str, Any]:
    """`authenticated`/`profile`/optional `error` for one CLI's auth status.

    Every failure mode below -- missing binary, a failed subprocess, undecodable
    output bytes, non-JSON stdout AND stderr, zero profiles, or an ambiguous
    active profile -- means NOT authenticated. None of them may raise past
    this function.
    """
    resolved = shutil.which(binary_name)
    if resolved is None:
        return {"authenticated": False, "profile": None,
                "error": "%s CLI not on PATH: %r" % (binary_name, binary_name)}

    args = [resolved, "auth", "status"]
    if profile is not None:
        args.extend(["--profile", profile])

    try:
        result = subprocess.run(args, text=True, capture_output=True,
                                check=False, timeout=AUTH_TIMEOUT_SECONDS)
    except OSError as exc:
        return {"authenticated": False, "profile": None,
                "error": "%s auth status failed to start: %s" % (binary_name, exc)}
    except subprocess.TimeoutExpired:
        return {"authenticated": False, "profile": None,
                "error": "%s auth status timed out after %ds"
                         % (binary_name, AUTH_TIMEOUT_SECONDS)}
    except UnicodeDecodeError as exc:
        return {"authenticated": False, "profile": None,
                "error": "%s auth status emitted undecodable output: %s"
                         % (binary_name, exc)}

    if result.returncode != 0:
        combined = "\n".join(part for part in [result.stdout, result.stderr] if part)
        return {"authenticated": False, "profile": None,
                "error": "%s auth status exited %d: %s"
                        % (binary_name, result.returncode, _shorten(combined))}

    parsed, evidence = _loads_tolerant(result.stdout, result.stderr)
    if parsed is None:
        return {"authenticated": False, "profile": None,
                "error": "%s auth status returned no JSON payload: %s"
                         % (binary_name, evidence)}

    profiles = parsed.get("profiles") if isinstance(parsed, dict) else None
    if not isinstance(profiles, list):
        return {"authenticated": False, "profile": None,
                "error": "%s auth status returned no 'profiles' list" % binary_name}

    selection = _select_profile(binary_name, profiles)
    if "error" in selection:
        return {"authenticated": False, "profile": None, "error": selection["error"]}

    chosen = selection["profile"]
    return {"authenticated": bool(chosen.get("authenticated")), "profile": chosen.get("name")}


def _require_on_path(binary_name: str) -> dict[str, Any]:
    resolved = shutil.which(binary_name)
    row = {"binary": binary_name, "present": resolved is not None, "path": resolved}
    if resolved is None:
        row["error"] = ("%s executable was not located on PATH or in ~/.local/bin"
                        % binary_name)
    return row


def _check_brickognize() -> dict[str, Any]:
    """Probe provider health without identifying or uploading a figure."""
    try:
        response = requests.get(
            BRICKOGNIZE_HEALTH_URL,
            headers={"User-Agent": brickognize.USER_AGENT},
            timeout=BRICKOGNIZE_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 -- provider evidence, never an escape
        return {
            "reachable": False,
            "error": "%s: %s" % (type(exc).__name__, exc),
        }
    return {"reachable": True, "error": None}


def _check_minifig_detector() -> dict[str, Any]:
    return _check_minifig_detector_with_deadline(
        DETECTOR_CHECK_TIMEOUT_SECONDS)


def _check_minifig_detector_with_deadline(
    timeout_seconds: float,
) -> dict[str, Any]:
    """Load the selected runtime and pinned model exactly as detection does.

    A stalled Hugging Face ``from_pretrained`` (cold cache on a flaky
    network can hang indefinitely) must surface as a bounded warning row,
    never hang the mandatory pre-run gate.
    """
    row: dict[str, Any] = {
        "available": False,
        "detector": MINIFIG_DETECTOR,
        "model": minifig_detector.GROUNDING_DINO_MODEL,
        "revision": minifig_detector.GROUNDING_DINO_REVISION,
        "error": None,
    }
    loader_pool = ThreadPoolExecutor(max_workers=1)
    try:
        future = loader_pool.submit(
            minifig_detector.load_detector, MINIFIG_DETECTOR)
        try:
            future.result(timeout=timeout_seconds)
        except FuturesTimeoutError:
            row["error"] = (
                "detector load exceeded %ss deadline; treating as "
                "unavailable for this run" % timeout_seconds)
            return row
    except Exception as exc:  # noqa: BLE001 -- runtime/model failure is warning evidence
        row["error"] = "%s: %s" % (type(exc).__name__, exc)
        return row
    finally:
        loader_pool.shutdown(wait=False, cancel_futures=True)
    row["available"] = True
    return row


def _check_installed_cli_usage() -> dict[str, Any]:
    """Probe the INSTALLED legoscout binary for every minifig subcommand.

    The worktree can expose leaves the installed tool lacks until the next
    install; an identifier run would die mid-batch on the gap, so the gate
    catches it before any worker spawns.
    """
    row: dict[str, Any] = {
        "leaves": [],
        "missing": list(REQUIRED_MINIFIG_LEAVES),
        "error": None,
    }
    binary = shutil.which("legoscout")
    if binary is None:
        row["error"] = ("legoscout binary not found on PATH; install the "
                        "repo tool before running identifier batches")
        return row
    present: list[str] = []
    for leaf in REQUIRED_MINIFIG_LEAVES:
        probe = subprocess.run(
            [binary, "minifig", leaf, "--help"],
            capture_output=True,
            timeout=USAGE_PROBE_TIMEOUT_SECONDS,
        )
        if probe.returncode == 0:
            present.append(leaf)
    row["leaves"] = present
    row["missing"] = [
        leaf for leaf in REQUIRED_MINIFIG_LEAVES if leaf not in present
    ]
    return row


def _read_registry() -> tuple[list[str] | None, list[str], str | None]:
    """ONE guarded read of the live registry: the active namespace list, its
    structural problems, and an error string when the database itself is
    unreadable (missing file, corruption, another process holding an
    exclusive lock -- all seen on real Dropbox-synced ledgers). Never
    raises."""
    from ..sources import registry as registry_module

    try:
        active = list(registry_module.active_namespaces())
    except Exception as exc:  # noqa: BLE001 -- the whole point of this guard
        return None, [], ("registry database unreadable (%s): %s -- close the "
                          "writer or restore the ledger, then re-run"
                          % (type(exc).__name__, exc))
    try:
        problems = sorted(registry_module.check())
    except Exception as exc:  # noqa: BLE001
        problems = ["registry structural check raised: %s" % exc]
    return active, problems, None


def _check_source_cli_access(
    profile: str | None,
    namespaces: list[str] | None = None,
) -> tuple[dict[str, Any], list, list]:
    """Presence (every scoped active CLI-first namespace) plus live auth
    status for those whose registry row requires auth. `namespaces=None`
    means every active namespace. Auth round-trips run concurrently.

    Returns (per-source rows, failures, warnings); failures/warnings are
    (label, detail) pairs. A registry database that cannot be read is a
    FAILURE here, never an escape.
    """
    active, _problems, registry_error = _read_registry()
    rows: dict[str, Any] = {}
    failures: list[tuple[str, str]] = []
    warnings: list[tuple[str, str]] = []
    if active is None:
        failures.append(("registry", registry_error or "unreadable"))
        return rows, failures, warnings

    planned = sorted(set(namespaces)) if namespaces is not None else sorted(active)

    # Resolve every planned namespace's entry FIRST (fast, local reads),
    # then run only the required auth round-trips concurrently.
    entries: dict[str, dict[str, Any]] = {}
    auth_targets: list[tuple[str, str]] = []
    for namespace in planned:
        if namespace not in active:
            failures.append(("source:%s" % namespace,
                             "not an active source in the registry -- resolve "
                             "the run's source list first"))
            continue
        from ..sources import registry as registry_module
        try:
            entry = registry_module.payload(namespace, with_notes=False)
        except Exception as exc:  # noqa: BLE001 -- reported, never raised past
            failures.append(("source:%s" % namespace,
                             "registry payload unreadable: %s" % exc))
            continue
        entries[namespace] = entry
        access = entry.get("access") or {}
        raw_auth = access.get("auth_required", False)
        if not isinstance(raw_auth, bool):
            warnings.append(
                ("source:%s" % namespace,
                 "registry auth_required is %r, not a boolean -- treated as "
                 "false (presence-only check); fix the registry row" % (raw_auth,)))
        binary = SOURCE_CLI_BINARIES.get(namespace)
        if binary is None:
            if str(access.get("method", "")).startswith("CLI first"):
                failures.append(
                    ("source:%s" % namespace,
                     "active CLI-first source has no preflight rule -- add its "
                     "binary to SOURCE_CLI_BINARIES in pricing/preflight.py"))
            continue
        row = _require_on_path(binary)
        row["auth_required"] = bool(raw_auth)
        if not row["present"]:
            row["authenticated"] = None
            failures.append(("source:%s" % namespace,
                             "'%s' CLI not on PATH -- install it before this "
                             "run" % binary))
        elif row["auth_required"]:
            auth_targets.append((namespace, binary))
        else:
            # Public/no-login access: presence is the whole contract. Never
            # runs `auth status` (StockX explicitly must stay cold).
            row["authenticated"] = None
        rows[namespace] = row

    if auth_targets:
        with ThreadPoolExecutor(
                max_workers=min(INNER_AUTH_WORKERS, len(auth_targets))) as pool:
            statuses = dict(zip((ns for ns, _ in auth_targets),
                                pool.map(lambda t: _check(t[1], profile),
                                         auth_targets)))
        for namespace, binary in auth_targets:
            status = statuses[namespace]
            rows[namespace]["authenticated"] = status["authenticated"]
            if not status["authenticated"]:
                rows[namespace]["error"] = status.get("error")
                failures.append(("source:%s" % namespace,
                                 status.get("error") or "not authenticated"))
    return rows, failures, warnings


def _registry_health(namespaces: list[str] | None = None) -> dict[str, Any]:
    """Structural problems plus every scoped active source whose fees were
    never researched (landed-cost synthesis raises for those candidates).
    Structural problems are registry-wide regardless of scope. An unreadable
    database is reported as a problem, never raised."""
    from ..sources import registry as registry_module

    active_list, problems, registry_error = _read_registry()
    missing_fees: list[str] = []
    scoped: list[str] = []
    if registry_error:
        problems.append(registry_error)
    elif active_list is not None:
        scoped = sorted(set(active_list) & set(namespaces)) \
            if namespaces is not None else list(active_list)
        for namespace in scoped:
            try:
                fees = registry_module.payload(
                    namespace, with_notes=False).get("fees")
            except Exception as exc:  # noqa: BLE001 -- per-source, reported
                problems.append("%s: payload unreadable: %s" % (namespace, exc))
                continue
            if fees is None:
                missing_fees.append(namespace)
    return {"sources": len(scoped), "problems": problems,
            "missing_fee_config": sorted(missing_fees)}


def _ledger_writable() -> dict[str, Any]:
    db_path = Path(paths.DB_PATH)
    parent_writable = db_path.parent.is_dir() and os.access(db_path.parent, os.W_OK)
    exists = db_path.exists()
    writable = os.access(db_path, os.W_OK) if exists else parent_writable
    return {"path": str(db_path), "exists": exists, "writable": bool(writable)}


def _check_adam_server() -> dict[str, Any]:
    """SSH reachability plus the deployed display app's pm2 status -- the two
    things `deploy pull-db`/`push` need on every run."""
    ssh = shutil.which("ssh")
    if ssh is None:
        return {"reachable": False, "error": "ssh client not on PATH"}
    try:
        proc = subprocess.run(
            [ssh, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
             deploy_config.REMOTE_HOST, deploy_config.PM2_BIN, "jlist"],
            capture_output=True, text=True, check=False,
            timeout=SSH_TIMEOUT_SECONDS)
    except OSError as exc:
        return {"reachable": False, "error": "ssh %s failed to start: %s"
                                                % (deploy_config.REMOTE_HOST, exc)}
    except subprocess.TimeoutExpired:
        return {"reachable": False,
                "error": "ssh %s timed out after %ds"
                         % (deploy_config.REMOTE_HOST, SSH_TIMEOUT_SECONDS)}
    except UnicodeDecodeError as exc:
        return {"reachable": False,
                "error": "remote output undecodable: %s" % exc}
    if proc.returncode != 0:
        combined = "\n".join(part for part in [proc.stdout, proc.stderr] if part)
        return {"reachable": False,
                "error": "ssh %s exited %d: %s"
                         % (deploy_config.REMOTE_HOST, proc.returncode,
                            _shorten(combined))}
    rows, evidence = _loads_tolerant(proc.stdout, proc.stderr)
    if rows is None:
        return {"reachable": True, "pm2_app_online": False,
                "error": "remote `pm2 jlist` returned no JSON payload: %s"
                         % evidence}
    statuses = {}
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and row.get("name"):
            statuses[row["name"]] = (row.get("pm2_env") or {}).get("status")
    online = statuses.get(deploy_config.PM2_APP_NAME) == "online"
    out: dict[str, Any] = {"reachable": True, "pm2_app_online": online}
    if not online:
        out["error"] = ("pm2 app '%s' status is %r, not 'online'"
                        % (deploy_config.PM2_APP_NAME,
                           statuses.get(deploy_config.PM2_APP_NAME)))
    return out


def _check_agents(project_root: Path) -> dict[str, Any]:
    """Custom-agent definitions plus their executable harness contracts."""
    claude_missing = [name for name in AGENT_NAMES
                      if not (project_root / ".claude" / "agents"
                              / ("%s.md" % name)).is_file()]
    codex_missing = [name for name in AGENT_NAMES
                     if not (project_root / ".codex" / "agents"
                             / ("%s.toml" % name)).is_file()]
    parity_script = project_root / "scripts" / "check_hard_rules_parity.py"
    parity: dict[str, Any] = {"script_present": parity_script.is_file()}
    if parity_script.is_file():
        try:
            proc = subprocess.run(["python3", str(parity_script)],
                                  cwd=str(project_root), capture_output=True,
                                  text=True, check=False,
                                  timeout=PARITY_TIMEOUT_SECONDS)
            parity["ok"] = proc.returncode == 0
            if not parity["ok"]:
                combined = "\n".join(p for p in [proc.stdout, proc.stderr] if p)
                parity["error"] = _shorten(combined)
        except (OSError, subprocess.TimeoutExpired, UnicodeDecodeError) as exc:
            parity["ok"] = False
            parity["error"] = str(exc)
    else:
        parity["ok"] = False
        parity["error"] = ("scripts/check_hard_rules_parity.py is missing from "
                           "the project root")

    identifier_script = (
        project_root / "scripts" / "test_minifig_identifier_contracts.py")
    identifier: dict[str, Any] = {
        "script_present": identifier_script.is_file()}
    if identifier_script.is_file():
        try:
            proc = subprocess.run(
                ["python3", str(identifier_script)], cwd=str(project_root),
                capture_output=True, text=True, check=False,
                timeout=PARITY_TIMEOUT_SECONDS)
            identifier["ok"] = proc.returncode == 0
            if not identifier["ok"]:
                combined = "\n".join(
                    part for part in [proc.stdout, proc.stderr] if part)
                identifier["error"] = _shorten(combined)
        except (OSError, subprocess.TimeoutExpired, UnicodeDecodeError) as exc:
            identifier["ok"] = False
            identifier["error"] = str(exc)
    else:
        identifier["ok"] = False
        identifier["error"] = (
            "scripts/test_minifig_identifier_contracts.py is missing from "
            "the project root")
    return {"claude_definitions_missing": claude_missing,
            "codex_definitions_missing": codex_missing,
            "hard_rules_parity": parity,
            "identifier_contract": identifier}


def _check_skills() -> dict[str, Any]:
    skills_root = paths.LEGOSCOUT_ROOT.parent / "skills" / "project"
    missing = [name for name in PROJECT_SKILLS
               if not (skills_root / name / "SKILL.md").is_file()]
    return {"root": str(skills_root),
            "missing": missing,
            "global_standards_present": GLOBAL_STANDARDS_PATH.is_file()}


def _ensure_workspaces() -> dict[str, Any]:
    """Create the standard run directories when missing. A directory that
    cannot be created (parent is a file, read-only filesystem, permissions)
    is REPORTED, never raised -- the caller turns it into a FAIL line."""
    created: list[str] = []
    errors: list[str] = []
    for attr in ("SOURCE_RUNS", "LISTING_IMAGES_ROOT"):
        target = Path(getattr(paths, attr))
        if target.is_dir():
            continue
        try:
            target.mkdir(parents=True, exist_ok=True)
            created.append(str(target))
        except OSError as exc:
            errors.append("cannot create %s: %s" % (target, exc))
    return {"created": created, "errors": errors,
            "source_runs": paths.SOURCE_RUNS,
            "listing_images": paths.LISTING_IMAGES_ROOT}


def _dedupe(namespaces: list[str]) -> list[str]:
    """First occurrence wins; duplicates must not inflate blocker counts."""
    out: list[str] = []
    for ns in namespaces:
        if ns not in out:
            out.append(ns)
    return out


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mandatory FULL pre-run gate: verifies every dependency a "
                    "deal run touches -- comps credentials, source CLIs and "
                    "their auth sessions, the runtime browser, adam-server, "
                    "the source registry, the ledger working copy, agent "
                    "definitions and hard-rules parity, project skills, and "
                    "the run workspaces -- before any source worker starts.")
    parser.add_argument("--profile", default=None,
                        help="Check this profile on the comps/source tools "
                             "instead of each tool's own active profile. The "
                             "gmail outreach check always uses ITS OWN active "
                             "profile.")
    parser.add_argument("--source", action="append", default=None, metavar="NS",
                        help="Scope the source-CLI and fee-config checks to "
                             "this active namespace instead of every active "
                             "source. Repeatable (duplicates are collapsed). "
                             "Match a planned selected-source run; omit for "
                             "an all-active run.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    scoped = _dedupe(args.source) if args.source is not None else None
    checks: dict[str, Any] = {}
    warnings: list[str] = []
    failures: list[tuple[str, str]] = []

    # Cheap local checks first (all sub-millisecond filesystem stats).
    browser_row = _require_on_path(PLAYWRIGHT_CLI)
    checks["runtime_browser"] = browser_row
    if not browser_row["present"]:
        failures.append(("runtime_browser", browser_row["error"]))

    ledger_row = _ledger_writable()
    checks["ledger_db"] = ledger_row
    if not ledger_row["writable"]:
        failures.append(("ledger_db",
                         "%s is not writable (exists=%s)"
                         % (ledger_row["path"], ledger_row["exists"])))

    skills_row = _check_skills()
    checks["skills"] = skills_row
    for name in skills_row["missing"]:
        failures.append(("skills", "project skill '%s' has no SKILL.md" % name))
    if not skills_row["global_standards_present"]:
        failures.append(("skills",
                         "global standards file missing: %s"
                         % GLOBAL_STANDARDS_PATH))

    workspaces_row = _ensure_workspaces()
    checks["workspaces"] = workspaces_row
    for error in workspaces_row["errors"]:
        failures.append(("workspaces", error))

    # Every expensive independent check runs CONCURRENTLY: auth round-trips,
    # ssh, parity, provider health, and detector runtime/model loading collapse
    # to roughly the slowest single wait instead of their sum.
    with ThreadPoolExecutor(max_workers=POOL_WORKERS) as pool:
        futures = {
            "bricklink": pool.submit(_check, BRICKLINK_COMMAND, args.profile),
            "ebay": pool.submit(_check, EBAY_COMMAND, args.profile),
            "sources": pool.submit(_check_source_cli_access, args.profile, scoped),
            "adam": pool.submit(_check_adam_server),
            "agents": pool.submit(_check_agents, paths.LEGOSCOUT_ROOT),
            "registry": pool.submit(_registry_health, scoped),
            "google": pool.submit(_check, GOOGLE_CLI, None),
            "brickognize": pool.submit(_check_brickognize),
            "minifig_detector": pool.submit(_check_minifig_detector),
            "installed_usage": pool.submit(_check_installed_cli_usage),
        }
        bricklink = futures["bricklink"].result()
        ebay = futures["ebay"].result()
        source_rows, source_failures, source_warnings = \
            futures["sources"].result()
        server_row = futures["adam"].result()
        agents_row = futures["agents"].result()
        registry_row = futures["registry"].result()
        google_status = futures["google"].result()
        brickognize_row = futures["brickognize"].result()
        detector_row = futures["minifig_detector"].result()
        usage_row = futures["installed_usage"].result()

    # 1. Comps credentials -- BrickLink AND eBay, live-authenticated.
    checks["comps_credentials"] = {"bricklink": bricklink, "ebay": ebay}
    for name, status in (("bricklink", bricklink), ("ebay", ebay)):
        if not status["authenticated"]:
            failures.append((name, status.get("error") or "not authenticated"))

    # 2. Source CLIs: presence everywhere, live auth where required.
    checks["source_clis"] = source_rows
    failures.extend(source_failures)
    warnings.extend("%s: %s" % pair for pair in source_warnings)

    # 3. Source registry: structure + researched fee configs.
    checks["registry"] = registry_row
    for problem in registry_row["problems"]:
        failures.append(("registry", problem))
    for namespace in registry_row["missing_fee_config"]:
        warnings.append("%s: no researched fee config -- landed-cost synthesis "
                        "raises for this source's candidates" % namespace)

    # 4. adam-server: SSH + the deployed display app's pm2 process.
    checks["adam_server"] = server_row
    if not server_row.get("reachable"):
        failures.append(("adam_server", server_row.get("error", "unreachable")))
    elif not server_row.get("pm2_app_online"):
        failures.append(("adam_server", server_row.get("error", "pm2 app offline")))

    # 5. Agent definitions + executable cross-runtime contracts.
    checks["agents"] = agents_row
    for name in agents_row["claude_definitions_missing"]:
        failures.append(("agents", ".claude/agents/%s.md is missing" % name))
    for name in agents_row["codex_definitions_missing"]:
        failures.append(("agents", ".codex/agents/%s.toml is missing" % name))
    if not agents_row["hard_rules_parity"]["ok"]:
        failures.append(("agents",
                         "hard-rules parity: %s"
                         % agents_row["hard_rules_parity"].get("error", "failed")))
    identifier_contract = agents_row.get("identifier_contract", {})
    if not identifier_contract.get("ok"):
        failures.append((
            "agents",
            "minifig identifier contract: %s"
            % identifier_contract.get("error", "failed"),
        ))

    # 6. Outreach channel -- WARNING tier: only the optional prospect half
    # needs Gmail, so a dead credential degrades rather than blocks.
    checks["outreach_channel"] = google_status
    if not google_status["authenticated"]:
        warnings.append("gmail outreach unavailable (%s) -- prospect email "
                        "drafts cannot be sent; deals half unaffected"
                        % (google_status.get("error") or "not authenticated"))

    # 7. Minifigure identification -- WARNING tier for provider/detector
    # outages, but a BLOCKER when the installed CLI lacks minifig leaves:
    # a run would die mid-batch on the missing subcommand, so it must not
    # start.
    checks["minifig_identification"] = {
        "brickognize": brickognize_row,
        "detector": detector_row,
        "installed_usage": usage_row,
    }
    if usage_row.get("error"):
        failures.append(("installed_cli", usage_row["error"]))
    elif usage_row["missing"]:
        failures.append((
            "installed_cli",
            "installed legoscout lacks minifig subcommands: %s -- reinstall "
            "the repo tool before running identifier batches"
            % ", ".join(usage_row["missing"])))
    if not brickognize_row["reachable"]:
        warnings.append(
            "brickognize unreachable (%s) -- every minifigure lot this run "
            "will be recorded as an identifier skip; bulk and set pricing "
            "unaffected" % (brickognize_row.get("error") or "unknown error"))
    if not detector_row["available"]:
        warnings.append(
            "minifig detector unavailable (%s) -- every minifigure lot this "
            "run will be recorded as an identifier skip; restore the declared "
            "local torch/transformers runtime and pinned model; bulk and set "
            "pricing unaffected" % (detector_row.get("error") or "unknown error"))

    ok = not failures
    print(json.dumps({"ok": ok, "checks": checks, "warnings": warnings},
                     indent=2))
    if not ok:
        print("FAIL: preflight found %d blocker(s):" % len(failures),
              file=sys.stderr)
        for label, detail in failures:
            print("FAIL: %s -- %s" % (label, detail), file=sys.stderr)
        print("Resolve every FAIL above before starting this run.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(None))
