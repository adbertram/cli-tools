#!/usr/bin/env python3
"""Regenerate coursecraft-cli usage.json from the live installed CLI.

Deterministic generator: reuses the cli-tool compliance test utilities
(discover_nested_commands / parse_help_parameters) so the produced command
tree and per-command arguments/options exactly match what
test_usage_json.py validates against the installed CLI.

Existing per-command enrichment (help / examples / usage_instructions) is
preserved by command path; new commands get parsed help text; removed
commands are dropped. Top-level metadata is preserved and refreshed.

Usage:
    python3 regenerate_usage.py [--cli coursecraft] [--check]

--check exits non-zero if usage.json would change (no write).
"""
import argparse
import json
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

# cli-tool test utilities are the source of truth for discovery + parsing.
CLI_TOOL_TESTS = Path(__file__).resolve().parents[1] / "cli-tool" / "tests"
sys.path.insert(0, str(CLI_TOOL_TESTS))

from cli_test_utils import (  # noqa: E402
    discover_nested_commands,
    leaf_command_paths,
    parse_help_commands,
    parse_help_parameters,
    run_cli_command,
)

TEST_CONFIG = CLI_TOOL_TESTS / "cli_test_config.toml"


def load_config():
    with open(TEST_CONFIG, "rb") as fh:
        return tomllib.load(fh)


def help_text(cli_executable, path, timeout):
    args = path.split() + ["--help"] if path else ["--help"]
    return run_cli_command(cli_executable, args, timeout=timeout).stdout


def build_tree(cli_name, cli_executable, config):
    skip_list = config["command_discovery"]["skip_list"]
    timeout = config["general"]["command_timeout"]
    max_depth = config["general"]["max_nested_depth"]
    cli_specific = config.get("cli_specific", {})
    if cli_name in cli_specific:
        max_depth = cli_specific[cli_name].get("max_nested_depth", max_depth)

    live_paths = sorted(
        discover_nested_commands(
            cli_executable, "", depth=0, max_depth=max_depth,
            skip_list=skip_list, timeout=timeout,
        )
    )

    # Parameters for each leaf-or-group command path.
    params = {p: parse_help_parameters(help_text(cli_executable, p, timeout)) for p in live_paths}
    helps = {p: extract_help_line(help_text(cli_executable, p, timeout)) for p in live_paths}
    return live_paths, params, helps


def extract_help_line(text):
    """First non-usage prose line of a --help output, best-effort."""
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("Usage:") or s.startswith("─") or s.startswith("╭") or s.startswith("│") or s.startswith("╰"):
            continue
        return s
    return ""


def existing_node_meta(old_usage):
    """Map command path -> {help, examples, usage_instructions} from old usage.json."""
    meta = {}

    def walk(tree, prefix):
        for name, node in (tree or {}).items():
            path = f"{prefix} {name}".strip()
            entry = {}
            for key in ("help", "examples", "usage_instructions"):
                if key in node:
                    entry[key] = node[key]
            meta[path] = entry
            walk(node.get("commands"), path)

    walk(old_usage.get("commands", {}), "")
    return meta


def assemble(live_paths, params, helps, old_meta):
    """Build nested commands dict from flat live paths."""
    root = {}
    for path in live_paths:
        parts = path.split(" ")
        cursor = root
        for i, part in enumerate(parts):
            cur_path = " ".join(parts[: i + 1])
            node = cursor.setdefault(part, {})
            # Set help: prefer preserved enrichment, else parsed help line.
            meta = old_meta.get(cur_path, {})
            if "help" in meta:
                node.setdefault("help", meta["help"])
            elif helps.get(cur_path):
                node.setdefault("help", helps[cur_path])
            if i == len(parts) - 1:
                p = params.get(cur_path, {"arguments": [], "options": []})
                node["arguments"] = p["arguments"]
                node["options"] = p["options"]
                if "examples" in meta:
                    node["examples"] = meta["examples"]
                if "usage_instructions" in meta:
                    node["usage_instructions"] = meta["usage_instructions"]
            else:
                node.setdefault("commands", {})
                # ensure group-level examples/usage_instructions preserved
                if "examples" in meta:
                    node.setdefault("examples", meta["examples"])
                if "usage_instructions" in meta:
                    node.setdefault("usage_instructions", meta["usage_instructions"])
                cursor = node["commands"]
    return root


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cli", default="coursecraft")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    cli_name = args.cli
    usage_path = Path(__file__).resolve().parent / "usage.json"
    old_usage = json.loads(usage_path.read_text())

    config = load_config()
    cli_executable = cli_name  # on PATH

    live_paths, params, helps = build_tree(cli_name, cli_executable, config)
    old_meta = existing_node_meta(old_usage)
    commands = assemble(live_paths, params, helps, old_meta)

    new_usage = dict(old_usage)
    new_usage["commands"] = commands
    # total_commands counts leaf commands only, matching the compliance test.
    new_usage["total_commands"] = len(leaf_command_paths(set(live_paths)))
    new_usage["discovered_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    new_text = json.dumps(new_usage, indent=2, ensure_ascii=False) + "\n"

    if args.check:
        if new_text != usage_path.read_text():
            print("usage.json is OUT OF DATE", file=sys.stderr)
            sys.exit(1)
        print("usage.json is current")
        return

    usage_path.write_text(new_text)
    print(f"Wrote {usage_path} ({len(live_paths)} commands)")


if __name__ == "__main__":
    main()
