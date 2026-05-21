#!/usr/bin/env python3
"""
Discover CLI tool command tree by parsing --help output.

Pure Python (stdlib only). Works with Typer/Click/Rich CLI tools.
Produces structured JSON with all commands, arguments, options, and examples.

Usage:
    python discover-cli.py <tool-name> [--output <file>] [--include-examples]
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone


# Options to filter out of every command
FILTERED_OPTIONS = {"--help", "--install-completion", "--show-completion"}


def run_help(args: list[str]) -> str | None:
    """Run a command with --help and return stdout, or None on failure."""
    env = os.environ.copy()
    env["COLUMNS"] = "200"
    env["NO_COLOR"] = "1"
    try:
        result = subprocess.run(
            args + ["--help"],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
        return result.stdout if result.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def extract_sections(text: str) -> dict[str, str]:
    """Extract named sections from Rich/Typer box-drawing output.

    Sections are bounded by:
        ╭─ Section Name ─...╮
        │ content            │
        ╰─...────────────────╯
    """
    sections = {}
    current_name = None
    current_lines = []

    for line in text.splitlines():
        # Section header: ╭─ Name ─╮ (with possible padding)
        header_match = re.match(r"^╭─\s*(.+?)\s*─+╮$", line.strip())
        if header_match:
            # Save previous section
            if current_name:
                sections[current_name] = "\n".join(current_lines)
            current_name = header_match.group(1).strip()
            current_lines = []
            continue

        # Section footer
        if line.strip().startswith("╰") and line.strip().endswith("╯"):
            if current_name:
                sections[current_name] = "\n".join(current_lines)
                current_name = None
                current_lines = []
            continue

        # Content line inside a section (strip box chars)
        if current_name:
            # Remove leading │ and trailing │
            content = line
            content = re.sub(r"^\s*│\s?", "", content)
            content = re.sub(r"\s*│\s*$", "", content)
            current_lines.append(content)

    return sections


def extract_description(text: str) -> str:
    """Extract the description text between Usage: line and first section.

    Stops at 'Examples:' or section boxes to avoid mixing examples into description.
    """
    lines = text.splitlines()
    desc_lines = []
    found_usage = False

    for line in lines:
        stripped = line.strip()
        # Skip until after the Usage: line
        if stripped.startswith("Usage:"):
            found_usage = True
            continue
        # Stop at first section box or examples block
        if stripped.startswith("╭"):
            break
        if stripped.lower().startswith("examples:") or stripped.lower() == "examples":
            break
        if found_usage and stripped:
            desc_lines.append(stripped)

    return " ".join(desc_lines).strip()


def extract_examples(text: str, tool_name: str) -> list[str]:
    """Extract example command lines from help text."""
    examples = []
    lines = text.splitlines()
    in_examples = False

    for line in lines:
        stripped = line.strip()
        # Remove box-drawing characters
        cleaned = re.sub(r"^│\s*", "", stripped)
        cleaned = re.sub(r"\s*│$", "", cleaned)
        cleaned = cleaned.strip()

        if cleaned.lower().startswith("examples:") or cleaned.lower() == "examples":
            in_examples = True
            continue

        # End of examples section at next section or empty gap after examples
        if in_examples:
            if cleaned.startswith("╭") or cleaned.startswith("╰"):
                in_examples = False
                continue
            # Lines that look like commands
            if cleaned.startswith(tool_name):
                examples.append(cleaned)

    return examples


def parse_commands(section_text: str) -> dict[str, str]:
    """Parse a Commands section into {name: description}."""
    commands = {}
    for line in section_text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Commands are formatted as: name  description (2+ spaces between)
        parts = re.split(r"\s{2,}", line, maxsplit=1)
        if len(parts) == 2:
            name, desc = parts
            commands[name.strip()] = desc.strip()
        elif len(parts) == 1 and parts[0]:
            # Command with no description
            commands[parts[0].strip()] = ""
    return commands


def parse_arguments(section_text: str) -> list[dict]:
    """Parse an Arguments section into structured argument dicts."""
    arguments = []
    lines = section_text.splitlines()

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Typer arguments: name  [TYPE]  description  [default: X] / [required]
        # The * prefix means required
        required = line.startswith("*")
        if required:
            line = line[1:].strip()

        # Typer formats:
        #   name      [TYPE]  description   (optional arg, type in brackets)
        #   name      TYPE  description     (required arg, type without brackets)
        #   name      description           (no type token at all)

        # Try bracketed type first: name  [TYPE]  description
        match = re.match(
            r"^(\w[\w-]*)\s+\[([A-Z_]+)\]\s+(.*)",
            line,
        )
        if match:
            name = match.group(1)
            arg_type = match.group(2)
            rest = match.group(3).strip()
        else:
            # Try bare type: name  TYPE  description (2+ spaces between each)
            match2 = re.match(
                r"^(\w[\w-]*)\s{2,}([A-Z][A-Z_0-9]+)\s{2,}(.*)",
                line,
            )
            if match2:
                name = match2.group(1)
                arg_type = match2.group(2)
                rest = match2.group(3).strip()
            else:
                # No type token — split on 2+ spaces
                parts = re.split(r"\s{2,}", line, maxsplit=1)
                if len(parts) >= 1:
                    name = parts[0]
                    arg_type = "TEXT"
                    rest = parts[1] if len(parts) > 1 else ""
                else:
                    continue

        # Check for [default: X] or [required] markers in the rest
        default = None
        default_match = re.search(r"\[default:\s*(.+?)\]", rest)
        if default_match:
            default = default_match.group(1)
            rest = rest[: default_match.start()].strip()

        if "[required]" in rest:
            required = True
            rest = rest.replace("[required]", "").strip()

        arg = {
            "name": name,
            "type": arg_type,
            "required": required,
            "help": rest.rstrip(". ").strip() if rest else "",
        }
        if default is not None:
            arg["default"] = default

        arguments.append(arg)

    return arguments


def parse_options(section_text: str) -> list[dict]:
    """Parse an Options section into structured option dicts."""
    options = []

    # Join continuation lines (lines that don't start with --)
    joined_lines = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("--") or stripped.startswith("*"):
            joined_lines.append(stripped)
        elif joined_lines:
            # Continuation of previous line
            joined_lines[-1] += " " + stripped

    for line in joined_lines:
        required = line.startswith("*")
        if required:
            line = line[1:].strip()

        # Skip filtered options
        if any(line.startswith(f) for f in FILTERED_OPTIONS):
            continue

        # Parse option line
        # Patterns:
        #   --name  -s  TYPE  help text  [default: X]
        #   --name  -s        help text  (boolean - no TYPE)
        #   --name      TYPE  help text
        #   --name            help text  (boolean)

        # Extract all --flag and -s tokens at the start
        flag_match = re.match(
            r"^(--[\w-]+)\s+(-\w)?\s*(.*)", line
        )
        if not flag_match:
            continue

        long_flag = flag_match.group(1)
        short_flag = flag_match.group(2)
        rest = flag_match.group(3).strip()

        # Check if next token is a TYPE (all uppercase or INTEGER/FLOAT/TEXT/PATH etc)
        type_match = re.match(r"^([A-Z][A-Z_0-9]+)\s+(.*)", rest)
        if type_match:
            opt_type = type_match.group(1)
            help_text = type_match.group(2).strip()
        else:
            # Boolean flag (no type token)
            opt_type = "bool"
            help_text = rest

        # Extract default value
        default = None
        default_match = re.search(r"\[default:\s*(.+?)\]", help_text)
        if default_match:
            default = default_match.group(1)
            help_text = help_text[: default_match.start()].strip()

        # Check for [required]
        if "[required]" in help_text:
            required = True
            help_text = help_text.replace("[required]", "").strip()

        # Check for [env var: X]
        env_var = None
        env_match = re.search(r"\[env var:\s*(.+?)\]", help_text)
        if env_match:
            env_var = env_match.group(1)
            help_text = help_text[: env_match.start()].strip()

        opt = {
            "name": long_flag,
            "type": opt_type,
            "required": required,
            "help": help_text.rstrip(". ").strip() if help_text else "",
        }
        if short_flag:
            opt["short"] = short_flag
        if default is not None:
            opt["default"] = default
        if env_var:
            opt["env_var"] = env_var

        options.append(opt)

    return options


def discover_command(
    cmd_path: list[str], tool_name: str, include_examples: bool
) -> dict | None:
    """Discover a single command and its subcommands recursively."""
    help_text = run_help(cmd_path)
    if not help_text:
        return None

    sections = extract_sections(help_text)
    description = extract_description(help_text)

    result = {}
    if description:
        result["help"] = description

    # Parse arguments
    if "Arguments" in sections:
        args = parse_arguments(sections["Arguments"])
        if args:
            result["arguments"] = args

    # Parse options
    if "Options" in sections:
        opts = parse_options(sections["Options"])
        if opts:
            result["options"] = opts

    # Extract examples
    if include_examples:
        examples = extract_examples(help_text, tool_name)
        if examples:
            result["examples"] = examples

    # Recurse into subcommands
    if "Commands" in sections:
        sub_commands = parse_commands(sections["Commands"])
        if sub_commands:
            result["commands"] = {}
            for cmd_name, cmd_desc in sub_commands.items():
                sub_result = discover_command(
                    cmd_path + [cmd_name], tool_name, include_examples
                )
                if sub_result:
                    result["commands"][cmd_name] = sub_result
                else:
                    # Fallback: use description from parent listing
                    result["commands"][cmd_name] = {"help": cmd_desc}

    return result


def count_leaf_commands(node: dict) -> int:
    """Count leaf commands (commands with no sub-commands)."""
    if "commands" not in node:
        return 1
    return sum(count_leaf_commands(v) for v in node["commands"].values())


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Discover CLI tool command tree via --help parsing"
    )
    parser.add_argument("tool", help="CLI tool name (must be on PATH)")
    parser.add_argument(
        "--output", "-o", help="Output file (default: stdout)"
    )
    parser.add_argument(
        "--include-examples",
        action="store_true",
        help="Extract example commands from help text",
    )
    args = parser.parse_args()

    # Verify tool exists
    help_text = run_help([args.tool])
    if help_text is None:
        print(f"Error: '{args.tool}' not found or --help failed", file=sys.stderr)
        sys.exit(1)

    # Discover full command tree
    tree = discover_command([args.tool], args.tool, args.include_examples)
    if tree is None:
        print(f"Error: Failed to parse --help output for '{args.tool}'", file=sys.stderr)
        sys.exit(1)

    # Build output
    output = {
        "tool": args.tool,
        "description": tree.get("help", ""),
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "total_commands": count_leaf_commands(tree),
    }

    # Hoist top-level options
    if "options" in tree:
        output["global_options"] = tree.pop("options")

    # Hoist commands to top level
    if "commands" in tree:
        output["commands"] = tree.pop("commands")

    result = json.dumps(output, indent=2)

    if args.output:
        with open(args.output, "w") as f:
            f.write(result + "\n")
        print(f"Written to {args.output} ({output['total_commands']} commands)", file=sys.stderr)
    else:
        print(result)


if __name__ == "__main__":
    main()
