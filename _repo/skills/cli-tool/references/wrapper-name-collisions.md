# Wrapper Name Collisions

Use this reference when a cli-tools wrapper shares an executable name with an upstream/vendor CLI, or when automation behaves differently from an interactive shell.

## Problem shape

A project script or cron job calls a bare command such as:

```bash
gemini ...
```

but multiple binaries with that name exist on the machine. Depending on PATH order, the command may resolve to:

- the intended cli-tools uv launcher under `~/.local/bin/<tool>`; or
- a Homebrew, npm, fnm, or vendor-installed upstream binary with a different command contract and auth state.

This can produce misleading errors: the upstream CLI accepts flags the wrapper rejects, or the wrapper supports subcommands the upstream CLI lacks.

## Diagnostic pattern

Before diagnosing auth, SDK, or API behavior, prove which executable is running:

```bash
tool=gemini
launcher="$(command -v "$tool")"
printf 'command -v %s: %s\n' "$tool" "$launcher"
python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$launcher"
head -1 "$launcher"
type -a "$tool"
```

For uv-installed cli-tools wrappers, the launcher normally points under:

```text
~/.local/share/uv/tools/<package>/bin/<tool>
```

and its shebang points at that tool venv's Python interpreter.

## Durable automation rule

For cron, scheduled agents, and project scripts where PATH can differ from an interactive shell, prefer the explicit cli-tools launcher path:

```bash
/Users/adam/.local/bin/<tool> ...
```

or otherwise assert that the selected executable is the cli-tools wrapper before continuing.

## Command-contract rule

After proving the wrapper, validate command syntax against:

```text
/Users/adam/Dropbox/GitRepos/cli-tools/_repo/skills/<tool>-cli/SKILL.md
/Users/adam/Dropbox/GitRepos/cli-tools/_repo/skills/<tool>-cli/usage.json
```

Do not copy flags from upstream/vendor docs unless the wrapper's service skill and `usage.json` expose those flags.

## Example: Gemini Deep Research

The cli-tools Gemini wrapper uses:

```bash
/Users/adam/.local/bin/gemini research start "<prompt>" --no-stream --timeout <seconds>
```

Google's upstream Node Gemini CLI uses a different headless interface such as `--prompt`/`--output-format`; that is not the cli-tools wrapper contract.

## Example: Kick auth login

Kick can exist as both a stale/vendor-style launcher on `/usr/local/bin/kick` and the cli-tools wrapper on `/Users/adam/.local/bin/kick`. The stale launcher may show `kick auth login` with no `--profile`/`--force`, while the cli-tools wrapper supports the documented profile-aware contract.

For Kick automation, prove the executable inside the same shell that will run auth:

```bash
export PATH="$HOME/.local/bin:$PATH"
command -v kick   # expect /Users/adam/.local/bin/kick
kick auth login --help
```

If `command -v kick` resolves outside `~/.local/bin`, fix PATH or call `/Users/adam/.local/bin/kick` explicitly before diagnosing auth failures or editing Kick workflow instructions.

## Example: n8n auth/status collision

n8n is a stronger collision case because this host can have upstream Homebrew binaries for **both** `n8n` and `n8n-cli`, while the repo-owned wrapper is `/Users/adam/.local/bin/n8n`.

A real failure shape was:

```bash
command -v n8n      # /opt/homebrew/bin/n8n
command -v n8n-cli  # /opt/homebrew/bin/n8n-cli
n8n auth status -t  # Error: Command "auth" not found
```

while the repo-owned wrapper succeeded:

```bash
/Users/adam/.local/bin/n8n auth status -t
```

Durable rule for n8n: do **not** try to escape the collision by switching from `n8n` to `n8n-cli`; that alias can collide too. For repo docs, skills, and automation, use the explicit wrapper path `/Users/adam/.local/bin/n8n` as the command contract, and treat bare-name PATH fixes only as optional interactive-shell cleanup.
