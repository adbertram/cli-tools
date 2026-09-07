#!/usr/bin/env python3
"""Create and verify fixed LegoScout minifigure model-route markers."""
from __future__ import annotations

import argparse
import hashlib
from copy import deepcopy
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

IDENTIFIER = {
    "model": "gpt-5.6-sol",
    "provider": "openai",
    "route": "codex-custom-agent",
}
CHECKER = {
    "model": "gpt-5.6-luna",
    "provider": "openai",
    "route": "codex-exec-checker",
}
IDENTIFIER_RUN_KEYS = {"model", "provider", "route", "status"}
CHECKER_RESULT_KEYS = {"model", "provider", "route", "verdict", "findings",
                       "verified_sha256", "request_sha256"}
LAUNCH_KEYS = {
    "version",
    "expected_model",
    "expected_provider",
    "expected_route",
    "expected_checker_model",
    "expected_checker_provider",
    "expected_checker_route",
    "input_path",
    "output_path",
    "launched_at",
}


class AuditError(ValueError):
    """Model-route evidence failed its exact contract."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _absolute(value: str, label: str, *, must_exist: bool) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise AuditError(f"{label} must be an absolute path")
    if must_exist and not path.exists():
        raise AuditError(f"{label} does not exist: {path}")
    return path.resolve(strict=False)


def _read_exact(path: Path, keys: set[str], label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditError(f"{label} is unreadable: {exc}") from exc
    if not isinstance(payload, dict) or set(payload) != keys:
        actual = sorted(payload) if isinstance(payload, dict) else type(payload).__name__
        raise AuditError(
            f"{label} keys must be exactly {sorted(keys)}; got {actual}")
    return payload


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    try:
        os.link(temporary, path)
    except FileExistsError as exc:
        raise AuditError(f"{path.name} already exists; use fresh scratch") from exc
    finally:
        temporary.unlink()


def launch(*, scratch_dir: str, input_path: str, output_path: str) -> dict[str, Any]:
    scratch = _absolute(scratch_dir, "scratch_dir", must_exist=True)
    if not scratch.is_dir():
        raise AuditError("scratch_dir must be a directory")
    source = _absolute(input_path, "input", must_exist=True)
    target = _absolute(output_path, "output", must_exist=False)
    marker = scratch / "identifier.launch.json"
    payload = {
        "version": 1,
        "expected_model": IDENTIFIER["model"],
        "expected_provider": IDENTIFIER["provider"],
        "expected_route": IDENTIFIER["route"],
        "expected_checker_model": CHECKER["model"],
        "expected_checker_provider": CHECKER["provider"],
        "expected_checker_route": CHECKER["route"],
        "input_path": str(source),
        "output_path": str(target),
        "launched_at": _now(),
    }
    _atomic_json(marker, payload)
    return {
        "ok": True,
        "phase": "launch",
        "marker_path": str(marker),
        "routes_match": True,
        "checker_verdict": None,
        "artifact_path": None,
    }


def _evidence(identifier_path: str, checker_path: str) -> tuple[dict, dict]:
    identifier = _read_exact(
        _absolute(identifier_path, "identifier_run_json", must_exist=True),
        IDENTIFIER_RUN_KEYS,
        "identifier run",
    )
    checker = _read_exact(
        _absolute(checker_path, "checker_result_json", must_exist=True),
        CHECKER_RESULT_KEYS,
        "checker result",
    )
    if identifier["status"] != "completed":
        raise AuditError("identifier status must be completed")
    for key, expected in IDENTIFIER.items():
        if identifier[key] != expected:
            raise AuditError(
                f"identifier {key} mismatch: expected {expected!r}, got {identifier[key]!r}")
    if checker["verdict"] != "pass":
        raise AuditError("checker verdict must be pass")
    if not isinstance(checker["findings"], list):
        raise AuditError("checker findings must be an array")
    for key, expected in CHECKER.items():
        if checker[key] != expected:
            raise AuditError(
                f"checker {key} mismatch: expected {expected!r}, got {checker[key]!r}")
    return identifier, checker


def gate(*, scratch_dir: str, identifier_run_json: str,
         checker_result_json: str) -> dict[str, Any]:
    scratch = _absolute(scratch_dir, "scratch_dir", must_exist=True)
    launch_marker = scratch / "identifier.launch.json"
    launch_payload = _read_exact(
        launch_marker, LAUNCH_KEYS, "identifier launch marker")
    expected = {
        "expected_model": IDENTIFIER["model"],
        "expected_provider": IDENTIFIER["provider"],
        "expected_route": IDENTIFIER["route"],
        "expected_checker_model": CHECKER["model"],
        "expected_checker_provider": CHECKER["provider"],
        "expected_checker_route": CHECKER["route"],
    }
    for key, value in expected.items():
        if launch_payload[key] != value:
            raise AuditError(
                f"launch marker {key} mismatch: expected {value!r}, "
                f"got {launch_payload[key]!r}")
    _evidence(identifier_run_json, checker_result_json)
    consume_review(scratch / "verified.json", identifier_run_json, checker_result_json)
    return {
        "ok": True,
        "phase": "gate",
        "marker_path": str(launch_marker),
        "routes_match": True,
        "checker_verdict": "pass",
        "artifact_path": None,
    }


def _sha256_file(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_artifact(raw: bytes) -> list[dict]:
    """The completion marker is the publication boundary, so the priced
    artifact must already be a non-empty JSON array of listing objects
    before any receipt exists."""
    try:
        payload = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"artifact is not readable JSON: {exc}") from exc
    if not isinstance(payload, list) or not payload:
        raise AuditError("artifact must be a non-empty JSON array")
    if not all(isinstance(row, dict) for row in payload):
        raise AuditError("artifact rows must be JSON objects")
    return payload


def complete(*, scratch_dir: str, identifier_run_json: str,
             checker_result_json: str, artifact: str) -> dict[str, Any]:
    gate(
        scratch_dir=scratch_dir,
        identifier_run_json=identifier_run_json,
        checker_result_json=checker_result_json,
    )
    scratch = _absolute(scratch_dir, "scratch_dir", must_exist=True)
    artifact_path = _absolute(artifact, "artifact", must_exist=True)
    if not artifact_path.is_file() or artifact_path.stat().st_size == 0:
        raise AuditError("artifact must be a non-empty file")
    artifact_raw = artifact_path.read_bytes()
    artifact_rows = _validate_artifact(artifact_raw)
    request = json.loads((scratch / "checker-request.json").read_bytes())
    if [row.get("listing_key") for row in artifact_rows] != request["listing_keys"]:
        raise AuditError("artifact listing coverage/order does not match reviewed listing keys")
    for row in artifact_rows:
        if row.get(RECEIPT_FIELD, {}).get("request") != request:
            raise AuditError("artifact receipt does not match this review request")
        validate_publication_record(row, kind="identification")
    launched = _read_exact(scratch / "identifier.launch.json", LAUNCH_KEYS, "launch")
    if str(artifact_path) != launched["output_path"]:
        raise AuditError("artifact path does not match launch output")
    identifier_path = _absolute(
        identifier_run_json, "identifier_run_json", must_exist=True)
    checker_path = _absolute(
        checker_result_json, "checker_result_json", must_exist=True)
    marker = scratch / "identifier.complete.json"
    # The receipt is ONE-SHOT and content-bound: it records the digests of
    # the exact evidence and artifact bytes that passed the gate. A rerun
    # against different bytes can never silently replace a completed run.
    payload = {
        "version": 3,
        "actual_model": IDENTIFIER["model"],
        "actual_provider": IDENTIFIER["provider"],
        "actual_route": IDENTIFIER["route"],
        "actual_checker_model": CHECKER["model"],
        "actual_checker_provider": CHECKER["provider"],
        "actual_checker_route": CHECKER["route"],
        "checker_verdict": "pass",
        "artifact_path": str(artifact_path),
        "artifact_sha256": hashlib.sha256(artifact_raw).hexdigest(),
        "verified_sha256": _sha256_file(scratch / "verified.json"),
        "identifier_evidence_sha256": _sha256_file(identifier_path),
        "checker_evidence_sha256": _sha256_file(checker_path),
        "completed_at": _now(),
    }
    if marker.exists():
        try:
            previous = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AuditError(
                f"existing completion marker is unreadable: {exc}") from exc
        same_bytes = ({key: value for key, value in previous.items() if key != "completed_at"}
                      == {key: value for key, value in payload.items() if key != "completed_at"})
        if not same_bytes:
            raise AuditError(
                "identifier.complete.json already completed for different "
                "evidence/artifact bytes; rerun the batch in fresh scratch")
        return {
            "ok": True,
            "phase": "complete",
            "marker_path": str(marker),
            "routes_match": True,
            "checker_verdict": "pass",
            "artifact_path": str(artifact_path),
        }
    _atomic_json(marker, payload)
    return {
        "ok": True,
        "phase": "complete",
        "marker_path": str(marker),
        "routes_match": True,
        "checker_verdict": "pass",
        "artifact_path": str(artifact_path),
    }


RECEIPT_FIELD = "minifig_review_receipt"
PUBLICATION_FIELDS = ("listing_key", "minifig_analysis", "figure_count", "figure_count_source")
PRICE_FIELDS = {"used", "unit_value", "extended_value", "null_value_reason", "errors"}
BASE_RECEIPT_FIELDS = {
    "version", "request", "identifier", "checker", "publication_sha256",
    "priced_row_sha256", "pricing_complete",
}
SYNTHESIS_DIGEST_FIELD = "synthesis_sha256"


def digest(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def publication_digest(record: dict, pricing_complete: bool) -> str:
    return digest({**{key: record[key] for key in PUBLICATION_FIELDS},
                   "pricing_complete": pricing_complete})


def synthesis_digest(record: dict) -> str:
    """Bind every persisted deal field except server-owned state and this receipt."""
    from ..ledger import db

    return digest({
        key: record.get(key)
        for key in db._COLUMNS
        if key not in db.SERVER_OWNED_FIELDS and key != RECEIPT_FIELD
    })


def bind_deal_record(record: dict) -> None:
    """Extend a reviewed identity receipt at the final canonical deal boundary."""
    receipt = record.get(RECEIPT_FIELD)
    if not isinstance(receipt, dict) or set(receipt) != BASE_RECEIPT_FIELDS:
        raise AuditError("deal binding requires the exact reviewed identity receipt")
    record[RECEIPT_FIELD] = {
        **deepcopy(receipt),
        SYNTHESIS_DIGEST_FIELD: synthesis_digest(record),
    }
    validate_publication_record(record, kind="deal")


def identity_digest(entries: list | None) -> str:
    return digest(None if entries is None else [
        {key: value for key, value in entry.items() if key not in PRICE_FIELDS}
        for entry in entries])


def review_manifest(artifact: dict) -> dict[str, str]:
    from . import minifig_identification as pipeline
    from ..ledger import minifig_analysis
    validated = pipeline._validate_price_artifact(artifact)
    return {
        row["listing_key"]: identity_digest(
            None if row["blocked"] else [minifig_analysis.normalize_entry(entry)
                                        for entry in row["entries"]])
        for row in (pipeline._prepared_listing(listing) for listing in validated["listings"])
    }


def freeze_review(verified: Path, identifier: Path, launch_marker: Path) -> dict:
    """Freeze the exact bytes and identity projections before dispatching the checker."""
    raw = verified.read_bytes()
    request = {
        "version": 3,
        "verified_sha256": hashlib.sha256(raw).hexdigest(),
        "identities": review_manifest(json.loads(raw)),
        "listing_keys": [row["listing_key"] for row in json.loads(raw)["listings"]],
        "identifier_sha256": _sha256_file(identifier),
        "launch_sha256": _sha256_file(launch_marker),
    }
    if not request["identities"]:
        raise AuditError("review input must have non-empty listing coverage")
    target = verified.parent / "checker-request.json"
    if target.exists():
        if json.loads(target.read_bytes()) != request:
            raise AuditError("checker request already frozen for different evidence; use fresh scratch")
    else:
        _atomic_json(target, request)
    return request


def consume_review(verified: Path, identifier_path: str | Path,
                   checker_path: str | Path, *, raw: bytes | None = None) -> tuple[dict, dict]:
    """Check once-read input bytes against the pre-review request and checker verdict."""
    if raw is None:
        raw = verified.read_bytes()
    request = json.loads((verified.parent / "checker-request.json").read_bytes())
    identifier, checker = _evidence(str(identifier_path), str(checker_path))
    launch_path = verified.parent / "identifier.launch.json"
    launch = _read_exact(launch_path, LAUNCH_KEYS, "identifier launch marker")
    for route, prefix in ((IDENTIFIER, "expected_"), (CHECKER, "expected_checker_")):
        if any(launch[prefix + key] != value for key, value in route.items()):
            raise AuditError("launch route mismatch")
    if request.get("version") != 3:
        raise AuditError("review request must be content-bound version 3")
    if request.get("verified_sha256") != hashlib.sha256(raw).hexdigest():
        raise AuditError("verified evidence changed after checker request")
    if (request.get("identifier_sha256") != _sha256_file(Path(identifier_path))
            or request.get("launch_sha256") != _sha256_file(launch_path)):
        raise AuditError("route evidence changed after checker request")
    artifact = json.loads(raw)
    if (request.get("identities") != review_manifest(artifact)
            or request.get("listing_keys") != [row["listing_key"] for row in artifact["listings"]]):
        raise AuditError("review identity manifest does not match verified evidence")
    if (checker["verified_sha256"] != request["verified_sha256"]
            or checker["request_sha256"] != digest(request)):
        raise AuditError("checker result does not bind frozen review request")
    return artifact, {"version": 3, "request": request,
                      "identifier": identifier, "checker": checker}


def attach_receipts(rows: list[dict], evidence: dict) -> None:
    if [row["listing_key"] for row in rows] != evidence["request"]["listing_keys"]:
        raise AuditError("priced listing coverage does not match reviewed coverage")
    for row in rows:
        row[RECEIPT_FIELD] = {
            **deepcopy(evidence),
            "publication_sha256": publication_digest(row, row["pricing_complete"]),
            "priced_row_sha256": digest(row),
            "pricing_complete": row["pricing_complete"],
        }
        validate_publication_record(row, kind="identification")


def validate_publication_record(record: dict, *, kind: str) -> None:
    """Require a portable content-bound receipt for new publication/ingestion only."""
    if kind not in {"identification", "deal"}:
        raise AuditError("publication kind must be identification or deal")
    receipt = record.get(RECEIPT_FIELD)
    if not isinstance(receipt, dict) or receipt.get("version") != 3:
        raise AuditError("new minifigure records require a content-bound review receipt version 3")
    request = receipt.get("request")
    identifier = receipt.get("identifier")
    checker = receipt.get("checker")
    expected_receipt_fields = (
        BASE_RECEIPT_FIELDS if kind == "identification"
        else BASE_RECEIPT_FIELDS | {SYNTHESIS_DIGEST_FIELD}
    )
    if (set(receipt) != expected_receipt_fields
            or not isinstance(request, dict) or request.get("version") != 3
            or not isinstance(identifier, dict) or set(identifier) != IDENTIFIER_RUN_KEYS
            or not isinstance(checker, dict) or set(checker) != CHECKER_RESULT_KEYS):
        raise AuditError("malformed review receipt evidence")
    expected_request_keys = {"version", "verified_sha256", "identifier_sha256", "launch_sha256",
                             "identities", "listing_keys"}
    if (set(request) != expected_request_keys
            or not isinstance(request["listing_keys"], list)
            or not all(isinstance(key, str) for key in request["listing_keys"])
            or len(set(request["listing_keys"])) != len(request["listing_keys"])
            or not isinstance(request["identities"], dict)
            or set(request["identities"]) != set(request["listing_keys"])
            or type(receipt["pricing_complete"]) is not bool
            or not isinstance(checker["findings"], list)
            or not all(isinstance(finding, str) for finding in checker["findings"])):
        raise AuditError("malformed frozen review request")
    hash_values = [request[key] for key in ("verified_sha256", "identifier_sha256", "launch_sha256")]
    hash_values.extend(request["identities"].values())
    if any(not isinstance(value, str) or len(value) != 64
           or any(char not in "0123456789abcdef" for char in value) for value in hash_values):
        raise AuditError("review request digests must be SHA-256 hex strings")
    if identifier["status"] != "completed" or checker["verdict"] != "pass":
        raise AuditError("review receipt requires completed identifier and checker pass")
    for evidence, route in ((identifier, IDENTIFIER), (checker, CHECKER)):
        if any(evidence[key] != value for key, value in route.items()):
            raise AuditError("review receipt model route mismatch")
    if (checker["verified_sha256"] != request.get("verified_sha256")
            or checker["request_sha256"] != digest(request)):
        raise AuditError("checker result does not bind frozen review request")
    if not all(key in record for key in PUBLICATION_FIELDS):
        raise AuditError("minifigure publication fields missing")
    if receipt.get("publication_sha256") != publication_digest(record, receipt["pricing_complete"]):
        raise AuditError("minifigure publication changed after pricing")
    identities = request.get("identities")
    if (not isinstance(identities, dict) or record["listing_key"] not in identities
            or identities[record["listing_key"]] != identity_digest(record["minifig_analysis"])):
        raise AuditError("published identity does not match reviewed identity")
    from ..orchestrator import validate_identification_result
    if kind == "identification":
        if receipt.get("priced_row_sha256") != digest({key: value for key, value in record.items()
                                                       if key != RECEIPT_FIELD}):
            raise AuditError("priced row changed after publication")
        if receipt.get("pricing_complete") != record.get("pricing_complete"):
            raise AuditError("pricing completeness does not match receipt")
        validate_identification_result(record, "reviewed publication")
    else:
        if receipt.get(SYNTHESIS_DIGEST_FIELD) != synthesis_digest(record):
            raise AuditError("minifigure deal changed after canonical synthesis")
        if receipt.get("pricing_complete") is False and record.get("profit_incomplete") is False:
            raise AuditError("incomplete reviewed pricing cannot become complete at ingestion")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    launch_parser = commands.add_parser("launch")
    launch_parser.add_argument("--scratch-dir", required=True)
    launch_parser.add_argument("--input", required=True)
    launch_parser.add_argument("--output", required=True)
    for name in ("gate", "complete"):
        subparser = commands.add_parser(name)
        subparser.add_argument("--scratch-dir", required=True)
        subparser.add_argument("--identifier-run-json", required=True)
        subparser.add_argument("--checker-result-json", required=True)
        if name == "complete":
            subparser.add_argument("--artifact", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "launch":
            result = launch(
                scratch_dir=args.scratch_dir,
                input_path=args.input,
                output_path=args.output,
            )
        elif args.command == "gate":
            result = gate(
                scratch_dir=args.scratch_dir,
                identifier_run_json=args.identifier_run_json,
                checker_result_json=args.checker_result_json,
            )
        else:
            result = complete(
                scratch_dir=args.scratch_dir,
                identifier_run_json=args.identifier_run_json,
                checker_result_json=args.checker_result_json,
                artifact=args.artifact,
            )
    except (AuditError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "errors": [str(exc)]}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
