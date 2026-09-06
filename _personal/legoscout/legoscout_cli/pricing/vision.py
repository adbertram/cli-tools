"""Harness-aware vision judgment for the LegoScout deals pipeline.

The pipeline has exactly a handful of genuinely non-deterministic judgments
(classify a listing photo, verify a minifig crop against a catalog image) that
need a vision-capable model. LegoScout has no Anthropic or OpenAI API key in
the secret store -- only `gemini-api-key` -- so the only way to reach a vision
model today is by shelling into a locally-installed, already-authenticated
agent CLI (`claude`, `codex`). Claude Code, Codex, and Antigravity carry
equivalent vision capability; DeepSeek Harness (`dsh`) does not.

`detect_harness()` is one deterministic read of the running process's
environment -- never a retry-on-failure chain. `judge()` resolves to exactly
one provider and shells to it exactly once; any failure raises past this
module rather than silently trying a different provider.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

CLAUDE_BINARY = "claude"
CODEX_BINARY = "codex"

# Harnesses with no native vision route through this fixed CLI instead --
# chosen once, deterministically. Never a runtime try-A-then-B fallback.
_NO_NATIVE_VISION = {"dsh", "unknown"}
DESIGNATED_FALLBACK_PROVIDER = "codex"

JUDGE_TIMEOUT_SECONDS = 120

_PROVIDER_MODELS = {
    "codex": "gpt-5.6-sol",
    "claude": "opus",
}


def detect_harness() -> str:
    """Which AI CLI harness is currently running this code, from its
    environment markers -- mirrors the elif chain already used by
    `learn/scripts/collect-history-context.sh`. One deterministic read of the
    environment, never a retry.

    Antigravity has no documented environment signal anywhere in this
    ecosystem (checked 2026-09-06); it and an unattended/cron invocation both
    fall through to "unknown".
    """
    if os.environ.get("CLAUDECODE"):
        return "claude"
    if os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_SHELL"):
        return "codex"
    if os.environ.get("DSH_SHELL"):
        return "dsh"
    return "unknown"


def resolve_provider() -> str:
    """The one CLI `judge()` will shell into for this process. `dsh` (no
    vision) and `unknown` (Antigravity or an unattended run -- no detection
    signal exists for either) both route to the fixed designated fallback."""
    harness = detect_harness()
    return DESIGNATED_FALLBACK_PROVIDER if harness in _NO_NATIVE_VISION else harness


def _judge_via_codex(images: list[Path], prompt: str, schema_path: Path,
                      model: str) -> dict[str, Any]:
    argv = [CODEX_BINARY, "exec", "-m", model]
    for image in images:
        argv.extend(["-i", str(image)])
    argv.extend(["--output-schema", str(schema_path), "--json",
                 "--skip-git-repo-check", "-s", "read-only", prompt])
    # codex exec reads stdin when it isn't closed -- probed hang, 2026-09-06.
    proc = subprocess.run(argv, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=JUDGE_TIMEOUT_SECONDS)
    if proc.returncode != 0:
        raise RuntimeError("codex exec exited %d: %s"
                           % (proc.returncode, (proc.stderr or proc.stdout)[:500]))
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        item = event.get("item") or {}
        if event.get("type") == "item.completed" and item.get("type") == "agent_message":
            return json.loads(item["text"])
    raise RuntimeError("codex exec produced no agent_message event: %s"
                       % proc.stdout[:500])


def _judge_via_claude(images: list[Path], prompt: str, schema_path: Path,
                       model: str) -> dict[str, Any]:
    # NOTE: the exact --output-format json field carrying the schema-validated
    # payload under --json-schema is unverified live (claude -p was rate-
    # limited during this feature's development, 2026-09-06). Documented
    # behavior for --output-format json without a schema is a `result` string
    # field; this reads that field and expects it to already be the
    # schema-conformant JSON text. Re-verify against a live run before relying
    # on this path in production.
    schema_text = schema_path.read_text()
    image_paths = ", ".join(str(image) for image in images)
    full_prompt = "Read the image(s) at %s. %s" % (image_paths, prompt)
    argv = [CLAUDE_BINARY, "-p", "--output-format", "json",
            "--json-schema", schema_text, "--allowedTools", "Read",
            "--model", model, full_prompt]
    proc = subprocess.run(argv, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=JUDGE_TIMEOUT_SECONDS)
    if proc.returncode != 0:
        raise RuntimeError("claude -p exited %d: %s"
                           % (proc.returncode, (proc.stderr or proc.stdout)[:500]))
    response = json.loads(proc.stdout)
    if response.get("is_error"):
        raise RuntimeError("claude -p returned an error: %s" % response.get("result"))
    if "result" not in response:
        raise RuntimeError("claude -p JSON output has no 'result' field: %s"
                           % proc.stdout[:500])
    return json.loads(response["result"])


def judge(images: list[Path], prompt: str, schema_path: Path) -> dict[str, Any]:
    """Shell to exactly one vision-capable CLI, once. Raises on any failure --
    never a silent fallback to a different provider."""
    provider = resolve_provider()
    model = _PROVIDER_MODELS[provider]
    if provider == "codex":
        return _judge_via_codex(images, prompt, schema_path, model)
    if provider == "claude":
        return _judge_via_claude(images, prompt, schema_path, model)
    raise RuntimeError("no judge implementation for provider %r" % provider)
