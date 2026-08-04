#!/usr/bin/env python3
"""Derive SKILL.md sections from a CLI skill's generated ``usage.json``.

``create-cli-tool-skill`` used to emit a fixed SKILL.md body: a ``quick_start``
table that always advertised ``<cli> auth login`` / ``<cli> auth status`` and a
``Command Groups`` list that always named ``auth`` and ``cache``. A CLI created
with ``--auth-type none`` has no ``auth`` group at all, so an agent that
followed the generated skill ran commands that do not exist.

``usage.json`` is generated from the installed CLI's live ``--help`` tree, so it
is the real command contract. This helper reads that tree and prints the two
sections that must match it. Groups and commands that do not exist are never
printed, so a CLI without ``auth`` gets no auth row and no auth group entry.

Usage:
    skill_content_from_usage.py <usage-json> <cli-name> --section quick-start
    skill_content_from_usage.py <usage-json> <cli-name> --section command-groups
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# Help text in usage.json is the command's full docstring line, which is often
# several sentences. A table cell and a group bullet want the opening sentence.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s")


class UsageContractError(RuntimeError):
    """Raised when usage.json does not describe a usable command tree."""


def load_commands(usage_path: Path) -> dict:
    if not usage_path.is_file():
        raise UsageContractError(f"MISSING_USAGE_JSON: {usage_path}")
    data = json.loads(usage_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise UsageContractError(
            f"JSON_CONTRACT_MISMATCH: {usage_path} root is {type(data).__name__}, expected object"
        )
    commands = data.get("commands")
    if not isinstance(commands, dict):
        raise UsageContractError(
            f"MISSING_JSON_PATH: commands in {usage_path} "
            f"(available keys: {sorted(data)})"
        )
    if not commands:
        raise UsageContractError(
            f"EMPTY_COMMAND_TREE: {usage_path} lists no commands. "
            "The CLI must be installed and expose at least one command group."
        )
    return commands


def child_commands(node: dict) -> dict:
    children = node.get("commands")
    if isinstance(children, dict) and children:
        return children
    return {}


def first_sentence(help_text: object) -> str:
    text = " ".join(str(help_text or "").split())
    if not text:
        return ""
    return _SENTENCE_END.split(text, 1)[0].rstrip(".")


def argument_tokens(node: dict) -> str:
    arguments = node.get("arguments")
    if not isinstance(arguments, list):
        return ""
    tokens = []
    for argument in arguments:
        if not isinstance(argument, dict) or "name" not in argument:
            raise UsageContractError(
                f"JSON_CONTRACT_MISMATCH: arguments entry {argument!r} has no name"
            )
        name = str(argument["name"]).upper()
        tokens.append(f"<{name}>" if argument.get("required") else f"[{name}]")
    return (" " + " ".join(tokens)) if tokens else ""


def leaf_commands(commands: dict) -> list[tuple[list[str], dict]]:
    """Return every runnable command path in the tree, parents excluded."""
    leaves: list[tuple[list[str], dict]] = []

    def walk(node_map: dict, path: list[str]) -> None:
        for name, node in node_map.items():
            if not isinstance(node, dict):
                raise UsageContractError(
                    f"JSON_CONTRACT_MISMATCH: commands.{'.'.join(path + [name])} "
                    f"is {type(node).__name__}, expected object"
                )
            current = path + [name]
            children = child_commands(node)
            if children:
                walk(children, current)
            else:
                leaves.append((current, node))

    walk(commands, [])
    return leaves


def quick_start_rows(commands: dict, cli_name: str) -> str:
    rows = []
    for path, node in leaf_commands(commands):
        invocation = " ".join([cli_name] + path) + argument_tokens(node)
        label = first_sentence(node.get("help")) or " ".join(path)
        rows.append(f"| {label} | `{invocation}` |")
    return "\n".join(rows)


def command_group_lines(commands: dict) -> str:
    lines = []
    for name, node in commands.items():
        summary = first_sentence(node.get("help"))
        children = child_commands(node)
        entry = f"- **{name}**"
        if summary:
            entry += f" -- {summary}"
        if children:
            entry += f" (subcommands: {', '.join(sorted(children))})"
        lines.append(entry)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("usage_json", type=Path)
    parser.add_argument("cli_name")
    parser.add_argument("--section", required=True, choices=["quick-start", "command-groups"])
    args = parser.parse_args()

    commands = load_commands(args.usage_json)
    if args.section == "quick-start":
        print(quick_start_rows(commands, args.cli_name))
    else:
        print(command_group_lines(commands))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
