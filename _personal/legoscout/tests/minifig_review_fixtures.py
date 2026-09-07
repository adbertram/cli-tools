"""Synthetic fixed-route reviews for offline minifigure publication tests."""
import hashlib
import json
from pathlib import Path

from legoscout_cli.pricing import minifig_checker_prompt, minifig_receipt


def prepare_review_files(scratch: Path, artifact: dict, output: Path) -> Path:
    """Freeze a real verified artifact, then write a synthetic checker pass."""
    scratch.mkdir(parents=True, exist_ok=True)
    verified = scratch / "verified.json"
    verified.write_text(json.dumps(artifact))
    handoff = scratch / "handoff.json"
    handoff.write_text(json.dumps([{"listing_key": row["listing_key"]}
                                  for row in artifact["listings"]]))
    minifig_receipt.launch(scratch_dir=str(scratch), input_path=str(handoff),
                          output_path=str(output))
    identifier = scratch / "identifier-run.json"
    identifier.write_text(json.dumps({**minifig_receipt.IDENTIFIER, "status": "completed"}))
    minifig_checker_prompt.build(verified_json=str(verified), identifier_run_json=str(identifier),
                                launch_marker_json=str(scratch / "identifier.launch.json"))
    request = json.loads((scratch / "checker-request.json").read_bytes())
    (scratch / "checker-result.json").write_text(json.dumps({
        **minifig_receipt.CHECKER, "verdict": "pass", "findings": [],
        "verified_sha256": request["verified_sha256"],
        "request_sha256": minifig_receipt.digest(request),
    }))
    return verified


def attach_test_receipts(rows: list[dict]) -> list[dict]:
    """Attach structurally real receipts backed by explicit synthetic review evidence.

    This helper supports existing canonical priced-row fixtures. Publication-path
    tests use prepare_review_files instead, which freezes the real input bytes.
    """
    request = {
        "version": 3,
        "verified_sha256": hashlib.sha256(b"synthetic offline verified fixture").hexdigest(),
        "identifier_sha256": hashlib.sha256(b"synthetic identifier").hexdigest(),
        "launch_sha256": hashlib.sha256(b"synthetic launch").hexdigest(),
        "listing_keys": [row["listing_key"] for row in rows],
        "identities": {row["listing_key"]: minifig_receipt.identity_digest(row["minifig_analysis"])
                       for row in rows},
    }
    evidence = {
        "version": 3, "request": request,
        "identifier": {**minifig_receipt.IDENTIFIER, "status": "completed"},
        "checker": {**minifig_receipt.CHECKER, "verdict": "pass", "findings": [],
                    "verified_sha256": request["verified_sha256"],
                    "request_sha256": minifig_receipt.digest(request)},
    }
    minifig_receipt.attach_receipts(rows, evidence)
    return rows
