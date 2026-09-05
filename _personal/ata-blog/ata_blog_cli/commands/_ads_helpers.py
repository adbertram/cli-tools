"""Shared helpers for --include-ads on wordpress-post get/list.

Keeps ad-scanning wiring DRY across the two commands.
"""
from __future__ import annotations

import json
import subprocess
import sys
from typing import List, Union

import typer

from ..ads_scanner import SCANNER_DEFAULTS, scan_pages


def run_wp_capture(args: List[str]) -> Union[dict, list]:
    """Run wordpress CLI, capture JSON output, exit on non-zero or non-JSON."""
    cmd = ["wordpress"] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        if result.stderr:
            sys.stderr.write(result.stderr)
        raise typer.Exit(result.returncode)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"wordpress CLI returned non-JSON: {e}\n")
        raise typer.Exit(1)


def reject_table_with_include_ads(table: bool, include_ads: bool) -> None:
    """Refuse the --table + --include-ads combination with a clear error."""
    if table and include_ads:
        raise typer.BadParameter(
            "cannot combine --table with --include-ads (ads output is JSON-only)"
        )


def inject_link_into_properties(args: List[str]) -> List[str]:
    """If --properties / -p is set and does NOT include 'link', add it.

    Handles three forms: `--properties X,Y`, `--properties=X,Y`, `-p X,Y`.
    """
    out = list(args)
    for i, a in enumerate(out):
        if a in ("--properties", "-p") and i + 1 < len(out):
            props = [p.strip() for p in out[i + 1].split(",")]
            if "link" not in props:
                props.append("link")
                out[i + 1] = ",".join(props)
            return out
        if a.startswith("--properties="):
            props = [p.strip() for p in a.split("=", 1)[1].split(",")]
            if "link" not in props:
                props.append("link")
                out[i] = "--properties=" + ",".join(props)
            return out
    return out


def _require_link(post: dict) -> str:
    link = post.get("link")
    if not link:
        sys.stderr.write(
            f"[ata-blog] Post {post.get('id')} has no 'link' field; cannot scan ads. "
            "Did you pass --properties without 'link'?\n"
        )
        raise typer.Exit(2)
    return link


def scan_and_merge(
    data: Union[dict, list],
    checks: int,
    interval: int,
    timeout: int,
    sponsored_warning: bool = False,
) -> Union[dict, list]:
    """Scan URL(s) via shared browser; merge under a top-level 'ads' key."""
    if isinstance(data, list):
        if sponsored_warning:
            sys.stderr.write(
                "[ata-blog] Note: sponsored posts have ads disabled; scans will return empty.\n"
            )
        if len(data) >= 3:
            sys.stderr.write(
                f"[ata-blog] Scanning {len(data)} posts serially; wall-clock "
                f">= {len(data)} * ({checks * interval}s between-reload + per-check GPT wait).\n"
            )
        links = [_require_link(p) for p in data]
        scans = scan_pages(links, checks=checks, interval=interval, per_check_timeout=timeout)
        return [{**p, "ads": s} for p, s in zip(data, scans)]
    # dict
    link = _require_link(data)
    scans = scan_pages([link], checks=checks, interval=interval, per_check_timeout=timeout)
    return {**data, "ads": scans[0]}


__all__ = [
    "run_wp_capture",
    "reject_table_with_include_ads",
    "inject_link_into_properties",
    "scan_and_merge",
    "SCANNER_DEFAULTS",
]
