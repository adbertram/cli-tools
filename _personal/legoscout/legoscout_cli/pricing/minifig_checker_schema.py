#!/usr/bin/env python3
"""Write the canonical strict response schema for the minifigure checker."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .minifig_receipt import CHECKER


def schema() -> dict:
    """Return the single checker response contract accepted by Codex."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Pre-price minifigure semantic checker result",
        "description": (
            "Verdict over verified pre-price evidence only; later route-audit "
            "and priced-output artifacts are outside this checker phase."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": ["model", "provider", "route", "verdict", "findings",
                     "verified_sha256", "request_sha256"],
        "properties": {
            "model": {"type": "string", "const": CHECKER["model"]},
            "provider": {"type": "string", "const": CHECKER["provider"]},
            "route": {"type": "string", "const": CHECKER["route"]},
            "verdict": {"type": "string", "enum": ["pass", "block"]},
            "verified_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "request_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "findings": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
    }


def write(output: str) -> Path:
    target = Path(output)
    if not target.is_absolute():
        raise ValueError("output must be an absolute path")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(write(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
