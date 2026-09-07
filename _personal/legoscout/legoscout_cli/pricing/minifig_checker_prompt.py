#!/usr/bin/env python3
"""Build the canonical pre-price semantic-checker prompt."""
from __future__ import annotations

import argparse
from pathlib import Path

from .minifig_receipt import freeze_review, digest


def build(*, verified_json: str, identifier_run_json: str,
          launch_marker_json: str) -> str:
    evidence = {
        "verified.json": Path(verified_json),
        "identifier run evidence": Path(identifier_run_json),
        "identifier launch marker": Path(launch_marker_json),
    }
    for label, path in evidence.items():
        if not path.is_absolute():
            raise ValueError(f"{label} path must be absolute")
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"{label} must be an existing non-empty file: {path}")

    request = freeze_review(evidence["verified.json"],
                            evidence["identifier run evidence"],
                            evidence["identifier launch marker"])
    return f"""Review the minifigure identifier's PRE-PRICE evidence only.

Evidence:
- verified evidence: {evidence['verified.json']}
- identifier run evidence: {evidence['identifier run evidence']}
- launch marker: {evidence['identifier launch marker']}

The frozen input SHA-256 is {request['verified_sha256']}.
The frozen review request SHA-256 is {digest(request)}.
Verify the input file SHA-256 matches before reviewing. Return block if it differs.
Echo those exact digests as verified_sha256 and request_sha256 in your result.

Check ordered listing/group coverage, exact verification keys, candidate order,
catalog evidence, semantic identity agreement, and identifier route evidence.
Return pass when this pre-price evidence satisfies those checks.

Phase boundary: checker-result.json is this checker's output and cannot be an
input requirement. identifier.complete.json and the priced identify artifact
are created only after a pass verdict. Do not inspect them, require them, or
block because they do not exist. Route audit and post-price validation own
checker-result.json, identifier.complete.json, and the priced artifact.
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verified-json", required=True)
    parser.add_argument("--identifier-run-json", required=True)
    parser.add_argument("--launch-marker-json", required=True)
    args = parser.parse_args()
    print(build(
        verified_json=args.verified_json,
        identifier_run_json=args.identifier_run_json,
        launch_marker_json=args.launch_marker_json,
    ), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
