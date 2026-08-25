"""Every leaf subcommand runs once, against a disposable ledger.

Two of the worst defects this tool has shipped were commands that had never
been executed. `legoscout deals build` omitted both of `build_deal_record`'s
keyword-only arguments and failed on 100% of invocations from the day of the
CLI cutover. Four `legoscout prospects` subcommands queried a column that does
not exist. Neither was subtle, neither had a test, and both would have been
caught the same day by a suite that simply RAN each command once.

So that is what this is. The command list is discovered from the Typer app --
never hand-written -- because a hand-written list drifts in exactly the way the
column lists did. `test_every_leaf_is_accounted_for` fails the moment a new
leaf subcommand appears without either a smoke case or an explicit, reasoned
skip, so nothing can slip into the CLI uncovered.

`SKIPPED` is the whole escape hatch, and it is deliberately loud: a command
lands there only when running it would make a live network call or a real-world
side effect, and each entry states which. Read it as the list of commands no
test protects.

Nothing here touches the real ledger. A session fixture takes a consistent
sqlite snapshot of it through a read-only connection, then repoints every
ledger path in the package at that copy, so a write command writes to the copy.
"""
from __future__ import annotations

import json
import os
import pkgutil
import sqlite3
import sys
import types

import pytest
from typer.testing import CliRunner

import legoscout_cli
from legoscout_cli import paths
from legoscout_cli.ledger import db as ledger_db
from legoscout_cli.main import app
from legoscout_cli.orchestrator import replay_fixtures
from legoscout_cli.prospector import hypothesis_types
from legoscout_cli.sources import registry


# --------------------------------------------------------------------------
# Discovery. The app is the source of truth for what commands exist.
# --------------------------------------------------------------------------

def _walk(typer_app, prefix=()):
    """Every leaf `(group, ..., command)` path registered on a Typer app."""
    for info in typer_app.registered_commands:
        name = info.name if info.name else info.callback.__name__.replace("_", "-")
        yield prefix + (name,)
    for group in typer_app.registered_groups:
        yield from _walk(group.typer_instance, prefix + (group.name,))


LEAVES = tuple(sorted(_walk(app)))


# --------------------------------------------------------------------------
# The disposable ledger.
# --------------------------------------------------------------------------

def _snapshot(real: str, dest: str) -> None:
    """A consistent copy of the ledger, taken without writing to the original.

    `sqlite3.Connection.backup` rather than a file copy: the live ledger runs in
    WAL mode, so copying the `.db` file alone can miss committed transactions
    still sitting in the write-ahead log. The source is opened `mode=ro` so this
    cannot touch Adam's ledger even by accident.
    """
    source = sqlite3.connect("file:%s?mode=ro" % real, uri=True)
    target = sqlite3.connect(dest)
    try:
        with target:
            source.backup(target)
    finally:
        source.close()
        target.close()


def _import_every_module() -> None:
    """Import the whole package, so the redirect below can see every module.

    A module imported lazily inside a function body is absent from `sys.modules`
    when the redirect runs, and would keep pointing at the real ledger.
    """
    for info in pkgutil.walk_packages(legoscout_cli.__path__,
                                      legoscout_cli.__name__ + "."):
        __import__(info.name)


def _rebind_defaults(monkeypatch, fn, real: str, replacement: str) -> None:
    if fn.__defaults__ and real in fn.__defaults__:
        monkeypatch.setattr(fn, "__defaults__", tuple(
            replacement if d == real else d for d in fn.__defaults__))
    if fn.__kwdefaults__ and real in fn.__kwdefaults__.values():
        monkeypatch.setattr(fn, "__kwdefaults__", {
            k: (replacement if v == real else v)
            for k, v in fn.__kwdefaults__.items()})


def _redirect_ledger(monkeypatch, real: str, replacement: str) -> None:
    """Point every ledger path in the package at the disposable copy.

    The ledger path reaches call sites three ways -- a module constant
    (`sweep.LEDGER`), a default argument (`db.get_deal(..., path=DB_PATH)`) and
    an instance attribute (`registry.sources.path`) -- so all three are rewritten
    here rather than a list of known names being maintained by hand.
    """
    modules = [m for m in list(sys.modules.values())
               if getattr(m, "__name__", "").startswith("legoscout_cli")]
    for module in modules:
        for name, value in list(vars(module).items()):
            if isinstance(value, str):
                if value == real:
                    monkeypatch.setattr(module, name, replacement)
            elif isinstance(value, types.FunctionType):
                _rebind_defaults(monkeypatch, value, real, replacement)
            elif isinstance(value, type):
                for attribute in list(vars(value).values()):
                    if isinstance(attribute, types.FunctionType):
                        _rebind_defaults(monkeypatch, attribute, real, replacement)
            elif getattr(value, "path", None) == real:
                monkeypatch.setattr(value, "path", replacement)


@pytest.fixture(scope="session")
def ledger(tmp_path_factory):
    real = paths.DB_PATH
    if not os.path.isfile(real):
        raise FileNotFoundError(
            "the ledger is missing at %s, so no command can be smoke-tested "
            "against it. It is the single source of truth; restore it from "
            "Dropbox rather than letting this suite skip." % real)
    copy = str(tmp_path_factory.mktemp("ledger") / "found_deals.db")
    _snapshot(real, copy)
    _import_every_module()
    with pytest.MonkeyPatch.context() as monkeypatch:
        _redirect_ledger(monkeypatch, real, copy)
        yield copy


@pytest.fixture(scope="session")
def ids(ledger):
    """Real identifiers, read out of the copy rather than hardcoded."""
    deal = ledger_db.query(
        "SELECT listing_key, source, seller_id FROM deals "
        "WHERE seller_id IS NOT NULL ORDER BY listing_key LIMIT 1")[0]
    namespace = sorted(registry.sources.table())[0]
    conn = registry._connect(ledger)
    try:
        note = conn.execute(
            "SELECT id, namespace FROM source_notes "
            "WHERE id IS NOT NULL ORDER BY id LIMIT 1").fetchone()
        if note is None:
            raise RuntimeError(
                "source_notes has no row with a non-null id -- the leaf-command "
                "smoke test needs one real note id to invoke `sources notes get`")
        prospect = conn.execute(
            "SELECT prospect_id FROM prospects ORDER BY prospect_id LIMIT 1").fetchone()
        contact = conn.execute(
            "SELECT contact_id FROM contacts ORDER BY contact_id LIMIT 1").fetchone()
        run = conn.execute(
            "SELECT run_id FROM prospect_runs ORDER BY run_id LIMIT 1").fetchone()
    finally:
        conn.close()
    return {
        "listing_key": deal["listing_key"],
        "source": deal["source"],
        "seller_id": deal["seller_id"],
        "namespace": namespace,
        "note_id": note[0],
        "note_source": note[1],
        "prospect_id": str(prospect[0]),
        "contact_id": str(contact[0]),
        "run_id": str(run[0]),
        "hypothesis_type": sorted(hypothesis_types.table())[0],
    }


@pytest.fixture(scope="session")
def files(tmp_path_factory, ledger):
    """The JSON operands the file-taking commands need, written once."""
    root = tmp_path_factory.mktemp("operands")
    candidate = {
        "listing_key": "shopgoodwill|999999999",
        "source": "shopgoodwill",
        "title": "LEGO bulk lot 12 lbs",
        "url": "https://shopgoodwill.com/item/999999999",
        "direct_url": "https://shopgoodwill.com/item/999999999",
        "id": "999999999",
        "posted_date": "2026-08-01T00:00:00Z",
        "listing_type": "auction",
        "auction_end_date": "2026-08-20T00:00:00Z",
        "current_price": 40.0,
        "price_basis": "current_price",
        "weight_lbs": 12.0,
        "item_location": "Evansville, IN 47725",
        "available_fulfillment": ["shipping"],
        "shipping_estimate": {"shipping_price": 18.0, "handling_price": 0.0,
                              "service": "smoke-test operand"},
        "image_urls": [],
        "seller_id": "smoke", "seller_name": "smoke",
    }
    appraisal = {
        "listing_category": "bulk",
        "estimated_total": 58.0,
        "handling_fee": 0.0,
        "per_lb_price": 4.83,
        "per_lb_price_basis": "landed",
        "confidence": "medium",
        "shipping_estimated": False,
        "pickup_miles": 0.0,
        "fee_breakdown": {
            "hammer": 40.0, "premium_pct": 0.0, "premium_amount": 0.0,
            "sales_tax_pct": 0.0, "sales_tax_amount": 0.0,
            "shipping_handling": 18.0, "shipping_estimated": False,
            "shipping_unknown": False, "landed_is_floor": False,
            "landed_total": 58.0,
        },
        "observations": {
            "description": "",
            "vision": {"status": "no_images", "image_count": None,
                       "target_colors": "unknown", "color_families": [],
                       "themes": [], "minifigs": "not_visible",
                       "contamination": [], "retired_sets_visible": None,
                       "weight_estimate_lbs": None, "weight_confidence": None,
                       "notes": "smoke-test operand carries no images"},
            "model_score": 50,
            "model_rationale": "The smoke fixture has neutral deal evidence.",
        },
    }
    prospect = {
        "name": "LegoScout Smoke Test Thrift",
        "hypothesis_type": sorted(hypothesis_types.table())[0],
        "location": "Evansville, IN",
        "evidence_url": "https://example.invalid/legoscout-smoke-test",
        "contacts": [{"channel": "email", "value": "smoke@example.invalid"}],
    }
    contact = {"prospect_id": 1, "channel": "email",
               "value": "smoke-contact@example.invalid"}
    run = {"run_key": "legoscout-smoke-test-run",
           "hypothesis_type": sorted(hypothesis_types.table())[0],
           "searches": ["smoke test"], "result_count": 0,
           "notes": "written by the leaf-subcommand smoke test"}
    written = {}
    for name, payload in (("candidate", candidate), ("appraisal", appraisal),
                          ("triage", []), ("prospect", prospect),
                          ("contact", contact), ("run", run),
                          ("entry", {ADDED_SOURCE: _source_entry(ADDED_SOURCE)})):
        path = root / ("%s.json" % name)
        path.write_text(json.dumps(payload), encoding="utf-8")
        written[name] = str(path)
    manifest_dir = root / "run-manifest"
    manifest_dir.mkdir()
    for namespace in registry.active_namespaces():
        payload = {
            "source": namespace,
            "checked": False,
            "blocked": True,
            "blocker": "offline smoke fixture",
            "candidate_records": [],
            "unavailable_updates": [],
            "unchanged_duplicate_keys": [],
            "learning_notes": [],
            "actions_requiring_approval": [],
            "evidence_summary": "The offline smoke fixture blocks live access.",
            "completed_at": "2026-08-15T00:00:00Z",
        }
        (manifest_dir / (namespace + ".json")).write_text(
            json.dumps(payload), encoding="utf-8")
    written["run_manifest"] = str(manifest_dir)
    return written


# Two throwaway namespaces, so `add` and `remove` do not depend on each other's
# test running first. Both exist only inside the disposable copy.
ADDED_SOURCE = "legoscout-smoke-add"
REMOVED_SOURCE = "legoscout-smoke-remove"


def _source_entry(namespace: str) -> dict:
    """A fully researched registry entry -- the shape `sources add` demands.

    Written out in full rather than derived from `sources add --template`,
    because the template is TODO markers and the validator rejects those. Every
    field here is a field the validator checks.
    """
    return {
        "display_name": "LegoScout smoke test %s" % namespace,
        "aliases": [],
        "short": namespace,
        "status": "dormant",
        "namespace": namespace,
        "listing_key_format": "%s|<numeric lot id>" % namespace,
        "access": {
            "method": "Direct fetch, no CLI/browser needed",
            "how": "a smoke-test fixture; this source is not real",
            "notes": "exists only inside the test's disposable ledger copy",
            "auth_required": False,
        },
        "capability": {
            "can_offer": False,
            "offer_method": "none",
            "conditional": False,
            "notes": "a test fixture cannot receive an offer",
            "evidence": "https://example.invalid/smoke-test",
            "verified_at": "2026-08-06",
        },
        "fees": None,
        "notes": [{
            "id": "%s-2026-08-06-1" % namespace,
            "date": "2026-08-06",
            "text": "created by the leaf-subcommand smoke test",
            "supersedes": None,
        }],
        "auction_tier": "never",
    }


@pytest.fixture(scope="session")
def removable_source(ledger):
    """A registered source with no deals on it, for `sources remove` to delete.

    Seeded through the registry's own connection rather than through
    `sources add`, so this case does not depend on that case having run.
    """
    entry = _source_entry(REMOVED_SOURCE)
    conn = registry._connect(ledger)
    try:
        payload = {k: v for k, v in entry.items() if k != "notes"}
        conn.execute("INSERT OR REPLACE INTO sources (namespace, payload) "
                     "VALUES (?, ?)", (REMOVED_SOURCE, json.dumps(payload)))
    finally:
        conn.close()
    return REMOVED_SOURCE


# --------------------------------------------------------------------------
# The cases. `args` builds the minimum valid invocation; `shape` is the
# contract the command's stdout promises.
# --------------------------------------------------------------------------

JSON, TEXT = "json", "text"


def _case(args, shape=JSON):
    return {"args": args, "shape": shape}


def cases(ids, files):
    """path -> the minimum valid invocation, for every leaf that can be run."""
    return {
        ("triage",): _case([files["triage"]]),

        ("sources", "list"): _case([]),
        ("sources", "get"): _case([ids["namespace"]]),
        ("sources", "add"): _case([files["entry"]]),
        ("sources", "remove"): _case([REMOVED_SOURCE]),
        ("sources", "validate"): _case([], TEXT),
        ("sources", "watermarks"): _case([]),
        ("sources", "notes", "list"): _case([ids["note_source"]]),
        ("sources", "notes", "get"): _case([ids["note_id"]]),
        ("sources", "notes", "add"): _case(
            [ids["namespace"], "--text", "smoke test note", "--date", "2026-08-06"]),

        ("deals", "list"): _case(["--limit", "5"]),
        ("deals", "get"): _case([ids["listing_key"]]),
        ("deals", "refresh"): _case(["--list"], TEXT),
        ("deals", "build"): _case([files["candidate"], files["appraisal"]]),
        ("deals", "run-manifest"): _case([files["run_manifest"]]),
        ("deals", "validate"): _case([]),
        ("deals", "status"): _case([ids["listing_key"], "active"]),
        ("deals", "schema"): _case(["crawl", "--json"]),
        ("deals", "replay"): _case([], TEXT),

        ("sellers", "list"): _case(["--limit", "5"]),
        ("sellers", "get"): _case([ids["source"], ids["seller_id"]]),
        ("sellers", "favorite"): _case([ids["source"], ids["seller_id"], "--off"]),
        ("sellers", "backfill"): _case(["--dry-run"]),

        ("prospects", "list"): _case(["--limit", "5"]),
        ("prospects", "get"): _case([ids["prospect_id"]]),
        ("prospects", "contacts", "list"): _case(["--limit", "5"]),
        ("prospects", "contacts", "get"): _case([ids["contact_id"]]),
        ("prospects", "outreach", "list"): _case(["--limit", "5"]),
        ("prospects", "runs", "list"): _case(["--limit", "5"]),
        ("prospects", "runs", "get"): _case([ids["run_id"]]),
        ("prospects", "hypotheses", "list"): _case(["--limit", "5"]),
        ("prospects", "hypotheses", "get"): _case([ids["hypothesis_type"]]),
        ("prospects", "create"): _case([files["prospect"]]),
        ("prospects", "contacts", "create"): _case([files["contact"]]),
        ("prospects", "runs", "create"): _case([files["run"]]),

        ("pricing", "fees"): _case(["--source", ids["namespace"]]),
        ("pricing", "landed-cost"): _case(
            ["--source", ids["namespace"], "--hammer", "40", "--shipping", "18"]),
        ("pricing", "pickup-area"): _case(["Evansville, IN 47725"]),
        ("pricing", "profit"): _case(
            ["--avg-price", "100", "--price-detail-count", "5",
             "--estimated-total", "50", "--fee-rate", "0.13"]),

        ("score", "deal"): _case([ids["listing_key"]]),
        ("score", "rescore"): _case(["--dry-run", "--limit", "5"]),

        ("display", "rows"): _case([]),
    }


# Commands that cannot be smoke-tested, and exactly why. Every entry is a live
# network call or a real-world side effect -- never "it was awkward". These are
# the commands no test protects.
SKIPPED: dict[tuple[str, ...], str] = {
    ("deals", "read"):
        "fetches the live marketplace listing to read one field; there is no "
        "offline path and no fixture mode",
    ("deals", "expire"):
        "re-verifies each expired listing against its live source, so a run "
        "makes one marketplace call per candidate row",
    ("prospects", "outreach", "get"):
        "the ledger holds no outreach row and the CLI has no command that "
        "creates one; an outreach row exists only after Adam approves a body, "
        "and seeding one here would fake that approval",
    ("prospects", "outreach", "send"):
        "sends a real email to a real prospect through the google CLI",
    ("pricing", "set-sales"):
        "calls BrickLink for sold comps",
    ("pricing", "ebay-comps"):
        "calls eBay's completed/sold search, a live browser-session scrape",
    ("pricing", "comps"):
        "calls both BrickLink (sold comps) and eBay's completed/sold search, a "
        "live browser-session scrape",
    ("pricing", "comps-batch"):
        "calls `pricing comps`'s own lookups concurrently across the whole "
        "batch -- both BrickLink sold comps and eBay's completed/sold search, "
        "a live browser-session scrape",
    ("pricing", "preflight"):
        "calls `bricklink auth status` and `ebay auth status`, each a live "
        "round-trip credential check against the real APIs, by design (that is "
        "the whole point of a preflight gate) -- there is no offline path",
    ("pricing", "shipping"):
        "calls the carrier for a live rate quote",
    ("pricing", "images"):
        "downloads a listing's photos from the live marketplace onto disk",
    ("pricing", "auctionninja-fees"):
        "fetches a live AuctionNinja lot page to read the house's published fees",
    ("pricing", "rebuild-pickup-area"):
        "downloads the Census and GeoNames geography dumps and rewrites the "
        "packaged pickup-area table",
    ("display", "serve"):
        "starts a long-lived HTTP server and opens a browser",
    ("deploy", "pull-db"):
        "sshes and scps against the real adam-server host",
    ("deploy", "push"):
        "sshes, scps, and git-archives against the real adam-server host",
    ("deploy", "status"):
        "sshes against the real adam-server host to read pm2/release state",
    ("deploy", "rollback"):
        "sshes against the real adam-server host and restarts its pm2 process",
}


# Commands this suite RUNS and that currently fail, with the defect named. They
# stay in `cases` -- not in `SKIPPED` -- so the coverage is real; the xfail is
# strict, so the day the owner fixes one of these the test FAILS and forces the
# entry out. This is what a smoke test is for: all three are the same defect as
# `deals build` was, a Typer wrapper calling a function with fewer arguments
# than its signature requires.
#
# They live in `legoscout_cli/commands/prospects.py`, which this change does not
# own.
KNOWN_BROKEN: dict[tuple[str, ...], str] = {
    ("prospects", "create"):
        "commands/prospects.py calls insert_prospect(record) but the signature "
        "is insert_prospect(prospect, contacts, *, path) -- TypeError on every "
        "invocation",
    ("prospects", "contacts", "create"):
        "commands/prospects.py calls insert_contact(record) but the signature "
        "is insert_contact(prospect_id, contact, *, path) -- TypeError on "
        "every invocation",
    ("prospects", "runs", "create"):
        "commands/prospects.py calls record_run(record) but the signature is "
        "record_run(run_key, hypothesis_type, searches, result_count, ...) -- "
        "TypeError on every invocation",
}


def test_known_broken_commands_are_still_run(ids, files):
    """A known defect is a case that runs, never a skip that hides it."""
    covered = set(cases(ids, files))
    for path in KNOWN_BROKEN:
        assert path in covered, "%s is marked broken but has no case" % " ".join(path)
        assert path not in SKIPPED, "%s must not be skipped as well" % " ".join(path)


def test_every_leaf_is_accounted_for(ids, files):
    """A new subcommand is covered, or skipped with a reason. Never neither.

    This is the assertion that stops the coverage from rotting. Add a command
    and this test fails until you have either smoke-tested it or written down
    why it cannot be.
    """
    known = set(cases(ids, files)) | set(SKIPPED)
    assert set(LEAVES) - known == set(), (
        "leaf subcommands with neither a smoke case nor a recorded skip reason")
    assert known - set(LEAVES) == set(), (
        "smoke cases or skips naming a subcommand that no longer exists")


def test_every_skip_states_a_reason():
    for path, reason in SKIPPED.items():
        assert len(reason.split()) >= 5, (
            "%s is skipped without a usable reason" % " ".join(path))


@pytest.fixture(scope="session")
def runner(ledger):
    return CliRunner()


@pytest.mark.parametrize("path", LEAVES, ids=lambda p: " ".join(p))
def test_leaf_subcommand_runs(path, request, runner, ids, files, ledger,
                              removable_source):
    if path in SKIPPED:
        pytest.skip(SKIPPED[path])
    if path == ("deals", "replay"):
        # `deals replay` replays real crawl fixtures under
        # `agent_workspaces/source-runs/<timestamp>/`, which AGENTS.md marks
        # "Per-run source worker artifacts. Disposable." When that run's
        # directory has been cleaned up there is nothing to replay, and the
        # command itself refuses to fabricate fixtures. Skipping here keeps the
        # rest of the suite green without turning replay into a no-op: restore
        # the run (or re-crawl) and this case runs again automatically.
        missing = replay_fixtures.missing_fixtures()
        if missing:
            pytest.skip(
                "replay fixtures missing under %s: %s -- the disposable per-run "
                "source-worker artifacts `deals replay` depends on were deleted; "
                "restore that run from Dropbox version history / adam-server "
                "releases or re-crawl, then this case runs again"
                % (replay_fixtures.FIXTURES, ", ".join(missing)))
    if path in KNOWN_BROKEN:
        # strict: fixing the command turns this into a FAILURE, which is the
        # prompt to delete the entry rather than let it rot into a permanent
        # exemption.
        request.applymarker(pytest.mark.xfail(reason=KNOWN_BROKEN[path],
                                              strict=True))
    case = cases(ids, files)[path]
    argv = list(path) + case["args"]
    result = runner.invoke(app, argv)
    # The output carries the `Error: ...` line the `@command` decorator prints;
    # the exception carries a traceback when the command died before that. A
    # failure message that shows only one of the two names nothing useful.
    assert result.exit_code == 0, "legoscout %s exited %s\noutput: %s\nraised: %r" % (
        " ".join(argv), result.exit_code, result.output[:2000], result.exception)
    assert result.stdout.strip(), "legoscout %s printed nothing" % " ".join(argv)
    if case["shape"] == JSON:
        json.loads(result.stdout)
