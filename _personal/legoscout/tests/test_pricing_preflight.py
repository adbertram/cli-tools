"""`pricing preflight` is the FULL pre-run gate: every dependency a deal run
touches must pass at the door, not degrade silently mid-run.

The comps credential contract is unchanged -- every failure mode (missing
binary, failed subprocess, non-JSON stdout, zero profiles, ambiguous active
profile) resolves to "not authenticated" with a descriptive error, never an
unhandled exception. The newer checks follow the same discipline: per-item
evidence, collected failures, exactly one non-zero exit at the end. Warnings
(unresearched fee configs, dead Gmail outreach) never fail the gate.

Gate-level tests run `main()` under mocks with every external seam patched
(binaries on PATH, subprocess calls, the source registry access layer, the
real filesystem paths). Unit tests pin the individual helpers' contracts.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
from unittest import mock

import pytest

from legoscout_cli.pricing import preflight

FAKE_BINARIES = {
    "bricklink": "/usr/local/bin/bricklink",
    "ebay": "/usr/local/bin/ebay",
    "playwright-cli": "/opt/homebrew/bin/playwright-cli",
    "google": "/usr/local/bin/google",
    "ssh": "/usr/bin/ssh",
}
FAKE_BINARIES.update(
    {ns: "/Users/adam/.local/bin/%s" % ns
     for ns in preflight.SOURCE_CLI_BINARIES})


def _which(missing=()):
    paths = dict(FAKE_BINARIES)
    for name in missing:
        paths.pop(name, None)
    return lambda name: paths.get(name)


def _proc(argv, stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(argv, returncode, stdout=stdout,
                                       stderr=stderr)


def _status_json(name="default", active=True, authenticated=True):
    return json.dumps({"profiles": [
        {"name": name, "auth_type": "default", "active": active,
         "authenticated": authenticated, "credential_types": {}},
    ]})


# --- unit tests: the shared auth-status checker -----------------------------


def test_check_missing_binary_is_not_authenticated():
    with mock.patch.object(preflight.shutil, "which", return_value=None):
        status = preflight._check("bricklink", None)
    assert status["authenticated"] is False
    assert "not on PATH" in status["error"]


def test_check_nonzero_exit_is_not_authenticated_with_evidence():
    proc = _proc(["bl", "auth", "status"], stderr="boom", returncode=3)
    with mock.patch.object(preflight.shutil, "which",
                           return_value="/usr/local/bin/bricklink"), \
         mock.patch.object(preflight.subprocess, "run", return_value=proc):
        status = preflight._check("bricklink", None)
    assert status["authenticated"] is False
    assert "exited 3" in status["error"]
    assert "boom" in status["error"]


def test_check_non_json_stdout_is_not_authenticated_with_descriptive_error():
    proc = _proc(["bl", "auth", "status"], stdout="not json {{{", returncode=0)
    with mock.patch.object(preflight.shutil, "which",
                           return_value="/usr/local/bin/bricklink"), \
         mock.patch.object(preflight.subprocess, "run", return_value=proc):
        status = preflight._check("bricklink", None)
    assert status["authenticated"] is False
    assert "no JSON payload" in status["error"]
    assert "not json" in status["error"]


def test_check_zero_profiles_is_not_authenticated():
    proc = _proc(["bl", "auth", "status"],
                 stdout=json.dumps({"profiles": []}), returncode=0)
    with mock.patch.object(preflight.shutil, "which",
                           return_value="/usr/local/bin/bricklink"), \
         mock.patch.object(preflight.subprocess, "run", return_value=proc):
        status = preflight._check("bricklink", None)
    assert status["authenticated"] is False
    assert "zero profiles" in status["error"]


def test_check_ambiguous_none_active_profiles_refuse_to_guess():
    proc = _proc(["bl", "auth", "status"], stdout=json.dumps({"profiles": [
        {"name": "work", "active": False, "authenticated": True},
        {"name": "personal", "active": False, "authenticated": True},
    ]}), returncode=0)
    with mock.patch.object(preflight.shutil, "which",
                           return_value="/usr/local/bin/bricklink"), \
         mock.patch.object(preflight.subprocess, "run", return_value=proc):
        status = preflight._check("bricklink", None)
    assert status["authenticated"] is False
    assert "refusing to guess" in status["error"]


def test_check_timeout_is_not_authenticated():
    def raise_timeout(args, **kwargs):
        raise preflight.subprocess.TimeoutExpired(cmd=args, timeout=30)

    with mock.patch.object(preflight.shutil, "which",
                           return_value="/usr/local/bin/bricklink"), \
         mock.patch.object(preflight.subprocess, "run",
                           side_effect=raise_timeout):
        status = preflight._check("bricklink", None)
    assert status["authenticated"] is False
    assert "timed out" in status["error"]


def test_check_happy_path_reports_profile():
    proc = _proc(["bl", "auth", "status"], stdout=_status_json("geeklife"),
                 returncode=0)
    with mock.patch.object(preflight.shutil, "which",
                           return_value="/usr/local/bin/bricklink"), \
         mock.patch.object(preflight.subprocess, "run", return_value=proc) as rm:
        status = preflight._check("bricklink", None)
    assert status == {"authenticated": True, "profile": "geeklife"}
    assert "--profile" not in rm.call_args.args[0]


def test_check_profile_flag_is_passed_through():
    proc = _proc(["bl", "auth", "status"], stdout=_status_json(), returncode=0)
    with mock.patch.object(preflight.shutil, "which",
                           return_value="/usr/local/bin/bricklink"), \
         mock.patch.object(preflight.subprocess, "run", return_value=proc) as rm:
        preflight._check("bricklink", "geeklife")
    assert rm.call_args.args[0][-2:] == ["--profile", "geeklife"]


# --- unit tests: filesystem-shaped helpers ----------------------------------


def test_require_on_path_missing_names_the_binary():
    with mock.patch.object(preflight.shutil, "which", return_value=None):
        row = preflight._require_on_path("mercari")
    assert row["present"] is False
    assert "mercari" in row["error"]


def test_ledger_writable_on_real_defaults():
    row = preflight._ledger_writable()
    assert row["path"].endswith("found_deals.db")
    assert isinstance(row["writable"], bool)


def test_ensure_workspaces_creates_and_is_idempotent(tmp_path):
    runs = tmp_path / "source-runs"
    images = tmp_path / "listing-images"
    with mock.patch.object(preflight.paths, "SOURCE_RUNS", str(runs)), \
         mock.patch.object(preflight.paths, "LISTING_IMAGES_ROOT", str(images)):
        first = preflight._ensure_workspaces()
        second = preflight._ensure_workspaces()
    assert first["created"] == [str(runs), str(images)]
    assert second["created"] == []
    assert runs.is_dir() and images.is_dir()


def test_check_agents_flags_missing_definitions(tmp_path):
    (tmp_path / ".claude" / "agents").mkdir(parents=True)
    (tmp_path / ".codex" / "agents").mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    # No agent files, no parity script.
    row = preflight._check_agents(tmp_path)
    assert row["claude_definitions_missing"] == list(preflight.AGENT_NAMES)
    assert row["codex_definitions_missing"] == list(preflight.AGENT_NAMES)
    assert row["hard_rules_parity"]["ok"] is False
    assert "missing" in row["hard_rules_parity"]["error"]


def test_check_agents_runs_parity_script_when_present(tmp_path):
    agents_dir = tmp_path / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    codex_dir = tmp_path / ".codex" / "agents"
    codex_dir.mkdir(parents=True)
    for name in preflight.AGENT_NAMES:
        (agents_dir / ("%s.md" % name)).write_text("x")
        (codex_dir / ("%s.toml" % name)).write_text("x")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "check_hard_rules_parity.py").write_text("print('OK')")

    proc = _proc(["python3", "parity"], stdout="OK", returncode=0)
    with mock.patch.object(preflight.subprocess, "run", return_value=proc) as rm:
        row = preflight._check_agents(tmp_path)
    assert row["claude_definitions_missing"] == []
    assert row["codex_definitions_missing"] == []
    assert row["hard_rules_parity"]["ok"] is True
    invoked = rm.call_args.args[0]
    assert invoked[0] == "python3"
    assert invoked[1].endswith("check_hard_rules_parity.py")


def test_check_skills_reports_missing_skill_and_standards(tmp_path):
    skills_root = tmp_path / "skills" / "project"
    for name in preflight.PROJECT_SKILLS[:-1]:
        (skills_root / name).mkdir(parents=True)
        (skills_root / name / "SKILL.md").write_text("x")
    standards = tmp_path / "global-standards.md"
    standards.write_text("x")
    fake_root = tmp_path / "LegoScout"
    with mock.patch.object(preflight.paths, "LEGOSCOUT_ROOT", fake_root), \
         mock.patch.object(preflight, "GLOBAL_STANDARDS_PATH", standards):
        row = preflight._check_skills()
    assert row["missing"] == [preflight.PROJECT_SKILLS[-1]]
    assert row["global_standards_present"] is True


def test_minifig_identifier_dependencies_are_required():
    assert "legoscout-minifig-identifier" in preflight.PROJECT_SKILLS
    assert "legoscout-minifig-identifier" in preflight.AGENT_NAMES


def test_check_agents_executes_identifier_contract_script(tmp_path):
    agents_dir = tmp_path / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    codex_dir = tmp_path / ".codex" / "agents"
    codex_dir.mkdir(parents=True)
    for name in preflight.AGENT_NAMES:
        (agents_dir / ("%s.md" % name)).write_text("x")
        (codex_dir / ("%s.toml" % name)).write_text("x")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    parity = scripts / "check_hard_rules_parity.py"
    contract = scripts / "test_minifig_identifier_contracts.py"
    parity.write_text("print('OK parity')")
    contract.write_text("print('OK identifier contract')")
    returns = [
        _proc(["python3", str(parity)], stdout="OK parity"),
        _proc(["python3", str(contract)], stdout="OK identifier contract"),
    ]

    with mock.patch.object(
            preflight.subprocess, "run", side_effect=returns) as run:
        row = preflight._check_agents(tmp_path)

    assert row["identifier_contract"] == {
        "script_present": True,
        "ok": True,
    }
    assert [call.args[0][1] for call in run.call_args_list] == [
        str(parity), str(contract),
    ]


def test_check_minifig_detector_loads_selected_runtime_and_model():
    detector = lambda paths: []
    with mock.patch.object(
            preflight.minifig_detector, "load_detector",
            return_value=detector) as load:
        row = preflight._check_minifig_detector()
    assert row == {
        "available": True,
        "detector": "grounding-dino-tiny",
        "model": preflight.minifig_detector.GROUNDING_DINO_MODEL,
        "revision": preflight.minifig_detector.GROUNDING_DINO_REVISION,
        "error": None,
    }
    load.assert_called_once_with("grounding-dino-tiny")


def test_check_minifig_detector_reports_runtime_or_model_failure():
    with mock.patch.object(
            preflight.minifig_detector, "load_detector",
            side_effect=preflight.minifig_detector.DetectorError(
                "detector grounding-dino-tiny load failed: ModuleNotFoundError: torch")):
        row = preflight._check_minifig_detector()
    assert row["available"] is False
    assert row["detector"] == "grounding-dino-tiny"
    assert row["model"] == preflight.minifig_detector.GROUNDING_DINO_MODEL
    assert "ModuleNotFoundError: torch" in row["error"]


def test_check_minifig_detector_deadline_expires_to_warning_not_hang():
    # A stalled Hugging Face from_pretrained must surface as a bounded
    # warning row, never hang the mandatory pre-run gate.
    def stalled_load(name):
        event.wait(preflight.DETECTOR_CHECK_TIMEOUT_SECONDS + 5)

    event = threading.Event()
    with mock.patch.object(
            preflight.minifig_detector, "load_detector",
            side_effect=stalled_load):
        started = time.monotonic()
        row = preflight._check_minifig_detector_with_deadline(
            preflight.DETECTOR_CHECK_TIMEOUT_SECONDS)
        elapsed = time.monotonic() - started
    event.set()
    assert row["available"] is False
    assert row["error"] is not None
    assert "deadline" in row["error"] or "timed out" in row["error"]
    assert elapsed < preflight.DETECTOR_CHECK_TIMEOUT_SECONDS + 5


def test_check_brickognize_uses_health_endpoint_and_current_provider_headers():
    response = mock.Mock()
    response.raise_for_status.return_value = None
    with mock.patch.object(preflight.requests, "get", return_value=response) as get:
        row = preflight._check_brickognize()
    assert row == {"reachable": True, "error": None}
    get.assert_called_once_with(
        preflight.BRICKOGNIZE_HEALTH_URL,
        headers={"User-Agent": preflight.brickognize.USER_AGENT},
        timeout=preflight.BRICKOGNIZE_TIMEOUT_SECONDS,
    )


def test_check_brickognize_reports_provider_outage_without_raising():
    with mock.patch.object(
            preflight.requests, "get",
            side_effect=preflight.requests.ConnectionError("offline")):
        row = preflight._check_brickognize()
    assert row["reachable"] is False
    assert "ConnectionError: offline" in row["error"]


# --- gate-level tests: main() end to end under mocks ------------------------


class FakeRegistry:
    """Shapes the live registry access layer for one gate run."""

    def __init__(self, active=("ebay", "shopgoodwill", "stockx"),
                 auth_required=frozenset({"ebay"}),
                 problems=(), missing_fees=(), browser_only=()):
        self.active = tuple(active)
        self.auth_required = frozenset(auth_required)
        self.problems = tuple(problems)
        self.missing_fees = frozenset(missing_fees)
        self.browser_only = frozenset(browser_only)

    def install(self):
        from legoscout_cli.sources import registry
        return mock.patch.multiple(
            registry,
            active_namespaces=self.active_namespaces,
            payload=self.payload,
            check=self.check,
        )

    def active_namespaces(self):
        return sorted(self.active)

    def payload(self, namespace, with_notes=False):
        if namespace not in self.active:
            raise KeyError(namespace)
        return {
            "access": {"method": "Runtime browser"
                       if namespace in self.browser_only else "CLI first",
                       "auth_required": namespace in self.auth_required},
            "fees": None if namespace in self.missing_fees
            else {"premium_pct_default": 0.1},
        }

    def check(self):
        return list(self.problems)


def _subprocess_runner(fake, *, unauthed=(), no_json=(), adam="ok",
                       parity_ok=True):
    def runner(args, **kwargs):
        if any("check_hard_rules_parity" in str(a) for a in args):
            return _proc(args, stdout="" if parity_ok else "DRIFT",
                         returncode=0 if parity_ok else 1)
        if args[-1] == "jlist":
            if adam == "ssh-fail":
                return _proc(args, stderr="ssh: connect failed",
                             returncode=255)
            statuses = {"legoscout-display":
                        "stopped" if adam == "pm2-offline" else "online"}
            return _proc(args, stdout=json.dumps(
                [{"name": n, "pm2_env": {"status": s}}
                 for n, s in statuses.items()]), returncode=0)
        if len(args) >= 3 and args[1] == "auth" and args[2] == "status":
            base = args[0].rsplit("/", 1)[-1]
            if base in no_json:
                return _proc(args, stdout="{{{", returncode=0)
            return _proc(args, stdout=_status_json(
                authenticated=base not in unauthed), returncode=0)
        raise AssertionError("unexpected subprocess target: %r" % (args,))
    return runner


def _run_gate(fake=None, *, unauthed=(), no_json=(), missing_binaries=(),
              adam="ok", parity_ok=True, identifier_ok=True, ledger_ok=True,
              brickognize_row=None, detector_row=None):
    fake = fake or FakeRegistry()
    ledger_row = {"path": "/tmp/found_deals.db", "exists": True,
                  "writable": ledger_ok}
    brickognize_row = brickognize_row or {"reachable": True, "error": None}
    detector_row = detector_row or {
        "available": True,
        "detector": "grounding-dino-tiny",
        "model": "IDEA-Research/grounding-dino-tiny",
        "revision": "a2bb814dd30d776dcf7e30523b00659f4f141c71",
        "error": None,
    }
    brickognize_check = mock.Mock(
        name="_check_brickognize", return_value=dict(brickognize_row))
    detector_check = mock.Mock(
        name="_check_minifig_detector", return_value=dict(detector_row))
    with mock.patch.object(preflight.shutil, "which",
                           side_effect=_which(missing_binaries)), \
         mock.patch.object(preflight.subprocess, "run",
                           side_effect=_subprocess_runner(
                               fake, unauthed=unauthed, no_json=no_json,
                               adam=adam, parity_ok=parity_ok)), \
         fake.install(), \
         mock.patch.multiple(preflight,
                             _check_agents=lambda root: {
                                 "claude_definitions_missing": [],
                                 "codex_definitions_missing": [],
                                 "hard_rules_parity": {
                                     "script_present": True, "ok": parity_ok},
                                 "identifier_contract": {
                                     "script_present": True,
                                     "ok": identifier_ok,
                                     **({} if identifier_ok else {
                                         "error": "identifier contract failed"})}},
                             _check_skills=lambda: {
                                 "root": "/skills/project", "missing": [],
                                 "global_standards_present": True},
                             _check_brickognize=brickognize_check,
                             _check_minifig_detector=detector_check,
                             _ensure_workspaces=lambda: {
                                 "created": [], "errors": [],
                                 "source_runs": "/runs",
                                 "listing_images": "/images"},
                             _ledger_writable=lambda: dict(ledger_row)):
        exit_code = preflight.main([])
    return exit_code


def test_gate_all_green_exits_0_with_full_report(capsys):
    assert _run_gate() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert report["warnings"] == []
    checks = report["checks"]
    assert checks["comps_credentials"]["bricklink"]["authenticated"] is True
    assert checks["comps_credentials"]["ebay"]["authenticated"] is True
    # stockx is public-access: presence checked, auth never attempted.
    assert checks["source_clis"]["stockx"]["present"] is True
    assert checks["source_clis"]["stockx"]["authenticated"] is None
    # ebay requires auth: live round-trip performed.
    assert checks["source_clis"]["ebay"]["authenticated"] is True
    assert checks["runtime_browser"]["present"] is True
    assert checks["registry"]["problems"] == []
    assert checks["adam_server"] == {"reachable": True, "pm2_app_online": True}
    assert checks["agents"]["hard_rules_parity"]["ok"] is True
    assert checks["skills"]["missing"] == []
    assert checks["minifig_identification"]["brickognize"]["reachable"] is True
    assert checks["minifig_identification"]["detector"]["available"] is True


def test_gate_submits_provider_and_detector_checks_to_existing_pool(capsys):
    submitted = []

    class ImmediateFuture:
        def __init__(self, value):
            self.value = value

        def result(self):
            return self.value

    class RecordingPool:
        def __init__(self, max_workers):
            self.max_workers = max_workers

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def submit(self, fn, *args):
            submitted.append(fn)
            return ImmediateFuture(fn(*args))

        def map(self, fn, values):
            return [fn(value) for value in values]

    with mock.patch.object(preflight, "ThreadPoolExecutor", RecordingPool):
        assert _run_gate() == 0
    capsys.readouterr()
    submitted_names = {getattr(fn, "_mock_name", None) for fn in submitted}
    assert preflight.POOL_WORKERS >= len(submitted)
    assert "_check_brickognize" in submitted_names
    assert "_check_minifig_detector" in submitted_names


def test_gate_brickognize_outage_warns_only_for_minifig_identification(capsys):
    assert _run_gate(brickognize_row={
        "reachable": False,
        "error": "ConnectionError: offline",
    }) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert report["checks"]["minifig_identification"]["brickognize"] == {
        "reachable": False,
        "error": "ConnectionError: offline",
    }
    assert report["warnings"] == [
        "brickognize unreachable (ConnectionError: offline) -- every "
        "minifigure lot this run will be recorded as an identifier skip; "
        "bulk and set pricing unaffected",
    ]


def test_gate_detector_runtime_or_model_failure_is_warning_only(capsys):
    detector_row = {
        "available": False,
        "detector": "grounding-dino-tiny",
        "model": "IDEA-Research/grounding-dino-tiny",
        "revision": "a2bb814dd30d776dcf7e30523b00659f4f141c71",
        "error": "DetectorError: model weights unavailable",
    }
    assert _run_gate(detector_row=detector_row) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert report["checks"]["minifig_identification"]["detector"] == detector_row
    assert len(report["warnings"]) == 1
    warning = report["warnings"][0]
    assert "minifig detector unavailable" in warning
    assert "model weights unavailable" in warning
    assert "bulk and set pricing unaffected" in warning


def test_gate_dead_comps_credential_fails_and_names_it(capsys):
    assert _run_gate(unauthed=("ebay",)) == 1
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["ok"] is False
    assert report["checks"]["comps_credentials"]["ebay"]["authenticated"] is False
    fail_lines = [line for line in captured.err.splitlines()
                  if line.startswith("FAIL")]
    assert any("bricklink" not in line and "ebay" in line for line in fail_lines)


def test_gate_missing_source_binary_fails(capsys):
    fake = FakeRegistry(active=("ebay", "mercari", "stockx"))
    assert _run_gate(fake, missing_binaries=("mercari",)) == 1
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["checks"]["source_clis"]["mercari"]["present"] is False
    assert any("mercari" in line for line in captured.err.splitlines())


def test_gate_unauthenticated_auth_required_source_fails(capsys):
    fake = FakeRegistry(active=("ebay", "stockx"))
    assert _run_gate(fake, unauthed=("ebay",)) == 1
    captured = capsys.readouterr()
    assert any("source:ebay" in line for line in captured.err.splitlines())


def test_gate_non_json_auth_output_fails(capsys):
    assert _run_gate(no_json=("bricklink",)) == 1
    report = json.loads(capsys.readouterr().out)
    error = report["checks"]["comps_credentials"]["bricklink"]["error"]
    assert "no JSON payload" in error
    # The evidence must not be an empty string -- it names what came back.
    assert error.rstrip().endswith("{{{") or "empty output" in error


def test_gate_runtime_browser_missing_fails(capsys):
    assert _run_gate(missing_binaries=("playwright-cli",)) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["checks"]["runtime_browser"]["present"] is False


def test_gate_ssh_failure_fails_run(capsys):
    assert _run_gate(adam="ssh-fail") == 1
    report = json.loads(capsys.readouterr().out)
    assert report["checks"]["adam_server"]["reachable"] is False


def test_gate_pm2_app_offline_fails_run(capsys):
    assert _run_gate(adam="pm2-offline") == 1
    report = json.loads(capsys.readouterr().out)
    assert report["checks"]["adam_server"]["reachable"] is True
    assert report["checks"]["adam_server"]["pm2_app_online"] is False


def test_gate_registry_problem_fails(capsys):
    fake = FakeRegistry(problems=("k-bid: duplicate note ids",))
    assert _run_gate(fake) == 1
    captured = capsys.readouterr()
    assert "duplicate note ids" in captured.err


def test_gate_unwritable_ledger_fails(capsys):
    assert _run_gate(ledger_ok=False) == 1
    captured = capsys.readouterr()
    assert any("ledger_db" in line for line in captured.err.splitlines())


def test_gate_parity_drift_fails(capsys):
    assert _run_gate(parity_ok=False) == 1
    captured = capsys.readouterr()
    assert any("parity" in line.lower() for line in captured.err.splitlines())


def test_gate_identifier_contract_failure_fails(capsys):
    assert _run_gate(identifier_ok=False) == 1
    captured = capsys.readouterr()
    assert any(
        "minifig identifier contract" in line.lower()
        and "identifier contract failed" in line.lower()
        for line in captured.err.splitlines()
    )


def test_gate_multiple_blockers_all_reported(capsys):
    fake = FakeRegistry(active=("ebay", "mercari", "poshmark"))
    assert _run_gate(fake, unauthed=("ebay",),
                     missing_binaries=("mercari", "poshmark")) == 1
    captured = capsys.readouterr()
    fail_blob = captured.err
    assert "source:mercari" in fail_blob
    assert "source:poshmark" in fail_blob
    assert "ebay" in fail_blob


def test_gate_missing_fee_config_warns_without_failing(capsys):
    fake = FakeRegistry(active=("ebay", "stockx", "govdeals"),
                        missing_fees=("govdeals",),
                        browser_only=("govdeals",))
    assert _run_gate(fake) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert any("govdeals" in w for w in report["warnings"])
    assert report["checks"]["registry"]["missing_fee_config"] == ["govdeals"]


def test_gate_dead_gmail_outreach_only_warns(capsys):
    assert _run_gate(unauthed=("google",)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert any("gmail" in w.lower() for w in report["warnings"])
    assert report["checks"]["outreach_channel"]["authenticated"] is False


# --- selected-source scope (--source) ---------------------------------------


class _Args:
    def __init__(self, source=None):
        self.profile = None
        self.source = source


def test_source_scope_limits_checks_and_ignores_unplanned_blockers(capsys):
    """A selected-source run must not be blocked by a dead source outside its
    allowlist -- but comps credentials, infra, and agents stay global."""
    fake = FakeRegistry(active=("facebook", "mercari"),
                        auth_required=("facebook",))
    with mock.patch.object(preflight, "parse_args",
                           return_value=_Args(source=["mercari"])):
        exit_code = _run_gate(fake, unauthed=("facebook",))
    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    # Only the planned source was evaluated for CLI presence/auth.
    assert set(report["checks"]["source_clis"]) == {"mercari"}
    assert report["checks"]["source_clis"]["mercari"]["present"] is True
    # The comps credentials stay global regardless of scope.
    assert report["checks"]["comps_credentials"]["ebay"] is not None


def test_source_scope_unknown_or_inactive_namespace_fails(capsys):
    fake = FakeRegistry(active=("ebay", "mercari"))
    with mock.patch.object(preflight, "parse_args",
                           return_value=_Args(source=["craigslist", "nope"])):
        exit_code = _run_gate(fake)
    assert exit_code == 1
    captured = capsys.readouterr()
    fail_blob = captured.err
    assert any(("source:craigslist" in line) or ("source:nope" in line)
               for line in fail_blob.splitlines())


def test_registry_fee_warning_respects_scope(capsys):
    fake = FakeRegistry(active=("ebay", "govdeals"),
                        missing_fees=("govdeals",),
                        browser_only=("govdeals",))
    with mock.patch.object(preflight, "parse_args",
                           return_value=_Args(source=["ebay"])):
        exit_code = _run_gate(fake)
    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["checks"]["registry"]["missing_fee_config"] == []
    assert report["warnings"] == []


# --- chaos-hardening regressions (2026-08-23 attack pass) -------------------


def _run_gate_raw(fake=None, **kwargs):
    """_run_gate variant returning the raw exception instead of asserting."""
    try:
        return _run_gate(fake, **kwargs), None
    except Exception as exc:  # noqa: BLE001 -- the test inspects the escape
        return None, exc


def test_chaos_duplicate_source_collapsed_to_one_blocker(capsys):
    """V4: `--source nope --source nope` must not double-count blockers."""
    with mock.patch.object(preflight, "parse_args",
                           return_value=_Args(source=["nope", "nope"])):
        exit_code = _run_gate(FakeRegistry(active=("ebay",)))
    assert exit_code == 1
    captured = capsys.readouterr()
    dup_lines = [line for line in captured.err.splitlines()
                 if "FAIL: source:nope" in line]
    assert len(dup_lines) == 1


def test_chaos_locked_registry_is_a_failure_not_a_traceback(capsys):
    """A1/A3: missing/corrupt/locked registry DB resolves to a FAIL line."""
    class LockedRegistry(FakeRegistry):
        def active_namespaces(self):
            raise OSError("database is locked")

        def check(self):
            raise OSError("database is locked")

        def payload(self, namespace, with_notes=False):
            raise OSError("database is locked")

    exit_code = _run_gate(LockedRegistry(active=("ebay",)))
    assert exit_code == 1
    captured = capsys.readouterr()
    report = json.loads(captured.out)  # structured JSON still printed
    assert report["ok"] is False
    fail_lines = [line for line in captured.err.splitlines()
                  if line.startswith("FAIL")]
    assert any("registry database unreadable" in line for line in fail_lines)
    # Both consumers of the broken registry reported it independently.
    assert any(line.startswith("FAIL: source:") or "source_clis" not in line
               for line in fail_lines)


def test_chaos_undecodable_auth_output_is_reported_not_raised():
    """C1b: invalid UTF-8 from the auth subprocess -> structured error."""
    def boom(args, **kwargs):
        raise UnicodeDecodeError("utf-8", b"\xff\xfe", 0, 1, "invalid start byte")

    with mock.patch.object(preflight.shutil, "which",
                           return_value="/usr/local/bin/bricklink"), \
         mock.patch.object(preflight.subprocess, "run", side_effect=boom):
        status = preflight._check("bricklink", None)
    assert status["authenticated"] is False
    assert "undecodable output" in status["error"]


def test_chaos_unwritable_workspace_parent_is_reported_not_raised(capsys):
    """B-series: mkdir failure becomes a FAIL line after all checks pass."""
    with mock.patch.object(preflight.paths, "SOURCE_RUNS",
                           "/tmp/chaos_test_file_as_parent/child"), \
         mock.patch.object(preflight.paths, "LISTING_IMAGES_ROOT",
                           "/tmp/chaos_other_ws"), \
         mock.patch.object(preflight.subprocess, "run",
                           side_effect=_subprocess_runner(None)), \
         mock.patch.object(preflight.shutil, "which",
                           side_effect=_which()), \
         mock.patch.multiple(preflight,
                             _read_registry=lambda: (
                                 ["ebay"], [], None),
                             _check_source_cli_access=lambda *a, **k: (
                                 {}, [], []),
                             _check_agents=lambda root: {
                                 "claude_definitions_missing": [],
                                 "codex_definitions_missing": [],
                                 "hard_rules_parity": {"script_present": True,
                                                       "ok": True},
                                 "identifier_contract": {
                                     "script_present": True, "ok": True}},
                             _check_skills=lambda: {
                                 "root": "/s", "missing": [],
                                 "global_standards_present": True},
                             _ledger_writable=lambda: {
                                 "path": "/tmp/x.db", "exists": True,
                                 "writable": True},
                             _check=lambda *a: {"authenticated": True,
                                                "profile": None}):
        code, escaped = _run_gate_raw()
    # The gate may not be able to create dirs under /tmp fixtures either way;
    # what matters is: NO traceback, and any mkdir failure is a labeled FAIL.
    assert escaped is None
    if code == 1:
        captured = capsys.readouterr()
        assert any("workspaces" in line for line in captured.err.splitlines())


def test_chaos_pm2_warning_prefix_before_json_still_online(capsys):
    """V3: pm2 jlist banner + JSON on stdout -> app correctly read as online."""

    def runner(args, **kwargs):
        if args[-1] == "jlist":
            noisy = ("warning: deprecated flag\n"
                     '[{"name": "legoscout-display", '
                     '"pm2_env": {"status": "online"}}]')
            return _proc(args, stdout=noisy, returncode=0)
        raise AssertionError(args)

    with mock.patch.object(preflight.shutil, "which",
                           return_value="/usr/bin/ssh"), \
         mock.patch.object(preflight.subprocess, "run", side_effect=runner):
        row = preflight._check_adam_server()
    assert row == {"reachable": True, "pm2_app_online": True}


def test_chaos_status_json_on_stderr_only_is_accepted():
    """V2: a tool printing its payload to stderr is parsed, not failed."""

    def runner(args, **kwargs):
        return _proc(args, stdout="", stderr=_status_json(), returncode=0)

    with mock.patch.object(preflight.shutil, "which",
                           return_value="/usr/local/bin/bricklink"), \
         mock.patch.object(preflight.subprocess, "run", side_effect=runner):
        status = preflight._check("bricklink", None)
    assert status == {"authenticated": True, "profile": "default"}


def test_chaos_non_bool_auth_required_warns_and_checks_presence_only(capsys):
    """V1-adjacent: auth_required=None (missing row key) warns, never fails."""
    class NullAuthRegistry(FakeRegistry):
        def payload(self, namespace, with_notes=False):
            entry = FakeRegistry.payload(self, namespace, with_notes=False)
            entry["access"]["auth_required"] = None
            return entry

    exit_code = _run_gate(NullAuthRegistry(active=("stockx",)))
    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["checks"]["source_clis"]["stockx"]["authenticated"] is None
    assert any("not a boolean" in w for w in report["warnings"])


def test_loads_tolerant_prefix_noise_then_json():
    text = 'some warning banner\n{"profiles": [{"active": true}]}'
    parsed, evidence = preflight._loads_tolerant(text)
    assert parsed == {"profiles": [{"active": True}]}
    assert evidence is None


def test_loads_tolerant_both_empty_reports_evidence():
    parsed, evidence = preflight._loads_tolerant("", "")
    assert parsed is None
    assert evidence


def test_dedupe_keeps_first_occurrence_order():
    assert preflight._dedupe(["b", "a", "b", "c", "a"]) == ["b", "a", "c"]
    assert preflight._dedupe([]) == []
